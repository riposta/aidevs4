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
    # Auto-inject API key into URL placeholders from lessons (plain + URL-encoded)
    from urllib.parse import unquote
    url = unquote(url)  # decode %C3%B3 → ó etc.
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


def http_post(url: str, body: str) -> str:
    """POST JSON body to any URL. API key auto-injected for hub.ag3nts.org URLs. Use for APIs that are NOT the main /verify endpoint (e.g. /api/zmail, /api/location, /api/shell). Body must be valid JSON string."""
    from urllib.parse import unquote
    url = unquote(url)
    try:
        body_obj = json.loads(body)
    except json.JSONDecodeError:
        return f"Error: body must be valid JSON, got: {body[:100]}"

    # Auto-inject apikey for hub URLs
    if "ag3nts.org" in url and isinstance(body_obj, dict) and "apikey" not in body_obj:
        body_obj["apikey"] = API_KEY

    log.info("POST %s body=%s", url, str(body_obj)[:200])
    try:
        resp = http.post(url, json=body_obj)
    except Exception as e:
        return f"HTTP error: {e}"

    content_type = resp.headers.get("content-type", "")
    if "json" in content_type:
        try:
            result = resp.json()
            output = json.dumps(result, ensure_ascii=False)
            # Detect flags
            if re.search(r"\{FLG:[^}]+\}", str(output)):
                log.info("FLAG FOUND in POST response")
            if len(output) > 10000:
                return output[:10000] + "\n... (truncated)"
            return output
        except Exception:
            pass
    return resp.text[:10000]


def download_file(url: str, store_key: str) -> str:
    """Download any URL and save content to store under given key. Returns metadata (type, size). For text files saves raw text, for binary saves base64. Does NOT return file content — use get_store(key) or run_python to process."""
    from urllib.parse import unquote
    url = unquote(url)
    url = url.replace("tutaj-twoj-klucz", API_KEY)
    url = url.replace("tutaj-twój-klucz", API_KEY)
    url = url.replace("{API_KEY}", API_KEY)
    log.info("Downloading %s -> store['%s']", url, store_key)
    try:
        resp = http.get(url)
    except Exception as e:
        return f"HTTP error: {e}"

    content_type = resp.headers.get("content-type", "")
    size = len(resp.content)

    if "text" in content_type or "json" in content_type or "csv" in content_type or "xml" in content_type:
        store_put(store_key, resp.text)
        return f"Downloaded text ({content_type}, {size} bytes) -> store['{store_key}']. Use get_store('{store_key}') or run_python to process."
    else:
        b64 = base64.b64encode(resp.content).decode()
        store_put(store_key, b64)
        return f"Downloaded binary ({content_type}, {size} bytes, base64) -> store['{store_key}']. Use run_python: base64.b64decode(_store_get('{store_key}'))"


def store_list() -> str:
    """List all keys currently in the store with their value sizes. Useful to see what data is available."""
    from core.store import _store
    if not _store:
        return "Store is empty"
    lines = []
    for key, value in sorted(_store.items()):
        preview = value[:80].replace("\n", " ") if len(value) <= 80 else value[:80].replace("\n", " ") + "..."
        lines.append(f"  {key}: {len(value)} chars — {preview}")
    return f"Store has {len(_store)} keys:\n" + "\n".join(lines)


def web_session(actions_json: str) -> str:
    """Execute a sequence of HTTP requests with persistent cookies (session). Useful for login flows and web scraping. actions_json is a JSON array of {method, url, data?, extract?} objects. Returns collected results."""
    import requests as req_lib
    actions = json.loads(actions_json)
    session = req_lib.Session()
    results = []

    for i, action in enumerate(actions):
        method = action.get("method", "GET").upper()
        url = action.get("url", "")
        data = action.get("data")
        extract = action.get("extract", "")  # regex to extract from response

        log.info("Session [%d] %s %s", i, method, url)
        try:
            if method == "POST":
                resp = session.post(url, data=data, allow_redirects=True)
            else:
                resp = session.get(url, allow_redirects=True)

            text = resp.text[:5000]
            if extract:
                matches = re.findall(extract, text, re.DOTALL)
                results.append(f"[{i}] {method} {url} -> {resp.status_code}, extracted: {matches[:20]}")
            else:
                results.append(f"[{i}] {method} {url} -> {resp.status_code}, {len(resp.text)} chars")
                if len(resp.text) <= 2000:
                    results.append(text)
        except Exception as e:
            results.append(f"[{i}] {method} {url} -> Error: {e}")

    return "\n".join(results)


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
