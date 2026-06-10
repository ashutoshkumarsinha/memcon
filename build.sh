#!/usr/bin/env bash
set -euo pipefail

VERSION="1.0"
RELEASE_DIR="releases"
HOST_ARCHIVE="memcon-v${VERSION}-host.tar.gz"
WIN_ARCHIVE="memcon-v${VERSION}-win64.zip"

echo "🛡️ Running automated pre-flight testing framework checks..."
if ! pytest -v test_memcon.py; then
    echo "🛑 Error: Unit tests failed. Halting the compilation matrix pipeline."
    exit 1
fi
echo "✅ Tests passed successfully! Moving to the compilation phase."

mkdir -p "${RELEASE_DIR}" dist build

echo "📦 Building native host binary..."
pyinstaller --onefile --name memcon memcon.py

echo "📦 Archiving host release..."
tar -czf "${RELEASE_DIR}/${HOST_ARCHIVE}" -C dist memcon

if command -v podman >/dev/null 2>&1; then
    echo "📦 Building Windows binary via Podman..."
    podman run --rm -v "$(pwd):/src" cdrx/pyinstaller-windows \
        "pyinstaller --onefile --name memcon /src/memcon.py" || true
    if [[ -f dist/memcon.exe ]]; then
        (cd dist && zip -q "../${RELEASE_DIR}/${WIN_ARCHIVE}" memcon.exe)
    fi
else
    echo "⚠️  Podman not found; skipping Windows cross-compile."
fi

echo "🔐 Generating SHA-256 manifest..."
python3 - <<'PY'
import hashlib
from pathlib import Path

release_dir = Path("releases")
lines = []
for path in sorted(release_dir.glob("memcon-v*")):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    lines.append(f"{digest}  {path.name}")

manifest = release_dir / "SHASUMS256.txt"
manifest.write_text("\n".join(lines) + ("\n" if lines else ""))
print(f"Wrote {manifest}")
PY

if command -v gpg >/dev/null 2>&1 && [[ -f "${RELEASE_DIR}/SHASUMS256.txt" ]]; then
    echo "🔏 Signing manifest..."
    gpg --detach-sign --armor -o "${RELEASE_DIR}/SHASUMS256.txt.sig" "${RELEASE_DIR}/SHASUMS256.txt" || true
fi

notify() {
    local msg="$1"
    if [[ "$(uname)" == "Darwin" ]] && command -v osascript >/dev/null 2>&1; then
        osascript -e "display notification \"${msg}\" with title \"memcon build\""
    elif command -v notify-send >/dev/null 2>&1; then
        notify-send "memcon build" "${msg}"
    fi
}

notify "Build complete: ${RELEASE_DIR}/"
echo "✅ Build pipeline finished. Artifacts in ${RELEASE_DIR}/"
