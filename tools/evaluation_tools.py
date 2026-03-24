import json
import zipfile
from io import BytesIO

from core import http
from core.config import API_KEY, HUB_URL
from core.log import get_logger
from core.store import store_put

log = get_logger("tools.evaluation")

SENSORS_URL = f"{HUB_URL}/dane/sensors.zip"

RANGES = {
    "temperature_K": (553, 873),
    "pressure_bar": (60, 160),
    "water_level_meters": (5.0, 15.0),
    "voltage_supply_v": (229.0, 231.0),
    "humidity_percent": (40.0, 80.0),
}

SENSOR_FIELDS = {
    "temperature": ["temperature_K"],
    "pressure": ["pressure_bar"],
    "water": ["water_level_meters"],
    "voltage": ["voltage_supply_v"],
    "humidity": ["humidity_percent"],
}

PROBLEM_CLAUSES = {
    "This state looks unstable",
    "The numbers feel inconsistent",
    "The latest behavior is concerning",
    "These readings look suspicious",
    "This is not the pattern I expected",
    "This check did not look right",
    "The signal profile looks unusual",
    "This report raises serious doubts",
    "The current result seems unreliable",
    "I can see a clear irregularity",
    "The report does not look healthy",
    "There is a visible anomaly here",
    "I am seeing an unexpected pattern",
    "This run shows questionable behavior",
    "The situation requires attention",
    "The output quality is doubtful",
    "I am not comfortable with this result",
    "Something is clearly off",
}


def _get_active_fields(sensor_type: str) -> set[str]:
    parts = sensor_type.split("/")
    active = set()
    for p in parts:
        active.update(SENSOR_FIELDS.get(p, []))
    return active


def _note_says_problem(note: str) -> bool:
    first_clause = note.split(",")[0].strip()
    return first_clause in PROBLEM_CLAUSES


def _check_data(d: dict) -> bool:
    """Return True if data has issues."""
    active_fields = _get_active_fields(d["sensor_type"])
    for field, (lo, hi) in RANGES.items():
        val = d[field]
        if field in active_fields:
            if val == 0 or val < lo or val > hi:
                return True
        else:
            if val != 0:
                return True
    return False


def find_anomalies() -> str:
    """Download sensor data, analyze all files, and store anomaly IDs for submission."""
    log.info("Downloading sensors.zip...")
    resp = http.get(SENSORS_URL)
    resp.raise_for_status()

    files = {}
    with zipfile.ZipFile(BytesIO(resp.content)) as zf:
        for name in zf.namelist():
            if name.endswith(".json"):
                with zf.open(name) as f:
                    files[name] = json.load(f)
    log.info("Loaded %d sensor files", len(files))

    anomalies = set()
    data_anomalies = 0
    note_anomalies = 0

    for fname, d in files.items():
        fid = fname.replace(".json", "")
        data_bad = _check_data(d)
        note_problem = _note_says_problem(d["operator_notes"])

        if data_bad or (not data_bad and note_problem):
            anomalies.add(fid)
            if data_bad:
                data_anomalies += 1
            else:
                note_anomalies += 1

    anomaly_list = sorted(anomalies)
    answer = {"recheck": anomaly_list}
    store_put("filtered", json.dumps(answer, ensure_ascii=False))
    log.info("Found %d anomalies (data: %d, note-only: %d)", len(anomaly_list), data_anomalies, note_anomalies)

    return f"Found {len(anomaly_list)} anomalies ({data_anomalies} data issues, {note_anomalies} note-only). Stored under 'filtered'. Submit with verify skill."
