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

MemCon is a **stateless, single-process CLI middleware** that transforms a shell invocation into a structured Ollama chat request. It does not maintain conversational state between runs; instead, it reconstructs context deterministically from filesystem configuration on every invocation.

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
│                           │ Ollama Client (HTTP stream)       │  │
│                           └─────────────────────────┬──────────┘  │
│                                                     │              │
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
| **Local-first** | All data stays on the operator's machine |

---

## 3. Component Architecture

### 3.1 Component map

```text
memcon.py
├── CLI Router           parse_args(), main()
├── Config Loader        load_global_config(), find_memcon_files()
├── Context Assembler    build_system_prompt(), read_memcon_context()
├── Workspace Engine     scan_workspace(), is_ignored(), check_syntax_validity()
├── Token Engine         calculate_precise_tokens(), get_dynamic_budget()
├── Compressor           compress_files_to_budget(), apply_budget_compression()
├── Payload Builder      assemble_payload()
├── Ollama Client        stream_ollama_chat()
└── Telemetry            append_history(), show_history()
```

### 3.2 Component responsibilities

| Component | Responsibility |
|-----------|----------------|
| **CLI Router** | Parse flags, dispatch to history/version/show-context or main pipeline |
| **Config Loader** | Bootstrap `global.json`, discover `.memcon` hierarchy |
| **Context Assembler** | Merge global persona + project rules into system prompt |
| **Workspace Engine** | Walk directory tree, filter, validate Python syntax |
| **Token Engine** | Heuristic token counting and model budget lookup |
| **Compressor** | Fit workspace files within remaining token budget |
| **Payload Builder** | Construct Ollama message array (system + workspace + user) |
| **Ollama Client** | HTTP streaming to `/api/chat` |
| **Telemetry** | Append/read session history |

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
            │ Ollama /api/chat    │
            │ (stream)            │
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
| Payload | `list[dict]` (Ollama messages) |
| Response | `str` (accumulated stream) |

---

## 5. Module Design

### 5.1 CLI Router

**Entry:** `main(argv)`

**Routing logic:**

```text
--version  → print version, exit 0
--history  → show_history(), exit 0
(default)  → resolve input → pipeline → Ollama or --show-context
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

### 5.4 Ollama Client

- Transport: `urllib.request` (stdlib)
- Mode: streaming (`stream: true`)
- Output: incremental stdout flush
- Accumulation: full response string returned for telemetry

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

This separation keeps project rules in the system role and code in a distinct user turn, matching Ollama chat conventions.

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

### 8.1 Ollama REST API

| Property | Value |
|----------|-------|
| Protocol | HTTP |
| Endpoint | `POST /api/chat` |
| Auth | None (local trust boundary) |
| Timeout | 600s |

### 8.2 Filesystem

| Path | Access | Purpose |
|------|--------|---------|
| `~/.config/memcon/global.json` | R/W | Global persona |
| `~/.config/memcon/history.json` | R/W | Session log |
| `.memcon` (ancestors) | R | Project context |
| `.memconignore` (PWD) | R | Scan filters |
| Workspace files | R | Scan input |

### 8.3 Environment

| Variable | Default |
|----------|---------|
| `OLLAMA_HOST` | `http://localhost:11434` |

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
├── devbox (Nix packages: python, pytest, pyinstaller, gnupg)
├── memcon.py (source)
└── test_memcon.py
```

### Production (end user)

```text
User Machine
├── memcon (single binary, no Python required)
├── Ollama (system service)
└── ~/.config/memcon/ (runtime state)
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
Operator          MemCon              Workspace Engine       Compressor         Ollama
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
   │                │ POST /api/chat (stream)                   │                │
   │                │────────────────────────────────────────────────────────────►│
   │                │◄────────────────────────────────────────────────────────────│ chunks
   │◄───────────────│ stream to stdout      │                   │                │
   │                │ write history.json    │                   │                │
   │                │──┐                    │                   │                │
   │                │◄─┘                    │                   │                │
```

### 11.2 Context preview (--show-context)

Same as above through compression, then print to stdout and exit without calling Ollama.

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
| Ollama unreachable | `RuntimeError`, unhandled → exit 1 |
| Invalid Python file | stderr warning, file skipped |
| Unreadable file | silently skipped |
| Binary/non-text file | excluded by extension filter |
| Invalid global.json | JSON parse error (unhandled) |

Design choice: fail loud on operator errors (empty prompt, budget); degrade gracefully on per-file scan errors.

---

## 13. Security Design

### Trust boundaries

```text
┌─────────────────────────────────────┐
│  Operator's local machine (trusted) │
│  ┌─────────┐      ┌──────────────┐  │
│  │ MemCon  │─────►│ Ollama       │  │
│  └────┬────┘      └──────────────┘  │
│       │ reads local files only      │
└───────┼─────────────────────────────┘
        ▼
   Filesystem (user permissions apply)
```

- No network calls except to configured `OLLAMA_HOST`
- No credential storage
- History contains full prompts — sensitive data risk on shared machines
- `.memconignore` is the primary exfiltration prevention for `--scan`
- Release integrity via SHA-256 + optional GPG

---

## 14. Future Considerations

| Area | Potential enhancement |
|------|----------------------|
| Context | Multi-turn session files |
| Retrieval | Embedding-based file selection instead of full scan |
| Tokenization | Model-specific tokenizer instead of heuristic |
| Integrations | IDE plugin, shell completion |
| Config | Schema validation for `global.json` |
| Platforms | Native Windows build without Docker |
| Observability | Structured logging, metrics export |

These are not planned for v1.0 and are documented for architectural continuity only.
