import json
import re

from core.config import API_KEY, VERIFY_URL
from core.log import get_logger
from core.store import store_put
from core.result import save_result
from core import http, event_log

log = get_logger("tools.filesystem")


def _api(answer) -> dict:
    resp = http.post(VERIFY_URL, json={"apikey": API_KEY, "task": "filesystem", "answer": answer})
    return resp.json()


def build_filesystem() -> str:
    """Build the complete filesystem structure from Natan's notes."""

    # === DATA FROM NOTES ===

    # Cities and what they NEED (from ogłoszenia.txt)
    cities = {
        "opalino": {"chleb": 45, "woda": 120, "mlotek": 6},
        "domatowo": {"makaron": 60, "woda": 150, "lopata": 8},
        "brudzewo": {"ryz": 55, "woda": 140, "wiertarka": 5},
        "darzlubie": {"wolowina": 25, "woda": 130, "kilof": 7},
        "celbowo": {"kurczak": 40, "woda": 125, "mlotek": 6},
        "mechowo": {"ziemniak": 100, "kapusta": 70, "marchew": 65, "woda": 165, "lopata": 9},
        "puck": {"chleb": 50, "ryz": 45, "woda": 175, "wiertarka": 7},
        "karlinkowo": {"makaron": 52, "wolowina": 22, "ziemniak": 95, "woda": 155, "kilof": 6},
    }

    # People managing cities (from rozmowy.txt)
    people = {
        "natan_rams": ("Natan Rams", "domatowo"),
        "iga_kapecka": ("Iga Kapecka", "opalino"),
        "rafal_kisiel": ("Rafal Kisiel", "brudzewo"),
        "marta_frantz": ("Marta Frantz", "darzlubie"),
        "oskar_radtke": ("Oskar Radtke", "celbowo"),
        "eliza_redmann": ("Eliza Redmann", "mechowo"),
        "damian_kroll": ("Damian Kroll", "puck"),
        "lena_konkel": ("Lena Konkel", "karlinkowo"),
    }

    # Items sold by cities (from transakcje.txt: source -> item -> target)
    # We need: item -> [selling cities]
    transactions = [
        ("darzlubie", "ryz"), ("puck", "marchew"), ("domatowo", "chleb"),
        ("opalino", "wolowina"), ("puck", "kilof"), ("karlinkowo", "wiertarka"),
        ("celbowo", "chleb"), ("brudzewo", "maka"), ("karlinkowo", "mlotek"),
        ("opalino", "makaron"), ("celbowo", "kapusta"), ("domatowo", "ziemniak"),
        ("opalino", "ryz"), ("mechowo", "kilof"), ("brudzewo", "chleb"),
        ("darzlubie", "ziemniak"), ("darzlubie", "kurczak"), ("karlinkowo", "ryz"),
        ("brudzewo", "lopata"), ("puck", "lopata"), ("mechowo", "maka"),
        ("mechowo", "mlotek"), ("celbowo", "kilof"), ("domatowo", "wiertarka"),
    ]

    items_sellers = {}  # item -> set of cities
    for city, item in transactions:
        items_sellers.setdefault(item, set()).add(city)

    log.info("Cities: %d, People: %d, Items: %d", len(cities), len(people), len(items_sellers))

    # === BUILD BATCH ===
    batch = []

    # Reset first
    batch.append({"action": "reset"})

    # Create directories
    batch.append({"action": "createDirectory", "path": "/miasta"})
    batch.append({"action": "createDirectory", "path": "/osoby"})
    batch.append({"action": "createDirectory", "path": "/towary"})

    # Create city files with JSON needs
    for city_name, needs in cities.items():
        content = json.dumps(needs, ensure_ascii=False)
        batch.append({
            "action": "createFile",
            "path": f"/miasta/{city_name}",
            "content": content,
        })

    # Create people files with markdown links
    for filename, (full_name, city) in people.items():
        content = f"{full_name} [miasto](/miasta/{city})"
        batch.append({
            "action": "createFile",
            "path": f"/osoby/{filename}",
            "content": content,
        })

    # Create item files with markdown links to selling cities
    for item, seller_cities in items_sellers.items():
        links = "\n".join(f"[{c}](/miasta/{c})" for c in sorted(seller_cities))
        batch.append({
            "action": "createFile",
            "path": f"/towary/{item}",
            "content": links,
        })

    log.info("Batch has %d operations", len(batch))

    # Send batch
    result = _api(batch)
    log.info("Batch result: %s", json.dumps(result, ensure_ascii=False)[:500])

    # Verify
    done_result = _api({"action": "done"})
    log.info("Done result: %s", json.dumps(done_result, ensure_ascii=False)[:500])

    flag_match = re.search(r"\{FLG:[^}]+\}", json.dumps(done_result))
    if flag_match:
        flag = flag_match.group(0)
        save_result("filesystem", {"action": "done"}, {"code": 0, "message": flag})
        return f"Filesystem created. Flag: {flag}"

    save_result("filesystem", {"action": "done"}, done_result)
    return f"Done result: {json.dumps(done_result, ensure_ascii=False)[:400]}"
