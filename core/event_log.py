import json
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "log"

_file = None
_task_name = None


def init(task_name: str) -> None:
    global _file, _task_name
    close()
    _task_name = task_name
    LOG_DIR.mkdir(exist_ok=True)
    _file = open(LOG_DIR / f"{task_name}.jsonl", "w")


def emit(event_type: str, agent: str = "", **kwargs) -> None:
    if _file is None:
        return
    entry = {
        "type": event_type,
        "agent": agent,
        "ts": datetime.now(timezone.utc).isoformat(),
        **kwargs,
    }
    _file.write(json.dumps(entry, ensure_ascii=False) + "\n")
    _file.flush()


def close() -> None:
    global _file
    if _file:
        _file.close()
        _file = None