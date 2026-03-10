#!/usr/bin/env python3
import logging
import sys

from core.log import get_logger, set_global_level

log = get_logger("main")


def main():
    # --verbose / -v flag sets DEBUG level, default is INFO
    if "--verbose" in sys.argv or "-v" in sys.argv:
        set_global_level(logging.DEBUG)
        sys.argv = [a for a in sys.argv if a not in ("--verbose", "-v")]
    else:
        set_global_level(logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: python run.py <task_name> [--verbose|-v]")
        print("Example: python run.py example")
        sys.exit(1)

    task_name = sys.argv[1]

    from core.event_log import init as init_event_log, close as close_event_log
    init_event_log(task_name)
    try:
        from tasks import run_task
        run_task(task_name)
    finally:
        close_event_log()


if __name__ == "__main__":
    main()
