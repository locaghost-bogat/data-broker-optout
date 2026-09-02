"""Request lifecycle: prepare, track, follow up.

A "request" is one (person, broker) pair. The engine never transmits anything on
its own -- preparing a request writes a review-ready .eml draft and opens the
broker's opt-out page; the user sends / submits. Status is then tracked here.
"""
from __future__ import annotations

import subprocess
import urllib.parse
import uuid
import webbrowser
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime

from . import brokers, storage, templates
from .models import Profile, Settings

REQUESTS_FILE = "requests.json"

STATUSES = [
    "not_started",
    "in_progress",
    "submitted",
    "awaiting_confirmation",
    "confirmed_removed",
    "rejected",
    "needs_followup",
]

STATUS_LABEL = {
    "not_started": "Not started",
    "in_progress": "In progress",
    "submitted": "Submitted",
    "awaiting_confirmation": "Awaiting confirmation",
    "confirmed_removed": "Removed ✓",
    "rejected": "Rejected",
    "needs_followup": "Needs follow-up",
}

OPEN_STATUSES = {"not_started", "in_progress", "submitted", "awaiting_confirmation", "needs_followup", "rejected"}
DONE_STATUSES = {"confirmed_removed"}


def _key(profile_id: str, broker_id: str) -> str:
    return f"{profile_id}:{broker_id}"


class RequestStore:
    def __init__(self) -> None:
        self._data: dict[str, dict] = storage.load_json(REQUESTS_FILE, {})

    def save(self) -> None:
        storage.save_json(REQUESTS_FILE, self._data)

    def get(self, profile_id: str, broker_id: str) -> dict:
        k = _key(profile_id, broker_id)
        rec = self._data.get(k)
        if rec is None:
            rec = {
                "id": uuid.uuid4().hex[:12],
                "profile_id": profile_id,
                "broker_id": broker_id,
                "status": "not_started",
                "law_basis": "",
                "listing_urls": [],
                "created_at": storage.now_iso(),
                "updated_at": storage.now_iso(),
                "sent_at": None,
                "confirmed_at": None,
                "next_action_due": None,
                "last_draft_path": None,
                "notes": "",
                "history": [],
            }
            self._data[k] = rec
        return rec

    def all_for_profile(self, profile_id: str) -> dict[str, dict]:
        return {
            b["id"]: self.get(profile_id, b["id"])
            for b in brokers.list_brokers()
        }

    def set_status(self, profile_id: str, broker_id: str, status: str, note: str = "") -> dict:
        if status not in STATUSES:
            raise ValueError(status)
        rec = self.get(profile_id, broker_id)
        rec["status"] = status
        rec["updated_at"] = storage.now_iso()
        if status in ("submitted", "awaiting_confirmation") and not rec["sent_at"]:
            rec["sent_at"] = storage.now_iso()
        if status == "confirmed_removed":
            rec["confirmed_at"] = storage.now_iso()
            rec["next_action_due"] = None
        rec["history"].append({"ts": storage.now_iso(), "event": f"status -> {status}", "note": note})
        self.save()
        return rec

    def add_note(self, profile_id: str, broker_id: str, note: str) -> None:
        rec = self.get(profile_id, broker_id)
        rec["notes"] = (rec["notes"] + "\n" if rec["notes"] else "") + f"[{storage.today_iso()}] {note}"
        rec["history"].append({"ts": storage.now_iso(), "event": "note", "note": note})
        rec["updated_at"] = storage.now_iso()
        self.save()

    def set_listing_urls(self, profile_id: str, broker_id: str, urls: list[str]) -> None:
        rec = self.get(profile_id, broker_id)
        rec["listing_urls"] = [u.strip() for u in urls if u.strip()]
        rec["updated_at"] = storage.now_iso()
        self.save()

    def schedule_followup(self, profile_id: str, broker_id: str, days: int) -> None:
        rec = self.get(profile_id, broker_id)
        rec["next_action_due"] = (date.today() + timedelta(days=days)).isoformat()
        self.save()

    def due_followups(self) -> list[dict]:
        today = date.today().isoformat()
        return [
            r for r in self._data.values()
            if r.get("next_action_due") and r["next_action_due"] <= today
            and r["status"] in OPEN_STATUSES
        ]


# ---------------------------------------------------------------------------
def progress_for_profile(store: RequestStore, profile_id: str) -> dict:
    recs = store.all_for_profile(profile_id)
    total = len(recs)
    done = sum(1 for r in recs.values() if r["status"] in DONE_STATUSES)
    submitted = sum(1 for r in recs.values() if r["status"] in
                    {"submitted", "awaiting_confirmation", "needs_followup"})
    not_started = sum(1 for r in recs.values() if r["status"] == "not_started")
    return {
        "total": total, "removed": done, "in_flight": submitted,
        "not_started": not_started,
        "pct": round(100 * done / total) if total else 0,
    }


# ---------------------------------------------------------------------------
def draft_eml(profile: Profile, broker: dict, settings: Settings,
              listing_urls: list[str] | None = None,
              law_basis: str | None = None) -> tuple[str, str, str]:
    """Write a .eml draft to the outbox. Returns (path, subject, body).

    Nothing is sent. Opening the .eml (double-click / `open`) loads it into Mail
    as an editable message so the user can review and send it themselves.
    """
    law = law_basis or (broker.get("law_basis") or [settings["default_law_basis"]])[0]
    if law not in templates._BUILDERS:
        law = settings["default_law_basis"]
    subject, body = templates.build(law, profile, broker, settings, listing_urls or [])

    to_addr = broker.get("privacy_email") or ""
    msg = EmailMessage()
    msg["To"] = to_addr
    msg["Subject"] = subject
    if settings["reply_to_email"] or profile.emails:
        msg["From"] = settings["reply_to_email"] or profile.emails[0]
    msg["Date"] = format_datetime(datetime.now())
    msg["X-Unsent"] = "1"  # Apple Mail: open as an unsent draft
    msg.set_content(body)

    safe_broker = "".join(c for c in broker["id"] if c.isalnum() or c in "-_")
    fname = f"{profile.id}_{safe_broker}_{law}_{storage.today_iso()}.eml"
    path = storage.path("outbox") / fname
    path.write_bytes(bytes(msg))
    return str(path), subject, body


def mailto_link(broker: dict, subject: str, body: str) -> str:
    q = urllib.parse.urlencode({"subject": subject, "body": body}, quote_via=urllib.parse.quote)
    return f"mailto:{broker.get('privacy_email','')}?{q}"


def open_path(path: str) -> None:
    subprocess.run(["open", path], check=False)


def open_url(url: str) -> None:
    if url:
        webbrowser.open(url)


def prepare_request(store: RequestStore, profile: Profile, broker: dict, settings: Settings,
                    open_browser: bool = True, open_draft: bool = True,
                    law_basis: str | None = None) -> dict:
    """One-click: build the draft, optionally open the opt-out page + draft,
    and move the request to 'in_progress'."""
    rec = store.get(profile.id, broker["id"])
    path, subject, body = draft_eml(profile, broker, settings, rec.get("listing_urls"), law_basis)
    rec["last_draft_path"] = path
    rec["law_basis"] = law_basis or rec.get("law_basis") or ""
    rec["updated_at"] = storage.now_iso()
    rec["history"].append({"ts": storage.now_iso(), "event": "draft prepared", "note": path})
    if rec["status"] == "not_started":
        rec["status"] = "in_progress"
    store.save()

    if open_browser and broker.get("opt_out_url"):
        open_url(broker["opt_out_url"])
    if open_draft and broker.get("method", "").find("email") >= 0:
        open_path(path)
    return {"record": rec, "draft_path": path, "subject": subject, "body": body,
            "mailto": mailto_link(broker, subject, body)}
