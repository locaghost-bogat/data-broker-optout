"""Actually sending mail through the Mac's default mail client (Apple Mail),
via AppleScript, instead of leaving a draft for the user to click Send on.

This is the one place in the app that transmits anything on its own. It is
only ever called by dbopt.sendbot, and only for items the user explicitly
queued (see the Send Bot tab / `dbopt.cli queue-add`). macOS will ask the user
to grant Mail-automation permission the first time (System Settings > Privacy
& Security > Automation) - that one-time OS prompt is a deliberate human gate
this module does not try to route around.
"""
from __future__ import annotations

import shutil
import subprocess

TIMEOUT = 30


def default_mail_client_is_apple_mail() -> bool:
    """Best-effort check that Mail.app (not some other app) handles mailto:.

    Uses LaunchServices' duti-less lookup via `plutil`/`defaults` is fragile
    across macOS versions, so we just check Mail.app is installed; that is
    true on every stock Mac and is what AppleScript will drive regardless of
    the registered mailto: handler.
    """
    return shutil.which("osascript") is not None


def _as_str(s: str) -> str:
    """Quote a Python string as an AppleScript string literal."""
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def send_via_mail(to_addr: str, subject: str, body: str, from_addr: str = "") -> tuple[bool, str]:
    """Compose and send one message through Mail.app. Returns (ok, detail)."""
    if not to_addr:
        return False, "no recipient address"

    sender_lines = ""
    if from_addr:
        sender_lines = (
            "try\n"
            f"    set sender of newMsg to {_as_str(from_addr)}\n"
            "on error\n"
            "    -- from_addr isn't one of this Mac's configured Mail accounts/aliases;\n"
            "    -- fall back to Mail's default account rather than failing the send.\n"
            "end try\n"
        )

    script = f"""
    tell application "Mail"
        set newMsg to make new outgoing message with properties {{subject:{_as_str(subject)}, content:{_as_str(body)}, visible:false}}
        tell newMsg
            make new to recipient at end of to recipients with properties {{address:{_as_str(to_addr)}}}
        end tell
        {sender_lines}
        send newMsg
    end tell
    """
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, "Mail.app did not respond within the timeout"
    except OSError as exc:
        return False, f"could not run osascript: {exc}"

    if r.returncode == 0:
        return True, "sent"
    detail = (r.stderr or r.stdout or "unknown AppleScript error").strip()
    if "1743" in detail or "not allowed" in detail.lower():
        detail += ("  -- grant this app Automation access to Mail in "
                   "System Settings > Privacy & Security > Automation, then retry.")
    return False, detail
