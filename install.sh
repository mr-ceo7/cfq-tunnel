#!/usr/bin/env bash
# ==============================================================================
# cfq-tunnel installer
# Installs cfq-tunnel into ~/.local/bin/cfq-tunnel
# ==============================================================================

set -e

REPO="https://github.com/mr-ceo7/cfq-tunnel"
SHARE_DIR="${HOME}/.local/share/cfq-tunnel"
TARGET_DIR="${HOME}/.local/bin"
TARGET_BIN="${TARGET_DIR}/cfq-tunnel"

echo "=== Installing cfq-tunnel ==="

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: Python 3.8+ is required but not installed." >&2
    exit 1
fi

mkdir -p "${TARGET_DIR}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
if [ -f "${SCRIPT_DIR}/cfq-tunnel" ] && [ -d "${SCRIPT_DIR}/cfq_tunnel" ]; then
    SOURCE="${SCRIPT_DIR}"
    echo "Installing from local repository (${SOURCE})..."
else
    echo "Downloading cfq-tunnel from GitHub..."
    TMP="$(mktemp -d)"
    trap 'rm -rf "${TMP}"' EXIT
    if command -v git >/dev/null 2>&1; then
        git clone --quiet --depth 1 "${REPO}.git" "${TMP}/cfq-tunnel"
    else
        curl -fsSL "${REPO}/archive/refs/heads/main.tar.gz" | tar -xz -C "${TMP}"
        mv "${TMP}/cfq-tunnel-main" "${TMP}/cfq-tunnel"
    fi
    SOURCE="${TMP}/cfq-tunnel"
fi

rm -rf "${SHARE_DIR}"
mkdir -p "${SHARE_DIR}"
cp -R "${SOURCE}/cfq_tunnel" "${SOURCE}/cfq-tunnel" "${SHARE_DIR}/"
chmod +x "${SHARE_DIR}/cfq-tunnel"
ln -sf "${SHARE_DIR}/cfq-tunnel" "${TARGET_BIN}"

echo "Installed: ${TARGET_BIN}"
if ! command -v cloudflared >/dev/null 2>&1; then
    echo "Note: cloudflared is not on your PATH. Install it from"
    echo "      https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
fi
case ":${PATH}:" in
    *":${TARGET_DIR}:"*) ;;
    *) echo "Note: add ${TARGET_DIR} to your PATH to run cfq-tunnel directly." ;;
esac
echo "Try: cfq-tunnel run --url http://127.0.0.1:8000"
