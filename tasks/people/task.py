import csv
import io
import json

import requests
from pathlib import Path
from pydantic import BaseModel

from core.agent import load_agents
from core.config import API_KEY
from core.log import get_logger
from core.verify import verify

TASK_NAME = "people"
TASK_DIR = Path(__file__).parent
CSV_URL = f"https://hub.ag3nts.org/data/{API_KEY}/people.csv"

# Filtering criteria
GENDER = "M"
BIRTH_CITY = "Grudziądz"
CURRENT_YEAR = 2026
AGE_MIN = 20
AGE_MAX = 40
REQUIRED_TAG = "transport"

VALID_TAGS = {"IT", "transport", "edukacja", "medycyna", "praca z ludźmi", "praca z pojazdami", "praca fizyczna"}

log = get_logger(TASK_NAME)


class PersonOut(BaseModel):
    name: str
    surname: str
    gender: str
    born: int
    city: str
    tags: list[str]


def download_csv() -> list[dict]:
    log.info("Downloading CSV from %s", CSV_URL)
    resp = requests.get(CSV_URL)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    rows = list(reader)
    log.info("Downloaded %d rows", len(rows))
    return rows


def filter_candidates(rows: list[dict]) -> list[dict]:
    candidates = []
    for row in rows:
        gender = row.get("gender", "").strip()
        birth_place = row.get("birthPlace", "").strip()
        birth_date = row.get("birthDate", "").strip()

        if gender != GENDER:
            continue
        if birth_place != BIRTH_CITY:
            continue

        try:
            birth_year = int(birth_date.split("-")[0])
        except (ValueError, IndexError):
            continue

        age = CURRENT_YEAR - birth_year
        if not (AGE_MIN <= age <= AGE_MAX):
            continue

        candidates.append(row)

    log.info("Filtered to %d candidates (%s, %s, age %d-%d)",
             len(candidates), GENDER, BIRTH_CITY, AGE_MIN, AGE_MAX)
    return candidates


def tag_all(tagger, candidates: list[dict]) -> list[list[str]]:
    """Send all candidates to tagger in one batch call."""
    batch_input = []
    for i, row in enumerate(candidates):
        batch_input.append({
            "id": i,
            "name": row["name"],
            "surname": row["surname"],
            "job": row.get("job", ""),
        })

    prompt = (
        f"Classify each person's job description. "
        f"Valid tags: {json.dumps(sorted(VALID_TAGS), ensure_ascii=False)}\n\n"
        f"People:\n{json.dumps(batch_input, ensure_ascii=False, indent=2)}"
    )

    result = tagger.run(prompt)

    try:
        # Strip markdown code fences if present
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]  # remove first line
            cleaned = cleaned.rsplit("```", 1)[0]  # remove closing fence

        parsed = json.loads(cleaned)
        tags_by_id = {item["id"]: item["tags"] for item in parsed}
        return [
            [t for t in tags_by_id.get(i, []) if t in VALID_TAGS]
            for i in range(len(candidates))
        ]
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        log.error("Failed to parse batch tagger response: %s", e)
        log.debug("Raw response: %s", result)
        return [[] for _ in candidates]


def run():
    rows = download_csv()
    candidates = filter_candidates(rows)

    agents = load_agents(TASK_DIR)
    tagger = agents["tagger"]
    tagger.registry = None

    all_tags = tag_all(tagger, candidates)

    answer = []
    for row, tags in zip(candidates, all_tags):
        log.info("%s %s — tags: %s", row["name"], row["surname"], tags)

        if REQUIRED_TAG not in tags:
            continue

        birth_year = int(row["birthDate"].split("-")[0])
        person = PersonOut(
            name=row["name"],
            surname=row["surname"],
            gender=row["gender"],
            born=birth_year,
            city=row["birthPlace"],
            tags=tags,
        )
        answer.append(person.model_dump())

    log.info("Final answer: %d people with '%s' tag", len(answer), REQUIRED_TAG)
    for p in answer:
        log.info("  %s %s (%d, %s) — %s", p["name"], p["surname"], p["born"], p["city"], p["tags"])

    return verify(TASK_NAME, answer)
