# Local MemCon — Functional & Technical Specification (v1.0)

**Document version:** 1.0  
**Software version:** 1.0  
**Status:** Implemented

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Scope](#3-scope)
4. [System Context](#4-system-context)
5. [Functional Requirements](#5-functional-requirements)
6. [Non-Functional Requirements](#6-non-functional-requirements)
7. [CLI Specification](#7-cli-specification)
8. [Configuration Specification](#8-configuration-specification)
9. [Algorithm Specifications](#9-algorithm-specifications)
10. [API Integration](#10-api-integration)
11. [Telemetry Specification](#11-telemetry-specification)
12. [Build & Release Specification](#12-build--release-specification)
13. [Test Specification](#13-test-specification)
14. [Out of Scope](#14-out-of-scope)

---

## 1. Executive Summary

Local MemCon is an ambient memory manager and command-line execution proxy for local and cloud LLM backends. It intercepts user prompts at query-construction time, harvests context from layered configuration sources, optimizes context footprint against model token budgets, and streams context-infused instructions to **Ollama**, **Anthropic**, **OpenAI**, or **Kiro CLI**.

The system solves **context decay** and **manual configuration fatigue** in local development workflows by eliminating the need to repeatedly supply system roles, personas, style guides, and codebase structure across separate shell sessions.

---

## 2. Problem Statement

Developers using LLMs from the shell typically:

- Re-enter system prompts and project conventions in every session
- Manually copy file contents into prompts for code-aware tasks
- Hit context window limits without structured compression
- Lack auditability of what was sent to the model

MemCon addresses these by providing a deterministic, configurable, budget-aware prompt assembly pipeline invoked from the shell.

---

## 3. Scope

### In scope (v1.0)

- CLI invocation from terminal
- Global, project, and workspace context layers
- `.memconignore` filtering
- Python AST pre-flight validation
- Model-aware token budgeting and file dropping
- Pluggable provider layer: Ollama, Anthropic, OpenAI, Kiro CLI
- `config.toml` for runtime constants and provider settings
- Local session history (50 entries)
- Single-file binary distribution (PyInstaller)
- Automated test suite (pytest)

### Out of scope (v1.0)

See [Section 14](#14-out-of-scope).

---

## 4. System Context

```text
┌─────────────┐     ┌──────────────┐     ┌──────────────────────────────┐
│   Operator  │────►│    MemCon    │────►│ Provider (one of):           │
│  (Terminal) │◄────│   (CLI Proxy)│◄────│ Ollama / Anthropic / OpenAI  │
└─────────────┘     └──────┬───────┘     │ / Kiro CLI (ACP/headless)    │
                           │              └──────────────────────────────┘
                           ▼
                  ┌─────────────────┐
                  │ ~/.config/memcon│
                  │ config.toml     │
                  │ global.json     │
                  │ history.json    │
                  └─────────────────┘
```

**Actors:**

| Actor | Role |
|-------|------|
| Operator | Invokes memcon from shell with prompt and flags |
| MemCon | Assembles context, enforces budget, routes to provider |
| Provider | Ollama HTTP, Anthropic/OpenAI REST, or Kiro subprocess |
| Filesystem | Source of `.memcon`, `.memconignore`, workspace files |

---

## 5. Functional Requirements

### FR-1: Context Layer Harvesting

| ID | Requirement |
|----|-------------|
| FR-1.1 | On startup, load or auto-create `~/.config/memcon/global.json` |
| FR-1.2 | Walk upward from `PWD` to `/`, collecting all `.memcon` files |
| FR-1.3 | Merge `.memcon` files root-to-leaf into project context |
| FR-1.4 | Combine global persona, style, and project context into system prompt |

### FR-2: Workspace Scanning (`--scan`)

| ID | Requirement |
|----|-------------|
| FR-2.1 | When `--scan` is set, iterate workspace files up to 3 directory levels deep |
| FR-2.2 | Parse `.memconignore` from project root (`PWD`) |
| FR-2.3 | Apply invariant exclusions: `.git/`, `node_modules/`, `__pycache__/`, `.venv/`, `venv/`, `dist/`, `build/`, `.memcon`, `.memconignore`, `.DS_Store` |
| FR-2.4 | Restrict to extensions: `.py`, `.js`, `.ts`, `.jsx`, `.tsx`, `.go`, `.rs`, `.html`, `.css`, `.json`, `.md`, `.txt`, `.yml`, `.yaml` |
| FR-2.5 | Run `ast.parse` on `.py` files; skip invalid files with stderr warning including line number |

### FR-3: Token Budget Management

| ID | Requirement |
|----|-------------|
| FR-3.1 | Estimate tokens using density-aware heuristic (see §9.1) |
| FR-3.2 | Map model name to budget: 70b→16k, 32b/14b→8k, 8b/llama3/phi3→4k, default→4k |
| FR-3.3 | If baseline (system + user input) exceeds budget, abort with error |
| FR-3.4 | If total exceeds budget, drop workspace files (alphabetically last first) until within budget |
| FR-3.5 | Include workspace files in alphabetical order while budget allows |

### FR-4: Provider Execution

| ID | Requirement |
|----|-------------|
| FR-4.1 | Support providers: `ollama`, `anthropic`, `openai`, `kiro` |
| FR-4.2 | Select provider via `--provider`, `MEMCON_PROVIDER`, or `config.toml` flags (`use_ollama`, `use_paid`, `use_kiro`, `paid_provider`); exactly one flag may be enabled |
| FR-4.2a | Provider resolution order: CLI `--provider` → `MEMCON_PROVIDER` → config flags → legacy `[provider].name` |
| FR-4.3 | Stream response tokens to stdout in real time |
| FR-4.4 | **Ollama:** POST to `{OLLAMA_HOST}/api/chat` with `stream: true` |
| FR-4.5 | **Anthropic:** POST to `/v1/messages` with SSE; system prompt in top-level `system` field |
| FR-4.6 | **OpenAI:** POST to `/v1/chat/completions` with SSE |
| FR-4.7 | **Kiro:** spawn `kiro-cli acp` (JSON-RPC) or `kiro-cli chat --no-interactive` (headless) |
| FR-4.8 | Load API keys from environment variables only (never from config files) |

### FR-5: Session Telemetry

| ID | Requirement |
|----|-------------|
| FR-5.1 | Append session record to `~/.config/memcon/history.json` after successful run |
| FR-5.2 | Record: timestamp (UTC ISO), cwd, provider, model, system prompt, workspace context, user input, response |
| FR-5.3 | Retain last 50 entries |
| FR-5.4 | `--history` displays last 10 entries in terminal |

### FR-6: Utility Commands

| ID | Requirement |
|----|-------------|
| FR-6.1 | `--version` prints `memcon v1.0` |
| FR-6.2 | `--show-context` prints assembled prompt without calling a provider |
| FR-6.3 | Positional arg as file path reads file contents as user prompt |
| FR-6.4 | No positional arg reads multiline prompt from stdin |

---

## 6. Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | Zero external Python dependencies at runtime (stdlib only in source) |
| NFR-2 | Single-file binary distribution via PyInstaller |
| NFR-3 | Build pipeline must pass pytest before compilation |
| NFR-4 | Release artifacts include SHA-256 manifest |
| NFR-5 | Cross-platform support: macOS, Linux (native), Windows (Podman cross-compile) |
| NFR-6 | Provider request timeout configurable (default 600 seconds) |

---

## 7. CLI Specification

```text
memcon [-h] [--provider PROVIDER] [--model MODEL] [--show-context] [--history] [--scan] [--version] [prompt_or_file]
```

### Positional arguments

| Argument | Type | Description |
|----------|------|-------------|
| `prompt_or_file` | Optional string | Prompt text, or filepath whose contents become the prompt |

### Options

| Flag | Short | Type | Default | Description |
|------|-------|------|---------|-------------|
| `--provider` | `-p` | string | from config | `ollama`, `anthropic`, `openai`, `kiro` |
| `--model` | `-m` | string | provider default | Target model name |
| `--show-context` | `-s` | boolean | false | Print prompt assembly; no API call |
| `--history` | `-hi` | boolean | false | Show last 10 sessions |
| `--scan` | `-sc` | boolean | false | Enable workspace scanning |
| `--version` | `-v` | boolean | false | Print version |

### Exit codes

| Code | Condition |
|------|-----------|
| 0 | Success |
| 1 | Empty prompt, budget exceeded, or unhandled error |

---

## 8. Configuration Specification

### 8.1 Application config (`config.toml`)

Bundled with the binary; user override at `~/.config/memcon/config.toml`.

| Section | Purpose |
|---------|---------|
| `[app]` | Version, description |
| `[provider]` | Provider flags (`use_ollama`, `use_paid`, `use_kiro`, `paid_provider`, legacy `name`) |

Example:

```toml
[provider]
use_ollama = true
use_paid = false
use_kiro = false
paid_provider = "anthropic"
```
| `[ollama]` | Ollama host, endpoint, default model |
| `[anthropic]` | Anthropic API settings |
| `[openai]` | OpenAI API settings |
| `[kiro]` | Kiro CLI path, mode (`acp`/`headless`), tool approval |
| `[tokens]` | Token estimation divisors |
| `[workspace]` | Scan depth, ignore lists, allowed extensions |
| `[[budgets.rules]]` | Model pattern → token budget |
| `[history]` | History retention limits |

Environment overrides: `MEMCON_PROVIDER`, `OLLAMA_HOST`, `OPENAI_BASE_URL`, `KIRO_CLI_PATH`, `KIRO_API_KEY`, `MEMCON_CONFIG_FILE`, `MEMCON_CONFIG_DIR`.

### 8.2 Global config (`~/.config/memcon/global.json`)

```json
{
  "persona": "string — system role description",
  "style": "string — response style guidance",
  "defaults": {
    "model": "string — default model name"
  }
}
```

Auto-created on first run if missing.

### 8.3 Project context (`.memcon`)

- Plain text file
- Discovered by upward directory traversal from `PWD`
- Multiple files merged in root-to-leaf order

### 8.4 Ignore rules (`.memconignore`)

- One rule per line
- `#` prefix for comments
- Glob patterns for files
- Trailing `/` for directory rules
- Evaluated via `fnmatch`

---

## 9. Algorithm Specifications

### 9.1 Token estimation

```
symbol_density = count({, }, [, ], =>) / len(text)
divisor = 3.4 if symbol_density >= 0.02 else 3.9
tokens = floor(len(text) / divisor)
```

### 9.2 Dynamic budget mapping

```
if "70b" in model_name.lower():  return 16000
if "32b" or "14b" in model_name: return 8000
if "8b" or "llama3" or "phi3":   return 4000
else:                             return 4000
```

### 9.3 Compression algorithm

1. Compute `baseline = tokens(system_prompt) + tokens(user_input)`
2. If `baseline > max_budget`: error
3. Iterate files in sorted order; include file if `tokens(content) <= remaining`
4. If total still exceeds budget, remove alphabetically last file and recompress

### 9.4 Message assembly

```json
[
  { "role": "system", "content": "<system_prompt>" },
  { "role": "user", "content": "Workspace files:\n<workspace_context>" },
  { "role": "user", "content": "<user_input>" }
]
```

Workspace user message omitted if workspace context is empty.

---

## 10. API Integration

### 10.1 Ollama — `POST {OLLAMA_HOST}/api/chat`

NDJSON stream; `message.content` chunks; `done: true` on final line.

### 10.2 Anthropic — `POST {base}/v1/messages`

SSE `content_block_delta` events; `system` field separate from `messages`; auth via `x-api-key`.

### 10.3 OpenAI — `POST {base}/v1/chat/completions`

SSE `choices[0].delta.content` chunks; Bearer token auth.

### 10.4 Kiro CLI — subprocess

| Mode | Invocation | Protocol |
|------|------------|----------|
| `acp` | `kiro-cli acp` | JSON-RPC 2.0 over stdio; `session/prompt` |
| `headless` | `kiro-cli chat --no-interactive` | stdout capture |

ACP streams via `session/update` notifications (`agent_message_chunk`).

---

## 11. Telemetry Specification

### History entry schema

```json
{
  "timestamp": "2026-06-09T14:32:01.123456+00:00",
  "cwd": "/path/to/project",
  "provider": "anthropic",
  "model": "claude-sonnet-4-20250514",
  "system_prompt": "...",
  "workspace_context": "...",
  "user_input": "...",
  "response": "..."
}
```

**Storage:** `~/.config/memcon/history.json` — JSON array, max 50 entries.

---

## 12. Build & Release Specification

### Pipeline (`build.sh`)

1. Run `pytest -v test_memcon.py` — halt on failure
2. `pyinstaller --onefile --add-data config.toml:. --collect-submodules providers memcon.py`
3. Archive native binary to `releases/memcon-v1.0-host.tar.gz`
4. Cross-compile Windows binary via Podman (`cdrx/pyinstaller-windows`) if available
5. Generate `releases/SHASUMS256.txt` (SHA-256 per archive)
6. GPG-sign manifest if `gpg` available
7. Desktop notification on completion

### Release artifacts

```text
releases/
├── memcon-v1.0-host.tar.gz
├── memcon-v1.0-win64.zip
├── SHASUMS256.txt
└── SHASUMS256.txt.sig
```

---

## 13. Test Specification

Test suite: `test_memcon.py` (pytest)

| Test | Validates |
|------|-----------|
| `test_token_calculator_plain_text` | Plain text token divisor (3.9) |
| `test_token_calculator_dense_code` | Dense code token divisor (3.4) |
| `test_ignore_rules_matching` | Invariant + custom ignore rules |
| `test_syntax_checker_valid_python` | Valid Python passes AST check |
| `test_syntax_checker_invalid_python` | Invalid Python returns line number |
| `test_workspace_compression_drops_excess_files` | Budget compression drops files |
| `test_dynamic_budget_mapping` | Model name → budget mapping |
| `test_config_loads_from_toml` | `config.toml` parsing |
| `test_provider_flags_paid_anthropic` | `use_paid` + `paid_provider` resolution |
| `test_provider_flags_kiro` | `use_kiro` flag resolution |
| `test_provider_flags_reject_multiple_enabled` | Rejects multiple enabled provider flags |
| `test_provider_legacy_name_fallback` | Legacy `[provider].name` fallback |
| `test_provider_config_anthropic` | Anthropic provider config |
| `test_provider_config_openai` | OpenAI provider config |
| `test_provider_config_kiro` | Kiro provider config |
| `test_kiro_prompt_formatting` | Kiro prompt flattening |
| `test_split_messages_extracts_system_prompt` | System message extraction |

All tests must pass before release build.

---

## 14. Out of Scope

- Multi-turn conversation memory
- GUI or IDE plugins
- Embedding / RAG retrieval
- Watchman or filesystem event integration
- Remote config sync
- Authentication / multi-user support
