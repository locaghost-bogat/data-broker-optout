#!/bin/bash
# Install the launchd agent that periodically checks the Send Bot queue and,
# if "Enable automatic sending" is on and the schedule says it's time, sends
# the next batch through Mail.app.
#
# Usage:  scripts/install-send-scheduler.sh [POLL_SECONDS]
#   POLL_SECONDS : how often launchd wakes the poller (default 300 = 5 min).
#                  The actual send cadence (interval/daily + batch size) is
#                  set on the app's Send Bot tab, not here.
set -euo pipefail

POLL="${1:-300}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$(command -v python3 || echo /usr/bin/python3)"

cd "$HERE"
PYTHONPATH="$HERE" "$PY" -m dbopt.cli install-send-scheduler --poll-seconds "$POLL"

echo
echo "Verify with:   launchctl list | grep databrokeroptout.sendbot"
echo "Run once now:  PYTHONPATH=\"$HERE\" \"$PY\" -m dbopt.cli process-queue --force"
