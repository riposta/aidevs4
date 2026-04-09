"""Python execution tool for the adaptive agent."""
from core.sandbox import execute
from core.log import get_logger

log = get_logger("tools.sandbox")


def run_python(code: str) -> str:
    """Execute Python code and return stdout. Available: json, csv, re, math, datetime, base64, zipfile, hashlib, heapq, collections, itertools, functools, statistics, requests. Use _store_put/_store_get for data. Use _API_KEY, _VERIFY_URL, _HUB_URL for API calls. Example: requests.post(_VERIFY_URL, json={"apikey": _API_KEY, "task": "x", "answer": {...}})"""
    log.info("Executing Python (%d chars)", len(code))
    result = execute(code)
    log.info("Result: %s", result[:300])
    return result
