"""Scanner: check whether a person's data shows up on a broker's site, and if
so, send the deletion request immediately -- on demand or on a schedule, for a
chosen person and a chosen set of brokers.

Two sources decide "does this broker have their data":

  1. Already-confirmed exposure -- broker["exposed"] is True, e.g. set by
     tools/apply_exposure_scan.py from a real scan (Optery, DeleteMe, etc.).
     This is the reliable source and is trusted without re-checking.

  2. A live, best-effort HTTP GET of the broker's own site, looking for the
     person's name in the response. In practice this fails on most
     people-search sites: they run CAPTCHA/Cloudflare bot-management that
     blocks a plain request immediately (verified against TruePeopleSearch,
     FastPeopleSearch, ThatsThem and USPhoneBook while building this - all
     four returned 403/CAPTCHA on the first try). So most live checks come
     back "blocked", not a real yes/no - that is logged honestly rather than
     guessed at, and nothing is sent for those. A genuine "match" only sends
     when the fetched page really contains the person's name.

Every check - match, no-match, blocked, or error - is written to the same
send log Send Bot uses (via sendbot.log_entry), tagged source="scan", so
"what did the scan find, and what did it send" is always answerable from one
place (Send Bot tab's log).
"""
from __future__ import annotations

import re
import ssl
import urllib.error
import urllib.request
from datetime import datetime

from . import brokers as brokers_mod
from . import engine, mailsend, templates
from .models import ProfileStore, Settings
from .sendbot import _parse_hhmm, log_entry  # shared cadence parsing + log

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 15

_BLOCK_MARKERS = ("captcha", "cloudflare", "access denied", "attention required",
                 "are you a robot", "unusual traffic", "verify you are human")
_NEGATIVE_MARKERS = ("no results", "0 results", "no records found", "no matches found",
                     "we could not find", "couldn't find any")


def _ssl_ctx() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def check_site(url: str, first_name: str, last_name: str) -> dict:
    """One best-effort GET. Returns {verdict, http_status, detail}.
    verdict is one of: 'match', 'no_match', 'blocked', 'error'."""
    if not url:
        return {"verdict": "error", "http_status": None, "detail": "No URL to check."}

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    status, body = None, ""
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_ctx()) as resp:
            status = resp.status
            body = resp.read(500_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            body = exc.read(500_000).decode("utf-8", "replace")
        except OSError:
            body = ""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"verdict": "error", "http_status": None, "detail": f"Could not reach the site: {exc}"}

    low = body.lower()
    if status in (403, 429) or any(m in low for m in _BLOCK_MARKERS):
        return {"verdict": "blocked", "http_status": status,
                "detail": ("The site blocked this automated check (CAPTCHA / bot protection). "
                          "Most people-search sites do this - it means 'can't tell', not 'no data'.")}

    fn, ln = (first_name or "").lower().strip(), (last_name or "").lower().strip()
    name_hit = bool(fn and ln and fn in low and ln in low)
    if name_hit:
        return {"verdict": "match", "http_status": status,
                "detail": f"Page loaded and contains \"{first_name} {last_name}\"."}
    if any(m in low for m in _NEGATIVE_MARKERS):
        return {"verdict": "no_match", "http_status": status, "detail": "Page loaded; site reports no results."}
    return {"verdict": "no_match", "http_status": status, "detail": "Page loaded; no name match found."}


def run_scan(profile_id: str, broker_ids: list[str], max_sends: int = 5,
            send_fn=None, check_fn=None) -> dict:
    """Check, and where confirmed, immediately send, for each broker id.

    Returns {"checked", "sent", "blocked", "no_match", "errors", "detail"}.
    send_fn / check_fn are injectable for tests (no real network / Mail calls).
    """
    settings = Settings()
    pstore = ProfileStore()
    rstore = engine.RequestStore()
    profile = pstore.get(profile_id)
    send = send_fn or mailsend.send_via_mail
    check = check_fn or check_site

    summary = {"checked": 0, "sent": 0, "blocked": 0, "no_match": 0, "errors": 0, "detail": ""}
    if not profile:
        summary["detail"] = "Person not found."
        return summary

    sent_count = 0
    for bid in broker_ids:
        broker = brokers_mod.get(bid)
        if not broker:
            continue
        summary["checked"] += 1
        already_confirmed = bool(broker.get("exposed"))

        if already_confirmed:
            result = {"verdict": "match", "http_status": None,
                     "detail": "Already confirmed exposed by a prior scan - skipped the live check."}
        else:
            result = check(broker.get("opt_out_url") or broker.get("site", ""),
                           profile.first_name, profile.last_name)

        will_send = (result["verdict"] == "match" and bool(broker.get("privacy_email"))
                    and sent_count < max_sends)

        if will_send:
            law = (broker.get("law_basis") or [settings["default_law_basis"]])[0]
            if law not in templates._BUILDERS:
                law = settings["default_law_basis"]
            rec = rstore.get(profile.id, broker["id"])
            subject, body = templates.build(law, profile, broker, settings, rec.get("listing_urls") or [])
            to_addr = broker.get("privacy_email") or ""
            from_addr = templates.contact_email(profile, settings, broker)
            eml_path, _, _ = engine.draft_eml(profile, broker, settings, rec.get("listing_urls"), law)

            ok, detail = send(to_addr, subject, body, from_addr)
            log_entry(profile_id=profile.id, profile_name=profile.display(),
                     broker_id=broker["id"], broker_name=broker.get("name", ""),
                     to=to_addr, from_addr=from_addr, subject=subject, body=body,
                     status="sent" if ok else "failed", error="" if ok else detail,
                     eml_path=eml_path, source="scan",
                     scan_verdict=result["verdict"], scan_detail=result["detail"])
            if ok:
                rstore.set_status(profile.id, broker["id"], "submitted", note="Auto-sent by Scanner")
                rstore.schedule_followup(profile.id, broker["id"],
                                         max(7, int(broker.get("typical_completion_days") or 14)))
                if not already_confirmed:
                    brokers_mod.mark_exposed(broker["id"], "Live scan match - " + result["detail"])
                summary["sent"] += 1
                sent_count += 1
            else:
                summary["errors"] += 1
        else:
            reason = result["detail"] if result["verdict"] != "match" else "Sends-per-run limit reached this run."
            log_entry(profile_id=profile.id, profile_name=profile.display(),
                     broker_id=broker["id"], broker_name=broker.get("name", ""),
                     to="", from_addr="", subject="", body="",
                     status="skipped", error=reason, eml_path="", source="scan",
                     scan_verdict=result["verdict"], scan_detail=result["detail"])
            if result["verdict"] == "blocked":
                summary["blocked"] += 1
            elif result["verdict"] == "error":
                summary["errors"] += 1
            else:
                summary["no_match"] += 1

    summary["detail"] = (f"checked {summary['checked']}, sent {summary['sent']}, "
                         f"blocked {summary['blocked']}, no match {summary['no_match']}, "
                         f"errors {summary['errors']}")
    return summary


def is_scan_due(settings: Settings, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    mode = settings["scan_schedule_mode"]
    if mode == "off":
        return False

    last_dt = None
    last = settings.get("scan_last_run")
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
        except ValueError:
            last_dt = None

    h, m = _parse_hhmm(settings.get("scan_daily_time") or "09:00")
    slot_today = now.replace(hour=h, minute=m, second=0, microsecond=0)

    if mode == "daily":
        if now < slot_today:
            return False
        return last_dt is None or last_dt < slot_today

    if mode == "weekly":
        if now.weekday() != int(settings.get("scan_weekday", 0) or 0):
            return False
        if now < slot_today:
            return False
        return last_dt is None or last_dt < slot_today

    return False
