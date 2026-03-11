import csv
import io
import json
from datetime import datetime

from core import http
from core.config import API_KEY, HUB_URL
from core.log import get_logger
from core.store import store_put

log = get_logger("tools.data")

BASE_URL = f"{HUB_URL}/data/{API_KEY}"
CURRENT_YEAR = datetime.now().year


def download_and_filter(dataset: str, filters_json: str, output_key: str) -> str:
    """Download a CSV dataset and filter rows. Stores result under output_key."""
    url = f"{BASE_URL}/{dataset}.csv"
    resp = http.get(url)
    resp.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    log.info("Downloaded %d rows from %s", len(rows), dataset)

    filters = json.loads(filters_json)
    age_min = filters.pop("age_min", None)
    age_max = filters.pop("age_max", None)

    candidates = []
    for row in rows:
        if not all(row.get(k, "").strip() == v for k, v in filters.items()):
            continue
        if age_min is not None or age_max is not None:
            try:
                birth_year = int(row["birthDate"].split("-")[0])
                age = CURRENT_YEAR - birth_year
            except (ValueError, IndexError, KeyError):
                continue
            if age_min and age < age_min:
                continue
            if age_max and age > age_max:
                continue
        candidates.append(row)

    log.info("Filtered to %d candidates", len(candidates))
    store_put(output_key, json.dumps(candidates, ensure_ascii=False))

    names = [f"{c.get('name', '')} {c.get('surname', '')}".strip() for c in candidates]
    return f"Filtered {len(candidates)} candidates into '{output_key}': {', '.join(names)}"
