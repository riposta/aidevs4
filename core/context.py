from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from openai import OpenAI
from core.config import OPENAI_API_KEY
from core.log import get_logger

log = get_logger("context")


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ContextEntry:
    """Single entry in the context window."""

    id: str
    role: MessageRole
    content: str
    pinned: bool = False
    tag: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_message(self) -> dict[str, Any]:
        if "raw_message" in self.metadata:
            return self.metadata["raw_message"]

        msg: dict[str, Any] = {"role": self.role.value, "content": self.content}
        if self.role == MessageRole.TOOL and "tool_call_id" in self.metadata:
            msg["tool_call_id"] = self.metadata["tool_call_id"]
        return msg


@dataclass
class Context:
    """
    Dynamic context manager.

    - pinned entries are never compacted
    - entries can be grouped by tag for selective compaction
    - supports copying entries between contexts
    """

    entries: list[ContextEntry] = field(default_factory=list)

    # -- adding entries ------------------------------------------------------

    def add(
        self,
        role: MessageRole | str,
        content: str,
        *,
        pinned: bool = False,
        tag: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ContextEntry:
        if isinstance(role, str):
            role = MessageRole(role)
        entry = ContextEntry(
            id=uuid.uuid4().hex[:8],
            role=role,
            content=content,
            pinned=pinned,
            tag=tag,
            metadata=metadata or {},
        )
        self.entries.append(entry)
        pin_label = " [pinned]" if pinned else ""
        tag_label = f" #{tag}" if tag else ""
        log.debug("Added %s entry%s%s (%d chars, id=%s)",
                  role.value, pin_label, tag_label, len(content), entry.id)
        return entry

    def add_system(self, content: str, *, pinned: bool = True, tag: str = "system") -> ContextEntry:
        return self.add(MessageRole.SYSTEM, content, pinned=pinned, tag=tag)

    def add_user(self, content: str, **kwargs) -> ContextEntry:
        return self.add(MessageRole.USER, content, **kwargs)

    def add_assistant(self, content: str, **kwargs) -> ContextEntry:
        return self.add(MessageRole.ASSISTANT, content, **kwargs)

    def add_raw(
        self,
        raw_message: dict[str, Any],
        *,
        pinned: bool = False,
        tag: str = "",
    ) -> ContextEntry:
        """Add a raw OpenAI message dict (e.g. assistant with tool_calls)."""
        role = MessageRole(raw_message.get("role", "assistant"))
        content = raw_message.get("content") or ""
        return self.add(
            role, content, pinned=pinned, tag=tag,
            metadata={"raw_message": raw_message},
        )

    # -- pinning / unpinning -------------------------------------------------

    def pin(self, entry_id: str) -> None:
        for e in self.entries:
            if e.id == entry_id:
                e.pinned = True
                log.debug("Pinned entry %s", entry_id)
                return

    def unpin(self, entry_id: str) -> None:
        for e in self.entries:
            if e.id == entry_id:
                e.pinned = False
                log.debug("Unpinned entry %s", entry_id)
                return

    # -- querying ------------------------------------------------------------

    def by_tag(self, tag: str) -> list[ContextEntry]:
        return [e for e in self.entries if e.tag == tag]

    def pinned_entries(self) -> list[ContextEntry]:
        return [e for e in self.entries if e.pinned]

    def unpinned_entries(self) -> list[ContextEntry]:
        return [e for e in self.entries if not e.pinned]

    # -- copying entries from another context --------------------------------

    def copy_from(self, other: "Context", *, tag: str | None = None, pinned_only: bool = False) -> None:
        source = other.entries
        if tag:
            source = [e for e in source if e.tag == tag]
        if pinned_only:
            source = [e for e in source if e.pinned]
        for e in source:
            self.entries.append(ContextEntry(
                id=uuid.uuid4().hex[:8],
                role=e.role,
                content=e.content,
                pinned=e.pinned,
                tag=e.tag,
                metadata=dict(e.metadata),
            ))
        log.debug("Copied %d entries (tag=%s, pinned_only=%s)", len(source), tag, pinned_only)

    # -- removing entries ----------------------------------------------------

    def remove(self, entry_id: str) -> None:
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.id != entry_id]
        if len(self.entries) < before:
            log.debug("Removed entry %s", entry_id)

    def clear_tag(self, tag: str, *, keep_pinned: bool = True) -> None:
        before = len(self.entries)
        self.entries = [
            e for e in self.entries
            if e.tag != tag or (keep_pinned and e.pinned)
        ]
        removed = before - len(self.entries)
        if removed:
            log.debug("Cleared %d entries with tag '%s'", removed, tag)

    # -- compaction ----------------------------------------------------------

    def compact(self, tag: str | None = None, model: str = "gpt-4o-mini") -> None:
        """
        Compact unpinned entries (optionally filtered by tag)
        into a single summary using an LLM.
        """
        if tag:
            targets = [e for e in self.entries if e.tag == tag and not e.pinned]
        else:
            targets = [e for e in self.entries if not e.pinned]

        if len(targets) <= 1:
            log.debug("Compact skipped — only %d unpinned entries", len(targets))
            return

        log.info("Compacting %d entries (tag=%s)", len(targets), tag or "all")

        parts = []
        for e in targets:
            if "raw_message" in e.metadata:
                raw = e.metadata["raw_message"]
                tool_calls = raw.get("tool_calls", [])
                calls_str = ", ".join(
                    f"{tc.get('function', {}).get('name', '?')}(...)" for tc in tool_calls
                )
                parts.append(f"[assistant → tool_calls: {calls_str}]")
            else:
                parts.append(f"[{e.role.value}] {e.content}")

        text = "\n\n".join(parts)

        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a context compaction agent. "
                        "Summarize the provided conversation fragment. "
                        "Preserve ALL key facts, decisions, tool results and conclusions. "
                        "Remove repetitions and small talk. "
                        "Respond with the summary only, no meta-commentary."
                    ),
                },
                {"role": "user", "content": text},
            ],
        )
        summary = response.choices[0].message.content or ""

        target_ids = {e.id for e in targets}
        self.entries = [e for e in self.entries if e.id not in target_ids]

        self.add(
            MessageRole.SYSTEM,
            f"[Compacted context]\n{summary}",
            tag=tag or "compacted",
        )
        log.info("Compacted %d entries → %d chars summary", len(targets), len(summary))

    # -- export to OpenAI messages -------------------------------------------

    def to_messages(self) -> list[dict[str, Any]]:
        return [e.to_message() for e in self.entries]

    def __len__(self) -> int:
        return len(self.entries)
