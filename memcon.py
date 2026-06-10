#!/usr/bin/env python3
"""Local MemCon — ambient memory manager and Ollama execution proxy."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AppConfig:
    version: str
    default_model: str
    config_dir: Path
    global_config_path: Path
    history_path: Path
    project_context_file: str
    ignore_file: str
    ollama_host: str
    ollama_chat_endpoint: str
    ollama_timeout_seconds: int
    ollama_stream: bool
    history_max_entries: int
    history_display_limit: int
    prompt_preview_length: int
    plain_text_divisor: float
    dense_code_divisor: float
    symbol_density_threshold: float
    code_symbols_pattern: str
    scan_max_depth: int
    invariant_ignore_dirs: frozenset[str]
    invariant_ignore_files: frozenset[str]
    allowed_extensions: frozenset[str]
    budget_rules: tuple[tuple[tuple[str, ...], int], ...]
    default_budget_tokens: int
    global_defaults: dict[str, Any]
    code_symbols: re.Pattern[str] = field(repr=False, compare=False)


def _bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def _resolve_config_path() -> Path:
    if env_path := os.environ.get("MEMCON_CONFIG_FILE"):
        return Path(env_path).expanduser()
    user_path = Path.home() / ".config" / "memcon" / "config.toml"
    bundled_path = _bundle_dir() / "config.toml"
    if user_path.is_file():
        return user_path
    return bundled_path


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_config(config_path: Path | None = None) -> AppConfig:
    path = config_path or _resolve_config_path()
    raw = _load_toml(path)

    app = raw["app"]
    paths = raw["paths"]
    ollama = raw["ollama"]
    history = raw["history"]
    tokens = raw["tokens"]
    workspace = raw["workspace"]
    budgets = raw["budgets"]
    global_defaults = raw["global_defaults"]

    config_dir = Path(
        os.environ.get(
            "MEMCON_CONFIG_DIR",
            str(Path.home() / paths["config_subdir"]),
        )
    ).expanduser()

    budget_rules = tuple(
        (tuple(rule["patterns"]), int(rule["tokens"]))
        for rule in budgets.get("rules", [])
    )

    return AppConfig(
        version=str(app["version"]),
        default_model=str(app["default_model"]),
        config_dir=config_dir,
        global_config_path=config_dir / paths["global_config_file"],
        history_path=config_dir / paths["history_file"],
        project_context_file=str(paths["project_context_file"]),
        ignore_file=str(paths["ignore_file"]),
        ollama_host=os.environ.get("OLLAMA_HOST", str(ollama["host"])).rstrip("/"),
        ollama_chat_endpoint=str(ollama["chat_endpoint"]),
        ollama_timeout_seconds=int(ollama["timeout_seconds"]),
        ollama_stream=bool(ollama["stream"]),
        history_max_entries=int(history["max_entries"]),
        history_display_limit=int(history["display_limit"]),
        prompt_preview_length=int(history["prompt_preview_length"]),
        plain_text_divisor=float(tokens["plain_text_divisor"]),
        dense_code_divisor=float(tokens["dense_code_divisor"]),
        symbol_density_threshold=float(tokens["symbol_density_threshold"]),
        code_symbols_pattern=str(tokens["code_symbols_pattern"]),
        scan_max_depth=int(workspace["scan_max_depth"]),
        invariant_ignore_dirs=frozenset(workspace["invariant_ignore_dirs"]),
        invariant_ignore_files=frozenset(workspace["invariant_ignore_files"]),
        allowed_extensions=frozenset(workspace["allowed_extensions"]),
        budget_rules=budget_rules,
        default_budget_tokens=int(budgets["default_tokens"]),
        global_defaults={
            "persona": str(global_defaults["persona"]),
            "style": str(global_defaults["style"]),
            "defaults": {"model": str(global_defaults["model"])},
        },
        code_symbols=re.compile(str(tokens["code_symbols_pattern"])),
    )


CFG = load_config()


def ensure_config_dir() -> None:
    CFG.config_dir.mkdir(parents=True, exist_ok=True)


def load_global_config() -> dict:
    ensure_config_dir()
    if not CFG.global_config_path.exists():
        CFG.global_config_path.write_text(
            json.dumps(CFG.global_defaults, indent=2) + "\n"
        )
        return dict(CFG.global_defaults)
    return json.loads(CFG.global_config_path.read_text())


def find_memcon_files(start: Path | None = None) -> list[Path]:
    """Walk upward from start (or cwd) to /, collecting project context files."""
    current = (start or Path.cwd()).resolve()
    found: list[Path] = []
    while True:
        candidate = current / CFG.project_context_file
        if candidate.is_file():
            found.append(candidate)
        if current == current.parent:
            break
        current = current.parent
    return list(reversed(found))


def read_memcon_context(paths: list[Path]) -> str:
    parts: list[str] = []
    for path in paths:
        parts.append(f"--- {path} ---\n{path.read_text()}")
    return "\n\n".join(parts)


def read_memconignore(root: Path) -> list[str]:
    ignore_path = root / CFG.ignore_file
    if not ignore_path.is_file():
        return []
    rules: list[str] = []
    for line in ignore_path.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            rules.append(stripped)
    return rules


def is_ignored(file_path: Path, root_dir: Path, ignore_rules: list[str]) -> bool:
    try:
        rel = file_path.resolve().relative_to(root_dir.resolve())
    except ValueError:
        return True

    rel_posix = rel.as_posix()
    parts = rel.parts

    for part in parts:
        if part in CFG.invariant_ignore_dirs:
            return True

    if rel.name in CFG.invariant_ignore_files:
        return True

    for rule in ignore_rules:
        if rule.endswith("/"):
            dir_name = rule.rstrip("/")
            if rel_posix == dir_name or rel_posix.startswith(dir_name + "/"):
                return True
            if dir_name in parts:
                return True
        elif fnmatch.fnmatch(rel.name, rule) or fnmatch.fnmatch(rel_posix, rule):
            return True

    if file_path.suffix.lower() not in CFG.allowed_extensions:
        return True

    return False


def calculate_precise_tokens(text: str) -> int:
    if not text:
        return 0
    symbol_hits = len(CFG.code_symbols.findall(text))
    density = symbol_hits / max(len(text), 1)
    divisor = (
        CFG.dense_code_divisor
        if density >= CFG.symbol_density_threshold
        else CFG.plain_text_divisor
    )
    return int(len(text) // divisor)


def get_dynamic_budget(model_name: str) -> int:
    name = model_name.lower()
    for patterns, tokens in CFG.budget_rules:
        if any(pattern in name for pattern in patterns):
            return tokens
    return CFG.default_budget_tokens


def check_syntax_validity(file_path: Path) -> tuple[bool, str]:
    if file_path.suffix != ".py":
        return True, ""
    try:
        ast.parse(file_path.read_text())
        return True, ""
    except SyntaxError as exc:
        line = exc.lineno or "?"
        return False, f"Syntax error in {file_path.name} at Line {line}: {exc.msg}"


def scan_workspace(
    root_dir: Path,
    ignore_rules: list[str],
    max_depth: int | None = None,
) -> dict[str, str]:
    files: dict[str, str] = {}
    root_dir = root_dir.resolve()
    depth_limit = CFG.scan_max_depth if max_depth is None else max_depth

    for dirpath, dirnames, filenames in os.walk(root_dir):
        current = Path(dirpath)
        try:
            depth = len(current.relative_to(root_dir).parts)
        except ValueError:
            continue
        if depth > depth_limit:
            dirnames.clear()
            continue

        dirnames[:] = [
            d
            for d in dirnames
            if not is_ignored(current / d, root_dir, ignore_rules)
        ]

        for name in sorted(filenames):
            file_path = current / name
            if is_ignored(file_path, root_dir, ignore_rules):
                continue
            if file_path.suffix == ".py":
                valid, err = check_syntax_validity(file_path)
                if not valid:
                    print(f"⚠️  {err}", file=sys.stderr)
                    continue
            try:
                rel_key = file_path.relative_to(root_dir).as_posix()
                files[rel_key] = file_path.read_text()
            except (OSError, UnicodeDecodeError):
                continue

    return files


def compress_files_to_budget(
    files: dict[str, str],
    baseline_tokens: int,
    max_budget: int,
) -> str:
    remaining = max_budget - baseline_tokens
    if remaining <= 0:
        return ""

    blocks: list[str] = []
    for rel_path in sorted(files):
        content = files[rel_path]
        tokens = calculate_precise_tokens(content)
        if tokens > remaining:
            continue
        header = f"### {rel_path}\n```\n{content}\n```"
        blocks.append(header)
        remaining -= tokens

    return "\n\n".join(blocks)


def scan_and_compress_workspace(
    root_dir: Path,
    baseline_tokens: int,
    max_budget_limit: int,
) -> str:
    ignore_rules = read_memconignore(root_dir)
    files = scan_workspace(root_dir, ignore_rules)
    return compress_files_to_budget(files, baseline_tokens, max_budget_limit)


def build_system_prompt(global_cfg: dict, memcon_context: str) -> str:
    parts = [
        global_cfg.get("persona", ""),
        global_cfg.get("style", ""),
    ]
    if memcon_context:
        parts.append(f"Project context:\n{memcon_context}")
    return "\n\n".join(p for p in parts if p)


def assemble_payload(
    system_prompt: str,
    workspace_context: str,
    user_input: str,
) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    if workspace_context:
        messages.append(
            {
                "role": "user",
                "content": f"Workspace files:\n{workspace_context}",
            }
        )
    messages.append({"role": "user", "content": user_input})
    return messages


def apply_budget_compression(
    system_prompt: str,
    workspace_files: dict[str, str],
    user_input: str,
    model: str,
) -> tuple[list[dict], str]:
    max_budget = get_dynamic_budget(model)
    baseline = calculate_precise_tokens(system_prompt) + calculate_precise_tokens(
        user_input
    )

    if baseline > max_budget:
        raise ValueError(
            f"Baseline prompt ({baseline} tokens) exceeds model budget ({max_budget})."
        )

    workspace_context = compress_files_to_budget(
        workspace_files, baseline, max_budget
    )
    total = baseline + calculate_precise_tokens(workspace_context)
    while workspace_files and total > max_budget:
        last_key = sorted(workspace_files)[-1]
        del workspace_files[last_key]
        workspace_context = compress_files_to_budget(
            workspace_files, baseline, max_budget
        )
        total = baseline + calculate_precise_tokens(workspace_context)

    return assemble_payload(system_prompt, workspace_context, user_input), workspace_context


def stream_ollama_chat(model: str, messages: list[dict]) -> str:
    payload = json.dumps(
        {"model": model, "messages": messages, "stream": CFG.ollama_stream}
    ).encode()
    req = urllib.request.Request(
        f"{CFG.ollama_host}{CFG.ollama_chat_endpoint}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    chunks: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=CFG.ollama_timeout_seconds) as resp:
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


def append_history(
    cwd: str,
    model: str,
    system_prompt: str,
    user_input: str,
    workspace_context: str,
    response: str,
) -> None:
    ensure_config_dir()
    history: list[dict] = []
    if CFG.history_path.exists():
        history = json.loads(CFG.history_path.read_text())

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cwd": cwd,
        "model": model,
        "system_prompt": system_prompt,
        "workspace_context": workspace_context,
        "user_input": user_input,
        "response": response,
    }
    history.append(entry)
    history = history[-CFG.history_max_entries :]
    CFG.history_path.write_text(json.dumps(history, indent=2) + "\n")


def show_history(limit: int | None = None) -> None:
    display_limit = CFG.history_display_limit if limit is None else limit
    if not CFG.history_path.exists():
        print("No session history found.")
        return
    history = json.loads(CFG.history_path.read_text())
    for idx, entry in enumerate(history[-display_limit:], start=1):
        ts = entry.get("timestamp", "?")
        model = entry.get("model", "?")
        cwd = entry.get("cwd", "?")
        prompt_preview = (entry.get("user_input") or "")[: CFG.prompt_preview_length]
        print(f"{idx}. [{ts}] model={model} cwd={cwd}")
        print(f"   prompt: {prompt_preview!r}")
        print()


def resolve_user_input(prompt_or_file: str | None) -> str:
    if prompt_or_file is None:
        if sys.stdin.isatty():
            print("Enter prompt (Ctrl+D / Ctrl+Z to finish):")
        return sys.stdin.read().strip()

    candidate = Path(prompt_or_file)
    if candidate.is_file():
        return candidate.read_text().strip()
    return prompt_or_file


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="memcon",
        description="Local ambient memory manager and Ollama execution proxy.",
    )
    parser.add_argument("prompt_or_file", nargs="?", default=None)
    parser.add_argument("-m", "--model", default=CFG.default_model)
    parser.add_argument("-s", "--show-context", action="store_true")
    parser.add_argument("-hi", "--history", action="store_true")
    parser.add_argument("-sc", "--scan", action="store_true")
    parser.add_argument("-v", "--version", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.version:
        print(f"memcon v{CFG.version}")
        return 0

    if args.history:
        show_history()
        return 0

    user_input = resolve_user_input(args.prompt_or_file)
    if not user_input:
        print("Error: empty prompt.", file=sys.stderr)
        return 1

    global_cfg = load_global_config()
    memcon_paths = find_memcon_files()
    memcon_context = read_memcon_context(memcon_paths)
    system_prompt = build_system_prompt(global_cfg, memcon_context)

    workspace_files: dict[str, str] = {}
    if args.scan:
        root = Path.cwd()
        ignore_rules = read_memconignore(root)
        workspace_files = scan_workspace(root, ignore_rules)

    try:
        messages, workspace_context = apply_budget_compression(
            system_prompt, workspace_files, user_input, args.model
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.show_context:
        print("=== System Prompt ===")
        print(system_prompt)
        if workspace_context:
            print("\n=== Workspace Context ===")
            print(workspace_context)
        print("\n=== User Input ===")
        print(user_input)
        return 0

    response = stream_ollama_chat(args.model, messages)
    append_history(
        cwd=str(Path.cwd()),
        model=args.model,
        system_prompt=system_prompt,
        user_input=user_input,
        workspace_context=workspace_context,
        response=response,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
