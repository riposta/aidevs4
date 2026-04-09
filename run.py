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

    from core.agent import _find_lesson, run_task_adaptive

    # Resolve identifier → lesson_path + task_name
    lesson_path, task_name = _find_lesson(identifier)

    if not lesson_path or not lesson_path.exists():
        if identifier == "proxy":
            from core.event_log import init as init_event_log, close as close_event_log
            init_event_log("proxy")
            try:
                from core.proxy import run
                run()
            finally:
                close_event_log()
            return
        log.error("No lesson found for '%s'", identifier)
        sys.exit(1)

    from core.event_log import init as init_event_log, close as close_event_log
    init_event_log(task_name)
    try:
        log.info("Running lesson: %s (task: %s)", lesson_path.name, task_name)
        run_task_adaptive(task_name, lesson=str(lesson_path.relative_to(lesson_path.parent.parent)))
    finally:
        close_event_log()


if __name__ == "__main__":
    main()
