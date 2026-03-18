import re
from collections import defaultdict

import requests
import tiktoken

from core.config import API_KEY, HUB_URL, VERIFY_URL
from core.log import get_logger
from core.store import store_put, store_get

log = get_logger("tools.failure")

LOG_URL = f"{HUB_URL}/data/{API_KEY}/failure.log"
ENC = tiktoken.encoding_for_model("gpt-4o")
SEVERITIES = ("INFO", "WARN", "ERRO", "CRIT")
LINE_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}):\d{2}\] \[(WARN|ERRO|CRIT)\] (.+)")
COMP_RE = re.compile(r"\b([A-Z][A-Z0-9_]*\d[A-Z0-9]*)\b|\b([A-Z]{3,})\b")
TOKEN_BUDGET = 1450


def _detect_components(lines):
    """Auto-detect component names from log lines by frequency analysis."""
    freq = defaultdict(int)
    for line in lines:
        for m in COMP_RE.finditer(line):
            name = m.group(1) or m.group(2)
            if name not in SEVERITIES:
                freq[name] += 1
    # Components appear many times; filter out rare words (< 5 occurrences)
    return {name for name, count in freq.items() if count >= 5}


def _extract_components(msg, known_components):
    """Extract all known components mentioned in a message.
    Returns list of component names in order of appearance.
    Falls back to regex if no known component found."""
    found = []
    for comp in known_components:
        idx = msg.find(comp)
        if idx != -1:
            found.append((idx, comp))
    if found:
        found.sort()
        return [comp for _, comp in found]
    m = COMP_RE.search(msg)
    if m:
        return [m.group(1) or m.group(2)]
    return ["UNKNOWN"]


def _shorten_message(msg, comp, max_len=80):
    """Generic message shortening: take key parts from first two sentences.
    Ensures the component name is always visible in the output."""
    sentences = [s.strip() for s in msg.split(".") if s.strip()]
    # Take first sentence; if too long, truncate
    result = sentences[0][:max_len] if sentences else msg[:max_len]
    # If there's a second sentence with new info, append key part
    if len(sentences) > 1 and len(result) < max_len - 15:
        second = sentences[1][:max_len - len(result) - 2]
        result = f"{result}. {second}"
    if len(result) > max_len:
        result = result[:max_len]
    # If component name got lost during truncation, prefix it
    if comp not in result:
        result = f"{comp}: {result}"
    return result


def _msg_signature(msg):
    """Normalize message for deduplication — remove changing numbers, truncate."""
    return re.sub(r"\d+\.?\d*", "N", msg)[:80]


def failure_fetch_logs() -> str:
    """Fetch the full failure log file and store it. Returns summary stats."""
    resp = requests.get(LOG_URL)
    resp.raise_for_status()
    text = resp.text.strip()
    lines = text.split("\n")
    store_put("failure_raw", text)

    counts = defaultdict(int)
    for line in lines:
        m = re.search(r"\[(INFO|WARN|ERRO|CRIT)\]", line)
        if m:
            counts[m.group(1)] += 1

    components = _detect_components(lines)

    summary = (
        f"Fetched {len(lines)} log lines.\n"
        f"Severity: INFO={counts['INFO']}, WARN={counts['WARN']}, ERRO={counts['ERRO']}, CRIT={counts['CRIT']}\n"
        f"Components found: {', '.join(sorted(components))}\n"
        f"Total tokens: {len(ENC.encode(text))}"
    )
    log.info(summary)
    return summary


def failure_search_logs(severity: str, component: str) -> str:
    """Search logs by severity (CRIT/ERRO/WARN/INFO or ALL) and component (name or ALL). Returns matching lines."""
    raw = store_get("failure_raw")
    if not raw:
        return "Error: logs not loaded. Call failure_fetch_logs first."

    lines = raw.split("\n")
    results = []
    for line in lines:
        sev_match = severity == "ALL" or f"[{severity}]" in line
        comp_match = component == "ALL" or component in line
        if sev_match and comp_match:
            results.append(line)

    if not results:
        return f"No lines matching severity={severity}, component={component}"

    tokens = len(ENC.encode("\n".join(results)))
    return f"Found {len(results)} lines ({tokens} tokens):\n" + "\n".join(results[:100])


def failure_compress_logs() -> str:
    """Compress logs: auto-detect components, deduplicate by message signature, keep CRIT + up to N ERRO/WARN per component. Fits within 1500 tokens."""
    raw = store_get("failure_raw")
    if not raw:
        return "Error: logs not loaded. Call failure_fetch_logs first."

    lines = raw.split("\n")
    known_components = _detect_components(lines)

    # Parse all non-INFO lines; create entry for each component mentioned
    events = []
    for line in lines:
        m = LINE_RE.match(line)
        if m:
            date, time, sev, msg = m.groups()
            comps = _extract_components(msg, known_components)
            for comp in comps:
                events.append({"date": date, "time": time, "sev": sev,
                               "comp": comp, "msg": msg})

    # Group by (component, message_signature), keep first and last occurrence
    groups = defaultdict(list)
    for e in events:
        key = (e["comp"], _msg_signature(e["msg"]))
        groups[key].append(e)

    deduped = []
    for (comp, sig), evts in groups.items():
        deduped.append(evts[0])
        if len(evts) > 1 and evts[-1]["time"] != evts[0]["time"]:
            deduped.append(evts[-1])
    deduped.sort(key=lambda e: (e["date"], e["time"]))

    # Shorten each line
    short_lines = []
    for e in deduped:
        short = _shorten_message(e["msg"], e["comp"])
        short_lines.append({
            "text": f"[{e['date']} {e['time']}] [{e['sev']}] {short}",
            "sev": e["sev"], "comp": e["comp"],
            "msg_key": _msg_signature(e["msg"])
        })

    # Assemble: all unique CRIT + up to N unique ERRO/WARN per component
    crit = []
    erro_by_comp = defaultdict(list)
    warn_by_comp = defaultdict(list)
    seen_crit = set()

    for sl in short_lines:
        if sl["sev"] == "CRIT":
            key = sl["text"][24:]  # after timestamp
            if key not in seen_crit:
                seen_crit.add(key)
                crit.append(sl["text"])
        elif sl["sev"] == "ERRO":
            erro_by_comp[sl["comp"]].append(sl)
        elif sl["sev"] == "WARN":
            warn_by_comp[sl["comp"]].append(sl)

    def pick_unique(items, max_n):
        seen = set()
        picked = []
        for item in items:
            key = item["msg_key"]
            if key not in seen:
                seen.add(key)
                picked.append(item["text"])
                if len(picked) >= max_n:
                    break
        return picked

    # Try progressively smaller per-component limits until within budget
    for max_per in (3, 2, 1):
        base = list(crit)
        for comp_lines in erro_by_comp.values():
            base.extend(pick_unique(comp_lines, max_per))
        for comp_lines in warn_by_comp.values():
            base.extend(pick_unique(comp_lines, max_per))
        base.sort()
        result = "\n".join(base)
        tokens = len(ENC.encode(result))
        if tokens <= TOKEN_BUDGET:
            break

    store_put("failure_compressed", result)
    log.info("Compressed to %d lines, %d tokens", len(base), tokens)
    return (f"Compressed log: {len(base)} lines, {tokens} tokens.\n\n"
            f"Preview (first 20 lines):\n" + "\n".join(base[:20]))


def failure_submit() -> str:
    """Submit compressed logs to verification. Reads from store key 'failure_compressed'."""
    compressed = store_get("failure_compressed")
    if not compressed:
        return "Error: no compressed logs. Call failure_compress_logs first."

    tokens = len(ENC.encode(compressed))
    if tokens > 1500:
        return f"Error: compressed logs are {tokens} tokens, exceeds 1500 limit. Compress further."

    payload = {
        "apikey": API_KEY,
        "task": "failure",
        "answer": {"logs": compressed},
    }
    log.info("Submitting %d tokens of compressed logs", tokens)
    resp = requests.post(VERIFY_URL, json=payload)
    data = resp.json()
    message = data.get("message", "")
    log.info("Submit result: %s", message[:500])

    if "FLG:" in message:
        store_put("filtered", message)
        return f"FLAG FOUND: {message}"

    return f"Response (code={data.get('code')}): {message}"


def failure_update_logs(additional_lines: str) -> str:
    """Add lines to compressed logs. Use when feedback says something is missing."""
    compressed = store_get("failure_compressed")
    if not compressed:
        return "Error: no compressed logs. Call failure_compress_logs first."

    updated = compressed + "\n" + additional_lines.strip()
    lines = updated.strip().split("\n")
    lines.sort()
    result = "\n".join(lines)
    tokens = len(ENC.encode(result))

    store_put("failure_compressed", result)
    return f"Updated compressed logs: {len(lines)} lines, {tokens} tokens"
