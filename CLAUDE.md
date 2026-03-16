# AIDevs4 Framework

## Architecture

```
aidevs4/
├── core/           # Framework (don't modify unless asked)
├── agents/         # Agent definitions (.md with YAML frontmatter)
├── skills/         # Skill definitions (.md with YAML frontmatter)
├── tools/          # Tool implementations (Python)
├── tasks/          # Task entry points
│   └── <name>/
│       ├── task.py       # def run() — loads agent and starts it
│       └── __init__.py
└── run.py          # CLI: python run.py <task_name> [-v]
```

## Responsibility Layers

| Layer | Contains | Knows about |
|-------|----------|-------------|
| **Agent** (.md) | Goal, skill names, high-level process | Only skill names and purpose |
| **Skill** (.md) | Tool usage instructions, task-specific parameters | Tool names, parameter values |
| **Tool** (.py) | Generic reusable logic | Store keys, APIs, data processing |
| **Task** (.py) | Agent wiring | Only which agent to load |

Agent NEVER mentions tool names directly — only refers to skills.
Skill contains concrete parameters (URLs, filter values, tag names).
Tool is generic and reusable across tasks.

## Adding a New Task — Step by Step

### 1. Create task entry point

```
tasks/<task_name>/task.py
tasks/<task_name>/__init__.py  (empty file)
```

`task.py` is minimal — only loads agent and runs it:

```python
from core.agent import get_agent

def run():
    solver = get_agent("<agent_name>")
    solver.run("<high-level instruction>")
```

If multiple agents need to collaborate, use `load_agents()`:

```python
from core.agent import load_agents

def run():
    agents = load_agents("agent1", "agent2")
    agents["agent1"].run("Do the task")
```

### 2. Create agent definition

File: `agents/<agent_name>.md`

```markdown
---
name: <display_name>
description: <one-line description>
model: gpt-4o
skills: skill1, skill2, skill3
---

You are a task solver agent. <describe the goal>

Activate each skill with `use_skill` before using its tools.

## Process

1. Use "skill1" skill to <purpose>
2. Use "skill2" skill to <purpose>
3. Use "skill3" skill to submit the answer
```

Rules:
- Process refers to SKILLS by name, never to specific tool functions
- `use_skill` activation requirement is in the system prompt — agent knows to call it
- Keep process high-level and semantic
- Model defaults to `gpt-5-nano` if omitted

### 3. Create skills (or reuse existing)

File: `skills/<skill_name>.md`

```markdown
---
name: <skill_name>
description: <one-line description shown to agent before activation>
tools: tool_func1, tool_func2
---

<Instructions for the agent — what tools to call and with what parameters>

Use `tool_func1` with param1="value1", param2="value2".
Then use `tool_func2` with tag="specific_tag".
```

Rules:
- Skill body contains task-specific parameters (filter values, tag names, URLs, etc.)
- `tools:` in frontmatter lists function names from the companion `_tools.py` file
- Description should be short — it's shown in system prompt before activation
- Body is shown only when agent calls `use_skill`

### 4. Create tool implementations

File: `tools/<skill_name>_tools.py` — filename must match skill name!

```python
import json
from core.log import get_logger
from core.store import store_put, store_get

log = get_logger("tools.<skill_name>")

def tool_func1(param1: str, param2: str) -> str:
    """One-line description for OpenAI function schema."""
    # Do work...
    result = process(param1, param2)

    # Store large data for next tools
    store_put("result_key", json.dumps(result, ensure_ascii=False))

    # Return short summary for agent context
    return f"Processed {len(result)} items: {summary}"

def tool_func2(tag: str) -> str:
    """Filter results by tag."""
    data = store_get("result_key")
    if data is None:
        return "Error: no data found. Run tool_func1 first."
    # Process...
    store_put("filtered", json.dumps(filtered, ensure_ascii=False))
    return f"Filtered to {len(filtered)} items"
```

Rules:
- Type hints required on all params (str, int, float, bool only)
- Always return `str` — this goes into agent context
- Return SHORT SUMMARIES, not raw data
- Use `store_put()`/`store_get()` for large data between tools
- Store is cleared at each `agent.run()` start
- Docstring becomes the tool description in OpenAI schema
- Logger name: `tools.<skill_name>`

### 5. Reusable skill: verify

The `verify` skill with `submit_answer(task_name)` is already available.
It reads from store key `"filtered"` and submits to verification API.
Just add `verify` to agent's skills list.

### 6. Test

```bash
python run.py <task_name>       # Normal run
python run.py <task_name> -v    # Verbose (DEBUG) logging
```

## Store Convention

Tools pass large data between each other via `core.store`:
- `store_put(key, json_string)` — save data
- `store_get(key)` — read data
- Agent never sees store contents — only short summaries

Common keys: `candidates`, `tagged`, `filtered` (used by verify skill).

## Existing Reusable Components

| Component | Type | Purpose |
|-----------|------|---------|
| `verify` | skill | Submit answer via `submit_answer(task_name)` — reads `"filtered"` from store |
| `compactor` | agent | Context compaction (gpt-4o-mini) |
| `summarizer` | agent | Data summarization (gpt-4o-mini) |

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

- Agent: `agents/<name>.md` (lowercase, underscores)
- Skill: `skills/<name>.md`
- Tools: `tools/<name>_tools.py` (must match skill stem!)
- Task: `tasks/<name>/task.py`
