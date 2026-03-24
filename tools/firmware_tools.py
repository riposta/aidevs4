import json
import time

from core import http
from core.config import API_KEY, HUB_URL
from core.log import get_logger
from core.store import store_put

log = get_logger("tools.firmware")

SHELL_URL = f"{HUB_URL}/api/shell"


def shell_exec(cmd: str) -> str:
    """Execute a command on the virtual machine shell. Returns command output."""
    payload = {"apikey": API_KEY, "cmd": cmd}
    log.info("Shell: %s", cmd)

    try:
        resp = http.post(SHELL_URL, json=payload)
    except Exception as e:
        return f"HTTP error: {e}"

    if resp.status_code == 429:
        return "Rate limited. Wait a moment and try again."

    if resp.status_code == 403:
        try:
            body = resp.json()
            msg = body.get("message", resp.text[:300])
            seconds = body.get("seconds", "unknown")
            return f"BANNED: {msg} (wait {seconds}s before retrying)"
        except Exception:
            return f"Access denied (banned): {resp.text[:300]}"

    # Parse JSON response (both success and 400 errors contain useful info)
    try:
        data = resp.json()
    except Exception:
        return resp.text[:2000]

    if not isinstance(data, dict):
        return json.dumps(data)[:2000]

    # Error responses (400+) have message field with useful error info
    if resp.status_code >= 400:
        error_msg = data.get("message", "Unknown error")
        return f"Error: {error_msg}"

    message = data.get("message", "")
    payload = data.get("data")

    if payload is not None:
        if isinstance(payload, list):
            result = message + "\n" + "\n".join(str(item) for item in payload)
        elif isinstance(payload, str):
            result = message + "\n" + payload
        else:
            result = message + "\n" + json.dumps(payload)
    else:
        result = message

    return result[:3000]


def firmware_store_answer(confirmation: str) -> str:
    """Store the ECCS confirmation code for submission. Code format: ECCS-xxxx..."""
    if not confirmation.startswith("ECCS-"):
        return f"Error: code must start with ECCS-, got: {confirmation[:20]}. Find the correct code."

    answer = {"confirmation": confirmation}
    store_put("filtered", json.dumps(answer, ensure_ascii=False))
    log.info("Answer stored: %s", confirmation)
    return f"Answer stored: {confirmation}. Now submit with verify skill: submit_answer(task_name='firmware', input_key='filtered')"
