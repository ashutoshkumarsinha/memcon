# Local MemCon — Deployment Guide

This guide covers building release artifacts, distributing binaries, and installing MemCon on end-user machines.

---

## Table of Contents

1. [Deployment Overview](#deployment-overview)
2. [Prerequisites](#prerequisites)
3. [Building Release Artifacts](#building-release-artifacts)
4. [Verifying Release Integrity](#verifying-release-integrity)
5. [Installing on End-User Systems](#installing-on-end-user-systems)
6. [Runtime Dependencies](#runtime-dependencies)
7. [Environment Configuration](#environment-configuration)
8. [Upgrade and Rollback](#upgrade-and-rollback)
9. [Troubleshooting](#troubleshooting)

---

## Deployment Overview

MemCon ships as a single-file native binary produced by PyInstaller. The build pipeline:

1. Runs the pytest suite as a pre-flight gate
2. Compiles a host binary (Linux/macOS) via PyInstaller
3. Optionally cross-compiles a Windows binary via Docker
4. Archives artifacts into `releases/`
5. Generates a SHA-256 manifest and optional GPG signature

```text
releases/
├── memcon-v1.0-host.tar.gz
├── memcon-v1.0-win64.zip
├── SHASUMS256.txt
└── SHASUMS256.txt.sig
```

---

## Prerequisites

### Build machine

| Tool | Purpose |
|------|---------|
| [devbox](https://www.jetify.com/devbox) | Reproducible build environment |
| Python 3.12 | Source runtime (provided by devbox) |
| pytest | Pre-flight test gate |
| PyInstaller | Binary compilation |
| Docker (optional) | Windows cross-compile via `cdrx/pyinstaller-windows` |
| GnuPG (optional) | Manifest signing |

### Target machine (end user)

| Tool | Purpose |
|------|---------|
| Ollama | Local LLM inference server |
| At least one pulled model | e.g. `ollama pull llama3` |

MemCon has **no Python runtime dependency** on the target machine when deployed as a compiled binary.

---

## Building Release Artifacts

### Using devbox (recommended)

```bash
cd memcon
devbox run build
```

This invokes `build.sh`, which:

1. Runs `pytest -v test_memcon.py` — build halts on failure
2. Produces `dist/memcon` (native host binary)
3. Archives to `releases/memcon-v1.0-host.tar.gz`
4. Cross-compiles Windows binary if Docker is available
5. Writes `releases/SHASUMS256.txt`
6. Signs manifest if GPG is configured
7. Sends a desktop notification on macOS/Linux

### Manual build

```bash
devbox shell
pytest -v test_memcon.py
pyinstaller --onefile --name memcon memcon.py
tar -czf releases/memcon-v1.0-host.tar.gz -C dist memcon
```

### Windows cross-compile

Requires Docker:

```bash
docker run --rm -v "$(pwd):/src" cdrx/pyinstaller-windows \
  "pyinstaller --onefile --name memcon /src/memcon.py"
```

If successful, `dist/memcon.exe` is zipped into `releases/memcon-v1.0-win64.zip`.

---

## Verifying Release Integrity

### SHA-256 checksum

```bash
cd releases
shasum -a 256 -c SHASUMS256.txt
```

Expected output:

```text
memcon-v1.0-host.tar.gz: OK
memcon-v1.0-win64.zip: OK
```

### GPG signature (if published)

```bash
gpg --verify SHASUMS256.txt.sig SHASUMS256.txt
```

A valid signature confirms the manifest was signed by the release maintainer's key.

---

## Installing on End-User Systems

### macOS / Linux

```bash
tar -xzf memcon-v1.0-host.tar.gz
chmod +x memcon
sudo mv memcon /usr/local/bin/   # or ~/.local/bin
```

Verify:

```bash
memcon --version
# memcon v1.0
```

### Windows

1. Extract `memcon-v1.0-win64.zip`
2. Move `memcon.exe` to a directory on your `PATH` (e.g. `C:\Tools\memcon\`)
3. Add that directory to system `PATH` if needed

Verify in PowerShell or CMD:

```text
memcon --version
```

### Shell alias (optional)

Add to `~/.bashrc`, `~/.zshrc`, or equivalent:

```bash
alias mc='memcon --scan'
```

### First-run bootstrap

On first execution, MemCon auto-creates:

```text
~/.config/memcon/
├── global.json    # global persona and defaults
└── history.json   # created after first successful run
```

No manual configuration is required to start using the tool.

---

## Runtime Dependencies

### Ollama

Install and start Ollama from [ollama.com](https://ollama.com), then pull a model:

```bash
ollama pull llama3
ollama serve   # usually runs automatically as a service
```

Confirm the API is reachable:

```bash
curl http://localhost:11434/api/tags
```

### Network

MemCon communicates with Ollama over HTTP. Default endpoint:

```text
http://localhost:11434
```

For remote Ollama instances, set `OLLAMA_HOST` before running MemCon (see below).

---

## Environment Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama API base URL |

Examples:

```bash
# Remote Ollama server
export OLLAMA_HOST=http://192.168.1.50:11434
memcon "Summarize this repo" --scan

# Custom port
export OLLAMA_HOST=http://127.0.0.1:11435
```

Persist in shell profile for all sessions.

---

## Upgrade and Rollback

### Upgrade

1. Verify checksums of the new release archive
2. Replace the installed binary
3. Run `memcon --version` to confirm

User config at `~/.config/memcon/` is preserved across upgrades.

### Rollback

1. Reinstall the previous binary from a known-good archive
2. Verify with `memcon --version`
3. `history.json` and `global.json` remain compatible across v1.0.x releases

---

## Troubleshooting

| Symptom | Likely cause | Resolution |
|---------|--------------|------------|
| `Ollama request failed` | Ollama not running | Start Ollama; verify `curl $OLLAMA_HOST/api/tags` |
| `Baseline prompt exceeds model budget` | Prompt too large for model | Shorten input or use a larger model (`-m`) |
| Build fails at pytest | Code regression | Fix failing tests before releasing |
| Windows binary missing | Docker unavailable | Install Docker or distribute host-only build |
| GPG sign skipped | No key configured | Run `gpg --gen-key` or skip signing for internal builds |
| Permission denied on binary | Missing execute bit | `chmod +x memcon` |

### Logs and diagnostics

- Session history: `memcon --history`
- Context preview (no API call): `memcon "test" --scan --show-context`
- Ollama model list: `ollama list`

---

## Security Considerations

- MemCon reads files from the local filesystem when `--scan` is used. Review `.memconignore` before scanning sensitive projects.
- `history.json` stores full prompts and responses locally. Restrict file permissions on shared machines:

  ```bash
  chmod 600 ~/.config/memcon/history.json
  ```

- Verify release checksums and GPG signatures before installing binaries from external sources.
