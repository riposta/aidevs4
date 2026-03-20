import json

from core import http
from core.config import API_KEY, VERIFY_URL
from core.log import get_logger
from core.store import store_put

log = get_logger("tools.drone")


def drone_submit(instructions: str) -> str:
    """Submit drone flight instructions as JSON array of command strings. Returns API response."""
    try:
        instr_list = json.loads(instructions)
    except json.JSONDecodeError:
        return "Error: instructions must be a valid JSON array of strings."

    payload = {
        "apikey": API_KEY,
        "task": "drone",
        "answer": {"instructions": instr_list},
    }
    log.info("Submitting %d instructions", len(instr_list))
    resp = http.post(VERIFY_URL, json=payload)
    resp.raise_for_status()
    data = resp.json()

    msg = data.get("message", "")
    code = data.get("code", -1)

    if "FLG:" in msg:
        store_put("filtered", json.dumps({"instructions": instr_list}, ensure_ascii=False))
        log.info("FLAG received: %s", msg)
        return f"SUCCESS! Flag: {msg}"

    log.info("Response (code=%d): %s", code, msg[:200])
    return f"API response (code={code}): {msg}"
