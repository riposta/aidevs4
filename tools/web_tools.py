import csv
import json
import os
import re
import subprocess
import time
import threading
import unicodedata
from io import StringIO
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import Flask, request as flask_request, jsonify

from core.config import API_KEY, VERIFY_URL
from core.log import get_logger
from core.store import store_put, store_get
from core.result import save_result
from core import http, event_log

log = get_logger("tools.web")


# =============================================================================
# OKO Editor functions (from okoeditor_tools.py)
# =============================================================================

OKO_URL = "https://oko.ag3nts.org"

# Known IDs from OKO system
SKOLWIN_ID = "380792b2c86d9c5be670b3bde48e187b"
PMR_ID = "351c0d9c90d66b4c040fff1259dd191d"


def _oko_update(page: str, entry_id: str, **kwargs) -> dict:
    """Send an update command to the OKO API."""
    answer = {
        "page": page,
        "id": entry_id,
        "action": "update",
        **kwargs,
    }
    payload = {"apikey": API_KEY, "task": "okoeditor", "answer": answer}
    log.info("Updating %s/%s: %s", page, entry_id, json.dumps(kwargs, ensure_ascii=False)[:200])
    resp = http.post(VERIFY_URL, json=payload)
    result = resp.json()
    log.info("Result: %s", json.dumps(result, ensure_ascii=False)[:300])
    return result


def _browse_oko():
    """Login and browse OKO to find current state and IDs."""
    session = requests.Session()
    session.post(f"{OKO_URL}/", data={
        "action": "login",
        "login": "Zofia",
        "password": "Zofia2026!",
        "access_key": API_KEY,
    }, allow_redirects=True)

    info = {}
    for page in ["", "zadania", "notatki"]:
        url = f"{OKO_URL}/{page}" if page else f"{OKO_URL}/"
        resp = session.get(url)
        entries = re.findall(
            r'href="/' + (page or 'incydenty') + r'/([a-f0-9]+)".*?<strong>(.+?)</strong>',
            resp.text, re.DOTALL
        )
        info[page or "incydenty"] = entries

    return info


def execute_oko_edits() -> str:
    """Execute all required OKO system edits: reclassify Skolwin, mark task done, add Komarowo incident."""
    results = []

    # First browse to see current state
    info = _browse_oko()
    log.info("Current incydenty: %s", [(eid, t.strip()) for eid, t in info.get("incydenty", [])])
    log.info("Current zadania: %s", [(eid, t.strip()) for eid, t in info.get("zadania", [])])

    # Find Skolwin incident and task IDs
    skolwin_incident_id = None
    skolwin_task_id = None
    redirect_incident_id = None

    for eid, title in info.get("incydenty", []):
        t = title.strip()
        if "Skolwin" in t or "skolwin" in t.lower():
            skolwin_incident_id = eid
            log.info("Found Skolwin incident: %s - %s", eid, t)
        elif "PMR" in t or "emisja" in t.lower():
            redirect_incident_id = eid

    for eid, title in info.get("zadania", []):
        t = title.strip()
        if "Skolwin" in t.lower() or "skolwin" in t.lower():
            skolwin_task_id = eid
            log.info("Found Skolwin task: %s - %s", eid, t)

    if not skolwin_incident_id:
        skolwin_incident_id = SKOLWIN_ID
    if not skolwin_task_id:
        skolwin_task_id = SKOLWIN_ID
    if not redirect_incident_id:
        redirect_incident_id = PMR_ID

    # 1. Reclassify Skolwin incident from MOVE03 (vehicle+human) to MOVE04 (animals)
    r1 = _oko_update(
        "incydenty", skolwin_incident_id,
        title="MOVE04 Trudne do klasyfikacji ruchy nieopodal miasta Skolwin",
        content="Czujniki zarejestrowały szybko poruszające się obiekty w pobliżu rzeki nieopodal Skolwina. Po analizie nagrań ustalono, że ruch był powodowany przez dzikie zwierzęta, najprawdopodobniej bobry, które przemieszczały się wzdłuż brzegu rzeki. Nie stwierdzono obecności ludzi ani pojazdów w okolicy.",
    )
    results.append(f"1. Reclassify Skolwin: {r1.get('message', r1)}")

    # 2. Mark Skolwin task as done with animal content
    r2 = _oko_update(
        "zadania", skolwin_task_id,
        done="YES",
        content="Analiza nagrań z okolic Skolwina zakończona. Zarejestrowany ruch pochodził od zwierząt - widziano tam bobry poruszające się w pobliżu rzeki. Brak oznak obecności ludzi lub pojazdów.",
    )
    results.append(f"2. Skolwin task done: {r2.get('message', r2)}")

    # 3. Change an existing incident to be about Komarowo human movement
    r3 = _oko_update(
        "incydenty", redirect_incident_id,
        title="MOVE01 Wykryto ruch ludzi w okolicach miasta Komarowo",
        content="System wykrył ruch ludzi w okolicach niezamieszkałego miasta Komarowo. Czujniki zarejestrowały kilka postaci poruszających się w pobliżu opuszczonych budynków. Ruch miał charakter zorganizowany i wymaga dalszej obserwacji.",
    )
    results.append(f"3. Komarowo incident: {r3.get('message', r3)}")

    summary = "\n".join(results)
    log.info("All edits completed:\n%s", summary)
    store_put("oko_edits_done", "true")
    return f"All 3 edits completed:\n{summary}"


def finalize_oko() -> str:
    """Run the done action to verify all edits and get the flag."""
    payload = {
        "apikey": API_KEY,
        "task": "okoeditor",
        "answer": {"action": "done"},
    }
    resp = http.post(VERIFY_URL, json=payload)
    result = resp.json()
    log.info("Done result: %s", json.dumps(result, ensure_ascii=False))

    flag_match = re.search(r"\{FLG:[^}]+\}", json.dumps(result))
    if flag_match:
        flag = flag_match.group(0)
        save_result("okoeditor", {"action": "done"}, {"code": 0, "message": flag})
        return f"Flag: {flag}"

    save_result("okoeditor", {"action": "done"}, result)
    return f"Done result: {json.dumps(result, ensure_ascii=False)}"


# =============================================================================
# Negotiations functions (from negotiations_tools.py)
# =============================================================================

# Module-level data storage (populated by fetch, used by server)
_cities = {}        # code -> name
_items = []         # list of (name, code)
_item_cities = {}   # item_code -> set of city_codes

DATA_URL = "https://hub.ag3nts.org/dane/s03e04_csv"


def _normalize(text: str) -> str:
    text = text.lower()
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


_STOP_WORDS = {
    "i", "a", "w", "z", "do", "na", "o", "od", "dla", "ze", "po",
    "to", "co", "jak", "czy", "ten", "ta", "te", "jest", "sa",
    "potrzebuje", "potrzeba", "szukam", "chce", "prosze", "mi",
    "sie", "mnie", "nam", "nas", "bedzie", "moze", "gdzie",
    "kupic", "znalezc", "dostac", "miec", "maja", "oferuja",
    "sprzedaja", "przedmiot", "produkt", "komponent", "element",
    "the", "an", "of", "for", "with", "need", "want", "find",
    "looking", "search", "buy", "have", "can", "you", "me", "please",
}


def _search_items(query: str) -> list:
    q_norm = _normalize(query)
    keywords = q_norm.split()
    keywords = [k for k in keywords if k not in _STOP_WORDS and len(k) > 1]

    if not keywords:
        return []

    results = []
    for name, code in _items:
        name_norm = _normalize(name)
        if all(kw in name_norm for kw in keywords):
            results.append((name, code))

    # Relaxed search if nothing found
    if not results:
        for name, code in _items:
            name_norm = _normalize(name)
            matched = sum(1 for kw in keywords if kw in name_norm)
            if matched >= max(1, len(keywords) // 2):
                results.append((name, code))

    return results


def _build_flask_app() -> Flask:
    app = Flask(__name__)

    @app.route("/api/search", methods=["POST"])
    def api_search():
        data = flask_request.get_json(force=True)
        query = data.get("params", "")
        log.info("Search query: %s", query)

        if not query or len(query.strip()) < 2:
            return jsonify({"output": "Podaj opis przedmiotu do wyszukania"})

        results = _search_items(query)
        if not results:
            return jsonify({"output": "Nie znaleziono przedmiotow pasujacych do zapytania"})

        lines = []
        for name, code in results[:5]:
            city_codes = _item_cities.get(code, set())
            city_names = sorted(_cities.get(cc, cc) for cc in city_codes)
            cities_str = ", ".join(city_names) if city_names else "brak"
            lines.append(f"{name}: {cities_str}")

        output = "\n".join(lines)
        # Total response {"output":"..."} must be under 500 bytes
        # JSON overhead ~14 bytes + possible escaping, so limit output to 450
        while len(json.dumps({"output": output}).encode("utf-8")) > 500:
            lines = lines[:-1]
            if not lines:
                output = output[:400]
                break
            output = "\n".join(lines)

        log.info("Search result (%d bytes total): %s",
                 len(json.dumps({"output": output}).encode("utf-8")), output[:200])
        return jsonify({"output": output})

    return app


def _start_tunnel(local_port: int) -> tuple:
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{local_port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    url = None
    deadline = time.time() + 30
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        log.info("tunnel: %s", line.strip())
        m = re.search(r'(https://[a-z0-9-]+\.trycloudflare\.com)', line)
        if m:
            url = m.group(1)
            break
    if not url:
        proc.terminate()
        raise RuntimeError("Failed to get tunnel URL")
    return proc, url


def fetch_negotiations_data() -> str:
    """Download CSV data files with items, cities and their connections."""
    global _cities, _items, _item_cities

    # Download CSVs
    cities_resp = http.get(f"{DATA_URL}/cities.csv")
    items_resp = http.get(f"{DATA_URL}/items.csv")
    connections_resp = http.get(f"{DATA_URL}/connections.csv")

    # Parse cities
    _cities = {}
    reader = csv.DictReader(StringIO(cities_resp.text))
    for row in reader:
        _cities[row["code"]] = row["name"]

    # Parse items
    _items = []
    reader = csv.DictReader(StringIO(items_resp.text))
    for row in reader:
        _items.append((row["name"], row["code"]))

    # Parse connections
    _item_cities = {}
    reader = csv.DictReader(StringIO(connections_resp.text))
    for row in reader:
        ic = row["itemCode"]
        cc = row["cityCode"]
        _item_cities.setdefault(ic, set()).add(cc)

    summary = f"Loaded {len(_cities)} cities, {len(_items)} items, {len(_item_cities)} item-city connections"
    log.info(summary)
    store_put("negotiations_data_loaded", "true")
    return summary


def start_negotiations_server() -> str:
    """Start API server with search endpoint, expose via tunnel, and submit tool URLs to verification. Data must be fetched first with fetch_negotiations_data."""
    if not _cities or not _items:
        # Auto-fetch if not loaded
        log.info("Data not loaded, fetching automatically...")
        fetch_negotiations_data()

    port = 5001
    app = _build_flask_app()

    os.environ.pop("WERKZEUG_SERVER_FD", None)
    os.environ.pop("WERKZEUG_RUN_MAIN", None)
    server = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, debug=False),
        daemon=True,
    )
    server.start()
    time.sleep(1)
    log.info("HTTP server started on port %d", port)
    event_log.emit("system", agent="negotiations", content=f"HTTP server on port {port}")

    # Start tunnel
    tunnel_proc, public_url = _start_tunnel(port)
    log.info("Tunnel: %s", public_url)
    event_log.emit("system", agent="negotiations", content=f"Tunnel: {public_url}")

    # Wait for DNS propagation
    time.sleep(5)

    # Submit tools to verify
    answer = {
        "tools": [
            {
                "URL": f"{public_url}/api/search",
                "description": "Wyszukuje przedmioty po opisie w języku naturalnym i zwraca nazwy miast, w których są dostępne. Parametr 'params' powinien zawierać opis szukanego przedmiotu, np. 'kabel miedziany 10m' lub 'rezystor 100 ohm'. Zwraca listę przedmiotów z miastami, w których można je kupić."
            }
        ]
    }

    log.info("Submitting tools to verify: %s", json.dumps(answer, ensure_ascii=False)[:500])
    event_log.emit("system", agent="negotiations", content=f"Submitting tools: {public_url}")

    try:
        result = http.post(VERIFY_URL, json={
            "apikey": API_KEY,
            "task": "negotiations",
            "answer": answer,
        })
        log.info("Submit result: %s", result.text[:500])
        event_log.emit("system", agent="negotiations", content=f"Submit result: {result.text[:200]}")
    except Exception as e:
        log.error("Submit error: %s", e)
        return f"Error submitting tools: {e}"

    # Keep tunnel alive
    log.info("Keeping tunnel alive for 120s for external agent queries...")
    event_log.emit("system", agent="negotiations", content="Waiting 120s for external agent...")
    time.sleep(120)

    tunnel_proc.terminate()
    tunnel_proc.wait(timeout=5)

    store_put("negotiations_tunnel_url", public_url)
    return f"Server was running at {public_url}. Tunnel closed. Now check the result."


def check_negotiations_result() -> str:
    """Check if the external agent has finished and retrieve the flag."""
    try:
        result = http.post(VERIFY_URL, json={
            "apikey": API_KEY,
            "task": "negotiations",
            "answer": {"action": "check"},
        })
        log.info("Check result: %s", result.text[:500])
        data = result.json()

        flag_match = re.search(r"\{FLG:[^}]+\}", json.dumps(data))
        if flag_match:
            flag = flag_match.group(0)
            save_result("negotiations", {"action": "check"}, {"code": 0, "message": flag})
            return f"Flag found: {flag}"

        save_result("negotiations", {"action": "check"}, data)
        return f"Check result: {json.dumps(data, ensure_ascii=False)[:400]}"
    except Exception as e:
        log.error("Check error: %s", e)
        return f"Error checking result: {e}"


# =============================================================================
# Wind Power functions (from windpower_tools.py)
# =============================================================================

CUTOFF_WIND = 14  # m/s - above this, turbine must shut down
MIN_WIND = 4      # m/s - below this, can't generate


def _windpower_api(action: str, **kwargs) -> dict:
    answer = {"action": action, **kwargs}
    resp = http.post(VERIFY_URL, json={"apikey": API_KEY, "task": "windpower", "answer": answer})
    return resp.json()


def _poll_until(expected_count: int, timeout: float) -> list:
    """Poll getResult until expected_count results or timeout."""
    results = []
    deadline = time.time() + timeout
    while len(results) < expected_count and time.time() < deadline:
        r = _windpower_api("getResult")
        if r.get("sourceFunction"):
            results.append(r)
            log.info("Got result %d/%d: %s", len(results), expected_count, r["sourceFunction"])
        else:
            time.sleep(0.2)
    return results


def configure_windpower() -> str:
    """Run the complete wind turbine configuration within 40s time limit."""
    t0 = time.time()

    # 1. Start service window
    r = _windpower_api("start")
    log.info("Started: %s (%.1fs)", r.get("message"), time.time() - t0)

    # 2. Queue all data requests in parallel
    with ThreadPoolExecutor(max_workers=3) as pool:
        pool.submit(_windpower_api, "get", param="weather")
        pool.submit(_windpower_api, "get", param="turbinecheck")
        pool.submit(_windpower_api, "get", param="powerplantcheck")

    log.info("All 3 data requests queued (%.1fs)", time.time() - t0)

    # 3. Poll for all 3 results (weather takes ~23s)
    data = {}
    results = _poll_until(3, timeout=28)
    for r in results:
        data[r["sourceFunction"]] = r

    log.info("Got %d/3 results (%.1fs)", len(data), time.time() - t0)

    if "weather" not in data:
        return f"Error: weather data not received in time ({time.time()-t0:.1f}s)"

    weather = data["weather"]
    powerplant = data.get("powerplantcheck", {})

    # 4. Analyze forecast
    forecast = weather.get("forecast", [])
    log.info("Forecast has %d entries", len(forecast))

    deficit_kw = powerplant.get("powerDeficitKw", "3-4")
    log.info("Power deficit: %s kW", deficit_kw)

    # Determine config points
    storm_configs = []    # (timestamp, wind, pitch=90, mode=idle)
    production_configs = []  # (timestamp, wind, pitch=0, mode=production)

    best_production = None  # track best wind for production
    for entry in forecast:
        ts = entry.get("timestamp", "")
        wind = float(entry.get("windMs", 0))

        if wind > CUTOFF_WIND:
            storm_configs.append((ts, wind))
        elif wind >= MIN_WIND:
            production_configs.append((ts, wind))
            if best_production is None or wind > best_production[1]:
                best_production = (ts, wind)

    log.info("Storm hours: %d, Production candidates: %d", len(storm_configs), len(production_configs))
    if best_production:
        log.info("Best production: %s at %.1f m/s", best_production[0], best_production[1])

    # Build exactly 4 config points: all storms + 1 best production
    all_configs = []  # (date, hour, wind, pitch, mode)
    for ts, wind in storm_configs:
        date, hour = ts.split(" ", 1)
        all_configs.append((date, hour, wind, 90, "idle"))

    if best_production:
        ts, wind = best_production
        date, hour = ts.split(" ", 1)
        all_configs.append((date, hour, wind, 0, "production"))

    log.info("Total config points needing codes: %d (%.1fs)", len(all_configs), time.time() - t0)

    # 5. Queue all unlock code requests in parallel
    with ThreadPoolExecutor(max_workers=10) as pool:
        for date, hour, wind, pitch, mode in all_configs:
            pool.submit(_windpower_api, "unlockCodeGenerator",
                        startDate=date, startHour=hour, windMs=wind, pitchAngle=pitch)

    log.info("All %d unlock code requests queued (%.1fs)", len(all_configs), time.time() - t0)

    # 6. Poll for all unlock codes
    code_results = _poll_until(len(all_configs), timeout=12)
    log.info("Got %d/%d unlock codes (%.1fs)", len(code_results), len(all_configs), time.time() - t0)

    # Map codes: key is "date hour" from signedParams
    unlock_codes = {}
    for cr in code_results:
        sp = cr.get("signedParams", {})
        src_date = sp.get("startDate", cr.get("startDate", ""))
        src_hour = sp.get("startHour", cr.get("startHour", ""))
        code = cr.get("unlockCode", "")
        if src_date and src_hour and code:
            key = f"{src_date} {src_hour}"
            unlock_codes[key] = code

    log.info("Mapped %d unlock codes", len(unlock_codes))

    # 7. Build and submit batch config
    configs = {}
    missing = 0
    for date, hour, wind, pitch, mode in all_configs:
        key = f"{date} {hour}"
        code = unlock_codes.get(key)
        if not code:
            log.warning("Missing code for %s (wind=%.1f)", key, wind)
            missing += 1
            continue
        configs[key] = {
            "pitchAngle": pitch,
            "turbineMode": mode,
            "unlockCode": code,
        }

    log.info("Submitting %d configs (%d missing) at %.1fs", len(configs), missing, time.time() - t0)
    if configs:
        r = _windpower_api("config", configs=configs)
        log.info("Config result: %s", json.dumps(r, ensure_ascii=False)[:300])

    # 8. Turbinecheck was already done in step 2. Skip if time is tight.
    elapsed_so_far = time.time() - t0
    if elapsed_so_far < 35:
        _windpower_api("get", param="turbinecheck")
        tc = _poll_until(1, timeout=max(1, 38 - elapsed_so_far))
        log.info("Turbinecheck2: %s (%.1fs)", "done" if tc else "timeout", time.time() - t0)
    else:
        log.info("Skipping second turbinecheck (%.1fs elapsed, initial one should count)", elapsed_so_far)

    # 9. Done
    elapsed = time.time() - t0
    log.info("Sending done at %.1fs", elapsed)
    r = _windpower_api("done")
    log.info("Done: %s", json.dumps(r, ensure_ascii=False)[:500])

    flag_match = re.search(r"\{FLG:[^}]+\}", json.dumps(r))
    if flag_match:
        flag = flag_match.group(0)
        save_result("windpower", {"action": "done"}, {"code": 0, "message": flag})
        return f"Flag: {flag} (completed in {elapsed:.1f}s)"

    save_result("windpower", {"action": "done"}, r)
    return f"Done: {json.dumps(r, ensure_ascii=False)[:400]} (elapsed: {elapsed:.1f}s)"
