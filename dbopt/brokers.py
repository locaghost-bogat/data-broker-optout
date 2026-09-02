"""Load, persist and merge the data-broker catalogue.

The working copy lives in the Application Support directory. On first run it is
seeded from data/brokers.seed.json shipped with the code. The monthly updater
merges a fresh list on top without discarding entries the user added or edited.
"""
from __future__ import annotations

import json
from typing import Any

from . import storage

BROKERS_FILE = "brokers.json"

# Factual fields the remote list is allowed to overwrite on an existing broker.
_REMOTE_FIELDS = (
    "name", "category", "site", "opt_out_url", "method", "privacy_email",
    "privacy_phone", "mailing_address", "confirmation", "requires_id",
    "typical_completion_days", "regions", "law_basis", "instructions",
    "last_verified",
)

REQUIRED_FIELDS = ("id", "name", "opt_out_url", "method")


def _read_seed() -> dict[str, Any]:
    return json.loads(storage.SEED_BROKERS.read_text(encoding="utf-8"))


def load() -> dict[str, Any]:
    """Return the working catalogue, seeding it on first use."""
    data = storage.load_json(BROKERS_FILE, None)
    if not data or "brokers" not in data:
        data = _read_seed()
        storage.save_json(BROKERS_FILE, data)
    return data


def save(data: dict[str, Any]) -> None:
    storage.backup_file(BROKERS_FILE)
    storage.save_json(BROKERS_FILE, data)


def list_brokers() -> list[dict[str, Any]]:
    return sorted(load().get("brokers", []), key=lambda b: b.get("name", "").lower())


def get(broker_id: str) -> dict[str, Any] | None:
    return next((b for b in load().get("brokers", []) if b.get("id") == broker_id), None)


def upsert(broker: dict[str, Any]) -> None:
    data = load()
    brokers = data.setdefault("brokers", [])
    for i, b in enumerate(brokers):
        if b.get("id") == broker.get("id"):
            broker.setdefault("source", "user")
            broker["user_modified"] = True
            brokers[i] = broker
            break
    else:
        broker.setdefault("source", "user")
        brokers.append(broker)
    save(data)


def remove(broker_id: str) -> None:
    data = load()
    data["brokers"] = [b for b in data.get("brokers", []) if b.get("id") != broker_id]
    save(data)


def validate_incoming(data: Any) -> list[dict[str, Any]]:
    """Raise ValueError unless *data* looks like a broker list; return the brokers."""
    if not isinstance(data, dict) or not isinstance(data.get("brokers"), list):
        raise ValueError("Update payload is not an object with a 'brokers' array.")
    brokers = data["brokers"]
    if not brokers:
        raise ValueError("Update payload contains zero brokers.")
    for b in brokers:
        if not isinstance(b, dict) or not all(b.get(f) for f in REQUIRED_FIELDS):
            raise ValueError(f"Broker entry missing required fields {REQUIRED_FIELDS}: {b!r:.120}")
    return brokers


def merge(remote: dict[str, Any]) -> dict[str, int]:
    """Merge a validated remote catalogue into the working copy.

    Rules:
      * new broker id            -> added
      * existing, not user-edited -> factual fields refreshed from remote
      * existing, user-edited     -> left alone (only 'last_verified' bumped)
      * local-only broker         -> kept
    Returns a summary dict {added, updated, unchanged, kept_local}.
    """
    remote_brokers = validate_incoming(remote)
    data = load()
    local = {b["id"]: b for b in data.get("brokers", [])}
    summary = {"added": 0, "updated": 0, "unchanged": 0, "kept_local": 0}

    for rb in remote_brokers:
        bid = rb["id"]
        if bid not in local:
            rb.setdefault("source", "remote")
            local[bid] = rb
            summary["added"] += 1
            continue
        lb = local[bid]
        if lb.get("user_modified"):
            if rb.get("last_verified"):
                lb["last_verified"] = rb["last_verified"]
            summary["unchanged"] += 1
            continue
        changed = False
        for f in _REMOTE_FIELDS:
            if f in rb and rb[f] != lb.get(f):
                lb[f] = rb[f]
                changed = True
        lb["source"] = "remote"
        summary["updated" if changed else "unchanged"] += 1

    remote_ids = {rb["id"] for rb in remote_brokers}
    for bid, lb in local.items():
        if bid not in remote_ids and lb.get("source") != "remote":
            summary["kept_local"] += 1

    data["brokers"] = list(local.values())
    data["list_version"] = remote.get("list_version", storage.today_iso())
    data["merged_at"] = storage.now_iso()
    save(data)
    return summary
