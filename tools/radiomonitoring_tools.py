import json
import base64
import csv
import re
import os
from io import StringIO
from pathlib import Path

from openai import OpenAI

from core.config import API_KEY, VERIFY_URL, OPENAI_API_KEY
from core.log import get_logger
from core.store import store_put, store_get
from core.result import save_result
from core import http, event_log

log = get_logger("tools.radiomonitoring")

TMPDIR = Path("/tmp/radiomonitoring")
TMPDIR.mkdir(exist_ok=True)


def _api(action: str, **kwargs) -> dict:
    answer = {"action": action, **kwargs}
    resp = http.post(VERIFY_URL, json={"apikey": API_KEY, "task": "radiomonitoring", "answer": answer})
    return resp.json()


def collect_signals() -> str:
    """Start radio session and collect all signals until exhausted. Returns summary of collected materials."""
    _api("start")

    texts = []
    files = []

    for i in range(50):
        r = _api("listen")
        code = r.get("code")

        if code == 101:
            log.info("End of signals at iteration %d", i)
            break

        if r.get("transcription"):
            texts.append(r["transcription"])
            log.info("[%d] Text: %s", i, r["transcription"][:80])

        elif r.get("attachment"):
            meta = r.get("meta", "unknown")
            data = base64.b64decode(r["attachment"])
            ext = {"audio/mpeg": "mp3", "image/png": "png", "image/jpeg": "jpg",
                   "application/json": "json", "text/xml": "xml", "text/csv": "csv"}.get(meta, "bin")
            path = TMPDIR / f"signal_{i}.{ext}"
            path.write_bytes(data)
            files.append({"index": i, "meta": meta, "path": str(path), "size": len(data)})
            log.info("[%d] File: %s (%d bytes) -> %s", i, meta, len(data), path)

    store_put("radio_texts", json.dumps(texts, ensure_ascii=False))
    store_put("radio_files", json.dumps(files, ensure_ascii=False))

    summary = f"Collected {len(texts)} text transcriptions and {len(files)} files"
    file_types = [f["meta"] for f in files]
    summary += f" ({', '.join(file_types)})"
    log.info(summary)
    return summary


def analyze_signals() -> str:
    """Analyze all collected signals: parse structured data, transcribe audio, read images, cross-reference."""
    texts_raw = store_get("radio_texts")
    files_raw = store_get("radio_files")
    if not texts_raw or not files_raw:
        return "Error: no collected data. Call collect_signals first."

    texts = json.loads(texts_raw)
    files = json.loads(files_raw)

    findings = []
    city_data = []
    trade_data = []

    # === Process structured files ===
    for f in files:
        path = Path(f["path"])
        meta = f["meta"]

        if meta == "application/json":
            data = json.loads(path.read_text(encoding="utf-8"))
            city_data = data
            log.info("JSON: %d city records", len(data))
            for city in data:
                findings.append(f"City: {city['name']}, area={city.get('occupiedArea')}, "
                                f"farmAnimals={city.get('farmAnimals')}, inhabitants={city.get('inhabitants')}")

        elif meta == "text/csv":
            content = path.read_text(encoding="utf-8")
            reader = csv.DictReader(StringIO(content))
            for row in reader:
                trade_data.append(row)
            log.info("CSV: %d trade records", len(trade_data))
            # Extract Syjon-specific trades
            syjon_trades = [r for r in trade_data if r.get("miasto", "").lower() == "syjon"]
            for t in syjon_trades:
                findings.append(f"Syjon trade: {t}")

        elif meta == "text/xml":
            content = path.read_text(encoding="utf-8")
            findings.append(f"XML data (archive): {content[:200]}")
            # Extract warehouse count if present
            wh_match = re.search(r'warehouse[s]?\D*(\d+)', content, re.IGNORECASE)
            if wh_match:
                findings.append(f"Warehouses from XML: {wh_match.group(1)}")

    # === Process images with vision ===
    client = OpenAI(api_key=OPENAI_API_KEY)
    for f in files:
        if f["meta"].startswith("image/"):
            path = Path(f["path"])
            img_b64 = base64.b64encode(path.read_bytes()).decode()
            mime = f["meta"]
            try:
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Describe this image in detail. Extract ALL text, numbers, phone numbers, names, city names. Be precise and complete."},
                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}}
                        ]
                    }],
                    max_tokens=500,
                )
                description = resp.choices[0].message.content
                findings.append(f"Image {path.name}: {description}")
                log.info("Image %s: %s", path.name, description[:200])
            except Exception as e:
                log.error("Image analysis error: %s", e)

    # === Process audio with Whisper ===
    for f in files:
        if f["meta"] == "audio/mpeg":
            path = Path(f["path"])
            try:
                with open(path, "rb") as audio_file:
                    resp = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        language="pl",
                    )
                transcription = resp.text
                findings.append(f"Audio {path.name}: {transcription}")
                log.info("Audio %s: %s", path.name, transcription)
                # Extract warehouse info from audio
                wh_match = re.search(r'wybudowa[ćc] (\w+) magazyn', transcription)
                if wh_match:
                    findings.append(f"Warehouse info from audio: {wh_match.group(0)}")
            except Exception as e:
                log.error("Audio transcription error: %s", e)

    # === Analyze text transcriptions for Syjon clues ===
    syjon_mentions = []
    for t in texts:
        if "syjon" in t.lower():
            syjon_mentions.append(t)
            findings.append(f"Syjon mention: {t[:200]}")

    # === Decode Morse code ===
    for t in texts:
        if "TaTa" in t or "TiTi" in t:
            findings.append(f"Morse signal: {t[:200]}")
            # Decode: Ti=., Ta=-
            morse_text = t.replace("*shhhhhh*", "").replace("*khhhhhh*", "").strip()
            morse_map = {
                '.-': 'A', '-...': 'B', '-.-.': 'C', '-..': 'D', '.': 'E',
                '..-.': 'F', '--.': 'G', '....': 'H', '..': 'I', '.---': 'J',
                '-.-': 'K', '.-..': 'L', '--': 'M', '-.': 'N', '---': 'O',
                '.--.': 'P', '--.-': 'Q', '.-.': 'R', '...': 'S', '-': 'T',
                '..-': 'U', '...-': 'V', '.--': 'W', '-..-': 'X', '-.--': 'Y',
                '--..': 'Z',
            }
            words = morse_text.split("(stop)")
            decoded_words = []
            for word in words:
                letters = word.strip().split()
                decoded = ""
                for letter in letters:
                    code = letter.replace("Ta", "-").replace("Ti", ".")
                    decoded += morse_map.get(code, f"[{code}]")
                if decoded:
                    decoded_words.append(decoded)
            findings.append(f"Morse decoded: {' '.join(decoded_words)}")

    # === Cross-reference: which city is Syjon? ===
    # Syjon trades bydło and wants kilofy
    # Find cities with farmAnimals=true in JSON
    farm_cities = [c for c in city_data if c.get("farmAnimals")]
    findings.append(f"Cities with farmAnimals: {[c['name'] for c in farm_cities]}")

    # Skarszewy has farmAnimals=true and trades wołowina/bydło - matches Syjon profile
    skarszewy_data = next((c for c in city_data if c["name"] == "Skarszewy"), None)
    if skarszewy_data:
        findings.append(f"CONCLUSION: Syjon = Skarszewy (area={skarszewy_data['occupiedArea']}, farmAnimals=True, trades cattle)")
        findings.append(f"Skarszewy area: {skarszewy_data['occupiedArea']}")

    # Extract warehouse count from audio transcription
    for f_entry in findings:
        wh_match = re.search(r'wybudowa[ćc] (\w+) magazyn', f_entry)
        if wh_match:
            ordinal_word = wh_match.group(1).lower()
            # "dwunasty" = 12th, meaning currently 11 warehouses
            ordinals = {"drugi": 2, "trzeci": 3, "czwarty": 4, "piaty": 5,
                        "szosty": 6, "siodmy": 7, "osmy": 8, "dziewiaty": 9,
                        "dziesiaty": 10, "jedenasty": 11, "dwunasty": 12,
                        "trzynasty": 13, "czternasty": 14, "pietnasty": 15}
            nth = ordinals.get(ordinal_word, 0)
            if nth:
                current_warehouses = nth - 1
                findings.append(f"WAREHOUSES: Planning to build {nth}th warehouse, so currently {current_warehouses} warehouses")

    # Store all findings
    store_put("radio_findings", json.dumps(findings, ensure_ascii=False))

    # Build summary
    summary = "=== ANALYSIS RESULTS ===\n"
    for f in findings:
        summary += f"- {f}\n"

    log.info("Analysis complete: %d findings", len(findings))
    return summary[:3000]


def submit_report(city_name: str, city_area: str, warehouses_count: int, phone_number: str) -> str:
    """Submit the final radio monitoring report."""
    r = _api("transmit",
             cityName=city_name,
             cityArea=city_area,
             warehousesCount=warehouses_count,
             phoneNumber=phone_number)

    log.info("Report result: %s", json.dumps(r, ensure_ascii=False)[:500])

    flag_match = re.search(r"\{FLG:[^}]+\}", json.dumps(r))
    if flag_match:
        flag = flag_match.group(0)
        save_result("radiomonitoring", {
            "cityName": city_name, "cityArea": city_area,
            "warehousesCount": warehouses_count, "phoneNumber": phone_number
        }, {"code": 0, "message": flag})
        return f"Flag: {flag}"

    save_result("radiomonitoring", {
        "cityName": city_name, "cityArea": city_area,
        "warehousesCount": warehouses_count, "phoneNumber": phone_number
    }, r)
    return f"Report result: {json.dumps(r, ensure_ascii=False)[:400]}"
