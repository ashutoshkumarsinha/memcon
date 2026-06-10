"""Ollama /api/chat streaming client."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


def stream_chat(model: str, messages: list[dict], cfg) -> str:
    provider = cfg.provider
    payload = json.dumps(
        {"model": model, "messages": messages, "stream": provider.stream}
    ).encode()
    req = urllib.request.Request(
        f"{provider.base_url}{provider.endpoint}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    chunks: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=provider.timeout_seconds) as resp:
            for raw_line in resp:
                line = raw_line.decode().strip()
                if not line:
                    continue
                data = json.loads(line)
                content = data.get("message", {}).get("content", "")
                if content:
                    print(content, end="", flush=True)
                    chunks.append(content)
                if data.get("done"):
                    break
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc

    print()
    return "".join(chunks)
