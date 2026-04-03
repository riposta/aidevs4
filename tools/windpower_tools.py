import json
import time
import re
from concurrent.futures import ThreadPoolExecutor

from core.config import API_KEY, VERIFY_URL
from core.log import get_logger
from core.store import store_put
from core.result import save_result
from core import http, event_log

log = get_logger("tools.windpower")

CUTOFF_WIND = 14  # m/s - above this, turbine must shut down
MIN_WIND = 4      # m/s - below this, can't generate


def _api(action: str, **kwargs) -> dict:
    answer = {"action": action, **kwargs}
    resp = http.post(VERIFY_URL, json={"apikey": API_KEY, "task": "windpower", "answer": answer})
    return resp.json()


def _poll_until(expected_count: int, timeout: float) -> list:
    """Poll getResult until expected_count results or timeout."""
    results = []
    deadline = time.time() + timeout
    while len(results) < expected_count and time.time() < deadline:
        r = _api("getResult")
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
    r = _api("start")
    log.info("Started: %s (%.1fs)", r.get("message"), time.time() - t0)

    # 2. Queue all data requests in parallel
    with ThreadPoolExecutor(max_workers=3) as pool:
        pool.submit(_api, "get", param="weather")
        pool.submit(_api, "get", param="turbinecheck")
        pool.submit(_api, "get", param="powerplantcheck")

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
            pool.submit(_api, "unlockCodeGenerator",
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
        r = _api("config", configs=configs)
        log.info("Config result: %s", json.dumps(r, ensure_ascii=False)[:300])

    # 8. Turbinecheck was already done in step 2. Skip if time is tight.
    elapsed_so_far = time.time() - t0
    if elapsed_so_far < 35:
        _api("get", param="turbinecheck")
        tc = _poll_until(1, timeout=max(1, 38 - elapsed_so_far))
        log.info("Turbinecheck2: %s (%.1fs)", "done" if tc else "timeout", time.time() - t0)
    else:
        log.info("Skipping second turbinecheck (%.1fs elapsed, initial one should count)", elapsed_so_far)

    # 9. Done
    elapsed = time.time() - t0
    log.info("Sending done at %.1fs", elapsed)
    r = _api("done")
    log.info("Done: %s", json.dumps(r, ensure_ascii=False)[:500])

    flag_match = re.search(r"\{FLG:[^}]+\}", json.dumps(r))
    if flag_match:
        flag = flag_match.group(0)
        save_result("windpower", {"action": "done"}, {"code": 0, "message": flag})
        return f"Flag: {flag} (completed in {elapsed:.1f}s)"

    save_result("windpower", {"action": "done"}, r)
    return f"Done: {json.dumps(r, ensure_ascii=False)[:400]} (elapsed: {elapsed:.1f}s)"
