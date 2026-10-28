#!/usr/bin/env bash
# Removes cfq-tunnel from ~/.local. Running services and their unit files are left alone.
set -e
rm -f "${HOME}/.local/bin/cfq-tunnel"
rm -rf "${HOME}/.local/share/cfq-tunnel"
echo "cfq-tunnel removed."
