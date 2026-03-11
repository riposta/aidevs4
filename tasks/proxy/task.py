import json
import os
import re
import subprocess
import time
import threading
from pathlib import Path

from flask import Flask, request as flask_request, jsonify
from openai import OpenAI

from core.agent import _load_agent_from_markdown, function_to_openai_tool
from core.config import OPENAI_API_KEY, PROXY_PORT
from core import event_log
from core.log import get_logger
from core.verify import verify

log = get_logger("proxy")

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Session storage: sessionID -> list of OpenAI messages
sessions: dict[str, list[dict]] = {}


def _start_tunnel(local_port: int) -> tuple[subprocess.Popen, str]:
    """Start cloudflared tunnel. Returns (process, public_url)."""
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{local_port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    url = None
    deadline = time.time() + 30
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        log.info("tunnel: %s", line.strip())
        m = re.search(r'(https://[a-z0-9-]+\.trycloudflare\.com)', line)
        if m:
            url = m.group(1)
            break

    if not url:
        proc.terminate()
        raise RuntimeError("Failed to get tunnel URL")

    return proc, url


def run():
    # Load agent definition
    agent = _load_agent_from_markdown(PROJECT_ROOT / "agents" / "proxy_assistant.md")

    # Pre-activate all skills to get tool functions
    for skill in agent.skills.values():
        for name, fn in skill.tool_fns.items():
            agent.tools[name] = fn

    system_prompt = agent._build_system()
    tool_schemas = [function_to_openai_tool(fn) for fn in agent.tools.values()]
    client = OpenAI(api_key=OPENAI_API_KEY)

    log.info("Loaded agent '%s' with %d tools", agent.name, len(agent.tools))
    event_log.emit("system", agent="proxy", content=f"Agent '{agent.name}' loaded with {len(agent.tools)} tools")
    event_log.emit("debug", agent="proxy", label="system_prompt", content=system_prompt)
    tool_names = [s["function"]["name"] for s in tool_schemas]
    event_log.emit("debug", agent="proxy", label="tools", content=f"Tools: {', '.join(tool_names)}")

    # Flask app
    app = Flask(__name__)

    @app.route("/", methods=["POST"])
    def handle():
        data = flask_request.json
        session_id = data.get("sessionID", "default")
        msg = data.get("msg", "")

        log.info("[%s] User: %s", session_id, msg[:200])
        event_log.emit("user", agent="proxy", content=f"[{session_id}] {msg}")

        # Get or create session messages
        if session_id not in sessions:
            sessions[session_id] = [{"role": "system", "content": system_prompt}]
            event_log.emit("system", agent="proxy", content=f"New session: {session_id}")

        messages = sessions[session_id]
        messages.append({"role": "user", "content": msg})

        # ReAct loop
        for iteration in range(10):
            event_log.emit("iteration", agent="proxy", content=f"[{session_id}] iteration {iteration + 1}")
            event_log.emit("debug", agent="proxy", label="context",
                           content=json.dumps([{"role": m.get("role", "?"), "content": str(m.get("content", ""))[:100]} for m in messages], ensure_ascii=False))

            kwargs = {"model": agent.model, "messages": messages}
            if tool_schemas:
                kwargs["tools"] = tool_schemas

            response = client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            event_log.emit("debug", agent="proxy", label="tokens",
                           content=f"usage: {response.usage.prompt_tokens}+{response.usage.completion_tokens}" if response.usage else "no usage")

            if choice.message.tool_calls:
                messages.append(choice.message.model_dump())
                for tc in choice.message.tool_calls:
                    fn_name = tc.function.name
                    fn_args = json.loads(tc.function.arguments)
                    log.info("[%s] Tool: %s(%s)", session_id, fn_name,
                             json.dumps(fn_args, ensure_ascii=False)[:200])
                    event_log.emit("tool_call", agent="proxy", name=fn_name, args=fn_args)

                    fn = agent.tools.get(fn_name)
                    if fn:
                        result = str(fn(**fn_args))
                    else:
                        result = f"Error: unknown tool '{fn_name}'"

                    log.info("[%s] Result: %s", session_id, result[:200])
                    event_log.emit("tool_result", agent="proxy", name=fn_name, content=result[:500])
                    messages.append({
                        "role": "tool",
                        "content": result,
                        "tool_call_id": tc.id,
                    })
                continue

            # Text response
            content = choice.message.content or ""
            messages.append({"role": "assistant", "content": content})
            log.info("[%s] Assistant: %s", session_id, content[:200])
            event_log.emit("response", agent="proxy", content=content)
            return jsonify({"msg": content})

        event_log.emit("error", agent="proxy", content=f"[{session_id}] Max iterations reached")
        return jsonify({"msg": "Error: could not process request"})

    # Start HTTP server
    # Clear Werkzeug env vars inherited from GUI parent process to avoid fd reuse
    os.environ.pop("WERKZEUG_SERVER_FD", None)
    os.environ.pop("WERKZEUG_RUN_MAIN", None)
    port = PROXY_PORT
    server = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, debug=False),
        daemon=True,
    )
    server.start()
    time.sleep(1)
    log.info("HTTP server started on port %d", port)
    event_log.emit("system", agent="proxy", content=f"HTTP server on port {port}")

    # Start tunnel
    tunnel_proc, public_url = _start_tunnel(port)
    log.info("Tunnel: %s", public_url)
    event_log.emit("system", agent="proxy", content=f"Tunnel: {public_url}")

    try:
        # Wait for tunnel DNS to propagate
        time.sleep(5)

        # Submit to verify
        session_id = "aidevs4-proxy-001"
        log.info("Submitting to verify: url=%s, sessionID=%s", public_url, session_id)
        event_log.emit("system", agent="proxy", content=f"Submitting to verify: {public_url}")
        try:
            result = verify("proxy", {"url": public_url, "sessionID": session_id})
            log.info("Verify result: %s", result)
            event_log.emit("response", agent="verify", content=str(result))
        except Exception as e:
            log.error("Verify error: %s", e)
            event_log.emit("error", agent="verify", content=str(e))

        # Keep tunnel alive for verify callbacks
        log.info("Keeping tunnel alive for callbacks (90s)...")
        time.sleep(90)
    finally:
        tunnel_proc.terminate()
        tunnel_proc.wait(timeout=5)
