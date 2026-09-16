"""Self-test: no third-party deps. Run with `python3 tests/test_core.py`."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Isolate all persistence in a throwaway dir.
_TMP = tempfile.mkdtemp(prefix="dbopt-test-")
os.environ["DBOPT_HOME"] = _TMP

from dbopt import brokers, storage                     # noqa: E402
from dbopt.engine import RequestStore, prepare_request, progress_for_profile  # noqa: E402
from dbopt.models import Address, MAX_PROFILES, Profile, ProfileStore, Settings  # noqa: E402
from dbopt import scanner, sendbot, templates, updater  # noqa: E402

failures = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


# --- storage / seed -------------------------------------------------------
cat = brokers.load()
check("seed catalogue loads", len(cat["brokers"]) >= 20)
check("every broker has required fields",
      all(all(b.get(f) for f in brokers.REQUIRED_FIELDS) for b in cat["brokers"]))

# --- profiles: max 5 ----------------------------------------------------
ps = ProfileStore()
for i in range(MAX_PROFILES):
    ps.add(Profile(first_name=f"P{i}", last_name="Test",
                   emails=[f"p{i}@example.com"],
                   addresses=[Address(city="Austin", state="TX")]))
check("stores 5 people", len(ProfileStore().profiles) == 5)
raised = False
try:
    ps.add(Profile(first_name="Six", last_name="Nope"))
except ValueError:
    raised = True
check("6th person rejected", raised)

person = ProfileStore().profiles[0]
ok, missing = person.is_complete_enough()
check("completeness check passes for filled profile", ok and not missing)

# --- request drafting (nothing sent) ----------------------------------
rs = RequestStore()
broker = brokers.list_brokers()[0]
res = prepare_request(rs, person, broker, Settings(),
                      open_browser=False, open_draft=False, law_basis="CCPA")
check("draft .eml written", os.path.exists(res["draft_path"]))
check("draft mentions the person", person.full_name in res["body"])
check("draft cites CCPA", "1798.105" in res["body"])
check("request moved to in_progress",
      rs.get(person.id, broker["id"])["status"] == "in_progress")

rs.set_status(person.id, broker["id"], "confirmed_removed")
prog = progress_for_profile(rs, person.id)
check("progress counts the removal", prog["removed"] == 1)

for law in ("CCPA", "GDPR", "US-STATE-GENERIC"):
    subj, body = templates.build(law, person, broker, Settings(), ["https://x/rec/1"])
    check(f"{law} template builds with listing url", "https://x/rec/1" in body and subj)

# --- updater merge ---------------------------------------------------
remote = {
    "list_version": "9999.99.99",
    "brokers": [
        {**broker, "privacy_phone": "1-555-CHANGED"},          # update existing
        {"id": "newbie", "name": "Newbie Data", "opt_out_url": "https://n/opt",
         "method": "form", "last_verified": "2026-09-02"},      # add new
    ],
}
summary = brokers.merge(remote)
check("merge added the new broker", summary["added"] == 1)
check("merge updated the existing broker", summary["updated"] == 1)
check("update applied to catalogue", brokers.get("newbie") is not None)
check("existing broker field refreshed",
      brokers.get(broker["id"])["privacy_phone"] == "1-555-CHANGED")

bad = False
try:
    brokers.validate_incoming({"brokers": [{"id": "x"}]})
except ValueError:
    bad = True
check("invalid update payload rejected", bad)

s = Settings()
s.update(last_update_applied=storage.now_iso(), update_interval_days=30)
check("update not due right after applying", not updater.is_due(s))

# --- Send Bot: queue, gating, retries, log (fake sender -- never touches Mail.app)
from datetime import datetime, timedelta  # noqa: E402

s.update(auto_send_enabled=False)
check("process_queue refuses unattended run when disabled",
      sendbot.process_queue(force=False)["status"] == "disabled")

s.update(auto_send_enabled=True, send_schedule_mode="interval",
        send_interval_minutes=30, send_last_run=None)
check("is_due() true when never run", sendbot.is_due(s))
s.update(send_last_run=datetime.now().isoformat(timespec="seconds"))
check("is_due() false right after running", not sendbot.is_due(s))
s.update(send_last_run=(datetime.now() - timedelta(minutes=31)).isoformat(timespec="seconds"))
check("is_due() true once the interval has elapsed", sendbot.is_due(s))

person2 = ProfileStore().profiles[1]
b_spokeo = brokers.get("spokeo")
b_acxiom = brokers.get("acxiom")
q = sendbot.SendQueue()
i1 = q.add(person2.id, b_spokeo["id"])
q.add(person2.id, b_spokeo["id"])  # duplicate add must not create a 2nd row
check("adding the same (person, broker) twice doesn't duplicate",
      len(q.pending()) == 1 and q.pending()[0]["id"] == i1["id"])
q.add(person2.id, b_acxiom["id"])
check("queue now has 2 distinct pending items", len(q.pending()) == 2)


def _fake_send(to, subject, body, frm):
    return (True, "ok") if "spokeo" in (to or "").lower() else (False, "simulated failure")


s.update(send_batch_size=5)
r = sendbot.process_queue(force=True, send_fn=_fake_send)
check("forced batch sends the good one and defers the bad one",
      r["sent"] == 1 and r["deferred"] == 1)
check("sent item's request record moved to submitted",
      RequestStore().get(person2.id, b_spokeo["id"])["status"] == "submitted")
for _ in range(2):
    sendbot.process_queue(force=True, send_fn=_fake_send)
q = sendbot.SendQueue()
statuses = {it["broker_id"]: it["status"] for it in q.all()}
check("after 3 failed attempts the item is marked failed (not retried forever)",
      statuses.get(b_acxiom["id"]) == "failed")
check("send log recorded both a success and a failure",
      {"sent", "failed"} <= {e["status"] for e in sendbot.read_log()})
check("send log entry carries the exact subject/body that was (attempted to be) sent",
      any(e["broker_id"] == b_spokeo["id"] and "1798.105" in e["body"] for e in sendbot.read_log()))

requeued = q.requeue(next(it["id"] for it in q.all() if it["status"] == "failed"))
check("requeue resets attempts and status", requeued["status"] == "queued" and requeued["attempts"] == 0)
removed = sendbot.SendQueue().clear_terminal()
check("clear_terminal drops the sent item, keeps the requeued one",
      removed == 1 and len(sendbot.SendQueue().pending()) == 1)

# A web-form-only broker (no privacy_email) must be skipped instantly -- not
# retried 3x -- and must not block a mailable item queued in the same batch.
_qclean = sendbot.SendQueue()
for _it in list(_qclean.all()):
    _qclean.remove(_it["id"])  # start this scenario from an empty queue
b_formonly = brokers.get("publicdatausa")
check("fixture broker really has no email on file", not b_formonly.get("privacy_email"))
q2 = sendbot.SendQueue()
q2.add(person2.id, b_formonly["id"])
q2.add(person2.id, b_spokeo["id"])
Settings().update(send_batch_size=1)
r = sendbot.process_queue(force=True, send_fn=_fake_send)
check("form-only broker skipped instantly, mailable one still sent in the same call",
      r["skipped"] == 1 and r["sent"] == 1)
statuses2 = {it["broker_id"]: it["status"] for it in sendbot.SendQueue().all()}
check("skipped item never consumed a retry attempt",
      next(it["attempts"] for it in sendbot.SendQueue().all()
          if it["broker_id"] == b_formonly["id"]) == 0)
check("skipped item's status is terminal ('skipped'), not left queued",
      statuses2.get(b_formonly["id"]) == "skipped")

# --- Scanner: confirmed-exposed brokers skip the live check; unconfirmed ones
# only send on a real 'match', never on 'blocked' (the common real-world case).
b_truthfinder = brokers.get("truthfinder")
b_checkpeople = brokers.get("checkpeople")
check("fixture brokers aren't pre-flagged exposed", not b_truthfinder.get("exposed") and not b_checkpeople.get("exposed"))


def _check_called(*_a, **_kw):
    raise AssertionError("check_fn must not be called for an already-exposed broker")


brokers.upsert({**b_truthfinder, "exposed": True, "exposed_note": "test fixture"})
res = scanner.run_scan(person2.id, [b_truthfinder["id"]], max_sends=5,
                       send_fn=lambda *a, **k: (True, "ok"), check_fn=_check_called)
check("already-exposed broker sends without ever calling the live checker",
      res["sent"] == 1 and res["checked"] == 1)

res = scanner.run_scan(person2.id, [b_checkpeople["id"]], max_sends=5,
                       send_fn=lambda *a, **k: (True, "ok"),
                       check_fn=lambda *a, **k: {"verdict": "blocked", "http_status": 403, "detail": "captcha"})
check("a 'blocked' live-check result never sends", res["sent"] == 0 and res["blocked"] == 1)
check("broker.get('exposed') stays false after a blocked check", not brokers.get(b_checkpeople["id"]).get("exposed"))

res = scanner.run_scan(person2.id, [b_checkpeople["id"]], max_sends=5,
                       send_fn=lambda *a, **k: (True, "ok"),
                       check_fn=lambda *a, **k: {"verdict": "match", "http_status": 200, "detail": "found the name"})
check("a real 'match' live-check result does send", res["sent"] == 1)
check("a live match gets remembered as exposed for next time",
      bool(brokers.get(b_checkpeople["id"]).get("exposed")))

res = scanner.run_scan(person2.id, [b_truthfinder["id"], b_checkpeople["id"]], max_sends=1,
                       send_fn=lambda *a, **k: (True, "ok"), check_fn=_check_called)
check("max_sends caps how many go out even when both are confirmed exposed", res["sent"] == 1)

from dbopt.models import Settings as _S  # noqa: E402
s3 = _S()
s3.update(scan_schedule_mode="off")
check("scanner is_due() false when schedule is off", not scanner.is_scan_due(s3))
s3.update(scan_schedule_mode="daily", scan_daily_time="00:00", scan_last_run=None)
check("scanner is_due() true for daily mode, never run", scanner.is_scan_due(s3))
s3.update(scan_schedule_mode="weekly", scan_weekday=(datetime.now().weekday() + 1) % 7, scan_last_run=None)
check("scanner is_due() false for weekly mode on the wrong weekday", not scanner.is_scan_due(s3))

print()
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("ALL PASS  (test data dir: %s)" % _TMP)
