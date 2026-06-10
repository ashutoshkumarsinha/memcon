# Local MemCon

Ambient memory manager and command-line proxy for [Ollama](https://ollama.com). MemCon sits between your shell and the local Ollama API, assembling context from global and project-level config, optionally scanning your workspace, and streaming responses while logging session history.

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

- [Ollama](https://ollama.com) running locally (default: `http://localhost:11434`)
- [devbox](https://www.jetify.com/devbox) for the development environment

Override the Ollama host with:

```bash
export OLLAMA_HOST=http://localhost:11434
```

## Quick start

```bash
cd memcon
devbox shell

# Run a prompt
python memcon.py "Explain this module" --scan

# Preview assembled context without calling Ollama
python memcon.py "Refactor auth" --scan --show-context

# View recent sessions
python memcon.py --history
```

## CLI reference

```text
memcon [-h] [--model MODEL] [--show-context] [--history] [--scan] [--version] [prompt_or_file]
```

| Flag | Description |
|------|-------------|
| `prompt_or_file` | Prompt text, or a file path whose contents become the prompt |
| `-m, --model` | Ollama model name (default: `llama3`) |
| `-s, --show-context` | Print the assembled prompt and exit |
| `-hi, --history` | Show the last 10 session entries |
| `-sc, --scan` | Scan workspace files (up to 3 directory levels) |
| `-v, --version` | Print version and exit |

With no positional argument, memcon reads a multiline prompt from stdin until `Ctrl+D` (Unix) or `Ctrl+Z` (Windows).

### Model token budgets

| Model pattern | Max tokens |
|---------------|------------|
| `*70b*` | 16,000 |
| `*32b*`, `*14b*` | 8,000 |
| `*8b*`, `*llama3*`, `*phi3*` | 4,000 |
| (default) | 4,000 |

## Configuration

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

Dependencies are managed through devbox (Python 3.12, pytest, pyinstaller, gnupg):

```bash
devbox shell          # enter environment
devbox run test       # run pytest suite
devbox run build      # run build pipeline (tests + pyinstaller + release archives)
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
├── memcon-v1.0-win64.zip      # requires Docker
├── SHASUMS256.txt
└── SHASUMS256.txt.sig         # requires GPG key
```

## Project layout

```text
memcon/
├── memcon.py          # CLI application
├── test_memcon.py     # pytest suite
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
