import json
import time

import requests

from core.config import API_KEY, VERIFY_URL
from core.log import get_logger
from core.store import store_put

log = get_logger("tools.railway")

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
    return text
