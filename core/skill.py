from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from core.log import get_logger

log = get_logger("skill")

PROJECT_ROOT = Path(__file__).parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills"
TOOLS_DIR = PROJECT_ROOT / "tools"


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse YAML frontmatter (--- delimited) and return (metadata, body)."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not m:
        return {}, text

    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"(\w[\w-]*):\s*(.*)", line)
        if kv:
            meta[kv.group(1)] = kv.group(2).strip()

    return meta, m.group(2)


def _load_tools_from_py(py_path: Path, tool_names: list[str]) -> dict[str, Callable]:
    """Import a Python file and extract named functions as tools."""
    if not py_path.exists():
        return {}

    spec = importlib.util.spec_from_file_location(py_path.stem, py_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    tools: dict[str, Callable] = {}
    for name in tool_names:
        fn = getattr(module, name, None)
        if fn is not None and callable(fn):
            tools[name] = fn
            log.debug("Loaded tool '%s' from %s", name, py_path)
        else:
            log.warning("Tool '%s' not found in %s", name, py_path)

    return tools


_tool_index: dict[str, Callable] | None = None


def _build_tool_index() -> dict[str, Callable]:
    """Build a global index of all tool functions from tools/*_tools.py files."""
    global _tool_index
    if _tool_index is not None:
        return _tool_index

    _tool_index = {}
    if not TOOLS_DIR.exists():
        return _tool_index

    for py_path in sorted(TOOLS_DIR.glob("*_tools.py")):
        spec = importlib.util.spec_from_file_location(py_path.stem, py_path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            log.warning("Failed to load %s: %s", py_path, e)
            continue
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if callable(obj) and not attr_name.startswith("_") and attr_name not in _tool_index:
                _tool_index[attr_name] = obj

    log.debug("Tool index built: %d functions from tools/", len(_tool_index))
    return _tool_index


def _find_tools(tool_names: list[str]) -> dict[str, Callable]:
    """Find tool functions by name from the global tool index."""
    index = _build_tool_index()
    tools: dict[str, Callable] = {}

    for name in tool_names:
        fn = index.get(name)
        if fn is not None:
            tools[name] = fn
            log.debug("Loaded tool '%s'", name)
        else:
            log.warning("Tool '%s' not found in any tools/*_tools.py file", name)

    return tools


@dataclass
class Skill:
    name: str
    description: str
    body: str
    tool_names: list[str] = field(default_factory=list)
    tool_fns: dict[str, Callable] = field(default_factory=dict)

    @classmethod
    def from_markdown(cls, path: Path) -> "Skill":
        text = path.read_text()
        meta, body = _parse_frontmatter(text)

        name = meta.get("name", path.stem)
        description = meta.get("description", "")
        tool_names = [t.strip() for t in meta.get("tools", "").split(",") if t.strip()]

        # Load tools by searching ALL tools/*_tools.py files
        tool_fns = _find_tools(tool_names) if tool_names else {}

        log.debug("Loaded skill '%s' (tools=%s) from %s", name, tool_names or "none", path)

        return cls(
            name=name,
            description=description,
            body=body.strip(),
            tool_names=tool_names,
            tool_fns=tool_fns,
        )


def load_skills(skill_names: list[str] | None = None) -> dict[str, Skill]:
    """Load skills from the root skills/ directory. If skill_names given, load only those."""
    if not SKILLS_DIR.exists():
        return {}

    if skill_names is not None:
        result = {}
        for name in skill_names:
            path = SKILLS_DIR / f"{name}.md"
            if path.exists():
                result[name] = Skill.from_markdown(path)
            else:
                log.warning("Skill '%s' not found at %s", name, path)
        return result

    return {
        p.stem: Skill.from_markdown(p)
        for p in sorted(SKILLS_DIR.glob("*.md"))
    }
