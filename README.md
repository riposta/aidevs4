# AIDevs4 Console

Self-improving agent framework for solving AI Devs (season 4) tasks. The agent reads lesson markdown files, discovers APIs on its own, solves tasks using generic tools, and learns from failures via reflection.

## Quick Start

```bash
# 1. Setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — set API_KEY and OPENAI_API_KEY

# 3. Add lessons
# Place lesson .md files from the AI Devs course into lessons/ directory
# The framework auto-detects task names from lesson content

# 4. Run a task
python run.py railway           # by task name
python run.py s01e05            # by lesson prefix
python run.py railway -v        # verbose mode

# 5. Run GUI
python gui/app.py               # http://localhost:5099
```

## How It Works

### Self-Improving Agent

The agent receives **no pre-written instructions** for solving tasks. Instead:

1. **Reads the lesson** — the `## Zadanie` section is extracted from the lesson markdown and passed as the user prompt
2. **Discovers the API** — calls `call_task_api(task, '{"action": "help"}')` to get API docs
3. **Explores and solves** — uses generic tools (HTTP, Python sandbox, LLM) to interact with the API
4. **Reflects on failure** — if an attempt fails, gpt-5.4 generates a structured reflection (what went wrong, what to try next)
5. **Learns from reflections** — next attempt gets previous reflections in system prompt, enabling the agent to avoid past mistakes

### Adding Lessons

Place lesson `.md` files from the AI Devs course into the `lessons/` directory:

```
lessons/
  s01e01-programowanie-interakcji-z-modelem-jezykowym-1773230257.md
  s01e02-techniki-laczenia-modelu-z-narzedziami-1773132164.md
  ...
```

**Requirements for lesson files:**
- Filename must start with lesson prefix (e.g. `s01e05-...`)
- Must contain a `## Zadanie` section (the practical task description)
- Must contain a JSON example with `"task": "task_name"` — this is how the framework detects the task name

On first run, the framework scans all lessons and generates `lesson_mapping.json`:
```json
{
  "s01e05": {
    "task_name": "railway",
    "file": "s01e05-zarzadzanie-jawnymi-...",
    "title": "Zarządzanie jawnymi oraz niejawnymi limitami modeli"
  }
}
```

Delete `lesson_mapping.json` to force regeneration after adding new lessons.

### Architecture

```
aidevs4/
├── core/               # Framework internals
│   ├── agent.py        # ReAct loop + run_task_adaptive() with reflection
│   ├── memory.py       # Reflections storage + generation (gpt-5.4)
│   ├── sandbox.py      # Python execution sandbox for run_python tool
│   ├── context.py      # Message context with pinning & compaction
│   ├── skill.py        # Skill loader (global tool index)
│   ├── store.py        # Key-value store for data between tools
│   ├── proxy.py        # Custom proxy task (Flask server)
│   ├── config.py       # .env config (API_KEY, OPENAI_API_KEY)
│   ├── verify.py       # POST to hub.ag3nts.org/verify
│   ├── http.py         # HTTP client with 429 retry
│   ├── event_log.py    # Structured JSONL event logging
│   └── log.py          # Color logger
├── agents/
│   └── adaptive_solver.md  # Self-improving agent (gpt-5.4)
├── tools/              # Generic tools (organized by category)
│   ├── base_tools.py   # call_task_api, fetch_url, http_post, download_file, store ops
│   ├── sandbox_tools.py # run_python (Python execution)
│   ├── ai_tools.py     # ask_llm (vision), text_to_speech, speech_to_text
│   ├── infra_tools.py  # start_server (Flask + cloudflare tunnel)
│   └── verify_tools.py # submit_answer, load_result
├── lessons/            # Lesson .md files (user-provided, gitignored)
├── lesson_mapping.json # Auto-generated: prefix → task_name
├── memory/
│   └── reflections/    # Per-task reflection logs (JSON)
├── skills/             # Legacy pre-written skills (fallback)
├── results/            # Task results (JSON, auto-saved)
├── gui/                # Web GUI (Flask)
├── log/                # Execution logs (.log + .jsonl)
└── run.py              # CLI entry point
```

### Generic Tools

The agent has these tools pre-registered — no activation needed:

| Tool | Purpose |
|------|---------|
| `call_task_api(task, answer)` | POST to /verify — main task API, auto-detects flags |
| `http_post(url, body)` | POST to any URL (e.g. /api/zmail, /api/shell) |
| `fetch_url(url)` | GET any URL, text returned directly, binary saved to store |
| `download_file(url, store_key)` | Download file to store without context bloat |
| `run_python(code)` | Execute Python (json, csv, re, math, datetime, base64, zipfile, hashlib, heapq) |
| `ask_llm(prompt, image_url)` | GPT-5.4 for text/vision analysis |
| `text_to_speech(text)` | OpenAI TTS → base64 MP3 |
| `speech_to_text(audio_base64)` | OpenAI Whisper → text |
| `web_session(actions_json)` | Login + browse with persistent cookies |
| `put_store(key, value)` | Save data to key-value store |
| `get_store(key)` | Retrieve data from store |
| `store_list()` | List all store keys with sizes |
| `submit_answer(task_name, input_key)` | Submit store data to verify API |

API key is auto-injected into URLs and hub.ag3nts.org POST bodies.

### Reflection Loop

```
Attempt 1: Agent reads lesson → tries to solve → fails
    ↓ gpt-5.4 generates reflection: {tools_used, summary, error, lesson}
Attempt 2: Agent reads lesson + reflection from attempt 1 → adjusts approach → succeeds
    ↓ reflection saved to memory/reflections/task_name.json
```

Reflections persist across runs. Max 3 attempts per run (configurable).

### Data Flow

```
Lesson .md
  ↓ extract ## Zadanie section
Agent (gpt-5.4)
  ├─ call_task_api("task", '{"action":"help"}')  → discovers API
  ├─ fetch_url("https://...")                     → downloads data
  ├─ run_python("import csv; ...")                → processes data
  ├─ call_task_api("task", '{"answer": ...}')     → submits answer
  │     └─ "FLAG FOUND: {FLG:...}"               → task solved!
  └─ result saved to results/task_name.json
```

## Web GUI

```bash
python gui/app.py    # starts on http://localhost:5099
```

### Dashboard

- **Lessons** — all 24 lessons listed with task names, flags (blurred, hover to reveal), log/result/run buttons
- **Agents** — agent definitions
- **Skills** — legacy skill files
- **Tools** — tool files with exported functions
- **Solved ring** — progress indicator

### Task Runner

Click **run** on any lesson to open the runner with live streaming:
- **Bubble view** — structured event bubbles (tool calls, results, reasoning)
- **Raw view** — plain text terminal output
- **Verbose** — toggle DEBUG logging
- **Stop** — kill running process

### Lesson Viewer

Click lesson title to view the full markdown content with run button.

## HTTP Retry

All requests to `hub.ag3nts.org` use `core.http` with automatic retry on 429:
- Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s, 64s, 128s, 256s, 512s
- Max 10 retries

## Environment Variables

```
API_KEY=         # hub.ag3nts.org API key
OPENAI_API_KEY=  # OpenAI API key
```
