"""LLM provider clients for MemCon."""

from __future__ import annotations

from providers.anthropic import stream_chat as stream_anthropic_chat
from providers.kiro import stream_chat as stream_kiro_chat
from providers.messages import split_messages
from providers.ollama import stream_chat as stream_ollama_chat
from providers.openai import stream_chat as stream_openai_chat

PROVIDERS = {
    "ollama": stream_ollama_chat,
    "anthropic": stream_anthropic_chat,
    "openai": stream_openai_chat,
    "kiro": stream_kiro_chat,
}

__all__ = ["PROVIDERS", "split_messages", "stream_chat"]


def stream_chat(provider_name: str, model: str, messages: list[dict], cfg) -> str:
    handler = PROVIDERS.get(provider_name)
    if handler is None:
        known = ", ".join(sorted(PROVIDERS))
        raise ValueError(f"Unknown provider {provider_name!r}. Choose from: {known}")
    return handler(model, messages, cfg)
