import json
from datetime import datetime, timezone
from pathlib import Path

from core.log import get_logger
from core.store import store_get, store_put
from core.verify import verify as _verify

log = get_logger("tools.verify")

RESULTS_DIR = Path(__file__).parent.parent / "results"


def submit_answer(task_name: str, input_key: str) -> str:
    """Submit data from store to the verification endpoint. Reads answer from input_key."""
    raw = store_get(input_key)
    if raw is None:
        return f"Error: no data found under '{input_key}'."

    answer = json.loads(raw)
    log.info("Submitting for task '%s' from key '%s'", task_name, input_key)
    result = _verify(task_name, answer)

    # Save result to results/<task_name>.json
    RESULTS_DIR.mkdir(exist_ok=True)
    result_path = RESULTS_DIR / f"{task_name}.json"
    result_data = {
        "task": task_name,
        "answer": answer,
        "response": result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    result_path.write_text(json.dumps(result_data, indent=2, ensure_ascii=False))
    log.info("Result saved to %s", result_path)

    return json.dumps(result, ensure_ascii=False)


def load_result(task_name: str, output_key: str) -> str:
    """Load a previous task result from results/<task_name>.json into store under output_key."""
    result_path = RESULTS_DIR / f"{task_name}.json"
    if not result_path.exists():
        return f"Error: no result found for task '{task_name}'."
    data = json.loads(result_path.read_text())
    answer = data.get("answer")
    store_put(output_key, json.dumps(answer, ensure_ascii=False))
    log.info("Loaded result for '%s' into '%s'", task_name, output_key)
    return f"Loaded result for '{task_name}' into '{output_key}'. Answer type: {type(answer).__name__}, preview: {str(answer)[:200]}"
