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
from dbopt import templates, updater                   # noqa: E402

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

print()
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("ALL PASS  (test data dir: %s)" % _TMP)
