import importlib
from pathlib import Path
from core.log import get_logger

log = get_logger("task")
TASKS_DIR = Path(__file__).parent


def run_task(task_name: str):
    task_dir = TASKS_DIR / task_name
    if not task_dir.exists():
        log.error("Task '%s' not found in %s", task_name, TASKS_DIR)
        raise ValueError(f"Task '{task_name}' not found in {TASKS_DIR}")

    log.info("Running task: %s", task_name)
    module = importlib.import_module(f"tasks.{task_name}.task")
    module.run()
    log.info("Task '%s' completed", task_name)
