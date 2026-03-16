import json
import base64
from datetime import date

from openai import OpenAI

from core import http
from core.config import API_KEY, HUB_URL, OPENAI_API_KEY
from core.log import get_logger
from core.store import store_put, store_get

log = get_logger("tools.sendit")

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

    # Store as answer for verify skill
    answer = json.dumps({"declaration": declaration}, ensure_ascii=False)
    store_put("filtered", answer)

    log.info("Declaration built and stored under 'filtered'")
    return f"Declaration built:\n{declaration}"
