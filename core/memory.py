"""Memory system: reflections, learned skills, tool catalog."""
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openai import OpenAI

from core.config import OPENAI_API_KEY
from core.log import get_logger

log = get_logger("memory")

PROJECT_ROOT = Path(__file__).parent.parent
MEMORY_DIR = PROJECT_ROOT / "memory"
LEARNED_SKILLS_DIR = MEMORY_DIR / "skills"
REFLECTIONS_DIR = MEMORY_DIR / "reflections"

LEARNED_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
REFLECTIONS_DIR.mkdir(parents=True, exist_ok=True)


def build_tool_catalog() -> str:
    """Build a compact catalog of generic base tools for the system prompt."""
    return """## Available Tools

### Base
- `call_task_api(task, answer)` — POST to hub.ag3nts.org/verify. answer must be a JSON string (object or array). Returns response JSON. Auto-detects flags.
- `fetch_url(url)` — GET any URL. Returns text content or base64:content_type:data for binary.
- `run_python(code)` — Execute Python code, returns stdout. Imports: json, csv, re, math, datetime, base64, zipfile, hashlib, heapq, collections, itertools, functools, statistics. Use _store_put(key, json_str) / _store_get(key) for data. Use _store_put_json(key, obj) for convenience.
- `put_store(key, value)` — Store string data under key for later retrieval.
- `get_store(key)` — Retrieve stored data by key.

### AI
- `ask_llm(prompt, image_url="")` — Ask GPT-4o-mini. Optional image_url for vision analysis.
- `text_to_speech(text)` — Convert text to base64 MP3 audio.
- `speech_to_text(audio_base64)` — Transcribe base64 audio to text.

### Infrastructure
- `start_server(routes_json)` — Start Flask server with dynamic routes + cloudflare tunnel. Returns public URL.

### Verify (activate with use_skill("verify") first)
- `submit_answer(task_name, input_key)` — Submit data from store to verify API.
- `load_result(task_name, output_key)` — Load previous task result into store."""


@dataclass
class Reflection:
    task_name: str
    attempt: int
    success: bool
    tools_used: list
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


def load_reflections(task_name: str) -> list:
    """Load all reflections for a task."""
    path = REFLECTIONS_DIR / f"{task_name}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [Reflection(**d) for d in data]


def format_reflections(reflections: list) -> str:
    """Format reflections as text for the system prompt."""
    if not reflections:
        return ""
    parts = ["## Previous Attempts\n"]
    for r in reflections[-3:]:
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
{{"tools_used": ["tool1", "tool2"], "summary": "what was tried in 1-2 sentences", "error": "error message if failed, empty string if success", "lesson": "what to do differently next time, or what worked well"}}"""

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
description: one-line description of what this task does
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
