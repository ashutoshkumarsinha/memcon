"""OpenAI Chat Completions API streaming client."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from providers.messages import split_messages


def _api_key(cfg) -> str:
    env_name = cfg.provider.api_key_env or "OPENAI_API_KEY"
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise RuntimeError(f"Missing API key: set {env_name} environment variable")
    return key


def stream_chat(model: str, messages: list[dict], cfg) -> str:
    provider = cfg.provider
    system_prompt, conversation = split_messages(messages)
    payload_messages: list[dict] = []
    if system_prompt:
        payload_messages.append({"role": "system", "content": system_prompt})
    payload_messages.extend(conversation)

    body = {
        "model": model,
        "messages": payload_messages,
        "stream": provider.stream,
        "max_tokens": provider.max_output_tokens,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_api_key(cfg)}",
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
                content = (
                    event.get("choices", [{}])[0]
                    .get("delta", {})
                    .get("content", "")
                )
                if content:
                    print(content, end="", flush=True)
                    chunks.append(content)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"OpenAI request failed ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI request failed: {exc}") from exc

    print()
    return "".join(chunks)
