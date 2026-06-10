# Local MemCon — User Guide

A practical guide for day-to-day use of MemCon as a shell-integrated assistant across **Ollama**, **Anthropic**, **OpenAI**, and **Kiro CLI**.

---

## Table of Contents

1. [What MemCon Does](#what-memcon-does)
2. [Getting Started](#getting-started)
3. [Choosing a Provider](#choosing-a-provider)
4. [Basic Usage](#basic-usage)
5. [Context Layers](#context-layers)
6. [Application Config (`config.toml`)](#application-config-configtoml)
7. [Workspace Scanning](#workspace-scanning)
8. [Filtering with .memconignore](#filtering-with-memconignore)
9. [Choosing a Model](#choosing-a-model)
10. [Inspecting Context](#inspecting-context)
11. [Session History](#session-history)
12. [Workflow Examples](#workflow-examples)
13. [Tips and Limitations](#tips-and-limitations)

---

## What MemCon Does

MemCon eliminates repeated manual context setup across shell sessions. Instead of pasting system prompts, style guides, and file contents every time you talk to a model, MemCon:

1. Loads your global persona automatically
2. Discovers project-specific rules from `.memcon` files
3. Optionally bundles workspace source files into the prompt
4. Fits everything within your model's token budget
5. Streams the response from your chosen provider
6. Logs the session for later review

MemCon is **not** a persistent chat UI. Each invocation builds a fresh, optimized prompt for a single query.

---

## Getting Started

### 1. Pick and configure a provider

| Provider | Setup |
|----------|-------|
| **Ollama** (default) | `ollama pull llama3` and ensure Ollama is running |
| **Anthropic** | `export ANTHROPIC_API_KEY=sk-ant-...` |
| **OpenAI** | `export OPENAI_API_KEY=sk-...` |
| **Kiro CLI** | Install from [kiro.dev](https://kiro.dev), then `kiro-cli auth login` |

### 2. Install MemCon

See [DEPLOYMENT.md](DEPLOYMENT.md) for binary installation, or run from source:

```bash
cd memcon
devbox shell
python memcon.py --version
```

### 3. Run your first prompt

```bash
memcon "What is a Python decorator?"
memcon "Refactor auth" --scan --provider anthropic -m claude-sonnet-4-20250514
```

On first run, MemCon creates `~/.config/memcon/global.json` with default persona settings.

---

## Choosing a Provider

### Default via `config.toml` (recommended)

Set **exactly one** flag to `true` in `[provider]` (or copy to `~/.config/memcon/config.toml`):

```toml
[provider]
use_ollama = true
use_paid = false
use_kiro = false
paid_provider = "anthropic"  # anthropic | openai when use_paid = true
```

| Goal | Config |
|------|--------|
| Local Ollama | `use_ollama = true` |
| Anthropic API | `use_paid = true`, `paid_provider = "anthropic"` |
| OpenAI API | `use_paid = true`, `paid_provider = "openai"` |
| Kiro CLI | `use_kiro = true` |

Then run without `-p`:

```bash
memcon "Explain decorators" --scan
```

**Resolution order:** `--provider` → `MEMCON_PROVIDER` → config flags → legacy `[provider].name`.

### One-off overrides (CLI or env)

```bash
# Local Ollama
memcon "Explain decorators" --provider ollama -m llama3

# Anthropic direct API
export ANTHROPIC_API_KEY=sk-ant-...
memcon "Write tests" --scan --provider anthropic -m claude-sonnet-4-20250514

# OpenAI direct API
export OPENAI_API_KEY=sk-...
memcon "Summarize module" --scan --provider openai -m gpt-4o

# Kiro CLI (ACP streaming)
kiro-cli auth login
memcon "Refactor payment service" --scan --provider kiro
```

### Kiro CLI modes

Configured in `config.toml` under `[kiro]`:

| Mode | Description | Auth |
|------|-------------|------|
| `acp` (default) | JSON-RPC agent protocol via `kiro-cli acp`; streams chunks | `kiro-cli auth login` |
| `headless` | `kiro-cli chat --no-interactive` | `KIRO_API_KEY` |

Headless is useful for CI pipelines:

```bash
export KIRO_API_KEY=...
# set mode = "headless" in config.toml or ~/.config/memcon/config.toml
memcon "Review PR" --scan --provider kiro
```

---

## Basic Usage

```text
memcon [-h] [--provider PROVIDER] [--model MODEL] [--show-context] [--history] [--scan] [--version] [prompt_or_file]
```

### Prompt as text

```bash
memcon "Write unit tests for the auth module" --scan --provider openai
```

### Prompt from a file

```bash
memcon prompts/refactor-brief.md --provider anthropic
```

### Multiline input (no argument)

```bash
memcon --provider ollama
```

Type or paste your prompt, then press `Ctrl+D` (macOS/Linux) or `Ctrl+Z` then Enter (Windows).

### Common flags

| Flag | Short | Effect |
|------|-------|--------|
| `--provider` | `-p` | Backend: `ollama`, `anthropic`, `openai`, `kiro` |
| `--model` | `-m` | Model name (default from provider section in `config.toml`) |
| `--scan` | `-sc` | Include workspace files in context |
| `--show-context` | `-s` | Print assembled prompt; no API call |
| `--history` | `-hi` | Show last 10 sessions |
| `--version` | `-v` | Print version |

### Makefile and devbox shortcuts

```bash
make run ARGS='"Explain this module" --scan'          # uses config.toml flags
make run-paid ARGS='"Summarize repo" --scan'          # when use_paid = true in config
make run-anthropic ARGS='"Write tests" --scan' MODEL=claude-sonnet-4-20250514
make run-kiro ARGS='"Refactor auth" --scan'
make show-context ARGS='"prompt" --scan'

devbox run test
devbox run build
devbox run run-kiro    # then pass prompt via stdin or ARGS with make
```

---

## Context Layers

MemCon assembles context from three tiers, applied in order:

### Tier 1 — Global persona

**File:** `~/.config/memcon/global.json`

```json
{
  "persona": "You are a senior backend engineer specializing in Python and Go.",
  "style": "Prefer concise answers with code examples. Use type hints.",
  "defaults": { "model": "llama3" }
}
```

### Tier 2 — Project context

**File:** `.memcon` in any ancestor directory — merged root-to-leaf upward from `PWD`.

### Tier 3 — Workspace files (optional)

Activated with `--scan`. See [Workspace Scanning](#workspace-scanning).

---

## Application Config (`config.toml`)

Runtime constants and per-provider defaults live in `config.toml`. Override location with `MEMCON_CONFIG_FILE`; user override at `~/.config/memcon/config.toml` takes precedence when present.

Key sections:

```toml
[provider]
use_ollama = true   # local Ollama
use_paid = false    # Anthropic or OpenAI (set paid_provider)
use_kiro = false    # Kiro CLI
paid_provider = "anthropic"  # anthropic | openai (when use_paid = true)

[ollama]
host = "http://localhost:11434"
default_model = "llama3"

[anthropic]
default_model = "claude-sonnet-4-20250514"
api_key_env = "ANTHROPIC_API_KEY"

[openai]
default_model = "gpt-4o"
api_key_env = "OPENAI_API_KEY"

[kiro]
mode = "acp"      # or "headless"
cli_path = "kiro-cli"
auto_approve_tools = true
```

Environment variables:

| Variable | Effect |
|----------|--------|
| `MEMCON_PROVIDER` | Default provider |
| `OLLAMA_HOST` | Ollama base URL |
| `OPENAI_BASE_URL` | OpenAI-compatible API base |
| `ANTHROPIC_API_KEY` | Anthropic credentials |
| `OPENAI_API_KEY` | OpenAI credentials |
| `KIRO_CLI_PATH` | Path to `kiro-cli` binary |
| `KIRO_API_KEY` | Kiro headless API key |

---

## Workspace Scanning

```bash
cd ~/projects/my-api
memcon "Find SQL injection risks" --scan --provider anthropic
```

- Traverses up to **3 directory levels** from `PWD`
- Filters via `.memconignore` and built-in exclusions
- Validates Python with `ast.parse` before inclusion
- Drops files when token budget is exceeded

**Cloud providers:** `--scan` sends file contents to third-party APIs. Review `.memconignore` carefully.

---

## Filtering with .memconignore

```text
secrets/
*.env
*.log
config/local.json
```

Always excluded: `.git/`, `node_modules/`, `__pycache__/`, `.venv/`, `venv/`, `dist/`, `build/`, `.memcon`, `.memconignore`, `.DS_Store`

---

## Choosing a Model

```bash
memcon "Explain this function" --scan -m gpt-4o --provider openai
```

Token budgets are defined in `config.toml` `[[budgets.rules]]`:

| Model pattern | Token budget |
|---------------|--------------|
| `claude-*`, `gpt-4*`, `kiro` | 128,000 |
| `70b` | 16,000 |
| `32b`, `14b` | 8,000 |
| `8b`, `llama3`, `phi3` | 4,000 |
| default | 4,000 |

---

## Inspecting Context

```bash
memcon "Refactor payment service" --scan --show-context --provider anthropic
```

Output includes system prompt, workspace context, user input, and selected provider/model. No API call is made.

---

## Session History

```bash
memcon --history
```

```text
1. [2026-06-09T14:32:01+00:00] provider=anthropic model=claude-sonnet-4-20250514 cwd=/home/user/my-api
   prompt: 'Find potential SQL injection risks'
```

Stored in `~/.config/memcon/history.json` (last 50 sessions).

---

## Workflow Examples

### Code review with Claude

```bash
export ANTHROPIC_API_KEY=sk-ant-...
cd ~/projects/web-app
memcon "Review src/auth/login.ts" --scan --provider anthropic
```

### Test generation with OpenAI

```bash
memcon test-spec.md --scan --provider openai -m gpt-4o
```

### Agentic coding with Kiro

```bash
kiro-cli auth login
memcon "Implement webhook endpoint with tests" --scan --provider kiro
```

### Local offline with Ollama

```bash
memcon "Difference between asyncio.gather and TaskGroup?" --provider ollama
```

---

## Tips and Limitations

### Tips

- Use `--show-context` before sending large scans to cloud providers
- Put project conventions in `.memcon`; personal preferences in `global.json`
- For Kiro CI jobs, use `mode = "headless"` and `KIRO_API_KEY`
- Never commit API keys; use environment variables only

### Limitations

- **Single-turn only** — no multi-turn memory between invocations
- **Scan depth** — 3 directory levels maximum
- **Token heuristic** — approximate, not model-specific tokenizers
- **Kiro ACP** — requires `kiro-cli` installed and authenticated
- **Cloud cost** — Anthropic/OpenAI/Kiro usage is billed per provider

### Error messages

| Message | Meaning |
|---------|---------|
| `Error: empty prompt.` | No text provided |
| `Baseline prompt exceeds model budget` | Shorten input or use a larger model |
| `Ollama request failed` | Ollama not reachable |
| `Anthropic request failed` | Check API key and model name |
| `OpenAI request failed` | Check API key and model name |
| `kiro-cli not found` | Install Kiro or set `KIRO_CLI_PATH` |
| `Missing API key` | Set the provider's key env var |
| `Multiple providers enabled` | Set only one of `use_ollama`, `use_paid`, `use_kiro` to true |

For deployment and installation, see [DEPLOYMENT.md](DEPLOYMENT.md).
