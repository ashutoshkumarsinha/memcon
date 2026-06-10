"""Shared message helpers for provider clients."""

from __future__ import annotations


def split_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    system_parts: list[str] = []
    conversation: list[dict] = []
    for message in messages:
        role = message.get("role", "")
        content = message.get("content", "")
        if role == "system":
            system_parts.append(str(content))
        else:
            conversation.append({"role": role, "content": content})
    return "\n\n".join(system_parts), conversation
