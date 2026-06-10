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

Local MemCon is an ambient memory manager and command-line execution proxy for the Ollama local LLM architecture. It intercepts user prompts at query-construction time, harvests context from layered configuration sources, optimizes context footprint against model token budgets, and streams context-infused instructions to local models.

The system solves **context decay** and **manual configuration fatigue** in local development workflows by eliminating the need to repeatedly supply system roles, personas, style guides, and codebase structure across separate shell sessions.

---

## 2. Problem Statement

Developers using local LLMs via Ollama typically:

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
- Ollama `/api/chat` streaming integration
- Local session history (50 entries)
- Single-file binary distribution (PyInstaller)
- Automated test suite (pytest)

### Out of scope (v1.0)

See [Section 14](#14-out-of-scope).

---

## 4. System Context

```text
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐     ┌────────────┐
│   Operator  │────►│    MemCon    │────►│  Ollama REST    │────►│ Local LLM  │
│  (Terminal) │◄────│   (CLI Proxy)│◄────│  /api/chat      │◄────│  (Model)   │
└─────────────┘     └──────┬───────┘     └─────────────────┘     └────────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │ ~/.config/memcon│
                  │  global.json    │
                  │  history.json   │
                  └─────────────────┘
```

**Actors:**

| Actor | Role |
|-------|------|
| Operator | Invokes memcon from shell with prompt and flags |
| MemCon | Assembles context, enforces budget, proxies to Ollama |
| Ollama | Local inference server |
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

### FR-4: Ollama Execution

| ID | Requirement |
|----|-------------|
| FR-4.1 | POST assembled messages to `{OLLAMA_HOST}/api/chat` with `stream: true` |
| FR-4.2 | Stream response tokens to stdout in real time |
| FR-4.3 | Support `OLLAMA_HOST` environment variable (default: `http://localhost:11434`) |

### FR-5: Session Telemetry

| ID | Requirement |
|----|-------------|
| FR-5.1 | Append session record to `~/.config/memcon/history.json` after successful run |
| FR-5.2 | Record: timestamp (UTC ISO), cwd, model, system prompt, workspace context, user input, response |
| FR-5.3 | Retain last 50 entries |
| FR-5.4 | `--history` displays last 10 entries in terminal |

### FR-6: Utility Commands

| ID | Requirement |
|----|-------------|
| FR-6.1 | `--version` prints `memcon v1.0` |
| FR-6.2 | `--show-context` prints assembled prompt without calling Ollama |
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
| NFR-5 | Cross-platform support: macOS, Linux (native), Windows (Docker cross-compile) |
| NFR-6 | Ollama request timeout: 600 seconds |

---

## 7. CLI Specification

```text
memcon [-h] [--model MODEL] [--show-context] [--history] [--scan] [--version] [prompt_or_file]
```

### Positional arguments

| Argument | Type | Description |
|----------|------|-------------|
| `prompt_or_file` | Optional string | Prompt text, or filepath whose contents become the prompt |

### Options

| Flag | Short | Type | Default | Description |
|------|-------|------|---------|-------------|
| `--model` | `-m` | string | `llama3` | Target Ollama model |
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

### 8.1 Global config (`~/.config/memcon/global.json`)

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

### 8.2 Project context (`.memcon`)

- Plain text file
- Discovered by upward directory traversal from `PWD`
- Multiple files merged in root-to-leaf order

### 8.3 Ignore rules (`.memconignore`)

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

### Ollama Chat API

**Endpoint:** `POST {OLLAMA_HOST}/api/chat`

**Request body:**

```json
{
  "model": "<model_name>",
  "messages": [ ... ],
  "stream": true
}
```

**Response:** Newline-delimited JSON stream. Each line:

```json
{
  "message": { "role": "assistant", "content": "<token_chunk>" },
  "done": false
}
```

Final line has `"done": true`.

---

## 11. Telemetry Specification

### History entry schema

```json
{
  "timestamp": "2026-06-09T14:32:01.123456+00:00",
  "cwd": "/path/to/project",
  "model": "llama3",
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
2. `pyinstaller --onefile --name memcon memcon.py`
3. Archive native binary to `releases/memcon-v1.0-host.tar.gz`
4. Cross-compile Windows binary via Docker (`cdrx/pyinstaller-windows`) if available
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

All tests must pass before release build.

---

## 14. Out of Scope

- Multi-turn conversation memory
- Cloud LLM providers (OpenAI, Anthropic, etc.)
- GUI or IDE plugins
- Embedding / RAG retrieval
- Watchman or filesystem event integration
- Remote config sync
- Authentication / multi-user support
