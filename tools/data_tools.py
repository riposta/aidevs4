import csv
import io
import json
from datetime import datetime

from openai import OpenAI

from core import http
from core.config import API_KEY, HUB_URL, OPENAI_API_KEY
from core.log import get_logger
from core.store import store_get, store_put

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


VALID_TAGS = ["IT", "transport", "edukacja", "medycyna", "praca z ludźmi", "praca z pojazdami", "praca fizyczna"]


def tag_people(input_key: str, output_key: str) -> str:
    """Classify each person's job description into tags. Reads from input_key, stores tagged results under output_key."""
    raw_data = store_get(input_key)
    if raw_data is None:
        return f"Error: no data found under '{input_key}'."

    candidates = json.loads(raw_data)
    batch = [
        {"id": i, "name": r["name"], "surname": r["surname"], "job": r.get("job", "")}
        for i, r in enumerate(candidates)
    ]

    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model="gpt-5.4",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a job classification agent. Assign tags to each person based on their job description.\n"
                    f"Valid tags: {json.dumps(VALID_TAGS)}\n"
                    "Respond ONLY with a JSON array: [{\"id\": 0, \"tags\": [...]}, ...]"
                ),
            },
            {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
        ],
    )
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]

    tags_by_id = {item["id"]: item["tags"] for item in json.loads(raw)}

    result = []
    for i, row in enumerate(candidates):
        tags = [t for t in tags_by_id.get(i, []) if t in VALID_TAGS]
        birth_year = int(row["birthDate"].split("-")[0])
        result.append({
            "name": row["name"],
            "surname": row["surname"],
            "gender": row["gender"],
            "born": birth_year,
            "city": row["birthPlace"],
            "tags": tags,
        })
        log.info("%s %s — %s", row["name"], row["surname"], tags)

    store_put(output_key, json.dumps(result, ensure_ascii=False))

    tag_counts = {}
    for r in result:
        for t in r["tags"]:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    summary = ", ".join(f"{t}: {c}" for t, c in sorted(tag_counts.items()))

    return f"Tagged {len(result)} people into '{output_key}'. Distribution: {summary}"


def filter_by_tag(tag: str, input_key: str, output_key: str) -> str:
    """Filter tagged people keeping only those with the given tag. Reads from input_key, stores under output_key."""
    raw_data = store_get(input_key)
    if raw_data is None:
        return f"Error: no data found under '{input_key}'."

    people = json.loads(raw_data)
    filtered = [p for p in people if tag in p.get("tags", [])]
    log.info("Filtered by tag '%s': %d / %d people", tag, len(filtered), len(people))

    store_put(output_key, json.dumps(filtered, ensure_ascii=False))

    names = [f"{p['name']} {p['surname']}" for p in filtered]
    return f"Filtered {len(filtered)} people with tag '{tag}' into '{output_key}': {', '.join(names)}"
