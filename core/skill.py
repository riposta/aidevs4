from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


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


@dataclass
class Skill:
    name: str
    description: str
    body: str
    tools: list[str] = field(default_factory=list)

    @classmethod
    def from_markdown(cls, path: Path) -> "Skill":
        text = path.read_text()
        meta, body = _parse_frontmatter(text)

        name = meta.get("name", path.stem)
        description = meta.get("description", "")
        tools = [t.strip() for t in meta.get("tools", "").split(",") if t.strip()]

        return cls(
            name=name,
            description=description,
            body=body.strip(),
            tools=tools,
        )


def load_skills(skills_dir: Path) -> dict[str, Skill]:
    if not skills_dir.exists():
        return {}
    return {
        p.stem: Skill.from_markdown(p)
        for p in sorted(skills_dir.glob("*.md"))
    }
