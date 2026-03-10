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
├── agents/             # Agent definitions (.md)
├── skills/             # Skill definitions (.md)
├── tools/              # Tool implementations (.py)
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
| **Task** | `tasks/<name>/task.py` | Agent wiring | Only which agent to load |
| **Agent** | `agents/<name>.md` | Goal, process steps | Skill names (never tool names) |
| **Skill** | `skills/<name>.md` | Tool usage instructions, parameters | Tool names, store keys |
| **Tool** | `tools/<name>_tools.py` | Reusable logic | APIs, data processing |

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

1. Agent gets system prompt (from `.md` body) + available skills list
2. Agent calls `use_skill("skill_name")` to unlock tools
3. Skill instructions + tool schemas are loaded into context
4. Agent calls tools with parameters from skill instructions
5. Tool results (summaries) go back to agent context
6. Loop continues until agent returns text response
7. Max iterations configurable per task (default: 10)

### Multi-Agent Collaboration

Agents can call each other via `call_agent(agent_name, message)`:

```python
# task.py — wire agents into shared registry
agents = load_agents("people_solver", "findhim_solver")
agents["findhim_solver"].run("Find the suspect...")
# findhim_solver can now call people_solver as a sub-agent
```

Sub-agent runs preserve the shared store (`clear_store=False`).

## Creating a New Task

### 1. Task entry point

```
tasks/<name>/task.py
tasks/<name>/__init__.py  (empty)
```

```python
from core.agent import get_agent

def run():
    solver = get_agent("<agent_name>")
    solver.run("<instruction>")
```

### 2. Agent definition — `agents/<name>.md`

```markdown
---
name: my_agent
description: One-line description
model: gpt-4o
skills: skill1, skill2, verify
---

You are a task solver agent.

Activate each skill with `use_skill` before using its tools.

## Process

1. Use "skill1" skill to <purpose>
2. Use "skill2" skill to <purpose>
3. Use "verify" skill to submit the answer for task "<name>" with input_key="answer"
```

### 3. Skill definition — `skills/<name>.md`

```markdown
---
name: my_skill
description: Short description (shown before activation)
tools: tool_func1, tool_func2
---

Use `tool_func1` with param1="value1", output_key="data".
Then use `tool_func2` with input_key="data", output_key="result".
```

### 4. Tool implementation — `tools/<name>_tools.py`

```python
import json
from core.log import get_logger
from core.store import store_put, store_get

log = get_logger("tools.<name>")

def tool_func1(param1: str, output_key: str) -> str:
    """One-line description for OpenAI function schema."""
    result = do_work(param1)
    store_put(output_key, json.dumps(result, ensure_ascii=False))
    return f"Processed {len(result)} items"  # short summary for agent
```

**Rules:**
- Type hints required (str, int, float, bool only)
- Always return `str` — goes into agent context
- Return SHORT summaries, store large data in `core.store`
- Docstring becomes the tool description in OpenAI schema
- Filename must match skill: skill `data` → `tools/data_tools.py`

### 5. Reuse existing components

| Component | Type | Purpose |
|-----------|------|---------|
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
