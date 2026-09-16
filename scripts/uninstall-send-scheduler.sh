#!/bin/bash
# Remove the Send Bot's launchd poller.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$(command -v python3 || echo /usr/bin/python3)"
cd "$HERE"
PYTHONPATH="$HERE" "$PY" -m dbopt.cli uninstall-send-scheduler
