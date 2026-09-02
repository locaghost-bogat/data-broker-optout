"""Data model: people (profiles), app settings, and helpers.

Up to MAX_PROFILES people are supported (requirement: "work with up to 5 people").
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

from . import storage

MAX_PROFILES = 5

PROFILES_FILE = "profiles.json"
SETTINGS_FILE = "settings.json"

LAW_BASES = ["CCPA", "GDPR", "US-STATE-GENERIC"]

DEFAULT_SETTINGS: dict[str, Any] = {
    # Where the monthly auto-update pulls a fresh broker list from. Any URL that
    # returns JSON in the same shape as data/brokers.seed.json works. Empty
    # string disables remote fetch (the bundled seed list is still used).
    "update_source_url": "",
    "auto_update_enabled": True,
    "update_interval_days": 30,
    "last_update_check": None,
    "last_update_applied": None,
    "last_update_summary": "",
    "default_law_basis": "CCPA",
    # Person filling in the requests (you, or an authorised agent acting for the
    # people in the profiles). Used only in the text of generated requests.
    "signature_name": "",
    "reply_to_email": "",
    "is_authorized_agent": True,
}


@dataclass
class Address:
    street: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    from_year: str = ""
    to_year: str = ""

    def one_line(self) -> str:
        bits = [self.street, self.city, self.state, self.zip]
        line = ", ".join(b for b in bits[:3] if b)
        if self.zip:
            line = f"{line} {self.zip}".strip()
        if self.from_year and self.to_year:
            line = f"{line} ({self.from_year}–{self.to_year})"
        elif self.from_year:
            line = f"{line} (since {self.from_year})"
        elif self.to_year:
            line = f"{line} (until {self.to_year})"
        return line.strip(", ").strip()


@dataclass
class Profile:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    label: str = ""              # short nickname shown in lists
    first_name: str = ""
    middle_name: str = ""
    last_name: str = ""
    aliases: list[str] = field(default_factory=list)      # maiden names, nicknames
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    addresses: list[Address] = field(default_factory=list)
    birth_year: str = ""
    notes: str = ""

    # ---- derived ---------------------------------------------------------
    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(p for p in parts if p).strip()

    def display(self) -> str:
        return self.label or self.full_name or "(unnamed)"

    def current_address(self) -> Address | None:
        if not self.addresses:
            return None
        # An address with no to_year is treated as current.
        for a in self.addresses:
            if not a.to_year:
                return a
        return self.addresses[0]

    def prior_addresses(self) -> list[Address]:
        cur = self.current_address()
        return [a for a in self.addresses if a is not cur]

    # ---- (de)serialisation --------------------------------------------
    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        d = dict(d)
        d["addresses"] = [Address(**a) for a in d.get("addresses", [])]
        for key in ("aliases", "emails", "phones"):
            d[key] = list(d.get(key) or [])
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    def is_complete_enough(self) -> tuple[bool, list[str]]:
        """Minimum info a broker will need to find and remove a record."""
        missing = []
        if not (self.first_name and self.last_name):
            missing.append("first and last name")
        if not self.current_address():
            missing.append("at least one address (city/state)")
        if not self.emails:
            missing.append("a contact email for confirmation links")
        return (not missing, missing)


# ---------------------------------------------------------------------------
class ProfileStore:
    def __init__(self) -> None:
        raw = storage.load_json(PROFILES_FILE, [])
        self.profiles: list[Profile] = [Profile.from_dict(x) for x in raw]

    def save(self) -> None:
        storage.backup_file(PROFILES_FILE)
        storage.save_json(PROFILES_FILE, [p.to_dict() for p in self.profiles])

    def get(self, pid: str) -> Profile | None:
        return next((p for p in self.profiles if p.id == pid), None)

    def add(self, p: Profile) -> Profile:
        if len(self.profiles) >= MAX_PROFILES:
            raise ValueError(f"This program supports at most {MAX_PROFILES} people.")
        self.profiles.append(p)
        self.save()
        return p

    def update(self, p: Profile) -> None:
        for i, existing in enumerate(self.profiles):
            if existing.id == p.id:
                self.profiles[i] = p
                self.save()
                return
        raise KeyError(p.id)

    def delete(self, pid: str) -> None:
        self.profiles = [p for p in self.profiles if p.id != pid]
        self.save()


# ---------------------------------------------------------------------------
class Settings:
    def __init__(self) -> None:
        data = dict(DEFAULT_SETTINGS)
        data.update(storage.load_json(SETTINGS_FILE, {}))
        self._data = data

    def __getitem__(self, key: str):
        return self._data.get(key, DEFAULT_SETTINGS.get(key))

    def __setitem__(self, key: str, value) -> None:
        self._data[key] = value

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def update(self, **kw) -> None:
        self._data.update(kw)
        self.save()

    def save(self) -> None:
        storage.save_json(SETTINGS_FILE, self._data)

    def as_dict(self) -> dict:
        return dict(self._data)
