"""Infrastructure tools: HTTP server with tunnel."""
import json
import os
import re
import subprocess
import threading
import time

from flask import Flask, request as flask_request, jsonify
from core.log import get_logger

log = get_logger("tools.infra")

_server_state = {"app": None, "tunnel": None, "url": None}


def start_server(routes_json: str) -> str:
    """Start a Flask HTTP server with dynamic routes and expose via cloudflare tunnel. routes_json is a JSON array of {path, method, response} objects. Returns public URL."""
    routes = json.loads(routes_json)
    app = Flask(__name__)

    for route in routes:
        path = route["path"]
        method = route.get("method", "POST")
        response_body = route.get("response", "{}")

        def make_handler(resp_body):
            def handler():
                data = flask_request.json if flask_request.is_json else {}
                log.info("Request: %s %s data=%s", flask_request.method, flask_request.path, str(data)[:200])
                return jsonify(json.loads(resp_body) if isinstance(resp_body, str) else resp_body)
            return handler

        app.add_url_rule(path, endpoint=path, view_func=make_handler(response_body), methods=[method])

    port = int(os.environ.get("PROXY_PORT", "5055"))
    os.environ.pop("WERKZEUG_SERVER_FD", None)
    os.environ.pop("WERKZEUG_RUN_MAIN", None)

    server_thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, debug=False),
        daemon=True,
    )
    server_thread.start()
    time.sleep(1)

    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    url = None
    deadline = time.time() + 30
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        m = re.search(r'(https://[a-z0-9-]+\.trycloudflare\.com)', line)
        if m:
            url = m.group(1)
            break

    if not url:
        proc.terminate()
        return "Error: failed to get tunnel URL"

    _server_state.update({"app": app, "tunnel": proc, "url": url})
    log.info("Server started: %s (port %d)", url, port)
    return f"Server running at: {url}"
