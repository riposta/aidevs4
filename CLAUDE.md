# AIDevs4 Framework

## Architecture

```
aidevs4/
├── core/           # Framework (don't modify unless asked)
├── agents/         # Agent definitions (.md with YAML frontmatter)
│   └── universal_solver.md  # Single agent for all tasks
├── skills/         # Skill definitions (.md — one per task)
├── tools/          # Tool implementations (Python — organized by category)
├── tasks/          # Task entry points (minimal stubs)
│   └── <name>/
│       ├── task.py       # def run() — calls run_task()
│       └── __init__.py
└── run.py          # CLI: python run.py <task_name> [-v]
```

## Responsibility Layers

| Layer | Contains | Knows about |
|-------|----------|-------------|
| **Task** (.py) | Minimal stub: `run_task(name, instruction)` | Task name and instruction text |
| **Agent** (.md) | Universal solver — generic process | Only "activate skill, follow instructions" |
| **Skill** (.md) | Tool usage instructions, task-specific parameters | Tool names, parameter values |
| **Tool** (.py) | Generic reusable logic, organized by category | Store keys, APIs, data processing |

One universal agent (`universal_solver`) handles all tasks.
Skills are lazy-loaded by name — agent activates them via `use_skill`.
Tools are organized by category (shell, transport, geo, etc.), not by task name.
Skill loader searches ALL `tools/*_tools.py` files for functions.

## Adding a New Task — Step by Step

### 1. Create task entry point

```
tasks/<task_name>/task.py
tasks/<task_name>/__init__.py  (empty file)
```

`task.py` is a minimal stub using the universal agent:

```python
from core.agent import run_task

def run():
    run_task("<task_name>", "<instruction describing what to do>")
```

`run_task` loads `universal_solver`, prefixes instruction with skill activation hint, and runs with 30 max iterations (configurable via `max_iterations` kwarg).

No per-task agent needed — the universal agent handles everything.

### 2. Create skill (one per task)

File: `skills/<task_name>.md` — skill name MUST match task name (convention).

```markdown
---
name: <task_name>
description: <one-line description shown to agent before activation>
tools: tool_func1, tool_func2
---

<Instructions for the agent — what tools to call and with what parameters>

Use `tool_func1` with param1="value1", param2="value2".
Then use `tool_func2` with tag="specific_tag".

After completion, use verify skill: submit_answer(task_name="<task_name>", input_key="filtered")
```

Rules:
- Skill name == task name (universal agent activates skill by task name)
- Skill body contains task-specific parameters (filter values, tag names, URLs, etc.)
- `tools:` in frontmatter lists function names — loader searches ALL `tools/*_tools.py` files
- Description should be short — it's shown in system prompt before activation
- Body is shown only when agent calls `use_skill`
- Include verify/submit instructions unless the tool handles submission internally

### 3. Add tools to existing category file (or create new category)

Tools are organized by category in `tools/<category>_tools.py`. Add new functions to the appropriate existing file:

| Category | File | What belongs here |
|----------|------|-------------------|
| `verify` | `verify_tools.py` | Answer submission, result loading |
| `data` | `data_tools.py` | CSV download, filtering, tagging, classification |
| `shell` | `shell_tools.py` | Remote command execution |
| `mail` | `mail_tools.py` | Email search and reading |
| `audio` | `audio_tools.py` | TTS, STT, phone conversations |
| `geo` | `geo_tools.py` | Geocoding, distance, location lookup |
| `grid` | `grid_tools.py` | Board/grid puzzle solving |
| `navigation` | `navigation_tools.py` | Pathfinding, route planning |
| `transport` | `transport_tools.py` | Railway, drone, package operations |
| `document` | `document_tools.py` | Document fetch, filesystem, declarations |
| `logs` | `logs_tools.py` | Log analysis and compression |
| `monitoring` | `monitoring_tools.py` | Signal collection and analysis |
| `web` | `web_tools.py` | Web scraping, API servers, tunnels |
| `classification` | `classification_tools.py` | Item categorization with budget |
| `evaluation` | `evaluation_tools.py` | Sensor data anomaly detection |

```python
import json
from core.log import get_logger
from core.store import store_put, store_get

log = get_logger("tools.<category>")

def tool_func1(param1: str, param2: str) -> str:
    """One-line description for OpenAI function schema."""
    result = process(param1, param2)
    store_put("result_key", json.dumps(result, ensure_ascii=False))
    return f"Processed {len(result)} items: {summary}"
```

Rules:
- Type hints required on all params (str, int, float, bool only)
- Always return `str` — this goes into agent context
- Return SHORT SUMMARIES, not raw data
- Use `store_put()`/`store_get()` for large data between tools
- Store is cleared at each `agent.run()` start
- Docstring becomes the tool description in OpenAI schema
- Logger name: `tools.<category>`
- Filename does NOT need to match skill name — loader searches globally

### 5. Reusable skill: verify

The `verify` skill is already available. Add `verify` to agent's skills list.

Tools provided by verify skill:
- `submit_answer(task_name, input_key)` — reads answer from store key `input_key`, submits to verification API, auto-saves result to `results/<task_name>.json`
- `load_result(task_name, output_key)` — loads a previous task's answer from `results/<task_name>.json` into store under `output_key` (useful when tasks depend on each other)

**IMPORTANT: The answer stored under `input_key` MUST be a JSON object or array, never a plain string.** The verification API rejects plain strings. Always store dicts or lists:

```python
# CORRECT — dict or list
store_put("filtered", json.dumps({"field": value}, ensure_ascii=False))
store_put("filtered", json.dumps([item1, item2], ensure_ascii=False))

# WRONG — plain string (will cause 400 Bad Request)
store_put("filtered", json.dumps("some text", ensure_ascii=False))
```

### 6. Result saving

Results are saved automatically by `submit_answer` to `results/<task_name>.json`.
For tasks with custom submit logic (not using verify skill), use `core.result.save_result`:

```python
from core.result import save_result

save_result("task_name", answer_data, {"code": 0, "message": "{FLG:...}"})
```

The GUI reads these files to show flags and results on the dashboard.

### 7. Test

```bash
python run.py <task_name>       # Normal run
python run.py <task_name> -v    # Verbose (DEBUG) logging
```

## Store Convention

Tools pass large data between each other via `core.store`:
- `store_put(key, json_string)` — save data
- `store_get(key)` — read data (returns `None` if key missing)
- Agent never sees store contents — only short summaries from tool return values

Common keys: `candidates`, `tagged`, `filtered` (default key read by verify skill).

## Existing Reusable Components

| Component | Type | Purpose |
|-----------|------|---------|
| `universal_solver` | agent | Universal task solver — handles all tasks via lazy skill loading |
| `verify` | skill | `submit_answer(task_name, input_key)` — submits answer + saves result |
| `verify` | skill | `load_result(task_name, output_key)` — loads previous task's answer into store |
| `compactor` | agent | Context compaction (gpt-5.4) |
| `summarizer` | agent | Data summarization (gpt-5.4) |

## Event Logging (GUI Bubbles)

Tasks that use `agent.run()` get bubble events automatically from `core/agent.py`.
Tasks with custom loops (like proxy) must emit events manually via `core.event_log`.

```python
from core import event_log
```

### Standard events (always visible in GUI):

| Type | When | Example |
|------|------|---------|
| `system` | Setup, config, status | `event_log.emit("system", agent="name", content="Server started")` |
| `user` | Incoming user message | `event_log.emit("user", agent="name", content=msg)` |
| `tool_call` | Before tool execution | `event_log.emit("tool_call", agent="name", name="fn_name", args={...})` |
| `tool_result` | After tool execution | `event_log.emit("tool_result", agent="name", name="fn_name", content=result)` |
| `response` | Final text response | `event_log.emit("response", agent="name", content=text)` |
| `error` | Errors | `event_log.emit("error", agent="name", content=str(e))` |

### Verbose events (visible only with verbose toggle in GUI):

| Type | When | Example |
|------|------|---------|
| `iteration` | Each ReAct loop step | `event_log.emit("iteration", agent="name", content="iteration 1")` |
| `debug` | Context, tokens, internals | `event_log.emit("debug", agent="name", label="context", content=json_str)` |
| `debug` | Token usage | `event_log.emit("debug", agent="name", label="tokens", content="500+120")` |
| `reasoning` | Model reasoning/thinking | `event_log.emit("reasoning", agent="name", content=text)` |

Verbose events use CSS class `bubble-debug` (hidden by default, shown with `.show-debug` toggle).

### Rules:
- Every custom ReAct loop MUST emit both standard and verbose events
- `agent` parameter should identify the source (agent name or component)
- `content` for tool_result should be truncated: `result[:500]`
- `debug` events accept a `label` kwarg (shown as badge: CONTEXT, TOKENS, etc.)
- Events are written to both JSONL log file and stderr (for live GUI streaming via `@@EVENT::` prefix)

## File Naming

- Agent: `agents/universal_solver.md` (single universal agent)
- Skill: `skills/<task_name>.md` (one per task, name matches task)
- Tools: `tools/<category>_tools.py` (organized by function category, NOT by task)
- Task: `tasks/<name>/task.py` (minimal stub calling `run_task`)

Exception: `proxy` task has custom `task.py` with Flask server (not using universal agent).
