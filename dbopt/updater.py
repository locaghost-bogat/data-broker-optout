"""Broker-list updates: manual (on demand) and automatic (once a month).

The automatic path is driven by a launchd agent (see scripts/) that runs
`python3 -m dbopt.cli update` on the 1st of each month. Both paths funnel through
run_update() so behaviour is identical.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from datetime import date, datetime

from . import brokers, storage
from .models import Settings

UPDATE_LOG = "update.log"
USER_AGENT = "data-broker-optout/1.0 (+local privacy tool)"
TIMEOUT = 30


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


def is_due(settings: Settings, on: date | None = None) -> bool:
    on = on or date.today()
    last = _parse_date(settings["last_update_applied"]) or _parse_date(settings["last_update_check"])
    if last is None:
        return True
    interval = int(settings.get("update_interval_days", 30) or 30)
    return (on - last).days >= interval


def fetch_remote(url: str) -> dict:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def run_update(force: bool = False, source: str = "manual") -> dict:
    """Check cadence, fetch, validate, merge. Returns a result dict; never raises
    for expected conditions (offline, not due, no URL) -- those come back in the
    result so the caller/log can report them."""
    settings = Settings()
    settings["last_update_check"] = storage.now_iso()
    settings.save()

    result = {"source": source, "when": storage.now_iso(), "status": "", "detail": "", "summary": None}

    if not force and not is_due(settings):
        result["status"] = "skipped"
        result["detail"] = f"Not due yet (interval {settings.get('update_interval_days', 30)} days)."
        storage.log_line(UPDATE_LOG, f"{source}: {result['detail']}")
        return result

    url = (settings["update_source_url"] or "").strip()
    if not url:
        result["status"] = "no-source"
        result["detail"] = ("No update source URL configured. Using the bundled seed "
                            "list. Set one in Settings to enable remote updates.")
        # Still make sure the working copy exists from seed.
        brokers.load()
        settings["last_update_applied"] = storage.now_iso()
        settings["last_update_summary"] = result["detail"]
        settings.save()
        storage.log_line(UPDATE_LOG, f"{source}: {result['detail']}")
        return result

    try:
        payload = fetch_remote(url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ssl.SSLError, ValueError, OSError) as exc:
        result["status"] = "error"
        result["detail"] = f"Fetch failed: {exc}"
        storage.log_line(UPDATE_LOG, f"{source}: {result['detail']}")
        return result

    try:
        summary = brokers.merge(payload)
    except ValueError as exc:
        result["status"] = "error"
        result["detail"] = f"Rejected update: {exc}"
        storage.log_line(UPDATE_LOG, f"{source}: {result['detail']}")
        return result

    text = (f"added {summary['added']}, updated {summary['updated']}, "
            f"unchanged {summary['unchanged']}, kept local {summary['kept_local']}")
    result["status"] = "ok"
    result["detail"] = text
    result["summary"] = summary
    settings["last_update_applied"] = storage.now_iso()
    settings["last_update_summary"] = text
    settings.save()
    storage.log_line(UPDATE_LOG, f"{source}: OK -- {text} (from {url})")
    return result


def read_log(max_lines: int = 200) -> str:
    p = storage.path("logs") / UPDATE_LOG
    if not p.exists():
        return "(no updates logged yet)"
    lines = p.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[-max_lines:])
