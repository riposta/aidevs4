import json
import os
import re
import subprocess
from pathlib import Path

from flask import Flask, render_template, request, jsonify, redirect, url_for, Response

PROJECT_ROOT = Path(__file__).parent.parent
AGENTS_DIR = PROJECT_ROOT / "agents"
SKILLS_DIR = PROJECT_ROOT / "skills"
TOOLS_DIR = PROJECT_ROOT / "tools"
TASKS_DIR = PROJECT_ROOT / "tasks"
RESULTS_DIR = PROJECT_ROOT / "results"
LOGS_DIR = PROJECT_ROOT / "log"
LESSONS_DIR = PROJECT_ROOT / "lessons"

app = Flask(__name__)
app.jinja_env.policies["json.dumps_kwargs"] = {"ensure_ascii": False}


def _extract_flag(data: dict) -> str:
    """Extract FLG:xxx from result data, return empty string if not found."""
    msg = data.get("response", {}).get("message", "")
    m = re.search(r"\{FLG:[^}]+\}", msg)
    return m.group(0) if m else ""


app.jinja_env.globals["extract_flag"] = _extract_flag


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


LESSON_TASK_MAP = {
    "s01e01": "nazwa-zadania", "s01e02": "findhim", "s01e03": "proxy",
    "s01e04": "sendit", "s01e05": "railway", "s02e01": "categorize",
    "s02e02": "electricity", "s02e03": "failure", "s02e04": "mailbox",
    "s02e05": "drone", "s03e01": "evaluation", "s03e02": "firmware",
    "s03e03": "reactor", "s03e04": "negotiations", "s03e05": "savethem",
    "s04e01": "okoeditor", "s04e02": "windpower", "s04e03": "domatowo",
    "s04e04": "filesystem", "s04e05": "foodwarehouse",
    "s05e01": "radiomonitoring", "s05e02": "phonecall",
    "s05e03": "shellaccess", "s05e04": "goingthere",
}


def _scan_lessons() -> list[dict]:
    """Scan lessons/ directory and extract lesson metadata."""
    lessons = []
    if not LESSONS_DIR.exists():
        return lessons
    for p in sorted(LESSONS_DIR.glob("*.md")):
        meta, body = _parse_frontmatter(p.read_text()[:2000])
        prefix = p.stem[:6]  # e.g. "s01e01"
        task_name = LESSON_TASK_MAP.get(prefix, "")
        season = prefix[:3]  # "s01"
        episode = prefix[3:]  # "e01"
        title = meta.get("title", p.stem.split("-", 1)[1].rsplit("-", 1)[0].replace("-", " ") if "-" in p.stem else p.stem)
        lessons.append({
            "file": p.name,
            "stem": p.stem,
            "prefix": prefix,
            "season": season,
            "episode": episode,
            "title": title,
            "task_name": task_name,
            "path": str(p.relative_to(PROJECT_ROOT)),
        })
    return lessons


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
    tools = _scan_tools()
    results = _scan_results()
    lessons = _scan_lessons()
    solved = {name for name, data in results.items()
              if data.get("response", {}).get("code", -1) == 0}
    logs = {p.stem for p in LOGS_DIR.glob("*.log")} if LOGS_DIR.exists() else set()
    total_fns = sum(len(t["functions"]) for t in tools)
    memory_dir = PROJECT_ROOT / "memory" / "skills"
    learned = {p.stem for p in memory_dir.glob("*.md")} if memory_dir.exists() else set()
    return render_template("dashboard.html", logs=logs, solved=solved, total_fns=total_fns,
                           agents=agents, skills=skills, tools=tools,
                           results=results, lessons=lessons, learned=learned)


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
model: gpt-5.4-mini
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


@app.route("/lesson/<path:filename>")
def lesson_view(filename):
    """View a lesson with rendered markdown and run button."""
    full = LESSONS_DIR / filename
    if not full.exists():
        return "Lesson not found", 404
    content = full.read_text()
    prefix = full.stem[:6]
    task_name = LESSON_TASK_MAP.get(prefix, "")
    has_result = (RESULTS_DIR / f"{task_name}.json").exists() if task_name else False
    has_log = (LOGS_DIR / f"{task_name}.log").exists() if task_name else False
    return render_template("lesson.html", filename=filename, content=content,
                           task_name=task_name, has_result=has_result, has_log=has_log)


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
        event_prefix = "@@EVENT::"

        try:
            with open(log_path, "w") as log_file:
                for line in proc.stdout:
                    stripped = line.rstrip()
                    if stripped.startswith(event_prefix):
                        # Structured event — send as bubble
                        payload = stripped[len(event_prefix):]
                        yield f"event: bubble\ndata: {payload}\n\n"
                    else:
                        # Raw log line
                        log_file.write(line)
                        log_file.flush()
                        yield f"data: {json.dumps(stripped)}\n\n"
            proc.wait()
            with open(log_path, "a") as log_file:
                log_file.write(f"[exit code: {proc.returncode}]\n")
            yield f"data: {json.dumps(f'[exit code: {proc.returncode}]')}\n\n"
        finally:
            _running_procs.pop(task_name, None)
        yield "event: done\ndata: done\n\n"

    return Response(generate(), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(debug=True, port=5099)
