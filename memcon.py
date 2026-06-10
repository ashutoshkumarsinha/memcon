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
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

VERSION = "1.0"
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

CONFIG_DIR = Path.home() / ".config" / "memcon"
GLOBAL_CONFIG_PATH = CONFIG_DIR / "global.json"
HISTORY_PATH = CONFIG_DIR / "history.json"

DEFAULT_GLOBAL_CONFIG = {
    "persona": "You are a helpful local coding assistant.",
    "style": "Be concise and precise.",
    "defaults": {"model": "llama3"},
}

INVARIANT_IGNORE_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
}

INVARIANT_IGNORE_FILES = {".memcon", ".memconignore", ".DS_Store"}

ALLOWED_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".go",
    ".rs",
    ".html",
    ".css",
    ".json",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
}

CODE_SYMBOLS = re.compile(r"[\{\}\[\]]|=>")


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_global_config() -> dict:
    ensure_config_dir()
    if not GLOBAL_CONFIG_PATH.exists():
        GLOBAL_CONFIG_PATH.write_text(
            json.dumps(DEFAULT_GLOBAL_CONFIG, indent=2) + "\n"
        )
        return dict(DEFAULT_GLOBAL_CONFIG)
    return json.loads(GLOBAL_CONFIG_PATH.read_text())


def find_memcon_files(start: Path | None = None) -> list[Path]:
    """Walk upward from start (or cwd) to /, collecting .memcon files."""
    current = (start or Path.cwd()).resolve()
    found: list[Path] = []
    while True:
        candidate = current / ".memcon"
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
    ignore_path = root / ".memconignore"
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
        if part in INVARIANT_IGNORE_DIRS:
            return True

    if rel.name in INVARIANT_IGNORE_FILES:
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

    if file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
        return True

    return False


def calculate_precise_tokens(text: str) -> int:
    if not text:
        return 0
    symbol_hits = len(CODE_SYMBOLS.findall(text))
    density = symbol_hits / max(len(text), 1)
    divisor = 3.4 if density >= 0.02 else 3.9
    return int(len(text) // divisor)


def get_dynamic_budget(model_name: str) -> int:
    name = model_name.lower()
    if "70b" in name:
        return 16000
    if "32b" in name or "14b" in name:
        return 8000
    if any(tag in name for tag in ("8b", "llama3", "phi3")):
        return 4000
    return 4000


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
    max_depth: int = 3,
) -> dict[str, str]:
    files: dict[str, str] = {}
    root_dir = root_dir.resolve()

    for dirpath, dirnames, filenames in os.walk(root_dir):
        current = Path(dirpath)
        try:
            depth = len(current.relative_to(root_dir).parts)
        except ValueError:
            continue
        if depth > max_depth:
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
    payload = json.dumps({"model": model, "messages": messages, "stream": True}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    chunks: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
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
    if HISTORY_PATH.exists():
        history = json.loads(HISTORY_PATH.read_text())

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
    history = history[-50:]
    HISTORY_PATH.write_text(json.dumps(history, indent=2) + "\n")


def show_history(limit: int = 10) -> None:
    if not HISTORY_PATH.exists():
        print("No session history found.")
        return
    history = json.loads(HISTORY_PATH.read_text())
    for idx, entry in enumerate(history[-limit:], start=1):
        ts = entry.get("timestamp", "?")
        model = entry.get("model", "?")
        cwd = entry.get("cwd", "?")
        prompt_preview = (entry.get("user_input") or "")[:80]
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
    parser.add_argument("-m", "--model", default="llama3")
    parser.add_argument("-s", "--show-context", action="store_true")
    parser.add_argument("-hi", "--history", action="store_true")
    parser.add_argument("-sc", "--scan", action="store_true")
    parser.add_argument("-v", "--version", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.version:
        print(f"memcon v{VERSION}")
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
