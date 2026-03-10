import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "log"

_file = None
_task_name = None

EVENT_PREFIX = "@@EVENT::"


def init(task_name: str) -> None:
    global _file, _task_name
    close()
    _task_name = task_name
    LOG_DIR.mkdir(exist_ok=True)
    _file = open(LOG_DIR / f"{task_name}.jsonl", "w")


def emit(event_type: str, agent: str = "", **kwargs) -> None:
    entry = {
        "type": event_type,
        "agent": agent,
        "ts": datetime.now(timezone.utc).isoformat(),
        **kwargs,
    }
    line = json.dumps(entry, ensure_ascii=False)
    # Write to JSONL file
    if _file is not None:
        _file.write(line + "\n")
        _file.flush()
    # Write to stderr (captured by GUI SSE endpoint)
    print(f"{EVENT_PREFIX}{line}", file=sys.stderr, flush=True)


def close() -> None:
    global _file
    if _file:
        _file.close()
        _file = None
