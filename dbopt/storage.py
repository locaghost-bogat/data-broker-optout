"""Filesystem layout and JSON persistence.

All user data lives under ~/Library/Application Support/Data Broker Opt-Out/ so the
app follows macOS conventions and survives reinstalls of the code.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
from datetime import date, datetime
from pathlib import Path

APP_DIR_NAME = "Data Broker Opt-Out"

# Location of this source checkout (used to find the seed broker list).
PKG_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PKG_ROOT.parent


def _find_seed() -> Path:
    """Locate data/brokers.seed.json across dev checkout, thin .app bundle and
    py2app standalone bundle."""
    env = os.environ.get("DBOPT_SEED")
    candidates = [Path(env)] if env else []
    candidates += [
        REPO_ROOT / "data" / "brokers.seed.json",          # dev checkout
        PKG_ROOT / "data" / "brokers.seed.json",           # data copied next to package
        Path(sys.prefix) / "data" / "brokers.seed.json",   # py2app Resources
    ]
    # .app/Contents/MacOS/<exe>  ->  .app/Contents/Resources/data/...
    exe_dir = Path(sys.executable).resolve().parent
    candidates.append(exe_dir.parent / "Resources" / "data" / "brokers.seed.json")
    for c in candidates:
        if c.is_file():
            return c
    return REPO_ROOT / "data" / "brokers.seed.json"


SEED_BROKERS = _find_seed()

_LOCK = threading.RLock()


def support_dir() -> Path:
    override = os.environ.get("DBOPT_HOME")
    if override:
        base = Path(override).expanduser()
    else:
        base = Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    for sub in ("outbox", "logs", "backups"):
        (base / sub).mkdir(exist_ok=True)
    return base


def path(name: str) -> Path:
    return support_dir() / name


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today_iso() -> str:
    return date.today().isoformat()


def load_json(name: str, default):
    p = path(name)
    with _LOCK:
        if not p.exists():
            return default
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Corrupt file: keep a copy, fall back to default.
            try:
                shutil.copy2(p, path("backups") / f"{name}.corrupt.{int(datetime.now().timestamp())}")
            except OSError:
                pass
            return default


def save_json(name: str, data) -> None:
    """Atomic write so a crash mid-save cannot corrupt the store."""
    p = path(name)
    with _LOCK:
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=f".{name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def backup_file(name: str) -> Path | None:
    p = path(name)
    if not p.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = path("backups") / f"{name}.{stamp}"
    with _LOCK:
        shutil.copy2(p, dest)
    return dest


def log_line(logname: str, message: str) -> None:
    p = path("logs") / logname
    with _LOCK:
        with p.open("a", encoding="utf-8") as fh:
            fh.write(f"{now_iso()}  {message}\n")
