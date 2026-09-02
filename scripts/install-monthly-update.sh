#!/bin/bash
# Install the launchd agent that refreshes the data-broker catalogue once a month.
# Runs on the 1st of every month at 10:00 local time.
#
# Usage:  scripts/install-monthly-update.sh [DAY] [HOUR]
#   DAY  : day of month 1-28   (default 1)
#   HOUR : hour of day  0-23   (default 10)
set -euo pipefail

DAY="${1:-1}"
HOUR="${2:-10}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Prefer a python3 that has Tkinter (python.org / Homebrew); fall back to system.
PY="$(command -v python3 || echo /usr/bin/python3)"

cd "$HERE"
PYTHONPATH="$HERE" "$PY" -m dbopt.cli install-monthly --day "$DAY" --hour "$HOUR"

echo
echo "Verify with:  launchctl list | grep databrokeroptout"
echo "Run once now: PYTHONPATH=\"$HERE\" \"$PY\" -m dbopt.cli update --force"
