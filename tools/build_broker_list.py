#!/usr/bin/env python3
"""Build a `brokers.json` for the Data Broker Opt-Out app from external sources.

Currently merges:
  * the app's own curated seed list  (data/brokers.seed.json)  -- authoritative
  * brianreumere/data-brokers        (per-broker YAML + joins/fronts.yml)

The seed list always wins on curated fields (privacy email/phone, mailing
address, hand-written instructions, verified opt-out URL). The external source
only ADDS brokers the seed does not have, and annotates existing ones when the
community list reports an opt-out as broken.

Output validates against dbopt.brokers.validate_incoming, so the file it writes
is guaranteed to be accepted by the app's updater.

Usage:
    python3 tools/build_broker_list.py                 # -> ./brokers.json
    python3 tools/build_broker_list.py -o public/brokers.json
    python3 tools/build_broker_list.py --src-dir /path/to/data-brokers  # no clone

Requires PyYAML (see tools/requirements.txt).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    sys.exit("PyYAML is required:  python3 -m pip install --user PyYAML")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SEED = REPO_ROOT / "data" / "brokers.seed.json"
DEFAULT_OUT = REPO_ROOT / "brokers.json"
SOURCE_REPO = "https://github.com/brianreumere/data-brokers"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

PROCESS_DESC = {
    "opt-out-search": "Use the broker's removal/opt-out search directly, then request removal of each result.",
    "search-for-removal": "Use the broker's removal/opt-out search directly, then request removal of each result.",
    "search-first": "Search the main site for your listing first, then submit its URL on the opt-out page.",
    "search-then-opt-out": "Search the main site for your listing first, then submit its URL on the opt-out page.",
    "control": "Search for the profile that matches your data, then use the 'control this profile' flow to request removal.",
    "search-then-control": "Search for the profile that matches your data, then use the 'control this profile' flow to request removal.",
}


def norm_id(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def prettify_key(key: str) -> str:
    s = re.sub(r"[_-]+", " ", key)
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    return s.strip().title()


def method_for(process: str | None, removal_url: str | None, blob: str) -> str:
    if process and "control" in process:
        return "account"
    if not removal_url and EMAIL_RE.search(blob):
        return "email"
    return "form"


def load_source(src_dir: Path) -> tuple[dict, dict]:
    data_dir = src_dir / "data"
    if not data_dir.is_dir():
        sys.exit(f"no 'data/' dir under {src_dir}")
    brokers: dict[str, dict] = {}
    for f in sorted(data_dir.glob("*.y*ml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for key, val in doc.items():
            if isinstance(val, dict):
                brokers[key] = val
    fronts = {}
    fpath = src_dir / "joins" / "fronts.yml"
    if fpath.is_file():
        fronts = yaml.safe_load(fpath.read_text(encoding="utf-8")) or {}
    return brokers, fronts


def convert_one(key: str, d: dict, today: str) -> dict:
    name = (d.get("names") or [prettify_key(key)])[0]
    url = d.get("url") or ""
    removal = d.get("removalUrl") or ""
    process = d.get("process")

    notes = d.get("notes") or []
    note_text = " ".join(n.get("note", "") for n in notes if isinstance(n, dict))
    status = d.get("status") or {}
    workaround = status.get("workaround") or d.get("help") or ""
    blob = " ".join([note_text, workaround])

    instr_parts = []
    if process in PROCESS_DESC:
        instr_parts.append(PROCESS_DESC[process])
    if status.get("working") is False:
        as_of = status.get("asOf") or "recently"
        instr_parts.append(f"COMMUNITY LIST: this opt-out was reported NOT working as of {as_of}.")
    if workaround:
        instr_parts.append("Workaround: " + " ".join(str(workaround).split()))
    if note_text:
        instr_parts.append("Note: " + " ".join(note_text.split()))
    for hl in d.get("helpLinks") or []:
        if isinstance(hl, dict) and hl.get("url"):
            instr_parts.append(f"Guide ({hl.get('site','link')}): {hl['url']}")

    emails = EMAIL_RE.findall(blob)
    method = method_for(process, removal, blob)

    as_of = status.get("asOf")
    last_verified = str(as_of) if as_of else today

    return {
        "id": norm_id(key) or norm_id(name),
        "name": name,
        "category": "people-search",
        "site": url,
        "opt_out_url": removal or url,
        "method": method,
        "privacy_email": emails[0] if emails else "",
        "privacy_phone": "",
        "mailing_address": "",
        "confirmation": "",
        "requires_id": False,
        "typical_completion_days": 0,
        "regions": ["US"],
        "law_basis": ["CCPA"],
        "instructions": "  ".join(instr_parts) or "See the broker's privacy / opt-out page for the current process.",
        "last_verified": last_verified,
        "source": "brianreumere",
    }


def build(seed_path: Path, src_dir: Path) -> tuple[dict, dict]:
    today = dt.date.today().isoformat()
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    out_brokers: dict[str, dict] = {norm_id(b["id"]): dict(b) for b in seed.get("brokers", [])}
    seed_ids = set(out_brokers)

    src_brokers, fronts = load_source(src_dir)
    stats = {"seed": len(seed_ids), "added": 0, "annotated": 0, "fronts_added": 0}

    for key, d in src_brokers.items():
        conv = convert_one(key, d, today)
        nid = conv["id"]
        if not nid or not conv["opt_out_url"]:
            continue
        if nid in out_brokers:
            existing = out_brokers[nid]
            status = (d.get("status") or {})
            if status.get("working") is False:
                warn = f"[community list: opt-out reported not working as of {status.get('asOf') or 'recently'}]"
                if warn not in existing.get("instructions", ""):
                    existing["instructions"] = (existing.get("instructions", "").rstrip() + "  " + warn).strip()
                    existing.setdefault("flags", []).append("community-reports-broken")
                    stats["annotated"] += 1
            continue
        out_brokers[nid] = conv
        stats["added"] += 1

    # Fronts: sites that reuse another broker's backend + opt-out.
    name_by_nid = {nid: b.get("name", nid) for nid, b in out_brokers.items()}
    for backend_key, front_keys in (fronts or {}).items():
        b_nid = norm_id(backend_key)
        backend = out_brokers.get(b_nid)
        if not backend:
            continue
        for fk in front_keys or []:
            f_nid = norm_id(fk)
            if f_nid in out_brokers:
                continue
            out_brokers[f_nid] = {
                "id": f_nid,
                "name": prettify_key(fk),
                "category": "people-search",
                "site": "",
                "opt_out_url": backend["opt_out_url"],
                "method": backend.get("method", "form"),
                "privacy_email": backend.get("privacy_email", ""),
                "privacy_phone": "",
                "mailing_address": "",
                "confirmation": "",
                "requires_id": False,
                "typical_completion_days": 0,
                "regions": ["US"],
                "law_basis": ["CCPA"],
                "instructions": (
                    f"This site displays data from {name_by_nid.get(b_nid, backend['name'])}. "
                    f"Completing the {name_by_nid.get(b_nid, backend['name'])} opt-out removes this listing too."
                ),
                "last_verified": today,
                "source": "brianreumere-front",
            }
            stats["fronts_added"] += 1

    result = {
        "schema_version": 1,
        "list_version": today,
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "note": (
            "Merged from the app's curated seed list (authoritative) and the "
            "community list brianreumere/data-brokers. Always confirm the current "
            "process on the broker's own privacy page. 'last_verified' is the "
            "date the entry was last checked by a human in its source."
        ),
        "sources": [
            {"name": "data-broker-optout seed", "url": "bundled"},
            {"name": "brianreumere/data-brokers", "url": SOURCE_REPO},
        ],
        "brokers": sorted(out_brokers.values(), key=lambda b: b["name"].lower()),
    }
    return result, stats


def clone(ref: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="dbroker-src-"))
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, SOURCE_REPO, str(tmp)],
        check=True, capture_output=True, text=True,
    )
    return tmp


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT, help=f"output path (default {DEFAULT_OUT})")
    ap.add_argument("--seed", type=Path, default=DEFAULT_SEED, help="base/authoritative list")
    ap.add_argument("--src-dir", type=Path, help="local checkout of brianreumere/data-brokers (skip clone)")
    ap.add_argument("--ref", default="main", help="git branch/tag to clone (default main)")
    ap.add_argument("--check", action="store_true", help="validate + print summary, do not write")
    args = ap.parse_args(argv)

    src_dir = args.src_dir
    cloned = None
    if not src_dir:
        print(f"cloning {SOURCE_REPO} @ {args.ref} ...")
        cloned = src_dir = clone(args.ref)

    try:
        result, stats = build(args.seed, src_dir)
    finally:
        if cloned:
            import shutil
            shutil.rmtree(cloned, ignore_errors=True)

    # Validate with the app's own rules.
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from dbopt.brokers import validate_incoming
        validate_incoming(result)
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"output failed the app's validation: {exc}")

    total = len(result["brokers"])
    print(
        f"seed={stats['seed']}  +added={stats['added']}  +fronts={stats['fronts_added']}  "
        f"annotated={stats['annotated']}  ->  {total} brokers"
    )

    if args.check:
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
