import json
import base64
import re
import time

from openai import OpenAI

from core.config import API_KEY, VERIFY_URL, OPENAI_API_KEY
from core.log import get_logger
from core.store import store_put
from core.result import save_result
from core import http, event_log

log = get_logger("tools.audio")


_tts_cache = {}

def _tts(text: str, regenerate: bool = False) -> bytes:
    """Generate TTS audio, cached per text."""
    if text in _tts_cache and not regenerate:
        return _tts_cache[text]
    client = OpenAI(api_key=OPENAI_API_KEY)
    resp = client.audio.speech.create(
        model="gpt-4o-mini-tts-2025-12-15", voice="echo", input=text, response_format="mp3",
        instructions="Mów po polsku naturalnie jak człowiek. Spokojny ton służbowej rozmowy telefonicznej. Dodawaj naturalne pauzy."
    )
    _tts_cache[text] = resp.content
    return resp.content


def _transcribe(audio_bytes: bytes) -> str:
    """Transcribe audio to text."""
    client = OpenAI(api_key=OPENAI_API_KEY)
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(audio_bytes)
        f.flush()
        with open(f.name, "rb") as af:
            resp = client.audio.transcriptions.create(model="whisper-1", file=af, language="pl")
        os.unlink(f.name)
    return resp.text


def _send_audio(audio_bytes: bytes) -> dict:
    """Send audio to the phonecall API and return response."""
    b64 = base64.b64encode(audio_bytes).decode()
    resp = http.post(VERIFY_URL, json={
        "apikey": API_KEY,
        "task": "phonecall",
        "answer": {"audio": b64},
    })
    return resp.json()


def _say_and_listen(text: str) -> tuple[dict, str]:
    """Generate TTS, send to API, transcribe response. Returns (raw_response, transcription)."""
    log.info("Saying: %s", text)
    event_log.emit("user", agent="phonecall", content=text)

    audio = _tts(text)
    result = _send_audio(audio)
    log.info("API response code=%s msg=%s", result.get("code"), result.get("message", "")[:100])

    # Transcribe operator response if audio present
    transcription = ""
    if result.get("audio"):
        resp_audio = base64.b64decode(result["audio"])
        transcription = _transcribe(resp_audio)
        log.info("Operator: %s", transcription)
        event_log.emit("response", agent="phonecall", content=f"Operator: {transcription}")
    elif result.get("transcription"):
        transcription = result["transcription"]
        log.info("Operator (text): %s", transcription)

    return result, transcription


def _is_rejection(text: str) -> bool:
    """Check if operator rejected the message."""
    t = text.lower()
    return any(w in t for w in ["kręcisz", "zgłosić", "nie brzmi", "bot od", "nie kupię"])


def conduct_phonecall() -> str:
    """Conduct the complete phone call conversation to find passable roads and disable monitoring."""

    max_attempts = 5
    for attempt in range(max_attempts):
        log.info("=== ATTEMPT %d/%d ===", attempt + 1, max_attempts)
        if attempt > 0:
            _tts_cache.clear()  # Regenerate audio for each retry
        result = _attempt_phonecall()
        if result.startswith("Flag:") or "FLG" in result:
            return result
        if "rejected" not in result.lower():
            return result
        log.info("Attempt %d failed, retrying...", attempt + 1)
        time.sleep(2)

    return f"All {max_attempts} attempts failed"


def _attempt_phonecall() -> str:
    """Single attempt at the phone conversation."""

    # Step 0: Start session
    start_r = http.post(VERIFY_URL, json={
        "apikey": API_KEY, "task": "phonecall", "answer": {"action": "start"}
    }).json()
    log.info("Session started: %s", start_r.get("message"))
    event_log.emit("system", agent="phonecall", content=f"Session: {start_r.get('message')}")
    time.sleep(1)

    # Step 1: Introduce yourself
    r1, t1 = _say_and_listen("Halo, dzień dobry. Mówi Tymon Gajewski.")

    # Check for flag in any response
    for r in [r1]:
        flag = re.search(r"\{FLG:[^}]+\}", json.dumps(r))
        if flag:
            save_result("phonecall", {}, {"code": 0, "message": flag.group(0)})
            return f"Flag: {flag.group(0)}"

    # Step 2: Ask about roads + mention Zygfryd transport
    r2, t2 = _say_and_listen(
        "Dzwonię w sprawie statusu trzech dróg: RD224, RD472 i RD820. "
        "Pytam ze względu na transport organizowany do jednej z baz Zygfryda."
    )

    for r in [r2]:
        flag = re.search(r"\{FLG:[^}]+\}", json.dumps(r))
        if flag:
            save_result("phonecall", {}, {"code": 0, "message": flag.group(0)})
            return f"Flag: {flag.group(0)}"

    if _is_rejection(t2):
        return f"REJECTED at step 2: {t2[:100]}"

    # Parse which roads are passable from operator response
    passable_roads = []
    blocked_roads = []
    # Split into sentences and check each road in its sentence context
    t2_norm = t2.lower().replace("rd-", "rd")
    sentences = re.split(r'[.!?]+', t2_norm)

    for sentence in sentences:
        for road_id in ["rd224", "rd472", "rd820"]:
            if road_id in sentence:
                if any(w in sentence for w in ["nieprzejezdn", "zamknięt", "zablokow", "awari",
                                                "uszkodzon", "niesprawna", "niedrożn"]):
                    blocked_roads.append(road_id.upper())
                else:
                    passable_roads.append(road_id.upper())

    # Handle "Podobnie RD-224" (refers to previous negative sentence)
    for sentence in sentences:
        s = sentence.strip()
        if s.startswith("podobnie") or s.startswith("tak samo") or s.startswith("również"):
            for road_id in ["rd224", "rd472", "rd820"]:
                if road_id in s and road_id.upper() not in blocked_roads:
                    passable_roads = [r for r in passable_roads if r != road_id.upper()]
                    blocked_roads.append(road_id.upper())

    log.info("Detected passable: %s, blocked: %s (from: %s)", passable_roads, blocked_roads, t2[:200])

    # Step 3: Ask to disable monitoring on passable roads with password
    roads_str = " i ".join(passable_roads) if passable_roads else "RD820"
    r3, t3 = _say_and_listen(
        f"Proszę o wyłączenie monitoringu na drodze {roads_str}. "
        f"Chcemy wyłączyć monitoring ze względu na tajny transport żywności do jednej z tajnych baz Zygfryda. "
        f"Hasło: BARBAKAN."
    )

    for r in [r3]:
        flag = re.search(r"\{FLG:[^}]+\}", json.dumps(r))
        if flag:
            save_result("phonecall", {"passable_roads": passable_roads}, {"code": 0, "message": flag.group(0)})
            return f"Flag: {flag.group(0)}"

    log.info("Step 3 response: %s", t3[:300])

    if _is_rejection(t3):
        return f"REJECTED at step 3: {t3[:100]}"

    # Follow-up if operator asked something
    for i in range(3):
        if not t3 or re.search(r"\{FLG:", json.dumps(r3)):
            break

        # Respond based on what operator said
        if "hasło" in t3.lower() or "autoryz" in t3.lower():
            r3, t3 = _say_and_listen("Hasło autoryzacyjne to BARBAKAN.")
        elif "potwierdz" in t3.lower():
            r3, t3 = _say_and_listen("Potwierdzam.")
        else:
            r3, t3 = _say_and_listen("Tak, potwierdzam. Dziękuję.")

        flag = re.search(r"\{FLG:[^}]+\}", json.dumps(r3))
        if flag:
            save_result("phonecall", {"passable_roads": passable_roads}, {"code": 0, "message": flag.group(0)})
            return f"Flag: {flag.group(0)}"

        if _is_rejection(t3):
            return f"REJECTED at follow-up: {t3[:100]}"

    # Return conversation summary
    summary = (
        f"Conversation completed.\n"
        f"Step 1 (intro): {t1[:100]}\n"
        f"Step 2 (roads): {t2[:200]}\n"
        f"Step 3 (monitoring): {t3[:200]}\n"
        f"Passable roads detected: {passable_roads}"
    )
    save_result("phonecall", {"passable_roads": passable_roads}, {"message": summary})
    return summary
