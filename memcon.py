#!/usr/bin/env python3
"""Local MemCon — ambient memory manager and LLM execution proxy."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from providers import PROVIDERS, stream_chat


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    default_model: str
    timeout_seconds: int = 600
    stream: bool = True
    base_url: str = ""
    endpoint: str = ""
    api_key_env: str | None = None
    api_version: str | None = None
    max_output_tokens: int = 4096
    cli_path: str = "kiro-cli"
    mode: str = "acp"
    auto_approve_tools: bool = True


@dataclass(frozen=True)
class AppConfig:
    version: str
    default_model: str
    provider_name: str
    provider: ProviderConfig
    config_dir: Path
    global_config_path: Path
    history_path: Path
    project_context_file: str
    ignore_file: str
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


def _load_provider_config(name: str, raw: dict[str, Any]) -> ProviderConfig:
    if name == "ollama":
        section = raw["ollama"]
        return ProviderConfig(
            name="ollama",
            base_url=os.environ.get("OLLAMA_HOST", str(section["host"])).rstrip("/"),
            endpoint=str(section["chat_endpoint"]),
            default_model=str(section["default_model"]),
            timeout_seconds=int(section["timeout_seconds"]),
            stream=bool(section["stream"]),
        )
    if name == "anthropic":
        section = raw["anthropic"]
        return ProviderConfig(
            name="anthropic",
            base_url=str(section["base_url"]).rstrip("/"),
            endpoint=str(section["messages_endpoint"]),
            default_model=str(section["default_model"]),
            api_key_env=str(section["api_key_env"]),
            api_version=str(section["api_version"]),
            max_output_tokens=int(section["max_output_tokens"]),
            timeout_seconds=int(section["timeout_seconds"]),
            stream=bool(section["stream"]),
        )
    if name == "openai":
        section = raw["openai"]
        base_url = os.environ.get(
            "OPENAI_BASE_URL", str(section["base_url"])
        ).rstrip("/")
        return ProviderConfig(
            name="openai",
            base_url=base_url,
            endpoint=str(section["chat_endpoint"]),
            default_model=str(section["default_model"]),
            api_key_env=str(section["api_key_env"]),
            max_output_tokens=int(section["max_output_tokens"]),
            timeout_seconds=int(section["timeout_seconds"]),
            stream=bool(section["stream"]),
        )
    if name == "kiro":
        section = raw["kiro"]
        return ProviderConfig(
            name="kiro",
            default_model=str(section["default_model"]),
            api_key_env=str(section.get("api_key_env", "KIRO_API_KEY")),
            timeout_seconds=int(section["timeout_seconds"]),
            cli_path=os.environ.get("KIRO_CLI_PATH", str(section.get("cli_path", "kiro-cli"))),
            mode=str(section.get("mode", "acp")),
            auto_approve_tools=bool(section.get("auto_approve_tools", True)),
        )
    known = "ollama, anthropic, openai, kiro"
    raise ValueError(f"Unknown provider {name!r}. Choose from: {known}")


def _resolve_provider_from_config(raw: dict[str, Any]) -> str:
    section = raw.get("provider", {})
    flag_map = {
        "ollama": bool(section.get("use_ollama", False)),
        "kiro": bool(section.get("use_kiro", False)),
        "paid": bool(section.get("use_paid", False)),
    }
    enabled = [name for name, active in flag_map.items() if active]

    if len(enabled) > 1:
        raise ValueError(
            "Multiple providers enabled in config.toml [provider]. "
            f"Set exactly one of use_ollama, use_paid, use_kiro to true (found: {enabled})."
        )
    if len(enabled) == 1:
        choice = enabled[0]
        if choice == "paid":
            paid = str(section.get("paid_provider", "anthropic")).lower()
            if paid not in ("anthropic", "openai"):
                raise ValueError(
                    f"Invalid paid_provider {paid!r}. Choose anthropic or openai."
                )
            return paid
        return choice

    return str(section.get("name", "ollama")).lower()


def load_config(
    config_path: Path | None = None,
    provider_name: str | None = None,
) -> AppConfig:
    path = config_path or _resolve_config_path()
    raw = _load_toml(path)

    app = raw["app"]
    paths = raw["paths"]
    history = raw["history"]
    tokens = raw["tokens"]
    workspace = raw["workspace"]
    budgets = raw["budgets"]
    global_defaults = raw["global_defaults"]
    resolved_provider = (
        provider_name
        or os.environ.get("MEMCON_PROVIDER")
        or _resolve_provider_from_config(raw)
    ).lower()
    provider = _load_provider_config(resolved_provider, raw)

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
        default_model=provider.default_model or str(app["default_model"]),
        provider_name=resolved_provider,
        provider=provider,
        config_dir=config_dir,
        global_config_path=config_dir / paths["global_config_file"],
        history_path=config_dir / paths["history_file"],
        project_context_file=str(paths["project_context_file"]),
        ignore_file=str(paths["ignore_file"]),
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


def append_history(
    cwd: str,
    provider: str,
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
        "provider": provider,
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
        provider = entry.get("provider", "?")
        model = entry.get("model", "?")
        cwd = entry.get("cwd", "?")
        prompt_preview = (entry.get("user_input") or "")[: CFG.prompt_preview_length]
        print(f"{idx}. [{ts}] provider={provider} model={model} cwd={cwd}")
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
        description="Local ambient memory manager and LLM execution proxy.",
    )
    parser.add_argument("prompt_or_file", nargs="?", default=None)
    parser.add_argument(
        "-p",
        "--provider",
        choices=tuple(sorted(PROVIDERS.keys())),
        default=None,
        help="LLM backend (default from config.toml or MEMCON_PROVIDER)",
    )
    parser.add_argument("-m", "--model", default=None)
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

    active_cfg = load_config(provider_name=args.provider)
    model = args.model or active_cfg.default_model

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
            system_prompt, workspace_files, user_input, model
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
        print(f"\n=== Provider ===\n{active_cfg.provider_name} / {model}")
        return 0

    try:
        response = stream_chat(
            active_cfg.provider_name, model, messages, active_cfg
        )
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    append_history(
        cwd=str(Path.cwd()),
        provider=active_cfg.provider_name,
        model=model,
        system_prompt=system_prompt,
        user_input=user_input,
        workspace_context=workspace_context,
        response=response,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
