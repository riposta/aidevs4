import io
import json
import re
import time

import numpy as np
import requests
from PIL import Image

from core import http, event_log
from core.config import API_KEY, HUB_URL, VERIFY_URL
from core.log import get_logger
from core.result import save_result
from core.store import store_put, store_get

log = get_logger("tools.grid")

TARGET_URL = f"{HUB_URL}/i/solved_electricity.png"
CURRENT_URL = f"{HUB_URL}/data/{API_KEY}/electricity.png"


# === Electricity functions ===


def _find_grid(arr):
    """Find 3x3 grid lines in grayscale image array. Returns (top, bottom, left, right)."""
    dark = arr < 100
    h, w = arr.shape

    def longest_run(row):
        max_run = curr = 0
        for v in row:
            if v:
                curr += 1
                max_run = max(max_run, curr)
            else:
                curr = 0
        return max_run

    def cluster(vals, gap=10):
        if not vals:
            return []
        clusters = [[vals[0]]]
        for v in vals[1:]:
            if v - clusters[-1][-1] <= gap:
                clusters[-1].append(v)
            else:
                clusters.append([v])
        return [int(sum(c) / len(c)) for c in clusters]

    h_runs = [longest_run(dark[r]) for r in range(h)]
    v_runs = [longest_run(dark[:, c]) for c in range(w)]

    h_lines = cluster([r for r in range(h) if h_runs[r] > max(h_runs) * 0.6])
    v_lines = cluster([c for c in range(w) if v_runs[c] > max(v_runs) * 0.6])

    if len(h_lines) < 4 or len(v_lines) < 4:
        raise ValueError(f"Could not find 3x3 grid: h_lines={h_lines}, v_lines={v_lines}")

    return h_lines[0], h_lines[3], v_lines[0], v_lines[3]


def _analyze_connections(arr):
    """Analyze 3x3 grid and return connections for each cell."""
    dark = arr < 100
    top, bottom, left, right = _find_grid(arr)
    cell_h = (bottom - top) / 3
    cell_w = (right - left) / 3

    result = {}
    for row in range(3):
        for col in range(3):
            y1 = int(top + row * cell_h)
            y2 = int(top + (row + 1) * cell_h)
            x1 = int(left + col * cell_w)
            x2 = int(left + (col + 1) * cell_w)

            cell = dark[y1:y2, x1:x2]
            ch, cw = cell.shape
            margin, band = 3, 8
            mid_h, mid_w = ch // 2, cw // 2

            t = cell[margin:margin + band, mid_w - band:mid_w + band].mean() > 0.3
            b = cell[ch - margin - band:ch - margin, mid_w - band:mid_w + band].mean() > 0.3
            le = cell[mid_h - band:mid_h + band, margin:margin + band].mean() > 0.3
            r = cell[mid_h - band:mid_h + band, cw - margin - band:cw - margin].mean() > 0.3

            conns = ""
            if t: conns += "T"
            if r: conns += "R"
            if b: conns += "B"
            if le: conns += "L"

            result[f"{row + 1}x{col + 1}"] = conns

    return result


def _rotate_cw(conns):
    """Rotate connections 90° clockwise."""
    mapping = {"T": "R", "R": "B", "B": "L", "L": "T"}
    return "".join(sorted(mapping[c] for c in conns))


def _rotations_needed(current, target):
    """Calculate how many 90° CW rotations to get from current to target."""
    curr = frozenset(current)
    tgt = frozenset(target)
    for i in range(4):
        if curr == tgt:
            return i
        curr = frozenset(_rotate_cw("".join(curr)))
    return -1


def electricity_reset() -> str:
    """Reset the puzzle board and return fresh state analysis compared to target."""
    log.info("Resetting puzzle board")
    # Reset
    resp = requests.get(f"{CURRENT_URL}?reset=1")
    resp.raise_for_status()
    current_arr = np.array(Image.open(io.BytesIO(resp.content)).convert("L"))

    # Fetch target
    resp_t = requests.get(TARGET_URL)
    resp_t.raise_for_status()
    target_arr = np.array(Image.open(io.BytesIO(resp_t.content)).convert("L"))

    # Analyze both
    current = _analyze_connections(current_arr)
    target = _analyze_connections(target_arr)

    store_put("electricity_target", json.dumps(target))
    store_put("electricity_current", json.dumps(current))

    # Calculate needed rotations
    rotations = {}
    for cell in sorted(current.keys()):
        n = _rotations_needed(current[cell], target[cell])
        if n > 0:
            rotations[cell] = n

    store_put("electricity_rotations", json.dumps(rotations))

    lines = ["Board reset. Analysis:"]
    lines.append(f"Target:  {json.dumps(target)}")
    lines.append(f"Current: {json.dumps(current)}")
    lines.append(f"Rotations needed: {json.dumps(rotations)}")
    total = sum(rotations.values())
    lines.append(f"Total API calls needed: {total}")

    result = "\n".join(lines)
    log.info(result)
    return result


def electricity_rotate(field: str) -> str:
    """Rotate a field 90 degrees clockwise. Field format: AxB (e.g. '2x3')."""
    payload = {
        "apikey": API_KEY,
        "task": "electricity",
        "answer": {"rotate": field},
    }
    log.info("Rotating field %s", field)
    resp = requests.post(VERIFY_URL, json=payload)
    data = resp.json()
    message = data.get("message", "")
    log.info("Rotate %s: %s", field, message[:200])

    if "FLG:" in message:
        store_put("filtered", message)
        save_result("electricity", {"rotate": field}, data)
        return f"FLAG FOUND: {message}"

    return f"Rotated {field}: {message}"


def electricity_solve() -> str:
    """Execute all needed rotations based on stored analysis. Resets board first."""
    # Reset and analyze
    reset_result = electricity_reset()

    raw = store_get("electricity_rotations")
    if not raw:
        return "Error: no rotation data. Run electricity_reset first."

    rotations = json.loads(raw)
    if not rotations:
        return "Board already solved! No rotations needed.\n" + reset_result

    results = [reset_result, ""]
    for cell, count in sorted(rotations.items()):
        for i in range(count):
            result = electricity_rotate(cell)
            results.append(f"  {cell} rotation {i + 1}/{count}: {result}")
            if "FLAG FOUND" in result:
                return "\n".join(results)
            time.sleep(0.3)

    # Verify final state
    results.append("\nAll rotations sent. Fetching updated state to verify...")
    resp = requests.get(CURRENT_URL)
    resp.raise_for_status()
    arr = np.array(Image.open(io.BytesIO(resp.content)).convert("L"))
    final = _analyze_connections(arr)
    target = json.loads(store_get("electricity_target"))

    mismatches = {k: (final[k], target[k]) for k in final if frozenset(final[k]) != frozenset(target[k])}
    if mismatches:
        results.append(f"WARNING: {len(mismatches)} cells still wrong: {json.dumps(mismatches)}")
    else:
        results.append("All cells match target!")

    return "\n".join(results)


# === Domatowo functions ===


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
