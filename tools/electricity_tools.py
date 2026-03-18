import io
import json
import time

import numpy as np
import requests
from PIL import Image

from core.config import API_KEY, HUB_URL, VERIFY_URL
from core.log import get_logger
from core.result import save_result
from core.store import store_put, store_get

log = get_logger("tools.electricity")

TARGET_URL = f"{HUB_URL}/i/solved_electricity.png"
CURRENT_URL = f"{HUB_URL}/data/{API_KEY}/electricity.png"


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
