# Local MemCon — High-Level Design (HLD)

**Document version:** 1.0  
**Software version:** 1.0

---

## Table of Contents

1. [Design Overview](#1-design-overview)
2. [Architecture Principles](#2-architecture-principles)
3. [Component Architecture](#3-component-architecture)
4. [Data Flow](#4-data-flow)
5. [Module Design](#5-module-design)
6. [Context Model](#6-context-model)
7. [Compression Strategy](#7-compression-strategy)
8. [External Interfaces](#8-external-interfaces)
9. [Storage Design](#9-storage-design)
10. [Deployment Architecture](#10-deployment-architecture)
11. [Sequence Diagrams](#11-sequence-diagrams)
12. [Error Handling](#12-error-handling)
13. [Security Design](#13-security-design)
14. [Future Considerations](#14-future-considerations)

---

## 1. Design Overview

MemCon is a **stateless, single-process CLI middleware** that transforms a shell invocation into a structured LLM request routed through a pluggable provider layer. It does not maintain conversational state between runs; instead, it reconstructs context deterministically from filesystem configuration on every invocation.

```text
┌──────────────────────────────────────────────────────────────────┐
│                         MemCon Process                           │
│                                                                  │
│  ┌────────────┐  ┌─────────────────┐  ┌──────────────────────┐  │
│  │ CLI Router │─►│ Context Engine  │─►│ Budget Compressor    │  │
│  └────────────┘  └────────┬────────┘  └──────────┬───────────┘  │
│                           │                       │              │
│                  ┌────────▼────────┐     ┌─────────▼──────────┐  │
│                  │ Workspace Parser│     │ Payload Builder    │  │
│                  └─────────────────┘     └─────────┬──────────┘  │
│                                                     │              │
│                           ┌─────────────────────────▼──────────┐  │
│                           │ Provider Router (stream_chat)     │  │
│                           └─────────┬────────────────────────┘  │
│         ┌──────────┬───────────────┼───────────────┬──────────┐  │
│         ▼          ▼               ▼               ▼          │  │
│    ┌────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │  │
│    │ Ollama │ │Anthropic │ │  OpenAI  │ │  Kiro CLI    │   │  │
│    │ HTTP   │ │ REST/SSE │ │ REST/SSE │ │ ACP/headless │   │  │
│    └────────┘ └──────────┘ └──────────┘ └──────────────┘   │  │
│                           ┌─────────────────────────▼──────────┐  │
│                           │ Telemetry Writer                  │  │
│                           └──────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. Architecture Principles

| Principle | Application |
|-----------|-------------|
| **Ephemeral context** | No cross-session memory; each run builds a fresh prompt |
| **Filesystem as config** | `.memcon` and `.memconignore` are plain text, version-controllable |
| **Fail safe on budget** | Abort if baseline exceeds budget; never silently truncate user input |
| **Progressive inclusion** | Workspace files added in sorted order until budget fills |
| **Zero runtime deps** | Stdlib-only source enables small PyInstaller binary |
| **Provider-pluggable** | Same context pipeline; swappable backends via `config.toml` |
| **Secrets via env** | API keys never stored in config files |

---

## 3. Component Architecture

### 3.1 Component map

```text
memcon.py
├── CLI Router           parse_args(), main()
├── Config Loader        load_config(), load_global_config(), find_memcon_files()
├── Context Assembler    build_system_prompt(), read_memcon_context()
├── Workspace Engine     scan_workspace(), is_ignored(), check_syntax_validity()
├── Token Engine         calculate_precise_tokens(), get_dynamic_budget()
├── Compressor           compress_files_to_budget(), apply_budget_compression()
├── Payload Builder      assemble_payload()
└── Telemetry            append_history(), show_history()

providers/
├── __init__.py          stream_chat(), PROVIDERS registry
├── messages.py          split_messages()
├── ollama.py            Ollama /api/chat NDJSON stream
├── anthropic.py         Anthropic /v1/messages SSE
├── openai.py            OpenAI /v1/chat/completions SSE
├── kiro.py              Kiro CLI subprocess (ACP or headless)
└── kiro_acp.py          JSON-RPC ACP client for kiro-cli
```

### 3.2 Component responsibilities

| Component | Responsibility |
|-----------|----------------|
| **CLI Router** | Parse flags, dispatch to history/version/show-context or main pipeline |
| **Config Loader** | Load `config.toml`, bootstrap `global.json`, discover `.memcon` hierarchy |
| **Context Assembler** | Merge global persona + project rules into system prompt |
| **Workspace Engine** | Walk directory tree, filter, validate Python syntax |
| **Token Engine** | Heuristic token counting and model budget lookup from `config.toml` |
| **Compressor** | Fit workspace files within remaining token budget |
| **Payload Builder** | Construct message array (system + workspace + user) |
| **Provider Router** | Dispatch to `ollama`, `anthropic`, `openai`, or `kiro` client |
| **Telemetry** | Append/read session history (includes `provider` field) |

---

## 4. Data Flow

### 4.1 Standard execution path

```text
Terminal Input
      │
      ▼
┌─────────────┐     ┌──────────────────┐
│ Resolve     │     │ Load global.json │
│ user input  │     │ + .memcon files  │
└──────┬──────┘     └────────┬─────────┘
       │                     │
       │              ┌──────▼──────┐
       │              │ System      │
       │              │ prompt      │
       │              └──────┬──────┘
       │                     │
       │    [--scan]  ┌──────▼──────┐
       │         ┌───►│ Workspace   │
       │         │    │ file dict   │
       │         │    └──────┬──────┘
       │         │           │
       └─────────┼───────────┤
                 │           ▼
                 │    ┌──────────────┐
                 │    │ Compress to  │
                 │    │ token budget │
                 │    └──────┬───────┘
                 │           │
                 ▼           ▼
            ┌─────────────────────┐
            │ Message payload     │
            └──────────┬──────────┘
                       │
              [--show-context]──► stdout (exit)
                       │
                       ▼
            ┌─────────────────────┐
            │ Provider client     │
            │ (HTTP or subprocess)│
            └──────────┬──────────┘
                       │
                       ▼
            ┌─────────────────────┐
            │ history.json      │
            └─────────────────────┘
```

### 4.2 Data types at pipeline stages

| Stage | Data structure |
|-------|----------------|
| Global config | `dict` (JSON) |
| MemCon paths | `list[Path]` |
| Workspace files | `dict[str, str]` (relative path → content) |
| System prompt | `str` |
| Workspace context | `str` (markdown blocks) |
| Payload | `list[dict]` (chat messages) |
| Provider config | `ProviderConfig` dataclass |
| Response | `str` (accumulated stream) |

---

## 5. Module Design

### 5.1 CLI Router

**Entry:** `main(argv)`

**Routing logic:**

```text
--version  → print version, exit 0
--history  → show_history(), exit 0
(default)  → resolve input → pipeline → provider or --show-context
```

**Input resolution priority:**

1. Positional argument as existing file → read contents
2. Positional argument as text → use directly
3. No argument → read stdin until EOF

### 5.2 Workspace Engine

**Traversal:** `os.walk` with depth limit (3 levels from root).

**Filter pipeline per file:**

```text
path → invariant dir check → invariant file check → .memconignore rules
     → extension allowlist → [if .py] AST validation → include
```

**Directory pruning:** Ignored directories are removed from `dirnames` during walk to avoid descending into `node_modules/`, etc.

### 5.3 Token Engine

Two-tier divisor model:

- **Narrative text** (low symbol density): 1 token ≈ 3.9 characters
- **Dense code** (symbol density ≥ 2%): 1 token ≈ 3.4 characters

Budget lookup is substring-based on model name (case-insensitive).

### 5.4 Provider clients

| Provider | Transport | Streaming |
|----------|-----------|-----------|
| Ollama | `urllib.request` HTTP | NDJSON lines |
| Anthropic | `urllib.request` HTTP | SSE `content_block_delta` |
| OpenAI | `urllib.request` HTTP | SSE `delta.content` |
| Kiro ACP | `subprocess` + JSON-RPC stdio | `session/update` chunks |
| Kiro headless | `subprocess` stdout | post-run print |

All providers accumulate the full response string for telemetry.

---

## 6. Context Model

### Three-tier hierarchy

```text
┌─────────────────────────────────────────┐
│ Tier 1: Global (~/.config/memcon/)      │
│  persona, style, defaults               │
├─────────────────────────────────────────┤
│ Tier 2: Project (.memcon files)         │
│  upward walk PWD → /                    │
│  merged root-first                      │
├─────────────────────────────────────────┤
│ Tier 3: Workspace (--scan)              │
│  filtered file contents                 │
│  subject to token budget                │
└─────────────────────────────────────────┘
```

### Prompt assembly order

1. **System message:** Tier 1 + Tier 2
2. **User message (workspace):** Tier 3 file blocks (if any)
3. **User message (query):** Operator input

Anthropic receives the system content in a top-level `system` field; OpenAI and Ollama use a `system` role message; Kiro receives a flattened markdown prompt.

---

## 7. Compression Strategy

### Budget allocation

```text
max_budget = get_dynamic_budget(model)
baseline   = tokens(system_prompt) + tokens(user_input)
remaining  = max_budget - baseline
```

### Inclusion policy

Files sorted alphabetically by relative path. Each file included if its content token count ≤ remaining budget. Files that individually exceed remaining space are skipped (not truncated).

### Overflow recovery

If assembled total still exceeds budget (due to markdown wrapper overhead not counted per-file), remove the alphabetically last file and recompress until within budget or no files remain.

### Hard stop

If `baseline > max_budget`, the run aborts. User input is never truncated.

---

## 8. External Interfaces

### 8.1 Provider APIs

| Provider | Protocol | Auth |
|----------|----------|------|
| Ollama | HTTP `POST /api/chat` | None (local) |
| Anthropic | HTTPS `POST /v1/messages` | `ANTHROPIC_API_KEY` |
| OpenAI | HTTPS `POST /v1/chat/completions` | `OPENAI_API_KEY` |
| Kiro | subprocess `kiro-cli acp` or `chat` | login or `KIRO_API_KEY` |

### 8.2 Filesystem

| Path | Access | Purpose |
|------|--------|---------|
| `config.toml` (bundled or user) | R | App constants, provider defaults |
| `~/.config/memcon/global.json` | R/W | Global persona |
| `~/.config/memcon/history.json` | R/W | Session log |
| `.memcon` (ancestors) | R | Project context |
| `.memconignore` (PWD) | R | Scan filters |
| Workspace files | R | Scan input |

### 8.3 Environment

| Variable | Purpose |
|----------|---------|
| `MEMCON_PROVIDER` | Default backend |
| `OLLAMA_HOST` | Ollama base URL |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Cloud credentials |
| `KIRO_CLI_PATH` / `KIRO_API_KEY` | Kiro binary and headless key |

---

## 9. Storage Design

### global.json

- Created once on first run
- User-editable between runs
- Not modified by MemCon after creation

### history.json

- Append-only per session (rewrite with tail-50 truncation)
- Full prompt and response stored for audit
- No encryption at rest (local trust model)

---

## 10. Deployment Architecture

### Development

```text
Developer Machine
├── devbox (python, pytest, pyinstaller, gnupg, podman)
├── memcon.py + providers/ + config.toml
├── Makefile / build.sh
└── test_memcon.py
```

### Production (end user)

```text
User Machine
├── memcon (single binary; embeds config.toml + providers)
├── chosen backend (Ollama / API keys / kiro-cli)
└── ~/.config/memcon/ (global.json, history.json, optional config.toml)
```

### Build pipeline

```text
pytest → pyinstaller → tar.gz/zip → SHA-256 manifest → GPG sign
```

No server infrastructure. Distribution is file-based (archives + checksums).

---

## 11. Sequence Diagrams

### 11.1 Standard query with workspace scan

```text
Operator          MemCon              Workspace Engine       Compressor         Provider
   │                │                       │                   │                │
   │ memcon "..."   │                       │                   │                │
   │ ──────────────►│                       │                   │                │
   │                │ load global.json      │                   │                │
   │                │ find .memcon files    │                   │                │
   │                │                       │                   │                │
   │                │ scan (--scan)         │                   │                │
   │                │──────────────────────►│                   │                │
   │                │                       │ filter + AST      │                │
   │                │◄──────────────────────│ file dict         │                │
   │                │                       │                   │                │
   │                │ compress to budget    │                   │                │
   │                │──────────────────────────────────────────►│                │
   │                │◄──────────────────────────────────────────│ messages       │
   │                │                       │                   │                │
   │                │ stream_chat(provider)                     │                │
   │                │────────────────────────────────────────────────────────────►│
   │                │◄────────────────────────────────────────────────────────────│ chunks
   │◄───────────────│ stream to stdout      │                   │                │
   │                │ write history.json    │                   │                │
   │                │──┐                    │                   │                │
   │                │◄─┘                    │                   │                │
```

### 11.2 Context preview (--show-context)

Same as above through compression, then print to stdout and exit without calling a provider.

### 11.3 History query

```text
Operator          MemCon
   │                │
   │ --history      │
   │ ──────────────►│
   │                │ read history.json
   │◄───────────────│ print last 10 entries
```

---

## 12. Error Handling

| Failure | Behavior |
|---------|----------|
| Empty prompt | stderr message, exit 1 |
| Baseline > budget | stderr message, exit 1 |
| Provider unreachable / auth failure | `RuntimeError`, stderr → exit 1 |
| Missing API key | `RuntimeError` for cloud providers |
| kiro-cli not found | `RuntimeError` with install hint |
| Invalid Python file | stderr warning, file skipped |
| Unreadable file | silently skipped |
| Binary/non-text file | excluded by extension filter |
| Invalid global.json | JSON parse error (unhandled) |

Design choice: fail loud on operator errors (empty prompt, budget); degrade gracefully on per-file scan errors.

---

## 13. Security Design

### Trust boundaries

```text
┌──────────────────────────────────────────────┐
│  Operator's machine                          │
│  ┌─────────┐      ┌────────────────────────┐ │
│  │ MemCon  │─────►│ Provider (local/cloud) │ │
│  └────┬────┘      └────────────────────────┘ │
│       │ reads local files; may send over net  │
└───────┼──────────────────────────────────────┘
        ▼
   Filesystem (user permissions apply)
```

- Network calls to configured provider endpoints when not using local Ollama
- API keys via environment variables only
- History contains full prompts — sensitive data risk on shared machines
- `.memconignore` is the primary exfiltration prevention for `--scan`
- Release integrity via SHA-256 + optional GPG

---

## 14. Future Considerations

| Area | Potential enhancement |
|------|----------------------|
| Context | Multi-turn session files; Kiro session persistence across runs |
| Retrieval | Embedding-based file selection instead of full scan |
| Tokenization | Model-specific tokenizer instead of heuristic |
| Providers | Additional backends (Gemini, Azure OpenAI) |
| Integrations | IDE plugin, shell completion |
| Kiro | Expose `_kiro.dev/metadata` credits in history |
| Platforms | Native Windows build without Podman |
| Observability | Structured logging, metrics export |

These are not planned for v1.0 and are documented for architectural continuity only.
