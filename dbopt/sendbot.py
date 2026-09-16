"""Send Bot: a queue of (person, broker) deletion requests that actually get
sent -- through Mail.app via dbopt.mailsend -- on a schedule or a fixed
interval, instead of being left as drafts for the user to click Send on.

Nothing here runs unattended unless the user has explicitly turned on
"auto_send_enabled" (Send Bot tab) AND installed the background scheduler
(scripts/install-send-scheduler.sh, a launchd agent). The GUI's own
"Process queue now" button calls process_queue(force=True), which always
works (it *is* the human confirmation) but still only sends one batch per
click, so pacing still applies.

Every attempt - success or failure - is appended to the send log with the
exact subject/body/recipient, so "what did we actually send" is always
answerable from the Send Bot tab.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from . import brokers, engine, mailsend, storage, templates
from .models import ProfileStore, Settings

QUEUE_FILE = "send_queue.json"
LOG_FILE = "send_log.json"
MAX_ATTEMPTS = 3


class SendQueue:
    def __init__(self) -> None:
        self._items: list[dict] = storage.load_json(QUEUE_FILE, [])

    def save(self) -> None:
        storage.save_json(QUEUE_FILE, self._items)

    def all(self) -> list[dict]:
        return list(self._items)

    def pending(self) -> list[dict]:
        return [i for i in self._items if i["status"] == "queued"]

    def get(self, item_id: str) -> dict | None:
        return next((i for i in self._items if i["id"] == item_id), None)

    def add(self, profile_id: str, broker_id: str, law_basis: str = "") -> dict:
        for i in self._items:
            if i["profile_id"] == profile_id and i["broker_id"] == broker_id and i["status"] == "queued":
                return i  # already queued for this pair
        item = {
            "id": uuid.uuid4().hex[:12],
            "profile_id": profile_id,
            "broker_id": broker_id,
            "law_basis": law_basis,
            "status": "queued",     # queued | sent | failed | skipped
            "created_at": storage.now_iso(),
            "attempts": 0,
            "last_error": "",
            "sent_at": None,
        }
        self._items.append(item)
        self.save()
        return item

    def remove(self, item_id: str) -> None:
        self._items = [i for i in self._items if i["id"] != item_id]
        self.save()

    def clear_terminal(self) -> int:
        """Drop finished (sent/failed/skipped) items; keep only queued ones."""
        before = len(self._items)
        self._items = [i for i in self._items if i["status"] == "queued"]
        self.save()
        return before - len(self._items)

    def requeue(self, item_id: str) -> dict | None:
        it = self.get(item_id)
        if it:
            it["status"] = "queued"
            it["attempts"] = 0
            it["last_error"] = ""
            self.save()
        return it

    def mark(self, item_id: str, status: str, error: str = "") -> dict | None:
        it = self.get(item_id)
        if it:
            it["status"] = status
            it["last_error"] = error
            if status == "sent":
                it["sent_at"] = storage.now_iso()
            self.save()
        return it


def add_to_queue(profile_id: str, broker_id: str, law_basis: str = "") -> dict:
    return SendQueue().add(profile_id, broker_id, law_basis)


def log_entry(**fields) -> None:
    entries = storage.load_json(LOG_FILE, [])
    entries.append({"ts": storage.now_iso(), **fields})
    storage.save_json(LOG_FILE, entries[-2000:])


def read_log(limit: int = 300) -> list[dict]:
    entries = storage.load_json(LOG_FILE, [])
    return list(reversed(entries[-limit:]))


def _parse_hhmm(hhmm: str) -> tuple[int, int]:
    try:
        h, m = hhmm.split(":")
        return int(h), int(m)
    except (ValueError, AttributeError):
        return 10, 0


def is_due(settings: Settings, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    mode = settings["send_schedule_mode"]
    if mode == "off":
        return False

    last_dt = None
    last = settings.get("send_last_run")
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
        except ValueError:
            last_dt = None

    if mode == "interval":
        minutes = max(1, int(settings.get("send_interval_minutes") or 60))
        return last_dt is None or (now - last_dt) >= timedelta(minutes=minutes)

    if mode == "daily":
        h, m = _parse_hhmm(settings.get("send_daily_time") or "10:00")
        slot_today = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if now < slot_today:
            return False
        return last_dt is None or last_dt < slot_today

    return False


def process_queue(force: bool = False, now: datetime | None = None,
                   send_fn=None) -> dict:
    """Send up to `send_batch_size` due items. Returns a summary dict.

    force=True (the GUI button, or `cli process-queue --force`) skips the
    enabled/cadence gates for this one call but still caps to one batch.
    send_fn overrides the mail-sending call (used by tests).
    """
    settings = Settings()
    now = now or datetime.now()
    send = send_fn or mailsend.send_via_mail
    summary = {"status": "", "sent": 0, "failed": 0, "deferred": 0, "detail": ""}

    if not force:
        if not settings["auto_send_enabled"]:
            summary["status"] = "disabled"
            summary["detail"] = "Auto-send is off."
            return summary
        if not is_due(settings, now):
            summary["status"] = "not-due"
            summary["detail"] = "Not due yet per the schedule."
            return summary

    q = SendQueue()
    pending = q.pending()
    if not pending:
        settings.update(send_last_run=now.isoformat(timespec="seconds"))
        summary["status"] = "empty"
        summary["detail"] = "Queue is empty."
        return summary

    batch_size = max(1, int(settings.get("send_batch_size") or 1))
    batch = pending[:batch_size]
    pstore = ProfileStore()
    rstore = engine.RequestStore()

    for item in batch:
        profile = pstore.get(item["profile_id"])
        broker = brokers.get(item["broker_id"])
        if not profile or not broker:
            q.mark(item["id"], "skipped", "person or broker no longer exists")
            summary["failed"] += 1
            continue

        law = item.get("law_basis") or (broker.get("law_basis") or [settings["default_law_basis"]])[0]
        if law not in templates._BUILDERS:
            law = settings["default_law_basis"]
        rec = rstore.get(profile.id, broker["id"])
        subject, body = templates.build(law, profile, broker, settings, rec.get("listing_urls") or [])
        to_addr = broker.get("privacy_email") or ""
        from_addr = templates.contact_email(profile, settings, broker)

        # A durable record of exactly what was (attempted to be) sent.
        eml_path, _, _ = engine.draft_eml(profile, broker, settings, rec.get("listing_urls"), law)

        ok, detail = send(to_addr, subject, body, from_addr)
        item["attempts"] += 1

        log_entry(profile_id=profile.id, profile_name=profile.display(),
                  broker_id=broker["id"], broker_name=broker.get("name", ""),
                  to=to_addr, from_addr=from_addr, subject=subject, body=body,
                  status="sent" if ok else "failed", error="" if ok else detail,
                  eml_path=eml_path)

        if ok:
            q.mark(item["id"], "sent")
            rstore.set_status(profile.id, broker["id"], "submitted", note="Auto-sent by Send Bot")
            rstore.schedule_followup(profile.id, broker["id"],
                                     max(7, int(broker.get("typical_completion_days") or 14)))
            summary["sent"] += 1
        elif item["attempts"] >= MAX_ATTEMPTS:
            q.mark(item["id"], "failed", detail)
            summary["failed"] += 1
        else:
            item["last_error"] = detail
            q.save()
            summary["deferred"] += 1

    settings.update(send_last_run=now.isoformat(timespec="seconds"))
    summary["status"] = "ok"
    summary["detail"] = (f"sent {summary['sent']}, failed {summary['failed']}, "
                         f"retrying later {summary['deferred']}")
    return summary
