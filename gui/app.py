import json
import os
import queue
import re
import subprocess
import threading
from pathlib import Path

from flask import Flask, render_template, request, jsonify, redirect, url_for, Response

PROJECT_ROOT = Path(__file__).parent.parent
AGENTS_DIR = PROJECT_ROOT / "agents"
SKILLS_DIR = PROJECT_ROOT / "skills"
TOOLS_DIR = PROJECT_ROOT / "tools"
TASKS_DIR = PROJECT_ROOT / "tasks"
RESULTS_DIR = PROJECT_ROOT / "results"
LOGS_DIR = PROJECT_ROOT / "log"

app = Flask(__name__)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"(\w[\w-]*):\s*(.*)", line)
        if kv:
            meta[kv.group(1)] = kv.group(2).strip()
    return meta, m.group(2)


def _scan_items(directory: Path, ext: str) -> list[dict]:
    items = []
    if not directory.exists():
        return items
    for p in sorted(directory.glob(f"*{ext}")):
        text = p.read_text()
        meta, body = _parse_frontmatter(text)
        items.append({
            "file": p.name,
            "stem": p.stem,
            "name": meta.get("name", p.stem),
            "description": meta.get("description", ""),
            "model": meta.get("model", ""),
            "skills": meta.get("skills", ""),
            "tools": meta.get("tools", ""),
            "path": str(p.relative_to(PROJECT_ROOT)),
        })
    return items


def _scan_tasks() -> list[dict]:
    tasks = []
    if not TASKS_DIR.exists():
        return tasks
    for p in sorted(TASKS_DIR.iterdir()):
        if p.is_dir() and (p / "task.py").exists():
            tasks.append({
                "name": p.name,
                "path": str((p / "task.py").relative_to(PROJECT_ROOT)),
                "has_agents": (p / "agents").exists(),
                "has_skills": (p / "skills").exists(),
            })
    return tasks


def _scan_results() -> dict[str, dict]:
    """Return dict mapping task_name -> result data."""
    results = {}
    if not RESULTS_DIR.exists():
        return results
    for p in sorted(RESULTS_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text())
            results[p.stem] = data
        except (json.JSONDecodeError, KeyError):
            pass
    return results


def _scan_tools() -> list[dict]:
    tools = []
    if not TOOLS_DIR.exists():
        return tools
    for p in sorted(TOOLS_DIR.glob("*.py")):
        # Extract public function names
        fns = []
        for line in p.read_text().splitlines():
            m = re.match(r"^def ([a-z_]\w*)\(", line)
            if m and not m.group(1).startswith("_"):
                fns.append(m.group(1))
        # Find matching skill
        skill_name = p.stem.removesuffix("_tools")
        tools.append({
            "file": p.name,
            "stem": p.stem,
            "skill": skill_name,
            "functions": fns,
            "path": str(p.relative_to(PROJECT_ROOT)),
        })
    return tools


# --- Routes ---

@app.route("/")
def dashboard():
    agents = _scan_items(AGENTS_DIR, ".md")
    skills = _scan_items(SKILLS_DIR, ".md")
    tasks = _scan_tasks()
    tools = _scan_tools()
    results = _scan_results()
    solved = {name for name, data in results.items()
              if data.get("response", {}).get("code", -1) == 0}
    logs = {p.stem for p in LOGS_DIR.glob("*.log")} if LOGS_DIR.exists() else set()
    total_fns = sum(len(t["functions"]) for t in tools)
    return render_template("dashboard.html", logs=logs, solved=solved, total_fns=total_fns,
                           agents=agents, skills=skills, tasks=tasks, tools=tools,
                           results=results)


@app.route("/edit/<path:filepath>")
def edit(filepath):
    full = PROJECT_ROOT / filepath
    if not full.exists():
        return "File not found", 404
    content = full.read_text()
    lang = "python" if filepath.endswith(".py") else "markdown"
    # Detect if this is a task file -> pass task_name for run button
    task_name = None
    has_log = False
    if filepath.startswith("tasks/") and filepath.endswith("/task.py"):
        task_name = filepath.split("/")[1]
        has_log = (LOGS_DIR / f"{task_name}.log").exists()
    return render_template("editor.html", filepath=filepath, content=content, lang=lang,
                           task_name=task_name, has_log=has_log)


@app.route("/api/save", methods=["POST"])
def save():
    data = request.json
    filepath = data.get("filepath")
    content = data.get("content")
    if not filepath or content is None:
        return jsonify({"error": "Missing filepath or content"}), 400
    full = PROJECT_ROOT / filepath
    if not full.exists() and not full.parent.exists():
        return jsonify({"error": "Parent directory does not exist"}), 400
    full.write_text(content)
    return jsonify({"ok": True})


@app.route("/new/<item_type>")
def new_item(item_type):
    return render_template("new_item.html", item_type=item_type)


@app.route("/api/create", methods=["POST"])
def create():
    data = request.json
    item_type = data.get("type")
    name = data.get("name", "").strip()
    if not name or not item_type:
        return jsonify({"error": "Missing name or type"}), 400

    if item_type == "agent":
        path = AGENTS_DIR / f"{name}.md"
        content = f"""---
name: {name}
description:
model: gpt-4o
skills:
---

You are a task solver agent.

Activate each skill with `use_skill` before using its tools.

## Process

1.
"""
        path.write_text(content)
        return jsonify({"ok": True, "redirect": url_for("edit", filepath=str(path.relative_to(PROJECT_ROOT)))})

    elif item_type == "skill":
        path = SKILLS_DIR / f"{name}.md"
        content = f"""---
name: {name}
description:
tools:
---

"""
        path.write_text(content)
        # Also create companion tools file
        tools_path = TOOLS_DIR / f"{name}_tools.py"
        if not tools_path.exists():
            tools_path.write_text(f'''import json

from core.log import get_logger
from core.store import store_get, store_put

log = get_logger("tools.{name}")

''')
        return jsonify({"ok": True, "redirect": url_for("edit", filepath=str(path.relative_to(PROJECT_ROOT)))})

    elif item_type == "task":
        task_dir = TASKS_DIR / name
        task_dir.mkdir(exist_ok=True)
        (task_dir / "__init__.py").write_text("")
        task_path = task_dir / "task.py"
        content = f"""from core.agent import get_agent


def run():
    solver = get_agent("{name}_solver")
    solver.run("")
"""
        task_path.write_text(content)
        return jsonify({"ok": True, "redirect": url_for("edit", filepath=str(task_path.relative_to(PROJECT_ROOT)))})

    return jsonify({"error": f"Unknown type: {item_type}"}), 400


@app.route("/api/delete", methods=["POST"])
def delete():
    data = request.json
    filepath = data.get("filepath")
    if not filepath:
        return jsonify({"error": "Missing filepath"}), 400
    full = PROJECT_ROOT / filepath
    if not full.exists():
        return jsonify({"error": "File not found"}), 404
    full.unlink()
    return jsonify({"ok": True})


@app.route("/result/<task_name>")
def result_page(task_name):
    result_path = RESULTS_DIR / f"{task_name}.json"
    if not result_path.exists():
        return "No result found", 404
    data = json.loads(result_path.read_text())
    return render_template("result.html", task_name=task_name, data=data)


@app.route("/log/<task_name>")
def log_page(task_name):
    jsonl_path = LOGS_DIR / f"{task_name}.jsonl"
    if jsonl_path.exists():
        events = []
        for line in jsonl_path.read_text().splitlines():
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return render_template("log_bubbles.html", task_name=task_name, events=events)
    # Fallback to plain text log
    log_path = LOGS_DIR / f"{task_name}.log"
    if not log_path.exists():
        return "No log found", 404
    content = log_path.read_text()
    return render_template("log.html", task_name=task_name, content=content)


@app.route("/run/<task_name>")
def run_task_page(task_name):
    return render_template("runner.html", task_name=task_name)


_running_procs: dict[str, subprocess.Popen] = {}


@app.route("/api/stop/<task_name>", methods=["POST"])
def stop_task(task_name):
    proc = _running_procs.get(task_name)
    if proc and proc.poll() is None:
        import signal
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        return jsonify({"ok": True})
    return jsonify({"error": "No running process"}), 404


@app.route("/api/run/<task_name>")
def run_task_stream(task_name):
    verbose = request.args.get("verbose", "false") == "true"

    def generate():
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        cmd = ["python", "run.py", task_name]
        if verbose:
            cmd.append("-v")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
            env=env,
            text=True,
            bufsize=1,
            preexec_fn=os.setsid,
        )
        _running_procs[task_name] = proc
        LOGS_DIR.mkdir(exist_ok=True)
        log_path = LOGS_DIR / f"{task_name}.log"
        jsonl_path = LOGS_DIR / f"{task_name}.jsonl"

        # Tail JSONL in background thread
        event_queue = queue.Queue()
        stop_tail = threading.Event()

        def tail_jsonl():
            pos = 0
            while not stop_tail.is_set():
                if jsonl_path.exists():
                    with open(jsonl_path, "r") as f:
                        f.seek(pos)
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    event_queue.put(json.loads(line))
                                except json.JSONDecodeError:
                                    pass
                        pos = f.tell()
                stop_tail.wait(0.1)

        tail_thread = threading.Thread(target=tail_jsonl, daemon=True)
        tail_thread.start()

        try:
            with open(log_path, "w") as log_file:
                for line in proc.stdout:
                    log_file.write(line)
                    log_file.flush()
                    yield f"data: {json.dumps(line.rstrip())}\n\n"
                    # Flush any pending bubble events
                    while not event_queue.empty():
                        ev = event_queue.get_nowait()
                        yield f"event: bubble\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
            proc.wait()
            # Flush remaining events
            stop_tail.set()
            tail_thread.join(timeout=1)
            while not event_queue.empty():
                ev = event_queue.get_nowait()
                yield f"event: bubble\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
            with open(log_path, "a") as log_file:
                log_file.write(f"[exit code: {proc.returncode}]\n")
            yield f"data: {json.dumps(f'[exit code: {proc.returncode}]')}\n\n"
        finally:
            stop_tail.set()
            _running_procs.pop(task_name, None)
        yield "event: done\ndata: done\n\n"

    return Response(generate(), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(debug=True, port=5099)
