#!/usr/bin/env python3
"""Mark the brokers from an Optery exposure scan as "has my info" in brokers.json.

Reads the 57 brokers shown in the screen recording (Optery dashboard, one per
page 1..57), matches them to the catalogue by domain / name, adds the handful
that are not in the catalogue, and stamps every matched entry with:

    "exposed": true
    "exposed_note": "<scan label>"

The app highlights `exposed` rows pink and floats them to the top of the Brokers
list. Run again after a catalogue rebuild to re-stamp (the builder also carries
the flags forward on its own).

    python3 tools/apply_exposure_scan.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BROKERS = REPO / "brokers.json"
SCAN_LABEL = "Optery scan 2026-09-03 - confirmed listing for Andrii Bogatyrov (Raleigh, NC)"

# (name, primary domain, best-effort opt-out URL).  "" opt-out -> use site root.
SCAN = [
    ("US Search", "ussearch.com", "https://www.ussearch.com/opt-out/submit/"),
    ("Intelius", "intelius.com", ""),
    ("Radaris", "radaris.com", ""),
    ("ZabaSearch", "zabasearch.com", "https://www.zabasearch.com/block_records/"),
    ("FastPeopleSearch", "fastpeoplesearch.com", ""),
    ("BeenVerified", "beenverified.com", ""),
    ("Whitepages", "whitepages.com", ""),
    ("ReversePhone", "reversephone.com", "https://www.reversephone.com/opt-out"),
    ("Lookup (scan entry 9 - logo unreadable)", "", ""),
    ("Addresses.com", "addresses.com", "https://www.addresses.com/optout.php"),
    ("Instant Checkmate", "instantcheckmate.com", ""),
    ("AdvancedBackgroundChecks", "advancedbackgroundchecks.com", ""),
    ("CyberBackgroundChecks", "cyberbackgroundchecks.com", "https://www.cyberbackgroundchecks.com/removal"),
    ("SmartBackgroundChecks", "smartbackgroundchecks.com", ""),
    ("TruthFinder", "truthfinder.com", ""),
    ("PeopleSmart", "peoplesmart.com", "https://www.peoplesmart.com/optout-signup"),
    ("NumberGuru", "numberguru.com", "https://www.numberguru.com/optout"),
    ("PrivateRecords", "privaterecords.net", ""),
    ("CourtCaseFinder", "courtcasefinder.com", "https://courtcasefinder.com/opt-out"),
    ("PeopleSearchUSA", "peoplesearchusa.org", "https://www.peoplesearchusa.org/opt_out"),
    ("InmatesSearcher", "inmatessearcher.com", "https://www.inmatessearcher.com/opt-out"),
    ("Public Record Reports", "publicrecordreports.com", "https://publicrecordreports.com/opt-out"),
    ("StateCourts", "statecourts.org", "https://statecourts.org/opt-out"),
    ("IDCrawl", "idcrawl.com", "https://www.idcrawl.com/opt-out"),
    ("North Carolina Court Records", "northcarolinacourtrecords.us", "https://northcarolinacourtrecords.us/opt-out"),
    ("Quick Public Records", "quickpublicrecords.com", "https://quickpublicrecords.com/opt-out"),
    ("MoneyBot5000", "moneybot5000.com", "https://moneybot5000.com/opt-out"),
    ("PropertyChecker", "propertychecker.com", "https://www.propertychecker.com/opt-out/"),
    ("CourtRecords.us", "courtrecords.us", "https://courtrecords.us/opt-out"),
    ("411.com", "411.com", "https://www.whitepages.com/suppression-requests"),
    ("CheckPeople", "checkpeople.com", ""),
    ("Phonebooks", "phonebooks.com", "https://www.phonebooks.com/optout.html"),
    ("USATrace", "usatrace.com", "https://www.usatrace.com/optout.php"),
    ("USPhoneBook", "usphonebook.com", ""),
    ("FamilyTreeNow", "familytreenow.com", ""),
    ("TruePeopleSearch", "truepeoplesearch.com", ""),
    ("Spokeo", "spokeo.com", ""),
    ("Quick People Trace", "quickpeopletrace.com", "https://www.quickpeopletrace.com/optout"),
    ("Wyty", "wyty.com", "https://wyty.com/remove"),
    ("SpyDialer", "spydialer.com", ""),
    ("USA People Search", "usa-people-search.com", ""),
    ("SealedRecords", "sealedrecords.net", "https://sealedrecords.net/opt-out"),
    ("VeriPages", "veripages.com", ""),
    ("NeighborWho", "neighborwho.com", ""),
    ("SearchQuarry", "searchquarry.com", "https://www.searchquarry.com/optout/"),
    ("FastBackgroundCheck", "fastbackgroundcheck.com", ""),
    ("SearchPeopleFree", "searchpeoplefree.com", ""),
    ("Ownerly", "ownerly.com", "https://www.ownerly.com/ccpa-optout/"),
    ("Social Catfish", "socialcatfish.com", "https://socialcatfish.com/opt-out/"),
    ("Checksecrets", "checksecrets.com", "https://checksecrets.com/opt-out"),
    ("PublicDataCheck", "publicdatacheck.com", ""),
    ("SpyFly", "spyfly.com", "https://www.spyfly.com/help-center/opt-out"),
    ("Public Information Services", "publicinfoservices.com", ""),
    ("PersonSearchers", "personsearchers.com", "https://personsearchers.com/opt-out"),
    ("Background Checkers", "backgroundcheckers.net", "https://www.backgroundcheckers.net/opt-out"),
    ("Search Public Records", "searchpublicrecords.com", ""),
    ("PeopleFinders", "peoplefinders.com", ""),
]

# scan name (normalised) -> catalogue id, for cases domain/name matching misses
MANUAL = {"peoplesmart": "peoplesmart", "411com": "whitepages"}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def domain(u: str) -> str:
    u = re.sub(r"^https?://", "", (u or "").lower()).split("/")[0]
    return re.sub(r"^www\.", "", u)


def main() -> int:
    data = json.loads(BROKERS.read_text(encoding="utf-8"))
    brokers = data["brokers"]
    by_id = {b["id"]: b for b in brokers}

    dom_idx: dict[str, str] = {}
    name_idx: dict[str, str] = {}
    for b in brokers:
        for u in (b.get("site"), b.get("opt_out_url")):
            dd = domain(u)
            if dd:
                dom_idx.setdefault(dd, b["id"])
        name_idx.setdefault(norm(b["name"]), b["id"])

    resolved: list[str] = []
    added = 0
    for name, dom, opturl in SCAN:
        if name.startswith("Lookup (scan entry 9"):
            continue  # can't identify -> skip rather than guess
        nid = MANUAL.get(norm(name)) or dom_idx.get(dom) or name_idx.get(norm(name))
        if not nid and dom:
            stem = dom.split(".")[0]
            nid = next((v for k, v in dom_idx.items() if k.split(".")[0] == stem), None)
        if not nid:
            nid = norm(name) or norm(dom)
            by_id[nid] = {
                "id": nid,
                "name": name,
                "category": "people-search",
                "site": f"https://{dom}" if dom else "",
                "opt_out_url": opturl or (f"https://{dom}" if dom else ""),
                "method": "form",
                "privacy_email": "",
                "privacy_phone": "",
                "mailing_address": "",
                "confirmation": "",
                "requires_id": False,
                "typical_completion_days": 14,
                "regions": ["US"],
                "law_basis": ["CCPA"],
                "instructions": ("Added from an Optery exposure scan. The opt-out URL is best-effort - "
                                 "confirm the current removal process on the site before submitting."),
                "last_verified": "2026-09-03",
                "source": "optery-scan",
            }
            brokers.append(by_id[nid])
            added += 1
        b = by_id[nid]
        b["exposed"] = True
        b["exposed_note"] = SCAN_LABEL
        resolved.append(nid)

    data["brokers"] = sorted(brokers, key=lambda x: x["name"].lower())
    data["exposure_scans"] = data.get("exposure_scans", {})
    data["exposure_scans"]["andrii-bogatyrov"] = {
        "label": SCAN_LABEL, "count": len(resolved), "broker_ids": sorted(set(resolved)),
    }
    BROKERS.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"resolved {len(resolved)} brokers  (+{added} newly added)  1 skipped (unidentified)")
    print(f"total catalogue now: {len(data['brokers'])}")
    print("exposed ids:", ", ".join(sorted(set(resolved))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
