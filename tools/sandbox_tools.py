"""Python execution tool for the adaptive agent."""
from core.sandbox import execute
from core.log import get_logger

log = get_logger("tools.sandbox")


def run_python(code: str) -> str:
    """Execute Python code and return stdout. Available imports: json, csv, re, math, datetime, base64, zipfile, hashlib, heapq, collections, itertools, functools, statistics. Use _store_put(key, json_str) and _store_get(key) to pass data between steps. Use _store_put_json(key, obj) for convenience."""
    log.info("Executing Python (%d chars)", len(code))
    result = execute(code)
    log.info("Result: %s", result[:300])
    return result
