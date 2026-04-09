import json
import hashlib
import random
import re
import time

from openai import OpenAI

from core.config import API_KEY, OPENAI_API_KEY, VERIFY_URL
from core.log import get_logger
from core.store import store_put
from core.result import save_result
from core import http, event_log

log = get_logger("tools.rocket")

BASE_URL = "https://hub.ag3nts.org"
SCANNER_URL = f"{BASE_URL}/api/frequencyScanner"
HINT_URL = f"{BASE_URL}/api/getmessage"
MAX_RETRIES = 8


def _send_game_command(command: str) -> dict:
    """Send a command to the goingthere game API."""
    payload = {
        "apikey": API_KEY,
        "task": "goingthere",
        "answer": {"command": command},
    }
    for attempt in range(MAX_RETRIES):
        try:
            resp = http.post(VERIFY_URL, json=payload)
            data = resp.json()
            log.info("Game command '%s' -> %s", command, json.dumps(data, ensure_ascii=False)[:300])
            return data
        except Exception as e:
            log.warning("Game command '%s' failed (attempt %d): %s", command, attempt + 1, e)
            time.sleep(1)
    raise RuntimeError(f"Game command '{command}' failed after {MAX_RETRIES} retries")


def _check_scanner() -> str:
    """Check frequency scanner. Returns raw text (may be corrupted)."""
    url = f"{SCANNER_URL}?key={API_KEY}"
    for attempt in range(MAX_RETRIES):
        try:
            resp = http.get(url)
            text = resp.text
            log.info("Scanner response (%d bytes): %s", len(text), text[:300])
            # Skip HTML error pages (502, etc.)
            if "<html" in text.lower() or "<!doctype" in text.lower():
                log.warning("Got HTML error page from scanner, retrying...")
                time.sleep(1)
                continue
            return text
        except Exception as e:
            log.warning("Scanner check failed (attempt %d): %s", attempt + 1, e)
            time.sleep(1)
    raise RuntimeError(f"Scanner check failed after {MAX_RETRIES} retries")


def _is_clear(raw: str) -> bool:
    """Check if scanner says it's clear (handles corrupted text)."""
    cleaned = re.sub(r'[^a-zA-Z\s]', '', raw).lower().strip()
    # Collapse repeated letters: "cleeeeeeear" -> "clear"
    collapsed = re.sub(r'(.)\1+', r'\1', cleaned)
    return "clear" in cleaned or "clear" in collapsed or "clr" in cleaned


def _extract_trap_fields(raw: str) -> dict | None:
    """Try to extract frequency and detectionCode from potentially corrupted scanner response."""
    if _is_clear(raw):
        return None

    # Try standard JSON parse first
    try:
        data = json.loads(raw)
        if "frequency" in data and "detectionCode" in data:
            return {"frequency": data["frequency"], "detectionCode": data["detectionCode"]}
    except (json.JSONDecodeError, TypeError):
        pass

    # Try parsing as JSON if wrapped in quotes or has extra chars
    # Remove leading/trailing whitespace and quotes
    stripped = raw.strip().strip('"').strip("'")
    try:
        data = json.loads(stripped)
        if "frequency" in data and "detectionCode" in data:
            return {"frequency": data["frequency"], "detectionCode": data["detectionCode"]}
    except (json.JSONDecodeError, TypeError):
        pass

    # Regex fallback for corrupted JSON (case-insensitive, tolerant of corrupted quotes)
    # Handle letter substitutions: d->b, o->0, etc. Match "frequency"/"frepuency"/"fr3quency" etc.
    freq_match = re.search(r'["\'\`]?fr\w*[qp]u?e?n\w*["\'\`]?\s*:\s*(\d+(?:\.\d+)?)', raw, re.IGNORECASE)
    # Match "detectionCode"/"betecti0nC0be"/"DeteCtIoNcoDe" etc.
    code_match = re.search(r'["\'\`]?[db]e?te?c?t\w*[Cc0]\w*[db]e?["\'\`]?\s*:\s*["\'\`]([^"\'\`\n]*)["\'\`]', raw, re.IGNORECASE)

    if freq_match and code_match:
        freq_str = freq_match.group(1)
        return {
            "frequency": float(freq_str) if '.' in freq_str else int(freq_str),
            "detectionCode": code_match.group(1),
        }

    # Last resort: find any number after something frequency-like, and any short alphanum string as code
    if "track" in raw.lower() or "being" in raw.lower():
        freq_match2 = re.search(r':\s*(\d{2,4})(?:\s|,|})', raw)
        code_match2 = re.search(r':\s*["\'\`]([A-Za-z0-9]{4,12})["\'\`]', raw)
        if freq_match2 and code_match2:
            freq_str = freq_match2.group(1)
            return {
                "frequency": int(freq_str),
                "detectionCode": code_match2.group(1),
            }

    log.warning("Could not parse scanner response (not clear, not JSON): %s", raw[:300])
    return None


def _disarm_trap(frequency, detection_code: str) -> bool:
    """Disarm a radar trap by sending SHA1 hash."""
    disarm_hash = hashlib.sha1((detection_code + "disarm").encode()).hexdigest()
    payload = {
        "apikey": API_KEY,
        "frequency": frequency,
        "disarmHash": disarm_hash,
    }
    log.info("Disarming: freq=%s, code=%s..., hash=%s", frequency, detection_code[:20], disarm_hash)
    for attempt in range(MAX_RETRIES):
        try:
            resp = http.post(SCANNER_URL, json=payload)
            text = resp.text
            log.info("Disarm response: %s", text[:300])
            # Accept anything that's not an explicit error about wrong data
            return True
        except Exception as e:
            log.warning("Disarm failed (attempt %d): %s", attempt + 1, e)
            time.sleep(1)
    return False


def _get_hint() -> str:
    """Get radio hint about rock position."""
    payload = {"apikey": API_KEY}
    for attempt in range(MAX_RETRIES):
        try:
            resp = http.post(HINT_URL, json=payload)
            data = resp.json()
            hint = data.get("hint", "")
            log.info("Hint: %s", hint)
            if hint:
                return hint
        except Exception as e:
            log.warning("Hint request failed (attempt %d): %s", attempt + 1, e)
        time.sleep(1)
    return ""


def _classify_hint(hint: str) -> str:
    """Classify where the rock is using keyword matching: 'left', 'right', or 'ahead'."""
    h = hint.lower()

    # Keywords for each direction
    # port = left (row above), starboard = right (row below)
    # bow/fore/nose/front/ahead/center/central/cockpit/heading = ahead (same row)
    left_words = ["port", "left"]
    right_words = ["starboard", "right"]
    ahead_words = ["bow", "fore", "nose", "front", "ahead", "center", "central",
                   "cockpit", "heading", "straight"]

    # Danger keywords - the rock/obstacle/hazard location
    danger_words = ["danger", "hazard", "obstacle", "rock", "obstruction", "problem",
                    "trouble", "blocked", "closed", "issue", "rough", "warning",
                    "occupied", "sitting", "lurking", "attached"]

    # Find sentences or clauses about danger
    # Strategy: find which direction word appears near danger context
    # Split into clauses
    clauses = re.split(r'[.,;!]', h)

    # For each clause, check if it mentions danger AND a direction
    for clause in clauses:
        has_danger = any(d in clause for d in danger_words)
        if not has_danger:
            continue
        # Which direction is the danger?
        for w in ahead_words:
            if w in clause:
                log.info("Keyword classified hint as: 'ahead' (keyword='%s' in danger clause)", w)
                return "ahead"
        for w in right_words:
            if w in clause:
                log.info("Keyword classified hint as: 'right' (keyword='%s' in danger clause)", w)
                return "right"
        for w in left_words:
            if w in clause:
                log.info("Keyword classified hint as: 'left' (keyword='%s' in danger clause)", w)
                return "left"

    # Fallback: check "safe" directions and infer danger from the remaining one
    # If two directions are described as safe/open/clear, the third is dangerous
    safe_words = ["safe", "open", "clear", "free", "room", "empty", "friendly",
                  "nothing", "breathing", "stay", "remains", "no concern", "no warning"]
    safe_left = False
    safe_right = False
    safe_ahead = False

    for clause in clauses:
        has_safe = any(s in clause for s in safe_words)
        if not has_safe:
            continue
        for w in left_words:
            if w in clause:
                safe_left = True
        for w in right_words:
            if w in clause:
                safe_right = True
        for w in ahead_words:
            if w in clause:
                safe_ahead = True

    if safe_left and safe_ahead and not safe_right:
        log.info("Keyword classified hint as: 'right' (left+ahead safe)")
        return "right"
    if safe_right and safe_ahead and not safe_left:
        log.info("Keyword classified hint as: 'left' (right+ahead safe)")
        return "left"
    if safe_left and safe_right and not safe_ahead:
        log.info("Keyword classified hint as: 'ahead' (left+right safe)")
        return "ahead"

    # LLM fallback
    return _classify_hint_llm(hint)


def _classify_hint_llm(hint: str) -> str:
    """Use LLM as fallback to classify where the rock is."""
    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = (
        "A rocket navigates a 3-row grid. The hint describes where a rock obstacle is.\n"
        "port/left = rock above (left), starboard/right = rock below (right), "
        "bow/fore/nose/front/center = rock ahead.\n\n"
        f"Hint: \"{hint}\"\n\n"
        "Where is the rock? Reply with one word: left, right, or ahead"
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-5-nano",
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=10,
        )
        answer = (resp.choices[0].message.content or "").strip().lower()
        log.info("LLM classified hint as: '%s'", answer)
        if answer in ("left", "right", "ahead"):
            return answer
        for w in ("ahead", "left", "right"):
            if w in answer:
                return w
    except Exception as e:
        log.warning("LLM hint classification failed: %s", e)
    log.warning("All classification failed for hint: '%s', defaulting to 'ahead'", hint[:80])
    return "ahead"


def _choose_command(rock_position: str, current_row: int) -> str:
    """Choose movement command based on rock position and current row.

    rock_position: 'left' (rock above), 'right' (rock below), 'ahead' (rock same row)
    Rows are 1-3. left command = row-1, right command = row+1, go = same row.
    """
    if rock_position == "ahead":
        # Rock is in same row - must dodge left or right
        if current_row <= 1:
            return "right"
        elif current_row >= 3:
            return "left"
        else:
            return random.choice(["left", "right"])  # randomize from middle
    elif rock_position == "left":
        # Rock is above (row-1) - don't go left
        if current_row >= 3:
            return "go"  # go straight (row 3, rock at 2)
        else:
            return "go"  # go straight is safe since rock is above
    elif rock_position == "right":
        # Rock is below (row+1) - don't go right
        if current_row <= 1:
            return "go"  # go straight (row 1, rock at 2)
        else:
            return "go"  # go straight is safe since rock is below
    return "go"


def navigate_rocket() -> str:
    """Navigate rocket through 3x12 grid to reach Grudziadz base, avoiding rocks and radar traps."""
    max_attempts = 30

    for game_attempt in range(1, max_attempts + 1):
        event_log.emit("system", agent="goingthere", content=f"=== Game attempt {game_attempt} ===")

        # Start new game
        state = _send_game_command("start")

        # Check for flag
        state_str = json.dumps(state, ensure_ascii=False) if isinstance(state, dict) else str(state)
        if "FLG:" in state_str:
            flag = re.search(r'\{?FLG:[^}]*\}?', state_str)
            if flag:
                save_result("goingthere", flag.group(0), state)
                return f"Flag: {flag.group(0)}"

        # Parse positions from structured response
        current_row = 2
        current_col = 1
        target_row = None

        if isinstance(state, dict):
            player = state.get("player", {})
            if isinstance(player, dict):
                current_row = player.get("row", 2)
                current_col = player.get("col", 1)
            base = state.get("base", {})
            if isinstance(base, dict):
                target_row = base.get("row")

        log.info("=== GAME %d: pos=(%d,%d), target_row=%s ===",
                game_attempt, current_row, current_col, target_row)

        crashed = False
        for step in range(11):
            event_log.emit("iteration", agent="goingthere",
                          content=f"Step {step+1}/11, pos=({current_row},{current_col})")

            # === SCANNER CHECK ===
            scanner_ok = False
            for scan_attempt in range(MAX_RETRIES):
                try:
                    raw_scanner = _check_scanner()
                    fields = _extract_trap_fields(raw_scanner)
                    if fields is None:
                        scanner_ok = True
                        break
                    else:
                        log.info("TRAP! freq=%s, code=%s", fields["frequency"], fields["detectionCode"][:30])
                        event_log.emit("system", agent="goingthere",
                                      content=f"Trap at col {current_col}! Disarming...")
                        if _disarm_trap(fields["frequency"], fields["detectionCode"]):
                            scanner_ok = True
                            break
                except Exception as e:
                    log.warning("Scanner attempt %d error: %s", scan_attempt + 1, e)
                    time.sleep(1)

            if not scanner_ok:
                log.error("Scanner failed, proceeding anyway")

            # === GET HINT ===
            hint = _get_hint()

            # === CLASSIFY HINT ===
            if hint:
                rock_pos = _classify_hint(hint)
            else:
                rock_pos = "ahead"  # no hint = assume worst case

            # === CHOOSE COMMAND ===
            command = _choose_command(rock_pos, current_row)

            # Bounds check
            if command == "left" and current_row <= 1:
                command = "go" if rock_pos != "ahead" else "right"
            elif command == "right" and current_row >= 3:
                command = "go" if rock_pos != "ahead" else "left"

            log.info("Step %d: hint='%s' -> rock=%s -> cmd='%s' (row=%d)",
                    step + 1, hint[:60] if hint else "NONE", rock_pos, command, current_row)
            event_log.emit("tool_call", agent="goingthere", name="move",
                          args={"command": command, "hint": hint[:80] if hint else "", "rock": rock_pos})

            # === EXECUTE MOVE ===
            result = _send_game_command(command)

            # Update position
            if command == "left":
                current_row -= 1
            elif command == "right":
                current_row += 1
            current_col += 1

            # Override with server data if available
            if isinstance(result, dict):
                player = result.get("player", {})
                if isinstance(player, dict) and "row" in player:
                    current_row = player["row"]
                    current_col = player.get("col", current_col)

            result_str = json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)
            event_log.emit("tool_result", agent="goingthere", name="move", content=result_str[:300])

            # Check for flag
            if "FLG:" in result_str:
                flag = re.search(r'\{?FLG:[^}]*\}?', result_str)
                if flag:
                    event_log.emit("response", agent="goingthere", content=f"Flag: {flag.group(0)}")
                    save_result("goingthere", flag.group(0), result)
                    return f"Mission complete! {flag.group(0)}"

            # Check for crash
            if isinstance(result, dict):
                crashed_flag = result.get("crashed", False)
                msg = str(result.get("message", "")).lower()
                if crashed_flag or any(w in msg for w in ["crash", "destroyed", "shot", "dead", "game over"]):
                    log.warning("CRASHED at step %d: %s", step + 1, result_str[:200])
                    event_log.emit("error", agent="goingthere", content=f"Crash at step {step+1}")
                    crashed = True
                    break

        if not crashed:
            log.info("Completed 11 moves without crash. Last result: %s", result_str[:300])

    return "Failed to complete mission after all attempts"
