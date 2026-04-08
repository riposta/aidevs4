import json
import time

import requests

from core import http
from core.config import API_KEY, HUB_URL, VERIFY_URL
from core.log import get_logger
from core.result import save_result
from core.store import store_put

log = get_logger("tools.transport")

# === Railway ===

MAX_RETRIES = 20


def _railway_api(action: str, **params) -> dict:
    """Send action to railway API with 503 retry and rate limit handling."""
    payload = {
        "apikey": API_KEY,
        "task": "railway",
        "answer": {"action": action, **params},
    }

    for attempt in range(1, MAX_RETRIES + 1):
        log.info("API call [%d]: action=%s params=%s", attempt, action, params)
        resp = requests.post(VERIFY_URL, json=payload)

        # Rate limit handling
        reset = resp.headers.get("X-RateLimit-Reset") or resp.headers.get("Retry-After")
        remaining = resp.headers.get("X-RateLimit-Remaining")
        if remaining is not None:
            log.info("Rate limit remaining: %s, reset: %s", remaining, reset)

        if resp.status_code in (503, 429):
            # reset may be a Unix timestamp or relative seconds
            wait = 2 ** min(attempt, 6) if resp.status_code == 503 else 10
            if reset and reset.isdigit():
                reset_val = int(reset)
                if reset_val > 1_000_000_000:  # Unix timestamp
                    wait = max(1, reset_val - int(time.time()))
                else:
                    wait = reset_val
            wait = min(wait, 30)  # cap at 30s
            log.warning("%d — retry %d/%d, waiting %ds", resp.status_code, attempt, MAX_RETRIES, wait)
            time.sleep(wait)
            continue

        log.info("Response [%d]: %s", resp.status_code, resp.text[:500])
        return resp.json()

    return {"error": f"Failed after {MAX_RETRIES} retries"}


def railway_help() -> str:
    """Get railway API documentation."""
    result = _railway_api("help")
    return json.dumps(result, ensure_ascii=False, indent=2)


def railway_getstatus(route: str) -> str:
    """Get current status of a route."""
    result = _railway_api("getstatus", route=route)
    return json.dumps(result, ensure_ascii=False)


def railway_reconfigure(route: str) -> str:
    """Enter reconfigure mode for a route."""
    result = _railway_api("reconfigure", route=route)
    return json.dumps(result, ensure_ascii=False)


def railway_setstatus(route: str, value: str) -> str:
    """Set route status (RTOPEN or RTCLOSE). Must be in reconfigure mode first."""
    result = _railway_api("setstatus", route=route, value=value)
    return json.dumps(result, ensure_ascii=False)


def railway_save(route: str) -> str:
    """Exit reconfigure mode and save changes for a route."""
    result = _railway_api("save", route=route)
    text = json.dumps(result, ensure_ascii=False)
    store_put("filtered", text)
    if "FLG:" in text:
        save_result("railway", {"route": route}, result)
    return text


# === Drone ===


def drone_submit(instructions: str) -> str:
    """Submit drone flight instructions as JSON array of command strings. Returns API response."""
    try:
        instr_list = json.loads(instructions)
    except json.JSONDecodeError:
        return "Error: instructions must be a valid JSON array of strings."

    payload = {
        "apikey": API_KEY,
        "task": "drone",
        "answer": {"instructions": instr_list},
    }
    log.info("Submitting %d instructions", len(instr_list))
    resp = http.post(VERIFY_URL, json=payload)
    resp.raise_for_status()
    data = resp.json()

    msg = data.get("message", "")
    code = data.get("code", -1)

    if "FLG:" in msg:
        store_put("filtered", json.dumps({"instructions": instr_list}, ensure_ascii=False))
        log.info("FLAG received: %s", msg)
        return f"SUCCESS! Flag: {msg}"

    log.info("Response (code=%d): %s", code, msg[:200])
    return f"API response (code={code}): {msg}"


# === Packages ===

PACKAGES_URL = f"{HUB_URL}/api/packages"


def check_package(packageid: str) -> str:
    """Check status and location of a package by its ID."""
    payload = {
        "apikey": API_KEY,
        "action": "check",
        "packageid": packageid,
    }
    log.info("Checking package %s", packageid)
    resp = http.post(PACKAGES_URL, json=payload)
    resp.raise_for_status()
    data = resp.json()
    log.info("Package %s: %s", packageid, data)
    return json.dumps(data, ensure_ascii=False)


def redirect_package(packageid: str, destination: str, code: str) -> str:
    """Redirect a package to a new destination. Requires package ID, destination code, and security code."""
    payload = {
        "apikey": API_KEY,
        "action": "redirect",
        "packageid": packageid,
        "destination": destination,
        "code": code,
    }
    log.info("Redirecting package %s to %s", packageid, destination)
    resp = http.post(PACKAGES_URL, json=payload)
    resp.raise_for_status()
    data = resp.json()
    log.info("Redirect result for %s: %s", packageid, data)
    return json.dumps(data, ensure_ascii=False)
