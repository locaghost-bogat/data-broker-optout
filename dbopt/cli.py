"""Command-line interface.

Used by the monthly launchd job (`update`) and for headless / scripted work.

    python3 -m dbopt.cli update [--force]
    python3 -m dbopt.cli status
    python3 -m dbopt.cli brokers
    python3 -m dbopt.cli people
    python3 -m dbopt.cli generate --person "Jane" [--broker spokeo] [--law CCPA]
    python3 -m dbopt.cli install-monthly     # install launchd auto-update
    python3 -m dbopt.cli uninstall-monthly
    python3 -m dbopt.cli gui                 # launch the app window
"""
from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path

from . import __bundle_id__, brokers, storage
from .engine import RequestStore, STATUS_LABEL, draft_eml, progress_for_profile
from .models import ProfileStore, Settings
from .updater import read_log, run_update

LAUNCH_LABEL = f"{__bundle_id__}.monthlyupdate"


def _find_person(pstore: ProfileStore, needle: str):
    needle_l = needle.lower()
    for p in pstore.profiles:
        if needle_l in (p.label.lower(), p.full_name.lower(), p.id.lower()):
            return p
    for p in pstore.profiles:
        if needle_l in p.full_name.lower() or needle_l in p.label.lower():
            return p
    return None


# ---------------------------------------------------------------------------
def cmd_update(args) -> int:
    res = run_update(force=args.force, source="cli")
    print(f"[{res['status']}] {res['detail']}")
    return 0 if res["status"] in ("ok", "skipped", "no-source") else 1


def cmd_status(args) -> int:
    s = Settings()
    print("Data Broker Opt-Out — status")
    print(f"  data dir           : {storage.support_dir()}")
    print(f"  brokers in catalog : {len(brokers.list_brokers())}")
    print(f"  update source url  : {s['update_source_url'] or '(none — bundled seed list)'}")
    print(f"  auto-update        : {'on' if s['auto_update_enabled'] else 'off'} "
          f"(every {s['update_interval_days']} days)")
    print(f"  last update check  : {s['last_update_check'] or 'never'}")
    print(f"  last update applied: {s['last_update_applied'] or 'never'}")
    print(f"  last update result : {s['last_update_summary'] or '—'}")
    pstore = ProfileStore()
    rstore = RequestStore()
    print(f"\n  people ({len(pstore.profiles)}/5):")
    for p in pstore.profiles:
        pr = progress_for_profile(rstore, p.id)
        print(f"    - {p.display():<24} removed {pr['removed']}/{pr['total']}  "
              f"({pr['pct']}%), {pr['in_flight']} in flight")
    return 0


def cmd_brokers(args) -> int:
    for b in brokers.list_brokers():
        print(f"  {b['id']:<26} {b.get('method',''):<12} {b.get('opt_out_url','')}")
    print(f"\n  {len(brokers.list_brokers())} brokers")
    return 0


def cmd_people(args) -> int:
    for p in ProfileStore().profiles:
        ok, missing = p.is_complete_enough()
        flag = "ok" if ok else f"missing: {', '.join(missing)}"
        print(f"  {p.id}  {p.display():<24} {flag}")
    return 0


def cmd_generate(args) -> int:
    pstore = ProfileStore()
    settings = Settings()
    person = _find_person(pstore, args.person)
    if not person:
        print(f"No person matching {args.person!r}. Known: "
              f"{', '.join(p.display() for p in pstore.profiles) or '(none)'}")
        return 1
    targets = [brokers.get(args.broker)] if args.broker else brokers.list_brokers()
    if args.broker and not targets[0]:
        print(f"No broker with id {args.broker!r}")
        return 1
    made = 0
    for b in targets:
        path, subject, _ = draft_eml(person, b, settings, law_basis=args.law)
        print(f"  {b['id']:<26} -> {path}")
        made += 1
    print(f"\n  {made} draft(s) written to {storage.path('outbox')}")
    print("  Review each one and send it from your mail client. Nothing was sent.")
    return 0


# ---------------------------------------------------------------------------
def _python_for_launchd() -> str:
    # Prefer a real framework python; sys.executable is fine when run from one.
    return sys.executable or "/usr/bin/python3"


def cmd_install_monthly(args) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    day = max(1, min(28, args.day))
    plist = {
        "Label": LAUNCH_LABEL,
        "ProgramArguments": [_python_for_launchd(), "-m", "dbopt.cli", "update"],
        "WorkingDirectory": str(repo_root),
        "EnvironmentVariables": {
            "PYTHONPATH": str(repo_root),
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            **({"DBOPT_HOME": os.environ["DBOPT_HOME"]} if os.environ.get("DBOPT_HOME") else {}),
        },
        # 1st of every month at HH:00 (local time). launchd repeats monthly
        # because only Day/Hour/Minute are pinned.
        "StartCalendarInterval": [{"Day": day, "Hour": args.hour, "Minute": 0}],
        "RunAtLoad": bool(args.run_now),
        "StandardOutPath": str(storage.path("logs") / "launchd.out.log"),
        "StandardErrorPath": str(storage.path("logs") / "launchd.err.log"),
    }
    agents = Path.home() / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    target = agents / f"{LAUNCH_LABEL}.plist"
    with target.open("wb") as fh:
        plistlib.dump(plist, fh)

    subprocess.run(["launchctl", "unload", str(target)], check=False,
                   capture_output=True)
    r = subprocess.run(["launchctl", "load", str(target)], check=False,
                       capture_output=True, text=True)
    Settings().update(auto_update_enabled=True)
    print(f"Installed monthly auto-update: {target}")
    print(f"  runs day {day} of each month at {args.hour:02d}:00, "
          f"command: {_python_for_launchd()} -m dbopt.cli update")
    if r.returncode != 0:
        print(f"  launchctl load said: {r.stderr.strip() or r.stdout.strip()}")
        print("  (On macOS 13+ you may need: launchctl bootstrap gui/$(id -u) "
              f"{target})")
    else:
        print("  launchctl load: ok")
    return 0


def cmd_uninstall_monthly(args) -> int:
    target = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_LABEL}.plist"
    if target.exists():
        subprocess.run(["launchctl", "unload", str(target)], check=False, capture_output=True)
        target.unlink()
        print(f"Removed {target}")
    else:
        print("No monthly auto-update agent installed.")
    Settings().update(auto_update_enabled=False)
    return 0


def cmd_log(args) -> int:
    print(read_log())
    return 0


def cmd_gui(args) -> int:
    from .gui import main as gui_main
    gui_main()
    return 0


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dbopt", description="Data Broker Opt-Out — CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    u = sub.add_parser("update", help="fetch + merge the broker list (respects monthly cadence)")
    u.add_argument("--force", action="store_true", help="ignore the cadence and update now")
    u.set_defaults(func=cmd_update)

    sub.add_parser("status", help="show configuration and per-person progress").set_defaults(func=cmd_status)
    sub.add_parser("brokers", help="list brokers in the catalogue").set_defaults(func=cmd_brokers)
    sub.add_parser("people", help="list configured people").set_defaults(func=cmd_people)
    sub.add_parser("log", help="print the update log").set_defaults(func=cmd_log)
    sub.add_parser("gui", help="open the application window").set_defaults(func=cmd_gui)

    g = sub.add_parser("generate", help="write request drafts for a person (nothing is sent)")
    g.add_argument("--person", required=True, help="label, full name, or id")
    g.add_argument("--broker", help="a single broker id (default: all)")
    g.add_argument("--law", choices=["CCPA", "GDPR", "US-STATE-GENERIC"], help="force a legal basis")
    g.set_defaults(func=cmd_generate)

    im = sub.add_parser("install-monthly", help="install the launchd monthly auto-update agent")
    im.add_argument("--day", type=int, default=1, help="day of month 1-28 (default 1)")
    im.add_argument("--hour", type=int, default=10, help="hour 0-23 (default 10)")
    im.add_argument("--run-now", action="store_true", help="also run once at load")
    im.set_defaults(func=cmd_install_monthly)

    sub.add_parser("uninstall-monthly", help="remove the launchd monthly agent").set_defaults(func=cmd_uninstall_monthly)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
