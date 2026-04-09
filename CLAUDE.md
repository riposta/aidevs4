# AIDevs4 Framework

## Architecture

```
aidevs4/
├── core/
│   ├── agent.py        # ReAct loop, run_task_adaptive() with reflection
│   ├── memory.py       # Reflections storage + generation
│   ├── sandbox.py      # Python sandbox for run_python
│   ├── context.py      # Message context with pinning & compaction
│   ├── skill.py        # Skill loader (global tool index from tools/*_tools.py)
│   ├── store.py        # Key-value store for data between tools
│   ├── proxy.py        # Custom proxy task (Flask + tunnel)
│   ├── config.py       # .env config (API_KEY, OPENAI_API_KEY)
│   ├── verify.py       # POST to hub.ag3nts.org/verify
│   ├── http.py         # HTTP client with 429 retry
│   ├── event_log.py    # Structured JSONL event logging
│   └── log.py          # Color logger
├── agents/
│   └── adaptive_solver.md  # Self-improving agent (gpt-5.4)
├── tools/              # Generic tools (by category)
│   ├── base_tools.py   # call_task_api, fetch_url, http_post, download_file, store ops, web_session
│   ├── sandbox_tools.py # run_python
│   ├── ai_tools.py     # ask_llm, text_to_speech, speech_to_text
│   ├── infra_tools.py  # start_server (Flask + cloudflare tunnel)
│   └── verify_tools.py # submit_answer, load_result
├── lessons/            # Lesson .md files (user-provided, gitignored)
├── lesson_mapping.json # Auto-generated from lessons/
├── memory/reflections/ # Per-task reflections (JSON)
├── skills/             # Legacy skills (fallback, not used by adaptive agent)
├── results/            # Task results (auto-saved)
├── gui/                # Web GUI
└── run.py              # CLI: python run.py <task_or_prefix> [-v]
```

## How the Self-Improving Agent Works

### Input: Lesson Files

User places lesson `.md` files from the AI Devs course into `lessons/` directory.
Each lesson contains a `## Zadanie` section with the practical task.

Framework auto-generates `lesson_mapping.json` by scanning lessons for `"task": "xxx"` patterns.

### Execution Flow

```
python run.py railway   (or: python run.py s01e05)
  ↓
1. Find lesson file via lesson_mapping.json
2. Extract ## Zadanie section (regex: ^## Zadanie)
3. Load reflections from memory/reflections/{task}.json
4. Create adaptive_solver agent with pre-registered generic tools
5. Inject reflections into system prompt
6. Pass task description as user prompt: [Task: railway]\n\n## Zadanie\n\n...
7. Agent uses tools to explore API and solve task
8. On success: save reflection, save result
9. On failure: generate reflection (gpt-5.4), retry (max 3 attempts)
```

### Generic Tools (pre-registered, no activation needed)

| Tool | Signature | Purpose |
|------|-----------|---------|
| `call_task_api` | `(task, answer)` | POST to /verify — main task API, auto-detects flags |
| `http_post` | `(url, body)` | POST to any URL — apikey auto-injected for hub URLs |
| `fetch_url` | `(url)` | GET any URL — text returned, binary saved to store |
| `download_file` | `(url, store_key)` | Download to store without context bloat |
| `run_python` | `(code)` | Python sandbox (json, csv, re, math, datetime, base64, zipfile, hashlib, heapq) |
| `ask_llm` | `(prompt, image_url)` | GPT-5.4 text/vision |
| `text_to_speech` | `(text)` | OpenAI TTS → base64 MP3 |
| `speech_to_text` | `(audio_base64)` | Whisper → text |
| `web_session` | `(actions_json)` | HTTP session with cookies (login + browse) |
| `put_store` | `(key, value)` | Save to key-value store |
| `get_store` | `(key)` | Load from store |
| `store_list` | `()` | List store keys + sizes |
| `submit_answer` | `(task_name, input_key)` | Submit from store to verify API |
| `load_result` | `(task_name, output_key)` | Load previous result into store |

### Reflection System

After each attempt (success or failure), `core/memory.py` generates a structured reflection:
```json
{
  "task_name": "railway",
  "attempt": 1,
  "success": true,
  "tools_used": ["call_task_api"],
  "summary": "Called help, discovered API, executed reconfigure→setstatus→save",
  "error": "",
  "lesson": "Use help endpoint first, follow exact sequence from docs"
}
```

Reflections are saved to `memory/reflections/{task}.json` and loaded into system prompt on next run.

### API Key Auto-Injection

- `call_task_api` adds `apikey` to POST body automatically
- `http_post` adds `apikey` to body for hub.ag3nts.org URLs
- `fetch_url` and `download_file` replace URL placeholders (`tutaj-twoj-klucz`, `{API_KEY}`) with actual key
- Agent never sees the API key

## Adding Lessons

1. Get lesson `.md` files from the AI Devs course
2. Place them in `lessons/` directory
3. Filename format: `s01e05-lesson-title-1234567890.md`
4. Each file must contain `## Zadanie` section and `"task": "task_name"` in JSON examples
5. Delete `lesson_mapping.json` to force regeneration (or it auto-generates on first run)

## Store Convention

Tools pass large data via `core.store` (key-value):
- `store_put(key, json_string)` — save data
- `store_get(key)` — read data (returns `None` if missing)
- Agent sees only short summaries from tool returns, not store contents
- `run_python` has store access via `_store_put(key, val)` / `_store_get(key)` / `_store_put_json(key, obj)`

## Event Logging (GUI Bubbles)

Standard events (always visible):
- `system`, `user`, `tool_call`, `tool_result`, `response`, `error`

Verbose events (toggle in GUI):
- `iteration`, `debug` (with label: CONTEXT, TOKENS), `reasoning`

Events stream via `@@EVENT::` prefix on stderr for GUI SSE.

## File Naming

- Agent: `agents/adaptive_solver.md` (single self-improving agent)
- Tools: `tools/<category>_tools.py` (base, sandbox, ai, infra, verify)
- Lessons: `lessons/s01e05-title-timestamp.md` (user-provided)
- Mapping: `lesson_mapping.json` (auto-generated)
- Reflections: `memory/reflections/<task_name>.json` (auto-generated)
- Results: `results/<task_name>.json` (auto-saved on flag)
- Legacy skills: `skills/<name>.md` (not used by adaptive agent)
- Legacy proxy: `core/proxy.py` (special case)
