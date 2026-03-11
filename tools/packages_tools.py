import json

from core import http
from core.config import API_KEY, HUB_URL
from core.log import get_logger

log = get_logger("tools.packages")

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
