import json
import re

from core.config import API_KEY, VERIFY_URL
from core.log import get_logger
from core.store import store_put
from core.result import save_result
from core import http, event_log

log = get_logger("tools.domatowo")


def _api(action: str, **kwargs) -> dict:
    answer = {"action": action, **kwargs}
    resp = http.post(VERIFY_URL, json={"apikey": API_KEY, "task": "domatowo", "answer": answer})
    result = resp.json()
    log.info("%s: code=%s msg=%s", action, result.get("code"), str(result.get("message", ""))[:200])
    return result


def _coord(row: int, col: int) -> str:
    """Convert grid (row, col) to API coordinate like 'F1'."""
    return chr(ord('A') + col) + str(row + 1)


def execute_rescue() -> str:
    """Execute the complete search and rescue operation in Domatowo."""
    # Reset
    r = _api("reset")
    event_log.emit("system", agent="domatowo", content=f"Reset: {r.get('message')}")

    # Get map to find B3 locations
    map_data = _api("getMap")
    grid = map_data["map"]["grid"]

    # Find all B3 tiles
    b3_tiles = []
    for row in range(len(grid)):
        for col in range(len(grid[row])):
            if grid[row][col] == "block3":
                b3_tiles.append((row, col, _coord(row, col)))

    log.info("B3 tiles: %s", [t[2] for t in b3_tiles])

    # Group B3 tiles into clusters by proximity
    # Cluster 1 (top): F1,G1,F2,G2 (rows 0-1, cols 5-6)
    # Cluster 2 (bottom-left): A10,B10,C10,A11,B11,C11 (rows 9-10, cols 0-2)
    # Cluster 3 (bottom-right): H10,I10,H11,I11 (rows 9-10, cols 7-8)

    cluster1 = [(r, c, coord) for r, c, coord in b3_tiles if r <= 2]
    cluster2 = [(r, c, coord) for r, c, coord in b3_tiles if r >= 9 and c <= 3]
    cluster3 = [(r, c, coord) for r, c, coord in b3_tiles if r >= 9 and c >= 7]

    log.info("Cluster1 (top): %s", [t[2] for t in cluster1])
    log.info("Cluster2 (bottom-left): %s", [t[2] for t in cluster2])
    log.info("Cluster3 (bottom-right): %s", [t[2] for t in cluster3])

    # === DEPLOY PHASE ===

    # Transporter 1: 2 scouts → cluster 1 (via road to D1)
    r1 = _api("create", type="transporter", passengers=2)
    t1_hash = r1.get("hash") or r1.get("unitHash") or r1.get("object")
    log.info("Transporter 1: %s", t1_hash)

    # Transporter 2: 2 scouts → cluster 2 (via road to B9)
    r2 = _api("create", type="transporter", passengers=2)
    t2_hash = r2.get("hash") or r2.get("unitHash") or r2.get("object")
    log.info("Transporter 2: %s", t2_hash)

    # Transporter 3: 2 scouts → cluster 3 (via road to I9)
    r3 = _api("create", type="transporter", passengers=2)
    t3_hash = r3.get("hash") or r3.get("unitHash") or r3.get("object")
    log.info("Transporter 3: %s", t3_hash)

    # Get objects to find hashes
    objects = _api("getObjects")
    log.info("Objects: %s", json.dumps(objects, ensure_ascii=False)[:500])

    # Use hashes directly from create responses
    t1 = r1.get("object")
    t2 = r2.get("object")
    t3 = r3.get("object")
    log.info("Transporter hashes: %s, %s, %s", t1, t2, t3)

    # === MOVE TRANSPORTERS ===

    # T1 → D1 (for cluster 1)
    _api("move", object=t1, where="D1")

    # T2 → B9 (for cluster 2)
    _api("move", object=t2, where="B9")

    # T3 → I9 (for cluster 3)
    _api("move", object=t3, where="I9")

    # === DISMOUNT SCOUTS ===

    _api("dismount", object=t1, passengers=2)
    _api("dismount", object=t2, passengers=2)
    _api("dismount", object=t3, passengers=2)

    # Get updated objects to find scout hashes
    objects = _api("getObjects")
    units = objects.get("objects", [])
    scouts = [u for u in units if u.get("typ") == "scout"]
    log.info("Scouts (%d): %s", len(scouts), [(s.get("id"), s.get("position")) for s in scouts])

    # === SEARCH PHASE ===
    # Move scouts to B3 tiles and inspect each

    found_human = None

    def _inspect_scout(scout_hash, coord):
        """Move scout to coord, inspect, check logs. Returns coord if human found."""
        nonlocal found_human
        if found_human:
            return found_human

        _api("move", object=scout_hash, where=coord)
        _api("inspect", object=scout_hash)

        # Check logs for the latest entry
        logs = _api("getLogs")
        log_entries = logs.get("logs", logs.get("entries", []))
        if log_entries:
            latest = log_entries[-1]
            text = str(latest.get("msg", latest) if isinstance(latest, dict) else latest).lower()
            log.info("Inspect %s: %s", coord, text[:150])

            # Positive detection: look for confirmed human presence
            negative = any(w in text for w in ["pusty", "nie ", "brak", "nic ", "empty", "nothing"])
            positive = any(w in text for w in ["odnalezien", "odnalezion", "znalezien", "znalezion",
                                                "potwierdzam", "jest człowiek", "jest ktoś",
                                                "żyje", "ranny człow", "ukryw", "partyzant",
                                                "found human", "person found", "someone here",
                                                "jest tu kto", "widzę człow", "ktoś tu jest",
                                                "osob"])
            if positive and not negative:
                log.info("HUMAN FOUND at %s! Log: %s", coord, latest)
                found_human = coord
                return coord
        return None

    # Organize scouts by proximity to clusters
    # Scouts near D1 → cluster 1 tiles
    # Scouts near B9 → cluster 2 tiles
    # Scouts near I9 → cluster 3 tiles

    # Sort scouts by position to assign them to clusters
    scouts_c1 = []  # near D1
    scouts_c2 = []  # near B9
    scouts_c3 = []  # near I9

    for s in scouts:
        pos = s.get("position", "")
        sh = s.get("id")
        col = ord(pos[0]) - ord('A') if pos else 0
        row = int(pos[1:]) - 1 if pos else 0

        if row <= 4:
            scouts_c1.append(sh)
        elif col <= 4:
            scouts_c2.append(sh)
        else:
            scouts_c3.append(sh)

    log.info("Scouts C1: %s, C2: %s, C3: %s", scouts_c1, scouts_c2, scouts_c3)

    # Search cluster 1: F1, G1, F2, G2
    if len(scouts_c1) >= 2:
        s1, s2 = scouts_c1[0], scouts_c1[1]
        for coord in ["F1", "G1"]:
            _inspect_scout(s1, coord)
            if found_human:
                break
        if not found_human:
            for coord in ["F2", "G2"]:
                _inspect_scout(s2, coord)
                if found_human:
                    break
    elif scouts_c1:
        for coord in ["F1", "G1", "F2", "G2"]:
            _inspect_scout(scouts_c1[0], coord)
            if found_human:
                break

    # Search cluster 2: A10, B10, C10, A11, B11, C11
    if not found_human and len(scouts_c2) >= 2:
        s1, s2 = scouts_c2[0], scouts_c2[1]
        for coord in ["A10", "B10", "A11"]:
            _inspect_scout(s1, coord)
            if found_human:
                break
        if not found_human:
            for coord in ["C10", "C11", "B11"]:
                _inspect_scout(s2, coord)
                if found_human:
                    break
    elif not found_human and scouts_c2:
        for coord in ["A10", "B10", "C10", "A11", "B11", "C11"]:
            _inspect_scout(scouts_c2[0], coord)
            if found_human:
                break

    # Search cluster 3: H10, I10, H11, I11
    if not found_human and len(scouts_c3) >= 2:
        s1, s2 = scouts_c3[0], scouts_c3[1]
        for coord in ["H10", "I10"]:
            _inspect_scout(s1, coord)
            if found_human:
                break
        if not found_human:
            for coord in ["H11", "I11"]:
                _inspect_scout(s2, coord)
                if found_human:
                    break
    elif not found_human and scouts_c3:
        for coord in ["H10", "I10", "H11", "I11"]:
            _inspect_scout(scouts_c3[0], coord)
            if found_human:
                break

    if not found_human:
        # Check expenses
        exp = _api("expenses")
        return f"Human not found in any B3 tile. Expenses: {json.dumps(exp, ensure_ascii=False)[:300]}"

    # === EVACUATION ===
    log.info("Calling helicopter to %s", found_human)
    r = _api("callHelicopter", destination=found_human)
    log.info("Helicopter result: %s", json.dumps(r, ensure_ascii=False)[:500])

    flag_match = re.search(r"\{FLG:[^}]+\}", json.dumps(r))
    if flag_match:
        flag = flag_match.group(0)
        save_result("domatowo", {"destination": found_human}, {"code": 0, "message": flag})
        return f"Partisan found at {found_human}! Helicopter called. Flag: {flag}"

    save_result("domatowo", {"destination": found_human}, r)
    return f"Helicopter called to {found_human}. Result: {json.dumps(r, ensure_ascii=False)[:400]}"
