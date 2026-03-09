#!/usr/bin/env python3
import logging
import sys

from core.log import get_logger

log = get_logger("main")


def main():
    # --verbose / -v flag sets DEBUG level, default is INFO
    if "--verbose" in sys.argv or "-v" in sys.argv:
        logging.getLogger().setLevel(logging.DEBUG)
        for name in logging.Logger.manager.loggerDict:
            if name.startswith("aidevs."):
                logging.getLogger(name).setLevel(logging.DEBUG)
        sys.argv = [a for a in sys.argv if a not in ("--verbose", "-v")]
    else:
        for name in logging.Logger.manager.loggerDict:
            if name.startswith("aidevs."):
                logging.getLogger(name).setLevel(logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: python run.py <task_name> [--verbose|-v]")
        print("Example: python run.py example")
        sys.exit(1)

    task_name = sys.argv[1]

    from tasks import run_task
    run_task(task_name)


if __name__ == "__main__":
    main()
