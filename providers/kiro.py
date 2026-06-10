"""Kiro CLI provider (ACP and headless modes)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from providers.kiro_acp import KiroACPClient
from providers.messages import split_messages


def _format_prompt(system_prompt: str, conversation: list[dict]) -> str:
    parts: list[str] = []
    if system_prompt:
        parts.append(f"# System instructions\n{system_prompt}")
    for message in conversation:
        role = message.get("role", "user").title()
        parts.append(f"## {role}\n{message.get('content', '')}")
    return "\n\n".join(parts)


def _resolve_cli_path(cfg) -> str:
    cli_path = os.environ.get("KIRO_CLI_PATH", cfg.provider.cli_path)
    resolved = shutil.which(cli_path)
    if not resolved:
        raise RuntimeError(
            f"kiro-cli not found ({cli_path!r}). Install from https://kiro.dev "
            "or set KIRO_CLI_PATH."
        )
    return resolved


def _stream_headless(prompt: str, model: str, cfg) -> str:
    cli_path = _resolve_cli_path(cfg)
    cmd = [cli_path, "chat", "--no-interactive"]
    if cfg.provider.auto_approve_tools:
        cmd.append("--trust-all-tools")
    if model and model != cfg.provider.default_model:
        cmd.extend(["--model", model])
    cmd.append(prompt)

    env = os.environ.copy()
    api_key_env = cfg.provider.api_key_env or "KIRO_API_KEY"
    if api_key_env not in env and not env.get("KIRO_API_KEY"):
        raise RuntimeError(
            f"Missing API key for headless mode: set {api_key_env} or run "
            "`kiro-cli auth login` and use mode = \"acp\"."
        )

    try:
        result = subprocess.run(
            cmd,
            cwd=str(Path.cwd()),
            capture_output=True,
            text=True,
            timeout=cfg.provider.timeout_seconds,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"kiro-cli timed out after {cfg.provider.timeout_seconds}s"
        ) from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown error").strip()
        raise RuntimeError(f"kiro-cli failed ({result.returncode}): {detail}")

    output = result.stdout or ""
    if output:
        print(output, end="" if output.endswith("\n") else "\n", flush=True)
    else:
        print()
    return output


def _stream_acp(prompt: str, model: str, cfg) -> str:
    cli_path = _resolve_cli_path(cfg)
    chunks: list[str] = []

    def on_chunk(text: str) -> None:
        print(text, end="", flush=True)
        chunks.append(text)

    try:
        with KiroACPClient(
            cli_path=cli_path,
            cwd=str(Path.cwd()),
            timeout_seconds=cfg.provider.timeout_seconds,
            auto_approve_tools=cfg.provider.auto_approve_tools,
            on_chunk=on_chunk,
        ) as client:
            session_id = client.session_new()
            if model and model != cfg.provider.default_model:
                try:
                    client.session_set_model(session_id, model)
                except RuntimeError:
                    pass
            result = client.session_prompt(session_id, prompt)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"kiro-cli not found at {cli_path!r}. Install from https://kiro.dev"
        ) from exc

    if not result.text and not chunks:
        raise RuntimeError(
            "kiro-cli returned an empty response. Ensure you are authenticated "
            "(`kiro-cli auth login`) or set KIRO_API_KEY for headless mode."
        )

    if not chunks and result.text:
        print(result.text, end="" if result.text.endswith("\n") else "\n", flush=True)

    if not chunks and not result.text.endswith("\n"):
        print()

    return result.text or "".join(chunks)


def stream_chat(model: str, messages: list[dict], cfg) -> str:
    system_prompt, conversation = split_messages(messages)
    if not conversation:
        raise ValueError("Kiro provider requires at least one user message")

    prompt = _format_prompt(system_prompt, conversation)
    mode = (cfg.provider.mode or "acp").lower()

    if mode == "headless":
        return _stream_headless(prompt, model, cfg)
    if mode == "acp":
        return _stream_acp(prompt, model, cfg)
    raise ValueError(f"Unknown kiro mode {mode!r}. Use 'acp' or 'headless'.")
