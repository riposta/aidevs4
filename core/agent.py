from __future__ import annotations

import json
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, get_type_hints

from openai import OpenAI
from pydantic import BaseModel

from core.config import OPENAI_API_KEY
from core.context import Context, MessageRole
from core import event_log
from core.log import get_logger
from core.skill import Skill, load_skills, _parse_frontmatter
from core.store import store_clear

log = get_logger("agent")

PROJECT_ROOT = Path(__file__).parent.parent
AGENTS_DIR = PROJECT_ROOT / "agents"


# ---------------------------------------------------------------------------
# Tool registry helpers
# ---------------------------------------------------------------------------

def _python_type_to_json(t: type) -> dict:
    mapping = {str: "string", int: "integer", float: "number", bool: "boolean"}
    return {"type": mapping.get(t, "string")}


def function_to_openai_tool(fn: Callable) -> dict:
    """Convert a Python function into an OpenAI function-calling tool schema."""
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        t = hints.get(name, str)
        properties[name] = {
            **_python_type_to_json(t),
            "description": "",
        }
        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": (fn.__doc__ or "").strip(),
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


# ---------------------------------------------------------------------------
# Agent Registry — enables agents to call each other
# ---------------------------------------------------------------------------

class AgentRegistry:
    """Central registry so agents can discover and call each other."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        self._agents[agent.name] = agent

    def get(self, name: str) -> Agent | None:
        return self._agents.get(name)

    def names(self) -> list[str]:
        return list(self._agents.keys())

    def descriptions(self) -> dict[str, str]:
        return {a.name: a.description for a in self._agents.values()}

    def call(self, agent_name: str, message: str) -> str:
        """Call another agent by name. Returns its text response. Preserves store."""
        agent = self._agents.get(agent_name)
        if agent is None:
            log.error("Agent '%s' not found. Available: %s", agent_name, self.names())
            return f"Error: agent '{agent_name}' not found. Available: {self.names()}"
        msg_preview = message[:80] + "..." if len(message) > 80 else message
        log.info("Delegating to '%s': %s", agent_name, msg_preview)
        result = agent.run(message, clear_store=False)
        log.info("'%s' returned: %s", agent_name, str(result)[:120])
        return str(result)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

@dataclass
class Agent:
    """Lightweight ReAct agent with OpenAI function calling and context management."""

    name: str
    description: str
    system_prompt: str
    model: str = "gpt-5.4"
    skills: dict[str, Skill] = field(default_factory=dict)
    tools: dict[str, Callable] = field(default_factory=dict)
    context: Context = field(default_factory=Context)
    max_iterations: int = 10
    registry: AgentRegistry | None = field(default=None, repr=False)

    # -- tool registration ---------------------------------------------------

    def tool(self, fn: Callable) -> Callable:
        """Decorator to register a tool function."""
        self.tools[fn.__name__] = fn
        log.debug("[%s] Registered tool: %s", self.name, fn.__name__)
        return fn

    def add_tool(self, fn: Callable) -> None:
        self.tools[fn.__name__] = fn
        log.debug("[%s] Registered tool: %s", self.name, fn.__name__)

    # -- context helpers -----------------------------------------------------

    def _build_system(self) -> str:
        parts = [self.system_prompt]
        if self.skills:
            parts.append("\n\n## Available skills (you MUST use_skill before calling any skill's tools)\n")
            for skill in self.skills.values():
                parts.append(f"- **{skill.name}**: {skill.description}")
        if self.registry:
            others = {n: d for n, d in self.registry.descriptions().items() if n != self.name}
            if others:
                parts.append("\n\n## Available agents (use the call_agent tool to delegate a subtask)\n")
                for name, desc in others.items():
                    parts.append(f"- **{name}**: {desc}")
        return "\n".join(parts)

    def _openai_tools(self) -> list[dict]:
        tools = [function_to_openai_tool(fn) for fn in self.tools.values()]

        # use_skill is always available — skills can be lazy-loaded from skills/ directory
        tools.append({
            "type": "function",
            "function": {
                "name": "use_skill",
                "description": (
                    "Activate a skill by name and unlock its tools. "
                    "You MUST call this before using any tools from a skill. "
                    "Skills are loaded from the skills/ directory. "
                    "Returns skill instructions and list of unlocked tools."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_name": {
                            "type": "string",
                            "description": "Name of the skill to activate",
                        },
                    },
                    "required": ["skill_name"],
                },
            },
        })

        if self.registry:
            others = [n for n in self.registry.names() if n != self.name]
            if others:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": "call_agent",
                        "description": (
                            f"Call another agent to perform a subtask. "
                            f"Available agents: {', '.join(others)}"
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "agent_name": {
                                    "type": "string",
                                    "description": "Name of the agent to call",
                                    "enum": others,
                                },
                                "message": {
                                    "type": "string",
                                    "description": "Message/task for the agent",
                                },
                            },
                            "required": ["agent_name", "message"],
                        },
                    },
                })

        return tools if tools else []

    # -- ReAct loop ----------------------------------------------------------

    def _execute_tool_call(self, fn_name: str, fn_args: dict) -> str:
        """Execute a tool call — registered tool, use_skill, or call_agent."""
        if fn_name == "use_skill":
            skill_name = fn_args["skill_name"]
            skill = self.skills.get(skill_name)
            # Lazy-load skill from skills/ directory if not pre-loaded
            if skill is None:
                skill_path = PROJECT_ROOT / "skills" / f"{skill_name}.md"
                if skill_path.exists():
                    skill = Skill.from_markdown(skill_path)
                    self.skills[skill_name] = skill
                    log.info("[%s] Lazy-loaded skill '%s' from %s", self.name, skill_name, skill_path)
                else:
                    log.warning("[%s] Skill '%s' not found", self.name, skill_name)
                    return f"Error: skill '{skill_name}' not found"
            # Register skill tools on the agent (lazy activation)
            activated = []
            for tool_name, tool_fn in skill.tool_fns.items():
                if tool_name not in self.tools:
                    self.tools[tool_name] = tool_fn
                    activated.append(tool_name)
            log.info("[%s] Activated skill '%s', unlocked tools: %s", self.name, skill_name, activated)
            return f"# {skill.name}\n\n{skill.body}\n\nTools now available: {', '.join(activated) or '(already loaded)'}"

        if fn_name == "call_agent" and self.registry:
            return self.registry.call(fn_args["agent_name"], fn_args["message"])

        fn = self.tools.get(fn_name)
        if fn is None:
            log.error("[%s] Unknown tool: %s", self.name, fn_name)
            return f"Error: unknown tool '{fn_name}'"
        try:
            result = fn(**fn_args)
            log.debug("[%s] %s → %s", self.name, fn_name, str(result)[:200])
            return str(result)
        except Exception as e:
            log.error("[%s] %s raised: %s", self.name, fn_name, e)
            return f"Error: {e}"

    def run(
        self,
        user_message: str,
        output_type: type[BaseModel] | None = None,
        clear_store: bool = True,
        **chat_kwargs,
    ) -> str | BaseModel:
        """
        ReAct loop with context management:
          1. Build messages from context
          2. Send to LLM
          3. If tool_calls -> execute (including call_agent), add to context, go to 2
          4. If text -> return (parsed via output_type if given)
        """
        log.info("[%s] Starting run (model=%s, tools=%d, skills=%d)",
                 self.name, self.model, len(self.tools), len(self.skills))

        # Reset context and data store for fresh run
        task_data = [e for e in self.context.entries if e.tag == "task_data" and e.pinned]
        self.context.entries = task_data
        if clear_store:
            store_clear()

        system_prompt = self._build_system()
        self.context.add_system(system_prompt, pinned=True, tag="system")
        self.context.add_user(user_message, tag="history")

        event_log.emit("system", self.name, content=system_prompt)
        event_log.emit("user", self.name, content=user_message)

        client = OpenAI(api_key=OPENAI_API_KEY)
        prev_msg_count = 0

        for iteration in range(self.max_iterations):
            messages = self.context.to_messages()
            tools_param = self._openai_tools()  # Rebuilt each iteration (skills may unlock new tools)
            log.info("[%s] Iteration %d, context entries: %d, tools: %d",
                     self.name, iteration + 1, len(self.context), len(tools_param))
            event_log.emit("iteration", self.name,
                           content=f"Iteration {iteration + 1}, {len(self.context)} entries, {len(tools_param)} tools")
            # Content-only summary for INFO
            for msg in messages[prev_msg_count:]:
                role = msg.get("role", "?")
                content = msg.get("content")
                if content:
                    log.info("[%s] [%s] %s", self.name, role, content[:300])
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        log.info("[%s] [%s] → %s(%s)", self.name, role,
                                 fn.get("name", "?"), fn.get("arguments", "")[:200])
            prev_msg_count = len(messages)
            # Full JSON only on DEBUG
            log.debug("[%s] Full context:\n%s",
                      self.name, json.dumps(messages, indent=2, ensure_ascii=False))
            event_log.emit("debug", self.name, label="context",
                           content=json.dumps(messages, indent=2, ensure_ascii=False))

            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                **chat_kwargs,
            }
            if tools_param:
                kwargs["tools"] = tools_param

            response = client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            usage = response.usage
            if usage:
                log.debug("[%s] Tokens — prompt: %d, completion: %d, total: %d",
                          self.name, usage.prompt_tokens, usage.completion_tokens, usage.total_tokens)
                event_log.emit("debug", self.name, label="tokens",
                               content=f"prompt: {usage.prompt_tokens}, completion: {usage.completion_tokens}, total: {usage.total_tokens}")

            # --- tool calls -> execute and loop ---
            if choice.finish_reason == "tool_calls" or choice.message.tool_calls:
                # Log reasoning if model included text alongside tool calls
                if choice.message.content:
                    log.info("[%s] Reasoning: %s", self.name, choice.message.content[:300])
                    event_log.emit("reasoning", self.name, content=choice.message.content)
                self.context.add_raw(choice.message.model_dump(), tag="history")

                for tool_call in choice.message.tool_calls:
                    fn_name = tool_call.function.name
                    fn_args = json.loads(tool_call.function.arguments)
                    log.info("[%s] Tool call: %s(%s)", self.name, fn_name,
                             json.dumps(fn_args, ensure_ascii=False)[:200])
                    event_log.emit("tool_call", self.name, name=fn_name, args=fn_args)

                    result = self._execute_tool_call(fn_name, fn_args)
                    log.info("[%s] %s → %s", self.name, fn_name, str(result)[:200])
                    event_log.emit("tool_result", self.name, name=fn_name, content=str(result))

                    self.context.add(
                        MessageRole.TOOL,
                        result,
                        tag="tool_result",
                        metadata={"tool_call_id": tool_call.id},
                    )
                continue

            # --- text response -> return ---
            content = choice.message.content or ""
            self.context.add_assistant(content, tag="history")
            log.info("[%s] Finished after %d iteration(s)", self.name, iteration + 1)
            log.info("[%s] Response: %s", self.name, content[:300])
            event_log.emit("response", self.name, content=content)

            if output_type is not None:
                return output_type.model_validate_json(content)
            return content

        log.error("[%s] Exceeded %d iterations", self.name, self.max_iterations)
        event_log.emit("error", self.name, content=f"Exceeded {self.max_iterations} iterations")
        raise RuntimeError(f"Agent '{self.name}' exceeded {self.max_iterations} iterations")

    def run_with_context(
        self,
        ctx: Context,
        user_message: str,
        output_type: type[BaseModel] | None = None,
        **chat_kwargs,
    ) -> str | BaseModel:
        """Run agent using an external context (for sharing between agents)."""
        self.context = ctx
        return self.run(user_message, output_type=output_type, **chat_kwargs)


# ---------------------------------------------------------------------------
# Loading from markdown
# ---------------------------------------------------------------------------

def _load_agent_from_markdown(path: Path) -> Agent:
    text = path.read_text()
    meta, body = _parse_frontmatter(text)

    name = meta.get("name", path.stem)
    description = meta.get("description", "")
    model = meta.get("model", "gpt-5.4")

    # Load referenced skills from root skills/ dir
    skill_names = [s.strip() for s in meta.get("skills", "").split(",") if s.strip()]
    agent_skills = load_skills(skill_names) if skill_names else {}

    agent = Agent(
        name=name,
        description=description,
        system_prompt=body.strip(),
        model=model,
        skills=agent_skills,
    )

    # Tools are NOT auto-registered — agent must use_skill first (lazy loading)

    log.debug("Loaded agent '%s' (model=%s, skills=%s) from %s",
              name, model, skill_names or "none", path)

    return agent


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_agent(name: str) -> Agent:
    """Load a single agent by name from the root agents/ directory."""
    path = AGENTS_DIR / f"{name}.md"
    if not path.exists():
        raise ValueError(f"Agent '{name}' not found at {path}")
    return _load_agent_from_markdown(path)


def load_agents(*names: str) -> dict[str, Agent]:
    """
    Load specific agents by name and wire them into a shared registry.
    If no names given, load all agents from agents/ directory.
    """
    if names:
        agents = {}
        for name in names:
            agents[name] = get_agent(name)
    else:
        if not AGENTS_DIR.exists():
            return {}
        agents = {
            p.stem: _load_agent_from_markdown(p)
            for p in sorted(AGENTS_DIR.glob("*.md"))
        }

    # Wire all agents into a shared registry
    registry = AgentRegistry()
    for agent in agents.values():
        registry.register(agent)
    for agent in agents.values():
        agent.registry = registry

    log.info("Loaded %d agent(s): %s", len(agents), list(agents.keys()))
    return agents


# ---------------------------------------------------------------------------
# Lesson ↔ task mapping (auto-generated from lessons/ directory)
# ---------------------------------------------------------------------------

LESSONS_DIR = PROJECT_ROOT / "lessons"
MAPPING_PATH = PROJECT_ROOT / "lesson_mapping.json"

_mapping_cache: dict | None = None


def _build_lesson_mapping() -> dict:
    """Scan lessons/ directory, extract task names from content, save mapping.json."""
    import re as _re
    mapping = {}  # prefix → {task_name, file, title}
    if not LESSONS_DIR.exists():
        return mapping
    for p in sorted(LESSONS_DIR.glob("*.md")):
        prefix = p.stem[:6]
        # Extract task name from JSON examples: "task": "railway"
        text = p.read_text()
        m = _re.search(r'"task"\s*:\s*"([a-z][a-z0-9_-]*)"', text)
        task_name = m.group(1) if m else ""
        # Extract title from frontmatter or filename
        fm_match = _re.search(r'^title:\s*(.+)$', text[:1000], _re.MULTILINE)
        if fm_match:
            title = fm_match.group(1).strip().strip('"')
        else:
            parts = p.stem.split("-", 1)
            title = parts[1].rsplit("-", 1)[0].replace("-", " ") if len(parts) > 1 else p.stem
        mapping[prefix] = {"task_name": task_name, "file": p.name, "title": title}
    # Save to mapping.json
    MAPPING_PATH.write_text(json.dumps(mapping, indent=2, ensure_ascii=False))
    log.info("Built lesson mapping: %d lessons -> %s", len(mapping), MAPPING_PATH)
    return mapping


def get_lesson_mapping() -> dict:
    """Get lesson mapping (cached). Auto-builds from lessons/ if mapping.json missing."""
    global _mapping_cache
    if _mapping_cache is not None:
        return _mapping_cache
    if MAPPING_PATH.exists():
        _mapping_cache = json.loads(MAPPING_PATH.read_text())
    else:
        _mapping_cache = _build_lesson_mapping()
    return _mapping_cache


def _find_lesson(identifier: str) -> tuple[Path | None, str]:
    """Find lesson file and task name by prefix or task name. Returns (path, task_name)."""
    mapping = get_lesson_mapping()
    # Direct prefix match (s01e05)
    if identifier in mapping:
        entry = mapping[identifier]
        return LESSONS_DIR / entry["file"], entry["task_name"]
    # Search by task name (railway)
    for prefix, entry in mapping.items():
        if entry["task_name"] == identifier:
            return LESSONS_DIR / entry["file"], entry["task_name"]
    return None, ""


def run_task(task_name: str, instruction: str, max_iterations: int = 30) -> str:
    """Load universal_solver, run it with task-specific instruction."""
    agent = get_agent("universal_solver")
    agent.max_iterations = max_iterations
    # Prefix instruction with skill activation hint
    full_instruction = f'[Task: {task_name}] First activate skill "{task_name}" using use_skill. Then: {instruction}'
    return agent.run(full_instruction)


def run_task_adaptive(task_name: str, lesson: str = "", max_attempts: int = 3, max_iterations: int = 30) -> str:
    """Run task with adaptive agent: reads lesson file, uses memory, reflects on failures.

    Args:
        task_name: Task identifier (e.g. 'railway')
        lesson: Path to lesson .md file. If empty, searches lessons/ directory.
        max_attempts: Number of retry attempts with reflection
        max_iterations: Max ReAct iterations per attempt
    """
    from core.memory import (
        load_reflections, format_reflections,
        save_reflection, generate_reflection,
    )
    import time

    # Find lesson file and resolve task_name
    if lesson:
        lesson_path = PROJECT_ROOT / lesson
    else:
        lesson_path, resolved_name = _find_lesson(task_name)
        if resolved_name:
            task_name = resolved_name
    if not lesson_path or not lesson_path.exists():
        raise FileNotFoundError(f"Lesson not found for '{task_name}'. Check lessons/ directory.")
    full_text = lesson_path.read_text()
    # Extract task section starting from "## Zadanie"
    import re as _re
    task_match = _re.search(r'^## Zadanie.*$', full_text, _re.MULTILINE)
    if task_match:
        task_description = full_text[task_match.start():]
        log.info("[adaptive] Extracted task section from %s (%d chars, starting at line %d)",
                 lesson_path.name, len(task_description),
                 full_text[:task_match.start()].count('\n') + 1)
    else:
        task_description = full_text
        log.warning("[adaptive] No '## Zadanie' section found in %s, using full lesson (%d chars)",
                    lesson_path.name, len(task_description))

    # Load memory
    reflections = load_reflections(task_name)

    result_path = PROJECT_ROOT / "results" / f"{task_name}.json"
    start_time = time.time()

    for attempt in range(1, max_attempts + 1):
        log.info("[adaptive] %s attempt %d/%d", task_name, attempt, max_attempts)

        # Build agent with pre-registered tools (no skill activation needed)
        agent = get_agent("adaptive_solver")
        agent.max_iterations = max_iterations

        from tools.base_tools import (call_task_api, fetch_url, put_store, get_store,
                                       http_post, download_file, store_list, web_session)
        from tools.sandbox_tools import run_python
        from tools.ai_tools import ask_llm, text_to_speech, speech_to_text
        from tools.verify_tools import submit_answer, load_result
        for fn in [call_task_api, fetch_url, http_post, download_file,
                   put_store, get_store, store_list, web_session,
                   run_python, ask_llm, text_to_speech, speech_to_text,
                   submit_answer, load_result]:
            agent.add_tool(fn)
        agent.skills.clear()

        # Inject reflections into system prompt
        refl_text = format_reflections(reflections)
        extra = []
        if refl_text:
            extra.append(refl_text)

        agent.system_prompt += "\n\n" + "\n".join(extra)

        # Task description goes as user prompt (first message)
        instruction = f"[Task: {task_name}]\n\n{task_description}"

        # Run agent
        try:
            result = agent.run(instruction)
        except RuntimeError as e:
            result = str(e)

        # Check for success (new result file created during this run)
        success = result_path.exists() and result_path.stat().st_mtime > start_time

        # Extract trajectory for reflection
        trajectory_parts = []
        for entry in agent.context.entries:
            if entry.tag == "tool_result":
                trajectory_parts.append(str(entry.content)[:500])
            elif entry.tag == "history" and isinstance(entry.content, dict):
                tool_calls = entry.content.get("tool_calls", [])
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    trajectory_parts.append(f"-> {fn.get('name', '?')}({fn.get('arguments', '')[:200]})")
        trajectory = "\n".join(trajectory_parts[-30:])

        # Generate and save reflection
        try:
            reflection = generate_reflection(
                task_name, task_description, trajectory, success, attempt
            )
            save_reflection(reflection)
            reflections.append(reflection)
        except Exception as e:
            log.error("[adaptive] Failed to generate reflection: %s", e)

        if success:
            log.info("[adaptive] %s SOLVED on attempt %d", task_name, attempt)
            return result

        log.warning("[adaptive] %s attempt %d failed", task_name, attempt)

    log.error("[adaptive] %s failed after %d attempts", task_name, max_attempts)
    raise RuntimeError(f"Task '{task_name}' failed after {max_attempts} attempts")
