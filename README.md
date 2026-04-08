# AIDevs4 Console

Agent framework for solving AI Devs (season 4) tasks. ReAct loop with OpenAI function calling, layered architecture (Agent > Skill > Tool), web GUI with live bubble logs.

## Quick Start

```bash
# 1. Setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — set API_KEY and OPENAI_API_KEY

# 3. Run a task
python run.py <task_name>        # normal mode
python run.py <task_name> -v     # verbose (DEBUG logging)

# 4. Run GUI
python gui/app.py                # http://localhost:5099
```

## Architecture

```
aidevs4/
├── core/               # Framework internals
│   ├── agent.py        # ReAct loop, agent registry, tool execution
│   ├── context.py      # Message context with pinning & compaction
│   ├── skill.py        # Skill loader (markdown frontmatter)
│   ├── store.py        # Key-value store for passing data between tools
│   ├── config.py       # .env config (API_KEY, OPENAI_API_KEY)
│   ├── verify.py       # POST to hub.ag3nts.org/verify
│   ├── http.py         # HTTP client with 429 retry (exponential backoff)
│   ├── event_log.py    # Structured JSONL event logging
│   └── log.py          # Color logger with global level control
├── agents/             # Agent definitions (.md) — universal_solver + utilities
├── skills/             # Skill definitions (.md) — one per task
├── tools/              # Tool implementations (.py) — organized by category
├── tasks/              # Task entry points
│   └── <name>/
│       ├── task.py     # def run() — loads agent(s) and starts
│       └── __init__.py
├── gui/                # Web GUI (Flask)
│   ├── app.py          # Routes, SSE streaming, CRUD
│   ├── templates/      # Jinja2 templates
│   └── static/         # CSS
├── results/            # Task results (JSON, auto-saved after verify)
├── log/                # Run logs (.log text + .jsonl structured)
└── run.py              # CLI entry point
```

## How It Works

### Responsibility Layers

| Layer | File | Contains | Knows about |
|-------|------|----------|-------------|
| **Task** | `tasks/<name>/task.py` | Minimal stub: `run_task(name, instruction)` | Task name + instruction |
| **Agent** | `agents/universal_solver.md` | Generic process: activate skill → follow instructions | "use_skill" mechanism |
| **Skill** | `skills/<task_name>.md` | Tool usage instructions, parameters | Tool names, store keys |
| **Tool** | `tools/<category>_tools.py` | Reusable logic by category | APIs, data processing |

One universal agent handles all tasks. Skills are lazy-loaded by name.
Tools organized by category (shell, transport, geo, etc.), not by task.

### Data Flow

```
Agent (LLM)
  │
  ├─ use_skill("data") ──► Skill instructions loaded into context
  │
  ├─ download_and_filter(...) ──► Tool executes, stores data in store
  │     │
  │     └─ store_put("candidates", json) ──► Large data stays in store
  │     └─ returns "Filtered 31 candidates"  ──► Short summary to agent
  │
  ├─ tag_people(...) ──► Reads from store, writes to store
  │
  └─ submit_answer(...) ──► Reads from store, POSTs to verify API
                              └─ Saves result to results/<task>.json
```

**Key principle**: Tools pass large data between each other via `core.store` (key-value). Agent context only gets short summaries. Store keys are defined in skill `.md` files.

### Agent Execution (ReAct Loop)

1. `run_task("task_name", "instruction")` loads universal_solver agent
2. Instruction is prefixed with `[Task: task_name] First activate skill "task_name"`
3. Agent calls `use_skill("task_name")` — skill is lazy-loaded from `skills/` directory
4. Skill instructions + tool schemas loaded into context (tools found globally across all `tools/*_tools.py`)
5. Agent calls tools with parameters from skill instructions
6. Tool results (summaries) go back to agent context
7. Loop continues until agent returns text response
8. Max iterations: 30 default (configurable per task)

## Creating a New Task

### 1. Task entry point (minimal stub)

```
tasks/<name>/task.py
tasks/<name>/__init__.py  (empty)
```

```python
from core.agent import run_task

def run():
    run_task("<task_name>", "<instruction describing what to do>")
```

No per-task agent needed — `run_task` uses the universal agent.

### 2. Skill definition — `skills/<task_name>.md`

Skill name MUST match task name (convention for lazy loading).

```markdown
---
name: <task_name>
description: Short description (shown before activation)
tools: tool_func1, tool_func2
---

Use `tool_func1` with param1="value1", output_key="data".
Then use `tool_func2` with input_key="data", output_key="result".

After completion, use verify skill: submit_answer(task_name="<task_name>", input_key="result")
```

### 3. Tool implementation — add to existing category file

Add functions to the appropriate `tools/<category>_tools.py` file:

| Category | File | What belongs here |
|----------|------|-------------------|
| `data` | `data_tools.py` | CSV download, filtering, tagging |
| `shell` | `shell_tools.py` | Remote command execution |
| `geo` | `geo_tools.py` | Geocoding, distance, location |
| `transport` | `transport_tools.py` | Railway, drone, packages |
| `web` | `web_tools.py` | Web scraping, API servers |
| `document` | `document_tools.py` | Document fetch, file creation |
| ... | ... | See CLAUDE.md for full list |

```python
def tool_func1(param1: str, output_key: str) -> str:
    """One-line description for OpenAI function schema."""
    result = do_work(param1)
    store_put(output_key, json.dumps(result, ensure_ascii=False))
    return f"Processed {len(result)} items"
```

**Rules:**
- Type hints required (str, int, float, bool only)
- Always return `str` — goes into agent context
- Return SHORT summaries, store large data in `core.store`
- Docstring becomes the tool description in OpenAI schema
- Tool files organized by category — loader searches ALL `tools/*_tools.py` globally

### 4. Reuse existing components

| Component | Type | Purpose |
|-----------|------|---------|
| `universal_solver` | agent | Universal task solver (handles all tasks) |
| `verify` | skill | `submit_answer(task_name, input_key)` — submits to API, saves result |
| `verify` | skill | `load_result(task_name, output_key)` — loads previous task result into store |
| `data` | skill | `download_and_filter(dataset, filters_json, output_key)` — CSV download |
| `compactor` | agent | Context compaction (gpt-4o-mini) |
| `summarizer` | agent | Data summarization (gpt-4o-mini) |

## Web GUI

```bash
python gui/app.py    # starts on http://localhost:5099
```

### Dashboard

Control panel at the top showing counts: Agents, Skills, Tools, Tasks, Solved (with ring chart).

Four sections below:
- **Agents** — click name to edit, hover for delete
- **Skills** — click name to edit, hover for delete
- **Tasks** — click name to edit, with **log**, **result**, and **run** buttons
- **Tools** — lists tool files with their exported functions

### Task Runner

Click **run** on any task to open the runner view:
- **Bubble view** (default) — live structured logs as chat bubbles:
  - `SYS` — system prompt (agent config)
  - `USER` — user message
  - `THINK` — agent reasoning
  - `→ TOOL` — tool call with arguments
  - `← RESULT` — tool return value
  - `RESPONSE` — final agent response
  - `ERROR` — errors
- **Raw view** — toggle "raw" for plain text terminal output
- **Verbose** — toggle for DEBUG level logging
- **Stop** — click running button to kill the process

### Results

After a task submits via `submit_answer`, the result is saved to `results/<task>.json` containing:
- `answer` — what was sent
- `response` — API response (code + message)
- `timestamp`

Results are visible as **result** links on tasks. The result page has **copy answer** and **copy prompt** buttons for reuse.

### Editor

Click any agent, skill, tool, or task name to edit in CodeMirror with:
- Syntax highlighting (Python / Markdown)
- Ctrl+S / Cmd+S to save
- **run** button when editing a task file

## HTTP Retry

All requests to `hub.ag3nts.org` use `core.http` with automatic retry on 429 (rate limit):
- Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s, 64s, 128s, 256s, 512s
- Max 10 retries

## Logging

Two modes controlled by `-v` flag:

| Level | What's logged |
|-------|---------------|
| **INFO** (default) | Iterations, message content, tool calls + results, reasoning |
| **DEBUG** (`-v`) | Full context JSON, token usage, all internal details |

Structured event logs are saved to `log/<task>.jsonl` for the bubble viewer.
Text logs are saved to `log/<task>.log`.

## Environment Variables

```
API_KEY=         # hub.ag3nts.org API key
OPENAI_API_KEY=  # OpenAI API key
```
