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
from core.log import get_logger
from core.skill import Skill, load_skills, _parse_frontmatter

log = get_logger("agent")


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
        """Call another agent by name. Returns its text response."""
        agent = self._agents.get(agent_name)
        if agent is None:
            log.error("Agent '%s' not found. Available: %s", agent_name, self.names())
            return f"Error: agent '{agent_name}' not found. Available: {self.names()}"
        msg_preview = message[:80] + "..." if len(message) > 80 else message
        log.info("Delegating to '%s': %s", agent_name, msg_preview)
        result = agent.run(message)
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
            parts.append("\n\n## Available skills (use the use_skill tool to load full instructions)\n")
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
                        "Load full skill instructions. "
                        "Returns the complete skill body with instructions."
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
            log.info("[%s] Loaded skill: %s", self.name, skill_name)
            return f"# {skill.name}\n\n{skill.body}"

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

        self.context.add_system(self._build_system(), pinned=True, tag="system")
        self.context.add_user(user_message, tag="history")

        client = OpenAI(api_key=OPENAI_API_KEY)
        tools_param = self._openai_tools()

        for iteration in range(self.max_iterations):
            messages = self.context.to_messages()
            log.debug("[%s] Iteration %d, context entries: %d",
                      self.name, iteration + 1, len(self.context))
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
                self.context.add_raw(choice.message.model_dump(), tag="history")

                for tool_call in choice.message.tool_calls:
                    fn_name = tool_call.function.name
                    fn_args = json.loads(tool_call.function.arguments)
                    log.info("[%s] Tool call: %s(%s)", self.name, fn_name,
                             json.dumps(fn_args, ensure_ascii=False)[:200])

                    result = self._execute_tool_call(fn_name, fn_args)

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
            log.debug("[%s] Response: %s", self.name, content[:300])

            if output_type is not None:
                return output_type.model_validate_json(content)
            return content

        log.error("[%s] Exceeded %d iterations", self.name, self.max_iterations)
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
# Loading from markdown (Claude Code frontmatter format)
# ---------------------------------------------------------------------------

def load_agent_from_markdown(
    path: Path,
    skills_dir: Path | None = None,
) -> Agent:
    text = path.read_text()
    meta, body = _parse_frontmatter(text)

    name = meta.get("name", path.stem)
    description = meta.get("description", "")
    model = meta.get("model", "gpt-4o")

    skill_names = [s.strip() for s in meta.get("skills", "").split(",") if s.strip()]

    all_skills = load_skills(skills_dir) if skills_dir else {}
    agent_skills = {s: all_skills[s] for s in skill_names if s in all_skills}

    log.debug("Loaded agent '%s' (model=%s, skills=%s) from %s",
              name, model, skill_names or "none", path)

    return Agent(
        name=name,
        description=description,
        system_prompt=body.strip(),
        model=model,
        skills=agent_skills,
    )


COMMON_AGENTS_DIR = Path(__file__).parent.parent / "agents"


def load_common_agents() -> dict[str, Agent]:
    """Load agents from the top-level agents/ directory (shared across tasks)."""
    if not COMMON_AGENTS_DIR.exists():
        return {}
    return {
        p.stem: load_agent_from_markdown(p)
        for p in sorted(COMMON_AGENTS_DIR.glob("*.md"))
    }


def load_agents(task_dir: Path) -> dict[str, Agent]:
    """Load task-specific + common agents, wire them into a shared registry."""
    agents_dir = task_dir / "agents"
    skills_dir = task_dir / "skills"

    agents = load_common_agents()

    if agents_dir.exists():
        for p in sorted(agents_dir.glob("*.md")):
            agents[p.stem] = load_agent_from_markdown(p, skills_dir)

    # Wire all agents into a shared registry
    registry = AgentRegistry()
    for agent in agents.values():
        registry.register(agent)
    for agent in agents.values():
        agent.registry = registry

    log.info("Loaded %d agent(s): %s", len(agents), list(agents.keys()))
    return agents
