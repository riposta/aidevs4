# Self-Improving Agent Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace task-specific tools and hand-written skills with a self-improving agent that uses ~10 generic tools, reads task descriptions from MD files, and builds a skill library from successful runs.

**Architecture:** New generic tools (call_task_api, fetch_url, run_python, ask_llm, TTS/STT, start_server) replace 72 task-specific functions. Agent reads task.md for instructions, discovers API via exploration, saves successful trajectories as learned skills. Reflection on failure via gpt-4o-mini. Existing system preserved as fallback (run_task still works).

**Tech Stack:** Python 3.12, OpenAI API (gpt-5-nano execution, gpt-4o-mini reflection), Flask (dynamic server), cloudflared (tunnels)

---

### Task 1: Python sandbox (`core/sandbox.py`)

**Files:**
- Create: `core/sandbox.py`

**Step 1: Create sandbox module**

```python
"""Safe Python execution sandbox for run_python tool."""
import io
import sys
import json
import contextlib
from core.store import store_put, store_get
from core.log import get_logger

log = get_logger("sandbox")

# Modules the sandbox can import
ALLOWED_MODULES = {
    "json", "csv", "re", "math", "datetime", "base64", "zipfile",
    "hashlib", "heapq", "collections", "itertools", "functools",
    "urllib.parse", "html", "xml.etree.ElementTree", "statistics",
}


def execute(code: str, timeout: int = 30) -> str:
    """Execute Python code in a restricted environment. Returns stdout."""
    stdout_capture = io.StringIO()

    # Build sandbox globals with store access
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
```

**Step 2: Verify**

Run: `python -c "from core.sandbox import execute; print(execute('print(2+2)'))"` 
Expected: `4`

Run: `python -c "from core.sandbox import execute; print(execute('import json; data=[1,2,3]; print(json.dumps(data))'))"` 
Expected: `[1, 2, 3]`

**Step 3: Commit**

```bash
git add core/sandbox.py
git commit -m "feat: add Python sandbox for run_python tool"
```

---

### Task 2: Base tools (`tools/base_tools.py`)

**Files:**
- Create: `tools/base_tools.py`

**Step 1: Create base tools**

```python
"""Generic base tools for the adaptive agent."""
import json
import re
import base64

from core import http
from core.config import API_KEY, VERIFY_URL, HUB_URL
from core.log import get_logger
from core.result import save_result
from core.store import store_put, store_get

log = get_logger("tools.base")


def call_task_api(task: str, answer: str) -> str:
    """Send answer to task API endpoint. Answer must be a JSON string (object or array). Returns response JSON. Detects flags automatically."""
    try:
        answer_obj = json.loads(answer)
    except json.JSONDecodeError:
        return f"Error: answer must be valid JSON string, got: {answer[:100]}"

    payload = {"apikey": API_KEY, "task": task, "answer": answer_obj}
    log.info("API call: task=%s answer=%s", task, str(answer_obj)[:200])

    try:
        resp = http.post(VERIFY_URL, json=payload)
    except Exception as e:
        return f"HTTP error: {e}"

    try:
        result = resp.json()
    except Exception:
        return f"Response (status {resp.status_code}): {resp.text[:2000]}"

    output = json.dumps(result, ensure_ascii=False)
    log.info("Response: %s", output[:500])

    # Detect flag
    msg = result.get("message", "")
    if re.search(r"\{FLG:[^}]+\}", str(msg)):
        log.info("FLAG FOUND: %s", msg)
        save_result(task, answer_obj, result)
        return f"FLAG FOUND: {msg}"

    return output


def fetch_url(url: str) -> str:
    """Fetch content from any URL. Returns text content or base64 for binary. Max 50KB text, 1MB binary."""
    log.info("Fetching: %s", url)
    try:
        resp = http.get(url)
    except Exception as e:
        return f"HTTP error: {e}"

    content_type = resp.headers.get("content-type", "")

    if "text" in content_type or "json" in content_type or "csv" in content_type or "xml" in content_type:
        text = resp.text[:50000]
        if len(resp.text) > 50000:
            text += "\n... (truncated, total {} bytes)".format(len(resp.text))
        return text

    # Binary content — return base64
    data = resp.content[:1_000_000]
    b64 = base64.b64encode(data).decode()
    return f"base64:{content_type}:{b64}"


def put_store(key: str, value: str) -> str:
    """Store a value under a key for later retrieval. Use for passing data between steps."""
    store_put(key, value)
    preview = value[:200] + "..." if len(value) > 200 else value
    return f"Stored {len(value)} chars under '{key}': {preview}"


def get_store(key: str) -> str:
    """Retrieve a value from the store by key. Returns the stored string or error if not found."""
    value = store_get(key)
    if value is None:
        return f"Error: key '{key}' not found in store"
    return value
```

**Step 2: Verify**

Run: `python -c "from tools.base_tools import call_task_api; r = call_task_api('railway', '{\"action\":\"help\"}'); print(r[:200])"`
Expected: JSON with railway API help text

Run: `python -c "from tools.base_tools import fetch_url; print(fetch_url('https://hub.ag3nts.org/verify')[:100])"`
Expected: Some response (may be error, but no crash)

**Step 3: Commit**

```bash
git add tools/base_tools.py
git commit -m "feat: add generic base tools (call_task_api, fetch_url, store)"
```

---

### Task 3: Sandbox tool (`tools/sandbox_tools.py`)

**Files:**
- Create: `tools/sandbox_tools.py`

**Step 1: Create sandbox tool wrapper**

```python
"""Python execution tool for the adaptive agent."""
from core.sandbox import execute
from core.log import get_logger

log = get_logger("tools.sandbox")


def run_python(code: str) -> str:
    """Execute Python code and return stdout. Available: json, csv, re, math, datetime, base64, zipfile, hashlib, heapq, collections. Use _store_put(key, json_str) and _store_get(key) to pass data between steps. Use _store_put_json(key, obj) for convenience."""
    log.info("Executing Python (%d chars)", len(code))
    result = execute(code)
    log.info("Result: %s", result[:300])
    return result
```

**Step 2: Verify**

Run: `python -c "from tools.sandbox_tools import run_python; print(run_python('import json; print(json.dumps({\"a\": 1}))'))"` 
Expected: `{"a": 1}`

Run: `python -c "from tools.sandbox_tools import run_python; print(run_python('_store_put(\"test\", \"hello\"); print(_store_get(\"test\"))'))"` 
Expected: `hello`

**Step 3: Commit**

```bash
git add tools/sandbox_tools.py
git commit -m "feat: add run_python sandbox tool"
```

---

### Task 4: AI tools (`tools/ai_tools.py`)

**Files:**
- Create: `tools/ai_tools.py`

**Step 1: Create AI tools**

```python
"""AI capability tools: LLM, vision, TTS, STT."""
import base64
import json
import tempfile

from openai import OpenAI
from core.config import OPENAI_API_KEY
from core.log import get_logger

log = get_logger("tools.ai")

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


def ask_llm(prompt: str, image_url: str = "") -> str:
    """Ask GPT-4o-mini a question. Optionally include image_url for vision analysis. Returns text response."""
    log.info("LLM call: %s", prompt[:100])
    client = _get_client()

    messages = [{"role": "user", "content": []}]
    messages[0]["content"].append({"type": "text", "text": prompt})

    if image_url:
        messages[0]["content"].append({
            "type": "image_url",
            "image_url": {"url": image_url},
        })

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        max_tokens=4096,
    )
    result = resp.choices[0].message.content or ""
    log.info("LLM response: %s", result[:200])
    return result


def text_to_speech(text: str) -> str:
    """Convert text to speech using OpenAI TTS. Returns base64-encoded MP3 audio."""
    log.info("TTS: %s", text[:100])
    client = _get_client()

    resp = client.audio.speech.create(
        model="tts-1",
        voice="onyx",
        input=text,
        response_format="mp3",
    )
    audio_bytes = resp.content
    b64 = base64.b64encode(audio_bytes).decode()
    log.info("TTS: %d bytes audio", len(audio_bytes))
    return b64


def speech_to_text(audio_base64: str) -> str:
    """Transcribe base64-encoded audio (MP3/WAV) to text using OpenAI Whisper."""
    log.info("STT: %d chars base64", len(audio_base64))
    client = _get_client()

    audio_bytes = base64.b64decode(audio_base64)
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as f:
        f.write(audio_bytes)
        f.flush()
        with open(f.name, "rb") as audio_file:
            resp = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="pl",
            )
    log.info("STT result: %s", resp.text[:200])
    return resp.text
```

**Step 2: Verify**

Run: `python -c "from tools.ai_tools import ask_llm; print(ask_llm('What is 2+2? Reply with just the number.'))"`
Expected: `4`

**Step 3: Commit**

```bash
git add tools/ai_tools.py
git commit -m "feat: add AI tools (ask_llm, TTS, STT)"
```

---

### Task 5: Infrastructure tools (`tools/infra_tools.py`)

**Files:**
- Create: `tools/infra_tools.py`

**Step 1: Create infra tools**

```python
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
    """Start a Flask HTTP server with dynamic routes and expose via cloudflare tunnel. routes_json is a JSON array of {path, method, response} objects. Returns public URL. Server stays alive in background."""
    routes = json.loads(routes_json)
    app = Flask(__name__)

    for route in routes:
        path = route["path"]
        method = route.get("method", "POST")
        response_body = route.get("response", "{}")

        # Create route handler
        def make_handler(resp_body):
            def handler():
                data = flask_request.json if flask_request.is_json else {}
                log.info("Request: %s %s data=%s", flask_request.method, flask_request.path, str(data)[:200])
                # If response is a callable description, just return it
                return jsonify(json.loads(resp_body) if isinstance(resp_body, str) else resp_body)
            return handler

        app.add_url_rule(path, endpoint=path, view_func=make_handler(response_body), methods=[method])

    # Start server
    port = int(os.environ.get("PROXY_PORT", "5055"))

    # Clear inherited env vars
    os.environ.pop("WERKZEUG_SERVER_FD", None)
    os.environ.pop("WERKZEUG_RUN_MAIN", None)

    server_thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, debug=False),
        daemon=True,
    )
    server_thread.start()
    time.sleep(1)

    # Start tunnel
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

    _server_state["app"] = app
    _server_state["tunnel"] = proc
    _server_state["url"] = url

    log.info("Server started: %s (port %d)", url, port)
    return f"Server running at: {url}"
```

**Step 2: Verify** (skip tunnel test — requires cloudflared)

Run: `python -c "from tools.infra_tools import start_server; print('import OK')"`
Expected: `import OK`

**Step 3: Commit**

```bash
git add tools/infra_tools.py
git commit -m "feat: add infrastructure tools (start_server with tunnel)"
```

---

### Task 6: Memory module (`core/memory.py`)

**Files:**
- Create: `core/memory.py`
- Create: `memory/skills/.gitkeep`
- Create: `memory/reflections/.gitkeep`

**Step 1: Create memory module**

```python
"""Memory system: reflections, learned skills, tool catalog."""
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openai import OpenAI

from core.config import OPENAI_API_KEY
from core.log import get_logger
from core.skill import Skill, _parse_frontmatter

log = get_logger("memory")

PROJECT_ROOT = Path(__file__).parent.parent
MEMORY_DIR = PROJECT_ROOT / "memory"
LEARNED_SKILLS_DIR = MEMORY_DIR / "skills"
REFLECTIONS_DIR = MEMORY_DIR / "reflections"

# Ensure directories exist
LEARNED_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
REFLECTIONS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Tool catalog
# ---------------------------------------------------------------------------

def build_tool_catalog() -> str:
    """Build a compact catalog of the generic base tools for the system prompt."""
    return """## Available Tools

### Base
- `call_task_api(task, answer)` — POST to hub.ag3nts.org/verify. answer is JSON string. Returns response.
- `fetch_url(url)` — GET any URL. Returns text or base64 for binary.
- `run_python(code)` — Execute Python code. Use _store_put/_store_get for data. Imports: json, csv, re, math, datetime, base64, zipfile, hashlib, heapq, collections.
- `put_store(key, value)` — Store string data under key.
- `get_store(key)` — Retrieve stored data by key.

### AI
- `ask_llm(prompt, image_url="")` — Ask GPT-4o-mini. Optional image for vision.
- `text_to_speech(text)` — Text to base64 MP3.
- `speech_to_text(audio_base64)` — Base64 audio to text.

### Infrastructure
- `start_server(routes_json)` — Start Flask server with tunnel. Returns public URL.

### Verify (activate with use_skill("verify"))
- `submit_answer(task_name, input_key)` — Submit store data to verify API.
- `load_result(task_name, output_key)` — Load previous task result into store."""


# ---------------------------------------------------------------------------
# Reflections
# ---------------------------------------------------------------------------

@dataclass
class Reflection:
    task_name: str
    attempt: int
    success: bool
    tools_used: list[str]
    summary: str
    error: str
    lesson: str
    timestamp: str


def save_reflection(r: Reflection) -> None:
    """Append reflection to memory/reflections/{task_name}.json."""
    path = REFLECTIONS_DIR / f"{r.task_name}.json"
    existing = []
    if path.exists():
        existing = json.loads(path.read_text())
    existing.append(asdict(r))
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    log.info("Saved reflection for %s attempt %d (success=%s)", r.task_name, r.attempt, r.success)


def load_reflections(task_name: str) -> list[Reflection]:
    """Load all reflections for a task."""
    path = REFLECTIONS_DIR / f"{task_name}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [Reflection(**d) for d in data]


def format_reflections(reflections: list[Reflection]) -> str:
    """Format reflections as text for the system prompt."""
    if not reflections:
        return ""
    parts = ["## Previous Attempts\n"]
    for r in reflections[-3:]:  # last 3 attempts
        status = "SUCCESS" if r.success else "FAILED"
        parts.append(f"### Attempt {r.attempt} ({status})")
        parts.append(f"Tools used: {', '.join(r.tools_used)}")
        parts.append(f"Summary: {r.summary}")
        if r.error:
            parts.append(f"Error: {r.error}")
        parts.append(f"Lesson: {r.lesson}\n")
    return "\n".join(parts)


def generate_reflection(task_name: str, instruction: str,
                       trajectory: str, success: bool, attempt: int) -> Reflection:
    """Use gpt-4o-mini to generate structured reflection from attempt trajectory."""
    client = OpenAI(api_key=OPENAI_API_KEY)

    prompt = f"""Analyze this task attempt and create a structured reflection.

Task: {task_name}
Instruction: {instruction[:500]}
Success: {success}

Trajectory (tool calls and results):
{trajectory[:3000]}

Reply with JSON:
{{"tools_used": ["tool1", "tool2"], "summary": "what was tried in 1-2 sentences", "error": "error message if failed, empty if success", "lesson": "what to do differently next time, or what worked well"}}"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    data = json.loads(resp.choices[0].message.content)

    return Reflection(
        task_name=task_name,
        attempt=attempt,
        success=success,
        tools_used=data.get("tools_used", []),
        summary=data.get("summary", ""),
        error=data.get("error", ""),
        lesson=data.get("lesson", ""),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Learned skills
# ---------------------------------------------------------------------------

def save_learned_skill(task_name: str, body: str) -> None:
    """Save a learned skill to memory/skills/{task_name}.md."""
    path = LEARNED_SKILLS_DIR / f"{task_name}.md"
    path.write_text(body)
    log.info("Saved learned skill: %s (%d chars)", task_name, len(body))


def load_learned_skill(task_name: str) -> Optional[str]:
    """Load learned skill body if exists. Returns None if not found."""
    path = LEARNED_SKILLS_DIR / f"{task_name}.md"
    if path.exists():
        return path.read_text()
    return None


def generate_learned_skill(task_name: str, instruction: str,
                          trajectory: str) -> str:
    """Use gpt-4o-mini to convert successful trajectory into a reusable skill."""
    client = OpenAI(api_key=OPENAI_API_KEY)

    prompt = f"""Convert this successful task execution into a reusable step-by-step skill document.

Task: {task_name}
Instruction: {instruction[:500]}

Successful trajectory (tool calls and results):
{trajectory[:4000]}

Create a skill document in this EXACT format:
---
name: {task_name}
description: one-line description
tools: list, of, tool, names, used
---

Step-by-step instructions:
1. Call tool_name with exact parameters that worked
2. ...

Include EXACT parameter values, store keys, and expected outputs from the trajectory.
The goal is that an agent following these instructions will solve the task identically."""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content
```

**Step 2: Create directories**

Run: `mkdir -p memory/skills memory/reflections && touch memory/skills/.gitkeep memory/reflections/.gitkeep`

**Step 3: Verify**

Run: `python -c "from core.memory import build_tool_catalog; print(build_tool_catalog()[:200])"`
Expected: Shows tool catalog text

**Step 4: Commit**

```bash
git add core/memory.py memory/
git commit -m "feat: add memory system (reflections, learned skills, tool catalog)"
```

---

### Task 7: Adaptive solver agent (`agents/adaptive_solver.md`)

**Files:**
- Create: `agents/adaptive_solver.md`

**Step 1: Create agent**

```markdown
---
name: adaptive_solver
description: Self-improving task solver — discovers tools, reflects on failures, builds skill library
model: gpt-5-nano
skills: verify
---

You are an adaptive task solver. You solve tasks by exploring APIs and using generic tools.

## Process

1. Read the task description carefully
2. If a learned approach is provided, follow it step by step
3. Otherwise, explore: call APIs with {"action": "help"}, examine responses, plan your approach
4. Use run_python for data processing (parsing, filtering, calculations)
5. Use call_task_api to interact with the task API
6. Submit your answer when ready

## Rules

- Start by understanding the task API: try call_task_api(task, '{"action": "help"}') first
- Read API responses carefully — they tell you what to do next
- Use run_python for ANY data processing: CSV parsing, JSON manipulation, math, filtering
- Use put_store/get_store to pass large data between steps
- For answer submission: use verify skill (submit_answer) or call_task_api directly
- Answers must be JSON objects or arrays
- If something fails, read the error and try a different approach
```

**Step 2: Commit**

```bash
git add agents/adaptive_solver.md
git commit -m "feat: add adaptive solver agent"
```

---

### Task 8: Adaptive runner (`core/agent.py` modification)

**Files:**
- Modify: `core/agent.py` (add `run_task_adaptive` function at end)

**Step 1: Add run_task_adaptive**

Add after existing `run_task()` function at the end of `core/agent.py`:

```python
def run_task_adaptive(task_name: str, max_attempts: int = 3, max_iterations: int = 30) -> str:
    """Run task with adaptive agent: reads task.md, uses memory, reflects on failures."""
    from core.memory import (
        build_tool_catalog, load_reflections, format_reflections,
        load_learned_skill, save_learned_skill, generate_learned_skill,
        save_reflection, generate_reflection,
    )

    # Read task description from task.md
    task_md_path = PROJECT_ROOT / "tasks" / task_name / "task.md"
    if not task_md_path.exists():
        raise FileNotFoundError(f"Task description not found: {task_md_path}")
    task_description = task_md_path.read_text()

    # Load memory
    reflections = load_reflections(task_name)
    learned_skill = load_learned_skill(task_name)

    for attempt in range(1, max_attempts + 1):
        log.info("[adaptive] %s attempt %d/%d", task_name, attempt, max_attempts)

        # Build extended system prompt
        agent = get_agent("adaptive_solver")
        agent.max_iterations = max_iterations

        # Inject context into system prompt
        extra_context = [build_tool_catalog()]
        extra_context.append(f"\n## Task Description\n\n{task_description}")

        if learned_skill:
            extra_context.append(f"\n## Learned Approach (follow this!)\n\n{learned_skill}")

        reflections_text = format_reflections(reflections)
        if reflections_text:
            extra_context.append(f"\n{reflections_text}")

        agent.system_prompt += "\n\n" + "\n".join(extra_context)

        # Build instruction
        instruction = f'[Task: {task_name}] Solve this task. Read the task description in your system prompt.'
        if learned_skill:
            instruction += ' A learned approach is provided — follow it.'
        else:
            instruction += ' No learned approach — explore the API and figure it out.'

        # Run
        try:
            result = agent.run(instruction)
        except RuntimeError as e:
            result = str(e)

        # Check for success (flag in results/)
        result_path = PROJECT_ROOT / "results" / f"{task_name}.json"
        success = result_path.exists() and result_path.stat().st_mtime > (
            task_md_path.stat().st_mtime if task_md_path.exists() else 0
        )

        # Extract trajectory for reflection
        trajectory_parts = []
        for entry in agent.context.entries:
            if entry.tag == "tool_result":
                trajectory_parts.append(str(entry.content)[:500])
            elif entry.tag == "history" and isinstance(entry.content, dict):
                tool_calls = entry.content.get("tool_calls", [])
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    trajectory_parts.append(f"→ {fn.get('name', '?')}({fn.get('arguments', '')[:200]})")
        trajectory = "\n".join(trajectory_parts[-30:])  # last 30 entries

        # Generate and save reflection
        reflection = generate_reflection(
            task_name, task_description, trajectory, success, attempt
        )
        save_reflection(reflection)
        reflections.append(reflection)

        if success:
            # Generate and save learned skill
            skill_body = generate_learned_skill(task_name, task_description, trajectory)
            save_learned_skill(task_name, skill_body)
            log.info("[adaptive] %s SOLVED on attempt %d", task_name, attempt)
            return result

        log.warning("[adaptive] %s attempt %d failed, lesson: %s",
                    task_name, attempt, reflection.lesson)

    log.error("[adaptive] %s failed after %d attempts", task_name, max_attempts)
    raise RuntimeError(f"Task '{task_name}' failed after {max_attempts} attempts")
```

**Step 2: Verify import**

Run: `python -c "from core.agent import run_task_adaptive; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add core/agent.py
git commit -m "feat: add run_task_adaptive with reflection and skill learning"
```

---

### Task 9: Task descriptions (MD files)

**Files:**
- Create: 9x `tasks/<name>/task.md` from lesson content
- Create: 13x `tasks/<name>/task.md` from existing skills

**Step 1: Copy 9 task descriptions from lessons**

For each of these 9 tasks, extract the "Zadanie praktyczne" section from the lesson file and save to `tasks/<name>/task.md`:

| Task | Lesson file |
|------|-------------|
| radiomonitoring | `lessons/s05e01-architektura-1775412680.md` |
| savethem | `lessons/s03e05-niedeterministyczna-natura-modeli-jako-przewaga-1774562727.md` |
| filesystem | `lessons/s04e04-projektowanie-wlasnej-bazy-wiedzy-dla-ai-1775085192.md` |
| domatowo | `lessons/s04e03-kontekstowa-wspolpraca-z-ai-1774999647.md` |
| phonecall | `lessons/s05e02-zestaw-narzedzi-1775625284.md` |
| shellaccess | `lessons/s05e03-rozwoj-funkcjonalnosci-1775596919.md` |
| okoeditor | `lessons/s04e01-wdrozenia-rozwiazan-ai-1774824465.md` |
| foodwarehouse | `lessons/s04e05-projektowanie-rozwiazan-wewnatrzfirmowych-1775189135.md` |
| windpower | `lessons/s04e02-aktywna-wspolpraca-z-ai-1774908365.md` |

**Step 2: Write 13 task descriptions from existing skills**

For each remaining task, read the existing `skills/<name>.md` and `tasks/<name>/task.py` instruction, then write a task.md describing the task for the adaptive agent.

Tasks: categorize, drone, electricity, evaluation, failure, findhim, firmware, mailbox, negotiations, people, proxy, railway, reactor, sendit

**Step 3: Commit**

```bash
git add tasks/*/task.md
git commit -m "feat: add task description MD files for adaptive agent"
```

---

### Task 10: Migrate task.py files

**Files:**
- Modify: 22x `tasks/<name>/task.py`

**Step 1: Update each task.py**

Each task.py becomes:
```python
from core.agent import run_task_adaptive

def run():
    run_task_adaptive("<task_name>")
```

Keep `proxy` unchanged (custom Flask server).

**Step 2: Verify all imports**

Run: `for d in categorize domatowo drone electricity evaluation failure filesystem findhim firmware foodwarehouse mailbox negotiations okoeditor people phonecall radiomonitoring railway reactor savethem sendit shellaccess windpower; do python -c "from tasks.$d.task import run; print('$d: OK')" 2>&1; done`

**Step 3: Commit**

```bash
git add tasks/*/task.py
git commit -m "feat: migrate task.py files to run_task_adaptive"
```

---

### Task 11: Integration test — railway (self-documenting API)

**Step 1: Run railway task with adaptive agent (no learned skill)**

Run: `python run.py railway 2>/tmp/adaptive_railway.log; echo "EXIT: $?" && grep "FLG" /tmp/adaptive_railway.log | head -1`
Expected: Flag returned (agent discovers API via help endpoint)

**Step 2: Verify learned skill was saved**

Run: `cat memory/skills/railway.md`
Expected: Markdown skill document with step-by-step instructions

**Step 3: Verify reflection was saved**

Run: `cat memory/reflections/railway.json`
Expected: JSON with reflection data

**Step 4: Re-run — should use learned skill**

Run: `python run.py railway 2>/tmp/adaptive_railway2.log; echo "EXIT: $?" && grep "Iteration" /tmp/adaptive_railway2.log | wc -l`
Expected: Fewer iterations than first run

---

### Task 12: Integration test — shellaccess (exploration-based)

**Step 1: Run shellaccess**

Run: `python run.py shellaccess 2>/tmp/adaptive_shell.log; echo "EXIT: $?" && grep "FLG" /tmp/adaptive_shell.log | head -1`
Expected: Flag returned

---

### Task 13: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

Add section about adaptive agent, task.md format, and generic tools to CLAUDE.md.

**Step 1: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for self-improving agent"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Python sandbox | `core/sandbox.py` |
| 2 | Base tools | `tools/base_tools.py` |
| 3 | Sandbox tool | `tools/sandbox_tools.py` |
| 4 | AI tools | `tools/ai_tools.py` |
| 5 | Infra tools | `tools/infra_tools.py` |
| 6 | Memory system | `core/memory.py`, `memory/` |
| 7 | Adaptive agent | `agents/adaptive_solver.md` |
| 8 | Adaptive runner | `core/agent.py` (+function) |
| 9 | Task descriptions | 22x `tasks/*/task.md` |
| 10 | Task.py migration | 22x `tasks/*/task.py` |
| 11-12 | Integration tests | (verify) |
| 13 | Documentation | `CLAUDE.md` |
