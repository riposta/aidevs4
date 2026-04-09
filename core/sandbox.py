"""Safe Python execution sandbox for run_python tool."""
import io
import sys
import json
import contextlib
from core.store import store_put, store_get
from core.log import get_logger

log = get_logger("sandbox")


def execute(code: str) -> str:
    """Execute Python code in a restricted environment. Returns stdout.
    Sandbox has access to: json, csv, re, math, datetime, base64, zipfile,
    hashlib, heapq, collections, itertools, functools, urllib.parse, html,
    xml.etree.ElementTree, statistics.
    Use _store_put(key, json_str) and _store_get(key) for data passing.
    Use _store_put_json(key, obj) for convenience."""
    stdout_capture = io.StringIO()

    sandbox_globals = {
        "__builtins__": __builtins__,
        "_store_put": store_put,
        "_store_get": store_get,
        "_store_put_json": lambda key, obj: store_put(key, json.dumps(obj, ensure_ascii=False)),
    }

    try:
        with contextlib.redirect_stdout(stdout_capture):
            exec(code, sandbox_globals)
        output = stdout_capture.getvalue()
        if len(output) > 10000:
            output = output[:10000] + "\n... (truncated)"
        return output if output else "(no output)"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"
