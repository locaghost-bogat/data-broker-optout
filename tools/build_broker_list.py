#!/usr/bin/env python3
"""Build a `brokers.json` for the Data Broker Opt-Out app from external sources.

Merges, in decreasing precedence:
  1. the app's own curated seed list   (data/brokers.seed.json)  -- authoritative
  2. brianreumere/data-brokers         (per-broker YAML + joins/fronts.yml)
  3. the California Data Broker Registry CSV (~600 registered brokers, each with
     a privacy email, mailing address, and a CCPA-rights / DSAR URL)

Higher-precedence sources win on curated fields (privacy email/phone, mailing
address, hand-written instructions, verified opt-out URL). Lower ones only ADD
brokers not already present, fill in blank contact fields on existing entries,
and annotate an entry when the community list reports its opt-out broken.

Output validates against dbopt.brokers.validate_incoming, so the file it writes
is guaranteed to be accepted by the app's updater.

Usage:
    python3 tools/build_broker_list.py                 # -> ./brokers.json
    python3 tools/build_broker_list.py -o public/brokers.json
    python3 tools/build_broker_list.py --src-dir /path/to/data-brokers  # no clone
    python3 tools/build_broker_list.py --no-ca         # skip the CA registry
    python3 tools/build_broker_list.py --ca-csv reg.csv  # use a local registry CSV

Requires PyYAML (see tools/requirements.txt).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    sys.exit("PyYAML is required:  python3 -m pip install --user PyYAML")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SEED = REPO_ROOT / "data" / "brokers.seed.json"
DEFAULT_OUT = REPO_ROOT / "brokers.json"
SOURCE_REPO = "https://github.com/brianreumere/data-brokers"
CA_REGISTRY_URL = "https://cppa.ca.gov/data_broker_registry/registry.csv"

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


_LEGAL_SUFFIX = re.compile(
    r"[\s,]+(inc|incorporated|llc|l\.l\.c|llp|lp|ltd|limited|corp|corporation|co|company|"
    r"holdings?|group|plc|gmbh|sa|nv|pty|dba)\.?$",
    re.I,
)


def company_id(name: str) -> str:
    """norm_id with common trailing legal suffixes stripped, so 'Acxiom LLC' and
    'Acxiom' collapse to the same id."""
    prev = None
    s = name or ""
    while s != prev:
        prev = s
        s = _LEGAL_SUFFIX.sub("", s).strip()
    return norm_id(s) or norm_id(name)


def clean_url(value: str) -> str:
    """First URL from a possibly multi-URL cell, with a scheme."""
    if not value:
        return ""
    first = re.split(r"[;\s]+", value.strip())[0].strip().rstrip(".,;")
    if not first:
        return ""
    if not first.lower().startswith(("http://", "https://")):
        first = "https://" + first.lstrip("/")
    return first


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


# --------------------------------------------------------------------------- CA registry
def _ssl_ctx() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def load_ca_registry(url: str = CA_REGISTRY_URL, local: Path | None = None) -> list[dict]:
    if local:
        text = local.read_text(encoding="utf-8-sig")
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (data-broker-optout builder)"})
        raw = urllib.request.urlopen(req, timeout=60, context=_ssl_ctx()).read()
        text = raw.decode("utf-8-sig", "replace")
    return list(csv.DictReader(io.StringIO(text)))


def _col(row: dict, *needles: str) -> str:
    """Value of the first column whose header contains all needles (case-insensitive).

    Robust to the registry's mixed straight/curly apostrophes and NB-hyphens.
    """
    for key, val in row.items():
        k = (key or "").lower()
        if all(n in k for n in needles):
            return (val or "").strip()
    return ""


def _yes(row: dict, *needles: str) -> bool:
    return _col(row, *needles).strip().lower() == "yes"


def convert_ca_row(row: dict, today: str) -> dict | None:
    name = _col(row, "data broker name")
    if not name:
        return None
    dba = _col(row, "doing business as")
    if dba and dba.lower() not in name.lower():
        name = f"{name} ({dba})"

    site = clean_url(_col(row, "primary website:"))
    email = _col(row, "primary contact email")
    phone = _col(row, "primary phone")
    rights = clean_url(_col(row, "exercise their ca consumer privacy rights"))
    opt_out = rights or site
    if not opt_out:
        return None

    addr_bits = [
        _col(row, "primary street address"), _col(row, "data broker city"),
        _col(row, "data broker state"), _col(row, "data broker zip"),
        _col(row, "data broker country"),
    ]
    mailing = ", ".join(b for b in addr_bits if b and b.upper() != "UNITED STATES")
    if _col(row, "data broker country") and "UNITED STATES" in _col(row, "data broker country").upper():
        mailing += ", USA"

    fcra = _yes(row, "regulated by the federal fair credit reporting act")
    glba = _yes(row, "regulated by the gramm", "bliley act")

    tags = []
    if _yes(row, "collects personal information of minors"):
        tags.append("collects data on minors")
    if _yes(row, "collects consumers", "biometric data"):
        tags.append("biometric data")
    if _yes(row, "collects consumers", "precise geolocation"):
        tags.append("precise geolocation")
    if _yes(row, "reproductive health care data"):
        tags.append("reproductive-health data")
    if _yes(row, "to a developer of a genai"):
        tags.append("sold/shared to a GenAI developer in the past year")
    if _yes(row, "to law enforcement in the past year"):
        tags.append("sold/shared to law enforcement")
    if _yes(row, "to a foreign actor"):
        tags.append("sold/shared to a foreign actor")

    instr = ["Registered California data broker (CA Data Broker Registry)."]
    instr.append(
        "Submit a CCPA/CPRA request to delete and to opt out of sale/sharing via the "
        "link above" + (f", or email {email}." if email else ".")
    )
    if tags:
        instr.append("Registry discloses: " + "; ".join(tags) + ".")
    if fcra:
        instr.append("FCRA-regulated for some data — that subset may be exempt from deletion; "
                     "ask them to delete everything not covered and to identify the exemption.")
    if glba:
        instr.append("GLBA-regulated for some data (similar exemption caveat).")

    return {
        "id": company_id(name),
        "name": name,
        "category": "registered-data-broker",
        "site": site,
        "opt_out_url": opt_out,
        "method": "form" if rights else ("email" if email else "form"),
        "privacy_email": email,
        "privacy_phone": phone,
        "mailing_address": mailing.strip(", "),
        "confirmation": "",
        "requires_id": bool(fcra or glba),
        "typical_completion_days": 45,
        "regions": ["US", "CA"],
        "law_basis": ["CCPA"],
        "instructions": "  ".join(instr),
        "last_verified": today,
        "source": "ca-registry",
    }


# --------------------------------------------------------------------------- merge
def build(seed_path: Path, src_dir: Path, ca_rows: list[dict] | None = None) -> tuple[dict, dict]:
    today = dt.date.today().isoformat()
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    out_brokers: dict[str, dict] = {norm_id(b["id"]): dict(b) for b in seed.get("brokers", [])}
    seed_ids = set(out_brokers)

    src_brokers, fronts = load_source(src_dir)
    stats = {"seed": len(seed_ids), "added": 0, "annotated": 0, "fronts_added": 0,
             "ca_added": 0, "ca_enriched": 0}

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

    # 3. California Data Broker Registry -- adds new brokers, fills blank contact
    #    fields on existing (non-user-edited) entries.
    for row in ca_rows or []:
        conv = convert_ca_row(row, today)
        if not conv or not conv["id"]:
            continue
        nid = conv["id"]
        if nid in out_brokers:
            existing = out_brokers[nid]
            if existing.get("user_modified"):
                continue
            filled = False
            for f in ("privacy_email", "privacy_phone", "mailing_address"):
                if not existing.get(f) and conv.get(f):
                    existing[f] = conv[f]
                    filled = True
            if "CA Data Broker Registry" not in existing.get("instructions", ""):
                existing["instructions"] = (
                    existing.get("instructions", "").rstrip()
                    + "  Also listed in the CA Data Broker Registry."
                ).strip()
                filled = True
            if filled:
                stats["ca_enriched"] += 1
            continue
        out_brokers[nid] = conv
        stats["ca_added"] += 1

    result = {
        "schema_version": 1,
        "list_version": today,
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "note": (
            "Merged from the app's curated seed list (authoritative), the community "
            "list brianreumere/data-brokers, and the California Data Broker Registry. "
            "Always confirm the current process on the broker's own privacy page. "
            "'last_verified' is the date the entry was last checked in its source."
        ),
        "sources": [
            {"name": "data-broker-optout seed", "url": "bundled"},
            {"name": "brianreumere/data-brokers", "url": SOURCE_REPO},
            {"name": "California Data Broker Registry", "url": CA_REGISTRY_URL},
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
    ap.add_argument("--no-ca", action="store_true", help="do not merge the California Data Broker Registry")
    ap.add_argument("--ca-csv", type=Path, help="use a local CA registry CSV instead of downloading")
    ap.add_argument("--ca-url", default=CA_REGISTRY_URL, help="CA registry CSV URL")
    ap.add_argument("--check", action="store_true", help="validate + print summary, do not write")
    args = ap.parse_args(argv)

    src_dir = args.src_dir
    cloned = None
    if not src_dir:
        print(f"cloning {SOURCE_REPO} @ {args.ref} ...")
        cloned = src_dir = clone(args.ref)

    ca_rows: list[dict] = []
    if not args.no_ca:
        try:
            if args.ca_csv:
                ca_rows = load_ca_registry(local=args.ca_csv)
            else:
                print(f"downloading CA Data Broker Registry ...")
                ca_rows = load_ca_registry(args.ca_url)
            print(f"  CA registry: {len(ca_rows)} rows")
        except Exception as exc:  # noqa: BLE001
            print(f"  WARNING: CA registry unavailable ({exc}) -- continuing without it")

    try:
        result, stats = build(args.seed, src_dir, ca_rows)
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
        f"seed={stats['seed']}  +community={stats['added']}  +fronts={stats['fronts_added']}  "
        f"+ca_registry={stats['ca_added']}  (ca_enriched={stats['ca_enriched']}, "
        f"annotated={stats['annotated']})  ->  {total} brokers"
    )

    if args.check:
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
