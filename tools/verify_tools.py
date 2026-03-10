import json

from core.log import get_logger
from core.store import store_get
from core.verify import verify as _verify

log = get_logger("tools.verify")


def submit_answer(task_name: str) -> str:
    """Submit filtered results to the verification endpoint. Reads from the latest filtered data."""
    raw = store_get("filtered")
    if raw is None:
        return "Error: no filtered data found. Run filter_by_tag first."

    answer = json.loads(raw)
    log.info("Submitting %d items for task '%s'", len(answer), task_name)
    result = _verify(task_name, answer)
    return json.dumps(result, ensure_ascii=False)
