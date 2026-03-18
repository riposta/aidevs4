import json
from datetime import datetime, timezone
from pathlib import Path

from core.log import get_logger

log = get_logger("result")

RESULTS_DIR = Path(__file__).parent.parent / "results"


def save_result(task_name: str, answer, response: dict) -> None:
    """Save task result to results/<task_name>.json for GUI display."""
    RESULTS_DIR.mkdir(exist_ok=True)
    result_path = RESULTS_DIR / f"{task_name}.json"
    result_data = {
        "task": task_name,
        "answer": answer,
        "response": response,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    result_path.write_text(json.dumps(result_data, indent=2, ensure_ascii=False))
    log.info("Result saved to %s", result_path)
