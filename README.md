# Local MemCon

Ambient memory manager and command-line proxy for local and cloud LLMs. MemCon assembles context from global and project-level config, optionally scans your workspace, and streams responses via **Ollama**, **Anthropic**, **OpenAI**, or **Kiro CLI**.

## Documentation

| Document | Description |
|----------|-------------|
| [User Guide](docs/USER_GUIDE.md) | Day-to-day usage, workflows, and configuration |
| [Deployment Guide](docs/DEPLOYMENT.md) | Building, installing, and verifying release binaries |
| [Specification](docs/SPEC.md) | Functional and technical requirements (v1.0) |
| [High-Level Design](docs/HLD.md) | Architecture, components, and data flow |

## Features

- **Layered context** — global persona (`~/.config/memcon/global.json`), project rules (`.memcon` files discovered upward from `PWD`), and optional workspace file scanning (`--scan`)
- **Smart filtering** — `.memconignore` support plus built-in exclusions for `node_modules/`, `.git/`, virtualenvs, and build artifacts
- **Python syntax pre-flight** — invalid `.py` files are skipped with a line-number warning before prompt assembly
- **Adaptive token budgets** — model-aware limits with automatic file dropping when context exceeds capacity
- **Session history** — last 50 runs stored in `~/.config/memcon/history.json`

## Prerequisites

- [devbox](https://www.jetify.com/devbox) for the development environment
- A configured LLM backend:
  - **Ollama** — local server at `http://localhost:11434`
  - **Anthropic** — `ANTHROPIC_API_KEY`
  - **OpenAI** — `OPENAI_API_KEY`
  - **Kiro CLI** — [kiro.dev](https://kiro.dev) with `kiro-cli auth login` or `KIRO_API_KEY`

### Provider selection

Set the active backend in `config.toml` (`use_ollama`, `use_paid`, `use_kiro`) or via CLI/env:

```bash
# Anthropic
export ANTHROPIC_API_KEY=sk-ant-...
memcon "Refactor auth" --scan --provider anthropic -m claude-sonnet-4-20250514

# OpenAI
export OPENAI_API_KEY=sk-...
memcon "Write tests" --scan --provider openai -m gpt-4o

# Ollama (default)
export OLLAMA_HOST=http://localhost:11434
memcon "Explain decorators" --provider ollama -m llama3

# Kiro CLI (ACP streaming)
kiro-cli auth login
memcon "Refactor auth module" --scan --provider kiro
```

| Variable | Effect |
|----------|--------|
| `MEMCON_PROVIDER` | Default provider (`ollama`, `anthropic`, `openai`, `kiro`) |
| `KIRO_CLI_PATH` | Path to `kiro-cli` binary |
| `KIRO_API_KEY` | API key for Kiro headless mode |
| `OLLAMA_HOST` | Ollama API base URL |
| `OPENAI_BASE_URL` | OpenAI-compatible API base (optional) |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |

## Quick start

```bash
cd memcon
devbox shell

# Run a prompt
python memcon.py "Explain this module" --scan

# Preview assembled context without calling a provider
python memcon.py "Refactor auth" --scan --show-context

# View recent sessions
python memcon.py --history
```

## CLI reference

```text
memcon [-h] [--provider PROVIDER] [--model MODEL] [--show-context] [--history] [--scan] [--version] [prompt_or_file]
```

| Flag | Description |
|------|-------------|
| `prompt_or_file` | Prompt text, or a file path whose contents become the prompt |
| `-p, --provider` | LLM backend: `ollama`, `anthropic`, `openai`, `kiro` |
| `-m, --model` | Model name (default from provider section in `config.toml`) |
| `-s, --show-context` | Print the assembled prompt and exit |
| `-hi, --history` | Show the last 10 session entries |
| `-sc, --scan` | Scan workspace files (up to 3 directory levels) |
| `-v, --version` | Print version and exit |

With no positional argument, memcon reads a multiline prompt from stdin until `Ctrl+D` (Unix) or `Ctrl+Z` (Windows).

### Model token budgets

Configured in `config.toml` under `[[budgets.rules]]`:

| Model pattern | Max tokens |
|---------------|------------|
| `claude-*`, `gpt-4*`, `kiro` | 128,000 |
| `*70b*` | 16,000 |
| `*32b*`, `*14b*` | 8,000 |
| `*8b*`, `*llama3*`, `*phi3*` | 4,000 |
| (default) | 4,000 |

## Configuration

### Application config (`config.toml`)

Runtime constants and defaults live in `config.toml` at the project root. Pick a default backend:

```toml
[provider]
use_ollama = true    # local Ollama
use_paid = false     # Anthropic or OpenAI
use_kiro = false     # Kiro CLI
paid_provider = "anthropic"  # when use_paid = true
```

Override paths:

| Variable | Effect |
|----------|--------|
| `MEMCON_PROVIDER` | Active LLM backend |
| `OLLAMA_HOST` | Ollama API base URL |
| `OPENAI_BASE_URL` | OpenAI API base URL |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Cloud provider credentials |
| `MEMCON_CONFIG_DIR` | User config directory (default: `~/.config/memcon`) |
| `MEMCON_CONFIG_FILE` | Path to an alternate `config.toml` |

A user-level override at `~/.config/memcon/config.toml` takes precedence over the bundled file when present.

### Global config

Created automatically on first run at `~/.config/memcon/global.json`:

```json
{
  "persona": "You are a helpful local coding assistant.",
  "style": "Be concise and precise.",
  "defaults": { "model": "llama3" }
}
```

### Project context

Add a `.memcon` file in any ancestor directory of your working tree. MemCon walks from `PWD` up to `/` and merges all discovered files into the system prompt.

### Workspace ignore rules

Create `.memconignore` in the project root using glob patterns and directory paths:

```text
*.log
secrets/
config/local.json
```

Scanned file types: `.py`, `.js`, `.ts`, `.jsx`, `.tsx`, `.go`, `.rs`, `.html`, `.css`, `.json`, `.md`, `.txt`, `.yml`, `.yaml`

## Development

Dependencies are managed through devbox (Python 3.12, pytest, pyinstaller, gnupg, podman, gnumake, zip, kiro-cli):

```bash
make help                                 # list targets and variables
make shell                                # enter devbox environment
make test                                 # run pytest suite
make build                                # run build pipeline
make run ARGS='"Explain this" --scan'      # uses config.toml provider flags
make run-anthropic ARGS='"Write tests" --scan'
make run-kiro ARGS='"Refactor auth" --scan'
make show-context ARGS='"prompt" --scan'   # preview without API call
```

Or use devbox directly:

```bash
devbox shell
devbox run test
devbox run build
make run-kiro ARGS='"Refactor auth" --scan'
devbox run help
```

Or run tests directly:

```bash
pytest -v test_memcon.py
```

### Build output

`build.sh` produces release artifacts under `releases/`:

```text
releases/
├── memcon-v1.0-host.tar.gz
├── memcon-v1.0-win64.zip      # requires Podman
├── SHASUMS256.txt
└── SHASUMS256.txt.sig         # requires GPG key
```

## Project layout

```text
memcon/
├── config.toml        # application constants and defaults
├── memcon.py          # CLI application
├── providers/         # ollama, anthropic, openai, kiro clients
├── test_memcon.py     # pytest suite
├── Makefile           # common dev/build targets
├── build.sh           # build and release pipeline
├── devbox.json        # dev environment
├── requirements.txt   # dependency reference (managed via devbox)
├── README.md
└── docs/
    ├── USER_GUIDE.md
    ├── DEPLOYMENT.md
    ├── SPEC.md
    └── HLD.md
```

## License

No license specified yet.
