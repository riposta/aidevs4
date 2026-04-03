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

from flask import Flask, request as flask_request, jsonify

from core.config import API_KEY, VERIFY_URL
from core.log import get_logger
from core.store import store_put, store_get
from core.result import save_result
from core import http, event_log

log = get_logger("tools.negotiations")

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
