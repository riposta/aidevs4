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
    model: str = "gpt-4o"
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

        if self.skills:
            tools.append({
                "type": "function",
                "function": {
                    "name": "use_skill",
                    "description": (
                        "Activate a skill and unlock its tools. "
                        "You MUST call this before using any tools from a skill. "
                        "Returns skill instructions and list of unlocked tools."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {
                                "type": "string",
                                "description": "Name of the skill to use",
                                "enum": list(self.skills.keys()),
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
            if skill is None:
                log.warning("[%s] Skill '%s' not found", self.name, skill_name)
                return f"Error: skill '{skill_name}' not found. Available: {list(self.skills.keys())}"
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
    model = meta.get("model", "gpt-4o")

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
