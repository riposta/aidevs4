"""Generic base tools for the adaptive agent."""
import json
import re
import base64

from core import http
from core.config import API_KEY, VERIFY_URL, HUB_URL
from core.log import get_logger
from core.result import save_result
from core.store import store_put, store_get

log = get_logger("tools.base")


def call_task_api(task: str, answer: str) -> str:
    """Send answer to task API. Provide ONLY the answer content as JSON string — apikey and task are added automatically. Example: call_task_api("railway", '{"action": "help"}'). Returns response JSON. Auto-detects flags."""
    try:
        answer_obj = json.loads(answer)
    except json.JSONDecodeError:
        return f"Error: answer must be valid JSON string, got: {answer[:100]}"

    # If agent accidentally included full payload with apikey/task, extract just the answer
    if isinstance(answer_obj, dict) and "answer" in answer_obj and "task" in answer_obj:
        answer_obj = answer_obj["answer"]

    payload = {"apikey": API_KEY, "task": task, "answer": answer_obj}
    log.info("API call: task=%s answer=%s", task, str(answer_obj)[:200])

    try:
        resp = http.post(VERIFY_URL, json=payload)
    except Exception as e:
        return f"HTTP error: {e}"

    try:
        result = resp.json()
    except Exception:
        return f"Response (status {resp.status_code}): {resp.text[:2000]}"

    output = json.dumps(result, ensure_ascii=False)
    log.info("Response: %s", output[:500])

    # Detect flag
    msg = result.get("message", "")
    if re.search(r"\{FLG:[^}]+\}", str(msg)):
        log.info("FLAG FOUND: %s", msg)
        save_result(task, answer_obj, result)
        return f"FLAG FOUND: {msg}"

    return output


def fetch_url(url: str) -> str:
    """Fetch content from any URL. API key is auto-injected into URLs containing placeholders. Returns text (max 50KB) or for binary: saves to store and returns metadata."""
    # Auto-inject API key into URL placeholders from lessons
    url = url.replace("tutaj-twoj-klucz", API_KEY)
    url = url.replace("tutaj-twój-klucz", API_KEY)
    url = url.replace("{API_KEY}", API_KEY)
    url = url.replace("{apikey}", API_KEY)
    log.info("Fetching: %s", url)
    try:
        resp = http.get(url)
    except Exception as e:
        return f"HTTP error: {e}"

    content_type = resp.headers.get("content-type", "")
    content_length = len(resp.content)

    if "text" in content_type or "json" in content_type or "csv" in content_type or "xml" in content_type:
        text = resp.text[:50000]
        if len(resp.text) > 50000:
            text += f"\n... (truncated, total {len(resp.text)} bytes)"
        return text

    # Binary content — save to store, return metadata only (don't bloat context)
    b64 = base64.b64encode(resp.content).decode()
    store_key = f"_file_{url.split('/')[-1]}"
    store_put(store_key, b64)
    return f"Binary file downloaded: {content_type}, {content_length} bytes, saved to store key '{store_key}'. Use run_python to process it: data = base64.b64decode(_store_get('{store_key}'))"


def put_store(key: str, value: str) -> str:
    """Store a value under a key for later retrieval. Use for passing data between steps."""
    store_put(key, value)
    preview = value[:200] + "..." if len(value) > 200 else value
    return f"Stored {len(value)} chars under '{key}': {preview}"


def get_store(key: str) -> str:
    """Retrieve a value from the store by key. Returns the stored string or error if not found."""
    value = store_get(key)
    if value is None:
        return f"Error: key '{key}' not found in store"
    return value
