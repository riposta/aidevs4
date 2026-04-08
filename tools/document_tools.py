import json
import re
import base64
from datetime import date

from openai import OpenAI

from core import http, event_log
from core.config import API_KEY, HUB_URL, OPENAI_API_KEY, VERIFY_URL
from core.log import get_logger
from core.result import save_result
from core.store import store_put, store_get

log = get_logger("tools.document")

# === Sendit ===

DOC_BASE = f"{HUB_URL}/dane/doc"


def fetch_spk_doc(filename: str) -> str:
    """Fetch a text documentation file from SPK docs. Returns file content."""
    url = f"{DOC_BASE}/{filename}"
    log.info("Fetching doc: %s", url)
    resp = http.get(url)
    resp.raise_for_status()
    content = resp.text
    log.info("Fetched %s (%d chars)", filename, len(content))

    # Store for reference
    store_put(f"doc:{filename}", content)

    # Return truncated for context
    if len(content) > 3000:
        return content[:3000] + f"\n\n... [truncated, full content stored as doc:{filename}]"
    return content


def fetch_spk_image(filename: str) -> str:
    """Fetch an image file from SPK docs and describe its content using vision. Returns text description."""
    url = f"{DOC_BASE}/{filename}"
    log.info("Fetching image: %s", url)
    resp = http.get(url)
    resp.raise_for_status()

    img_b64 = base64.b64encode(resp.content).decode()
    mime = "image/png" if filename.endswith(".png") else "image/jpeg"

    client = OpenAI(api_key=OPENAI_API_KEY)
    vision_resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this image in detail. If it contains a table, reproduce the full table content as text with all rows and columns. Be precise with all codes, names, and values."},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
            ],
        }],
        max_tokens=2000,
    )
    description = vision_resp.choices[0].message.content
    log.info("Image %s described: %s", filename, description[:200])
    store_put(f"img:{filename}", description)
    return description


def build_declaration(
    punkt_nadawczy: str,
    nadawca: str,
    punkt_docelowy: str,
    trasa: str,
    kategoria: str,
    opis_zawartosci: str,
    masa_kg: int,
    wdp: int,
    uwagi: str,
    kwota: str,
) -> str:
    """Build SPK declaration from provided fields. Formats exactly per template. Stores under 'filtered'."""
    today = date.today().isoformat()

    declaration = (
        "SYSTEM PRZESYŁEK KONDUKTORSKICH - DEKLARACJA ZAWARTOŚCI\n"
        "======================================================\n"
        f"DATA: {today}\n"
        f"PUNKT NADAWCZY: {punkt_nadawczy}\n"
        "------------------------------------------------------\n"
        f"NADAWCA: {nadawca}\n"
        f"PUNKT DOCELOWY: {punkt_docelowy}\n"
        f"TRASA: {trasa}\n"
        "------------------------------------------------------\n"
        f"KATEGORIA PRZESYŁKI: {kategoria}\n"
        "------------------------------------------------------\n"
        f"OPIS ZAWARTOŚCI (max 200 znaków): {opis_zawartosci}\n"
        "------------------------------------------------------\n"
        f"DEKLAROWANA MASA (kg): {masa_kg}\n"
        "------------------------------------------------------\n"
        f"WDP: {wdp}\n"
        "------------------------------------------------------\n"
        f"UWAGI SPECJALNE: {uwagi}\n"
        "------------------------------------------------------\n"
        f"KWOTA DO ZAPŁATY: {kwota}\n"
        "------------------------------------------------------\n"
        "OŚWIADCZAM, ŻE PODANE INFORMACJE SĄ PRAWDZIWE.\n"
        "BIORĘ NA SIEBIE KONSEKWENCJĘ ZA FAŁSZYWE OŚWIADCZENIE.\n"
        "======================================================"
    )

    # Store as answer for verify skill (must be JSON object, not string)
    store_put("filtered", json.dumps({"declaration": declaration}, ensure_ascii=False))

    log.info("Declaration built and stored under 'filtered'")
    return f"Declaration built:\n{declaration}"


# === Filesystem ===


def _filesystem_api(answer) -> dict:
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
    result = _filesystem_api(batch)
    log.info("Batch result: %s", json.dumps(result, ensure_ascii=False)[:500])

    # Verify
    done_result = _filesystem_api({"action": "done"})
    log.info("Done result: %s", json.dumps(done_result, ensure_ascii=False)[:500])

    flag_match = re.search(r"\{FLG:[^}]+\}", json.dumps(done_result))
    if flag_match:
        flag = flag_match.group(0)
        save_result("filesystem", {"action": "done"}, {"code": 0, "message": flag})
        return f"Filesystem created. Flag: {flag}"

    save_result("filesystem", {"action": "done"}, done_result)
    return f"Done result: {json.dumps(done_result, ensure_ascii=False)[:400]}"


# === Food Warehouse ===


def _foodwarehouse_api(answer) -> dict:
    resp = http.post(VERIFY_URL, json={"apikey": API_KEY, "task": "foodwarehouse", "answer": answer})
    return resp.json()


def build_orders() -> str:
    """Build all warehouse orders: reset, fetch data, create orders with signatures, append items, done."""

    # Reset
    r = _foodwarehouse_api({"tool": "reset"})
    log.info("Reset: %s", r.get("message"))

    # Fetch food4cities
    resp = http.get("https://hub.ag3nts.org/dane/food4cities.json")
    cities_needs = resp.json()
    log.info("Cities: %s", list(cities_needs.keys()))

    # Get destinations for our cities
    dest_map = {}
    for city in cities_needs:
        r = _foodwarehouse_api({"tool": "database", "query": f"select * from destinations where name = '{city.capitalize()}'"})
        rows = r.get("rows", [])
        if rows:
            dest_map[city] = str(rows[0]["destination_id"])
            log.info("Destination %s: %s", city, dest_map[city])
        else:
            # Try exact case
            r2 = _foodwarehouse_api({"tool": "database", "query": f"select * from destinations where lower(name) = '{city.lower()}'"})
            rows2 = r2.get("rows", [])
            if rows2:
                dest_map[city] = str(rows2[0]["destination_id"])
                log.info("Destination %s: %s (fallback)", city, dest_map[city])
            else:
                log.error("No destination found for %s", city)

    # Get a transport user (role=2, active)
    r = _foodwarehouse_api({"tool": "database", "query": "select * from users where role = 2 and is_active = 1 limit 1"})
    user = r["rows"][0]
    user_id = user["user_id"]
    login = user["login"]
    birthday = user["birthday"]
    log.info("Creator: id=%d, login=%s, birthday=%s", user_id, login, birthday)

    # For each city: generate signature, create order, append items
    for city, needs in cities_needs.items():
        dest = dest_map.get(city)
        if not dest:
            log.error("Skipping %s - no destination", city)
            continue

        # Generate signature
        sig_r = _foodwarehouse_api({
            "tool": "signatureGenerator",
            "action": "generate",
            "login": login,
            "birthday": birthday,
            "destination": dest,
        })
        signature = sig_r.get("hash", "")
        log.info("%s: signature=%s", city, signature[:16])

        # Create order
        create_r = _foodwarehouse_api({
            "tool": "orders",
            "action": "create",
            "title": f"Dostawa dla {city.capitalize()}",
            "creatorID": user_id,
            "destination": dest,
            "signature": signature,
        })
        order_id = create_r.get("id") or create_r.get("orderID") or (create_r.get("order", {}) or {}).get("id")
        log.info("%s: order created id=%s code=%s", city, order_id, create_r.get("code"))

        if not order_id:
            log.error("Failed to create order for %s: %s", city, json.dumps(create_r)[:200])
            continue

        # Append items (batch)
        append_r = _foodwarehouse_api({
            "tool": "orders",
            "action": "append",
            "id": order_id,
            "items": needs,
        })
        log.info("%s: items appended code=%s", city, append_r.get("code"))

    # Verify
    done_r = _foodwarehouse_api({"tool": "done"})
    log.info("Done: %s", json.dumps(done_r, ensure_ascii=False)[:500])

    flag_match = re.search(r"\{FLG:[^}]+\}", json.dumps(done_r))
    if flag_match:
        flag = flag_match.group(0)
        save_result("foodwarehouse", {"tool": "done"}, {"code": 0, "message": flag})
        return f"All orders created. Flag: {flag}"

    save_result("foodwarehouse", {"tool": "done"}, done_r)
    return f"Done: {json.dumps(done_r, ensure_ascii=False)[:400]}"
