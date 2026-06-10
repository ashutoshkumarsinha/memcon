# Local MemCon — User Guide

A practical guide for day-to-day use of MemCon as a shell-integrated assistant for local Ollama models.

---

## Table of Contents

1. [What MemCon Does](#what-memcon-does)
2. [Getting Started](#getting-started)
3. [Basic Usage](#basic-usage)
4. [Context Layers](#context-layers)
5. [Workspace Scanning](#workspace-scanning)
6. [Filtering with .memconignore](#filtering-with-memconignore)
7. [Choosing a Model](#choosing-a-model)
8. [Inspecting Context](#inspecting-context)
9. [Session History](#session-history)
10. [Workflow Examples](#workflow-examples)
11. [Tips and Limitations](#tips-and-limitations)

---

## What MemCon Does

MemCon eliminates repeated manual context setup across shell sessions. Instead of pasting system prompts, style guides, and file contents every time you talk to a local model, MemCon:

1. Loads your global persona automatically
2. Discovers project-specific rules from `.memcon` files
3. Optionally bundles workspace source files into the prompt
4. Fits everything within your model's token budget
5. Streams the response from Ollama
6. Logs the session for later review

MemCon is **not** a persistent chat UI. Each invocation builds a fresh, optimized prompt for a single query.

---

## Getting Started

### 1. Install Ollama and pull a model

```bash
ollama pull llama3
```

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
```

On first run, MemCon creates `~/.config/memcon/global.json` with default persona settings.

---

## Basic Usage

```text
memcon [-h] [--model MODEL] [--show-context] [--history] [--scan] [--version] [prompt_or_file]
```

### Prompt as text

```bash
memcon "Write unit tests for the auth module"
```

### Prompt from a file

```bash
memcon prompts/refactor-brief.md
```

The file contents become the user message.

### Multiline input (no argument)

```bash
memcon
```

Type or paste your prompt, then press `Ctrl+D` (macOS/Linux) or `Ctrl+Z` then Enter (Windows).

### Common flags

| Flag | Short | Effect |
|------|-------|--------|
| `--model` | `-m` | Set Ollama model (default: `llama3`) |
| `--scan` | `-sc` | Include workspace files in context |
| `--show-context` | `-s` | Print assembled prompt; do not call Ollama |
| `--history` | `-hi` | Show last 10 sessions |
| `--version` | `-v` | Print version |

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

Edit this file to set your default voice and preferences across all projects.

### Tier 2 — Project context

**File:** `.memcon` in any ancestor directory

Place a `.memcon` file in your repo root (or a parent directory):

```text
# .memcon
This project uses FastAPI with SQLAlchemy 2.0.
Follow PEP 8. All new endpoints require OpenAPI annotations.
Database migrations live in alembic/versions/.
```

MemCon walks from your current directory up to `/` and merges every `.memcon` file found, root-first.

### Tier 3 — Workspace files (optional)

Activated with `--scan`. See [Workspace Scanning](#workspace-scanning).

---

## Workspace Scanning

Use `--scan` when you want the model to see actual source files:

```bash
cd ~/projects/my-api
memcon "Find potential SQL injection risks" --scan
```

### Scan behavior

- Traverses up to **3 directory levels** from the current working directory
- Reads only permitted text/code extensions (`.py`, `.js`, `.ts`, `.go`, `.rs`, `.md`, etc.)
- Skips directories like `node_modules/`, `.git/`, `venv/` automatically
- Validates Python files with `ast.parse` before inclusion; broken files are skipped with a warning
- Drops files if total context exceeds the model token budget (alphabetically last files removed first)

### When to use `--scan`

| Scenario | Use `--scan`? |
|----------|---------------|
| General question, no code context needed | No |
| Code review, refactoring, test generation | Yes |
| Large monorepo | Yes, but add `.memconignore` rules |
| Sensitive repo with secrets | Only after configuring `.memconignore` |

---

## Filtering with .memconignore

Create `.memconignore` in your project root to exclude files from scanning:

```text
# Secrets and credentials
secrets/
*.env
config/local.json

# Generated output
*.log
coverage/
```

### Syntax

| Pattern | Matches |
|---------|---------|
| `*.log` | Files by glob |
| `secrets/` | Everything under `secrets/` |
| `config/local.json` | Specific file path |

Lines starting with `#` are comments.

### Always excluded (no config needed)

`.git/`, `node_modules/`, `__pycache__/`, `.venv/`, `venv/`, `dist/`, `build/`, `.memcon`, `.memconignore`, `.DS_Store`

---

## Choosing a Model

```bash
memcon "Explain this function" --scan -m qwen2.5:14b
```

MemCon adjusts the context token budget based on the model name:

| Model pattern | Token budget |
|---------------|--------------|
| Contains `70b` | 16,000 |
| Contains `32b` or `14b` | 8,000 |
| Contains `8b`, `llama3`, or `phi3` | 4,000 |
| Unknown models | 4,000 (safe default) |

Larger models accept more workspace files before compression kicks in.

List available models:

```bash
ollama list
```

---

## Inspecting Context

Before sending an expensive or sensitive prompt, preview what MemCon will send:

```bash
memcon "Refactor the payment service" --scan --show-context
```

Output sections:

```text
=== System Prompt ===
(your persona + .memcon context)

=== Workspace Context ===
(scanned file contents, if any fit the budget)

=== User Input ===
(your prompt)
```

No request is sent to Ollama in this mode.

---

## Session History

MemCon logs every completed run to `~/.config/memcon/history.json` (last 50 sessions retained).

View recent sessions:

```bash
memcon --history
```

Example output:

```text
1. [2026-06-09T14:32:01+00:00] model=llama3 cwd=/home/user/my-api
   prompt: 'Find potential SQL injection risks'

2. [2026-06-09T14:28:15+00:00] model=llama3 cwd=/home/user/my-api
   prompt: 'Write unit tests for auth.py'
```

Each entry stores the full system prompt, workspace context, user input, and model response. Use this for auditing what was sent to the model.

---

## Workflow Examples

### Code review

```bash
cd ~/projects/web-app
memcon "Review src/auth/login.ts for security issues" --scan -m llama3
```

### Generate tests from a spec file

```bash
memcon test-spec.md --scan -m codestral
```

### Project onboarding

Create `.memcon` in the repo:

```text
# .memcon
Monorepo layout:
- apps/api/     REST API (Python/FastAPI)
- apps/web/     React frontend
- packages/core/ shared types
```

Then ask:

```bash
memcon "Where should I add a new webhook endpoint?" --scan
```

### Quick question without code context

```bash
memcon "Difference between asyncio.gather and TaskGroup?"
```

### Debug context budget issues

```bash
memcon "long prompt here..." --scan --show-context
```

If workspace files are missing from the output, the token budget forced them to be dropped. Use a larger model or shorten your prompt.

---

## Tips and Limitations

### Tips

- Put stable project conventions in `.memcon`; put personal preferences in `global.json`
- Always run `--show-context` once when setting up a new project's `.memconignore`
- Use `-m` to match model size to task complexity and context needs
- Pipe output to a file: `memcon "..." --scan > response.txt` captures only stdout (streaming prints live)

### Limitations

- **Single-turn only** — no multi-turn conversation memory between invocations
- **Scan depth** — files more than 3 directories deep are not included
- **Token estimation** — uses a heuristic, not a tokenizer; actual model usage may differ
- **Python-only syntax check** — other languages are included without AST validation
- **Local only** — requires a running Ollama instance; no cloud fallback

### Error messages

| Message | Meaning |
|---------|---------|
| `Error: empty prompt.` | No text provided |
| `Baseline prompt exceeds model budget` | Your prompt + system context is too large; shorten input or use a bigger model |
| `Ollama request failed` | Cannot reach Ollama; check that the service is running |

For deployment and installation details, see [DEPLOYMENT.md](DEPLOYMENT.md).
