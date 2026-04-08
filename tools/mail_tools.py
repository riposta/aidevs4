import json

from core import http
from core.config import API_KEY, HUB_URL
from core.log import get_logger
from core.store import store_put

log = get_logger("tools.mail")

ZMAIL_URL = f"{HUB_URL}/api/zmail"


def mailbox_search(query: str, page: int = 1) -> str:
    """Search emails with Gmail-like query (from:, subject:, OR, AND). Returns list of matching emails."""
    payload = {"apikey": API_KEY, "action": "search", "query": query, "page": page, "perPage": 20}
    log.info("Searching: %s (page %d)", query, page)
    resp = http.post(ZMAIL_URL, json=payload)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("ok"):
        return f"Error: {data.get('error', 'unknown')}"

    items = data.get("items", [])
    total = data.get("pagination", {}).get("total", 0)
    lines = [f"Found {total} results (showing {len(items)}):"]
    for item in items:
        lines.append(
            f"  rowID={item['rowID']} msgID={item['messageID'][:12]}... "
            f"from={item['from']} date={item['date']} "
            f"subject=\"{item['subject']}\" snippet=\"{item.get('snippet', '')[:80]}\""
        )
    return "\n".join(lines)


def mailbox_read(message_id: str) -> str:
    """Read full email content by messageID (32-char hash)."""
    payload = {"apikey": API_KEY, "action": "getMessages", "ids": message_id}
    log.info("Reading message: %s", message_id)
    resp = http.post(ZMAIL_URL, json=payload)
    resp.raise_for_status()
    data = resp.json()

    if data.get("notFound"):
        return f"Message not found: {message_id}. Try mailbox_read_by_row with the rowID instead."

    items = data.get("items", [])
    if not items:
        return "No message returned."

    msg = items[0]
    return (
        f"From: {msg['from']}\nTo: {msg['to']}\nDate: {msg['date']}\n"
        f"Subject: {msg['subject']}\n\n{msg['message']}"
    )


def mailbox_read_by_row(row_id: int) -> str:
    """Read full email content by rowID (numeric). Use when messageID lookup fails."""
    payload = {"apikey": API_KEY, "action": "getMessages", "ids": row_id}
    log.info("Reading row: %d", row_id)
    resp = http.post(ZMAIL_URL, json=payload)
    resp.raise_for_status()
    data = resp.json()

    items = data.get("items", [])
    if not items:
        return f"No message at rowID {row_id}."

    msg = items[0]
    return (
        f"From: {msg['from']}\nTo: {msg['to']}\nDate: {msg['date']}\n"
        f"Subject: {msg['subject']}\n\n{msg['message']}"
    )


def mailbox_store_answer(date: str, password: str, confirmation_code: str) -> str:
    """Store the three found values as answer for submission. Date=YYYY-MM-DD, code=SEC-+32chars."""
    if len(confirmation_code) != 36:
        return f"Error: confirmation_code must be 36 chars, got {len(confirmation_code)}. Find the correct code."

    answer = {"date": date, "password": password, "confirmation_code": confirmation_code}
    store_put("filtered", json.dumps(answer, ensure_ascii=False))
    log.info("Answer stored: date=%s, password=%s, code=%s", date, password, confirmation_code)
    return f"Answer stored. date={date}, password={password}, code={confirmation_code}. Now submit with verify skill."
