import csv
import io
import json
import time

import requests

from core.config import API_KEY, HUB_URL, VERIFY_URL
from core.log import get_logger
from core.store import store_put, store_get

log = get_logger("tools.categorize")


def categorize_reset() -> str:
    """Reset the categorization budget and start fresh."""
    payload = {
        "apikey": API_KEY,
        "task": "categorize",
        "answer": {"prompt": "reset"},
    }
    resp = requests.post(VERIFY_URL, json=payload)
    log.info("Reset: %s", resp.text[:300])
    return resp.text[:300]


def categorize_fetch_csv() -> str:
    """Fetch fresh CSV with items to classify. Returns item list."""
    url = f"{HUB_URL}/data/{API_KEY}/categorize.csv"
    log.info("Fetching CSV: %s", url)
    resp = requests.get(url)
    resp.raise_for_status()

    reader = csv.DictReader(io.StringIO(resp.text))
    items = list(reader)
    store_put("categorize_items", json.dumps(items, ensure_ascii=False))

    summary = "\n".join(f"  {it['code']}: {it['description']}" for it in items)
    log.info("Fetched %d items", len(items))
    return f"Fetched {len(items)} items:\n{summary}"


def categorize_classify(prompt_template: str) -> str:
    """Send prompt for each item. Template must contain {id} and {description} placeholders. Returns results."""
    raw = store_get("categorize_items")
    if not raw:
        return "Error: no items loaded. Run categorize_fetch_csv first."

    items = json.loads(raw)
    results = []

    for item in items:
        prompt = prompt_template.format(id=item["code"], description=item["description"])
        payload = {
            "apikey": API_KEY,
            "task": "categorize",
            "answer": {"prompt": prompt},
        }
        resp = requests.post(VERIFY_URL, json=payload)
        data = resp.json()
        output = data.get("debug", {}).get("output", "?")
        message = data.get("message", "")
        results.append(f"{item['code']}: {output} ({message})")
        log.info("%s: %s -> %s", item["code"], output, message)

        if "FLG:" in message:
            store_put("filtered", message)
            return "\n".join(results) + f"\n\nFLAG FOUND: {message}"

        if data.get("code") not in (0, 1):
            return "\n".join(results) + f"\n\nERROR at {item['code']}: {message}"

        time.sleep(0.3)

    return "\n".join(results) + "\n\nAll items classified successfully (no flag yet?)."
