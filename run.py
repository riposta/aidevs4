#!/usr/bin/env python3
"""CLI entry point: python run.py <task_or_lesson> [-v]

Examples:
    python run.py railway          # find lesson by task name
    python run.py s01e05           # find lesson by prefix
    python run.py railway -v       # verbose mode
"""
import logging
import sys

from core.log import get_logger, set_global_level

log = get_logger("main")


def main():
    if "--verbose" in sys.argv or "-v" in sys.argv:
        set_global_level(logging.DEBUG)
        sys.argv = [a for a in sys.argv if a not in ("--verbose", "-v")]
    else:
        set_global_level(logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: python run.py <task_name_or_lesson_prefix> [--verbose|-v]")
        print("Examples:")
        print("  python run.py railway")
        print("  python run.py s01e05")
        sys.exit(1)

    identifier = sys.argv[1]

    from core.agent import LESSON_TASK_MAP, _find_lesson, run_task_adaptive

    # Resolve identifier → task_name + lesson_path
    if identifier in LESSON_TASK_MAP:
        # It's a lesson prefix like "s01e05"
        task_name = LESSON_TASK_MAP[identifier]
        lesson_path = _find_lesson(task_name)
    else:
        # Assume it's a task name like "railway"
        task_name = identifier
        lesson_path = _find_lesson(task_name)

    if not lesson_path or not lesson_path.exists():
        # Fallback: try old tasks/ system for proxy and other special tasks
        log.warning("No lesson found for '%s', trying legacy tasks/ system", identifier)
        from core.event_log import init as init_event_log, close as close_event_log
        init_event_log(task_name)
        try:
            from tasks import run_task
            run_task(task_name)
        finally:
            close_event_log()
        return

    from core.event_log import init as init_event_log, close as close_event_log
    init_event_log(task_name)
    try:
        log.info("Running lesson: %s (task: %s)", lesson_path.name, task_name)
        run_task_adaptive(task_name, lesson=str(lesson_path.relative_to(lesson_path.parent.parent)))
    finally:
        close_event_log()


if __name__ == "__main__":
    main()
