"""Anthropic Messages API streaming client."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from providers.messages import split_messages


def _api_key(cfg) -> str:
    env_name = cfg.provider.api_key_env or "ANTHROPIC_API_KEY"
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise RuntimeError(f"Missing API key: set {env_name} environment variable")
    return key


def stream_chat(model: str, messages: list[dict], cfg) -> str:
    provider = cfg.provider
    system_prompt, conversation = split_messages(messages)
    if not conversation:
        raise ValueError("Anthropic provider requires at least one user message")

    body: dict = {
        "model": model,
        "max_tokens": provider.max_output_tokens,
        "messages": conversation,
        "stream": provider.stream,
    }
    if system_prompt:
        body["system"] = system_prompt

    headers = {
        "Content-Type": "application/json",
        "x-api-key": _api_key(cfg),
        "anthropic-version": provider.api_version or "2023-06-01",
    }
    req = urllib.request.Request(
        f"{provider.base_url}{provider.endpoint}",
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )

    chunks: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=provider.timeout_seconds) as resp:
            for raw_line in resp:
                line = raw_line.decode().strip()
                if not line or not line.startswith("data:"):
                    continue
                payload = line[len("data:") :].strip()
                if not payload or payload == "[DONE]":
                    continue
                event = json.loads(payload)
                if event.get("type") != "content_block_delta":
                    continue
                text = event.get("delta", {}).get("text", "")
                if text:
                    print(text, end="", flush=True)
                    chunks.append(text)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Anthropic request failed ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Anthropic request failed: {exc}") from exc

    print()
    return "".join(chunks)
