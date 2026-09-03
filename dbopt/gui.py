"""Tkinter desktop UI.

Tkinter ships with the python.org macOS installers back to OS X 10.9, so this
runs on "macOS 10 and up" with no third-party packages.

Tabs: People (up to 5) · Brokers · Requests · Updates · About
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import __app_name__, __version__, brokers, theme
from .engine import (DONE_STATUSES, STATUS_LABEL, STATUSES, RequestStore,
                     mailto_link, open_path, open_url, prepare_request,
                     progress_for_profile)
from .models import LAW_BASES, MAX_PROFILES, Address, Profile, ProfileStore, Settings
from . import updater

PAD = 8


# --------------------------------------------------------------------------- helpers
def _split(text: str) -> list[str]:
    return [x.strip() for x in text.replace("\n", ",").split(",") if x.strip()]


def _join(items) -> str:
    return ", ".join(items or [])


def _addrs_to_text(addresses: list[Address]) -> str:
    # one address per line: street | city | state | zip | from_year | to_year
    return "\n".join(
        " | ".join([a.street, a.city, a.state, a.zip, a.from_year, a.to_year])
        for a in addresses
    )


def _text_to_addrs(text: str) -> list[Address]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        parts += [""] * (6 - len(parts))
        out.append(Address(street=parts[0], city=parts[1], state=parts[2],
                           zip=parts[3], from_year=parts[4], to_year=parts[5]))
    return out


# --------------------------------------------------------------------------- People tab
class PeopleTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=PAD)
        self.app = app
        self.store = app.pstore
        self.current: Profile | None = None

        left = ttk.Frame(self)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="People (max 5)").pack(anchor="w")
        self.listbox = tk.Listbox(left, width=26, height=12, exportselection=False)
        self.listbox.pack(fill="y", expand=True, pady=(2, 4))
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        btns = ttk.Frame(left)
        btns.pack(fill="x")
        ttk.Button(btns, text="New", command=self._new).pack(side="left")
        ttk.Button(btns, text="Delete", command=self._delete).pack(side="left", padx=4)

        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True, padx=(PAD * 2, 0))
        self.vars = {}
        rows = [
            ("label", "Nickname / label"),
            ("first_name", "First name"),
            ("middle_name", "Middle name"),
            ("last_name", "Last name"),
            ("birth_year", "Year of birth"),
            ("aliases", "Aliases (comma-separated)"),
            ("emails", "Emails (comma-separated)"),
            ("phones", "Phones (comma-separated)"),
        ]
        for i, (key, label) in enumerate(rows):
            ttk.Label(right, text=label).grid(row=i, column=0, sticky="w", pady=2)
            v = tk.StringVar()
            ttk.Entry(right, textvariable=v, width=52).grid(row=i, column=1, sticky="we", pady=2)
            self.vars[key] = v
        r = len(rows)
        ttk.Label(right, text="Addresses (one per line:\nstreet | city | state | zip | from_year | to_year)"
                  ).grid(row=r, column=0, sticky="nw", pady=2)
        self.addr_text = tk.Text(right, width=52, height=5, wrap="none")
        self.addr_text.grid(row=r, column=1, sticky="we", pady=2)
        ttk.Label(right, text="Notes").grid(row=r + 1, column=0, sticky="nw", pady=2)
        self.notes_text = tk.Text(right, width=52, height=4, wrap="word")
        self.notes_text.grid(row=r + 1, column=1, sticky="we", pady=2)
        right.columnconfigure(1, weight=1)

        save = ttk.Frame(right)
        save.grid(row=r + 2, column=1, sticky="e", pady=(6, 0))
        self.status_lbl = ttk.Label(right, text="", foreground="#666")
        self.status_lbl.grid(row=r + 2, column=0, sticky="w")
        ttk.Button(save, text="Save person", command=self._save,
                   style="Accent.TButton").pack(side="left")

        self.refresh()

    def refresh(self):
        self.listbox.delete(0, "end")
        for p in self.store.profiles:
            self.listbox.insert("end", p.display())
        self.app.refresh_people_dependents()

    def _on_select(self, _=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        self.current = self.store.profiles[sel[0]]
        self._load(self.current)

    def _load(self, p: Profile):
        self.vars["label"].set(p.label)
        self.vars["first_name"].set(p.first_name)
        self.vars["middle_name"].set(p.middle_name)
        self.vars["last_name"].set(p.last_name)
        self.vars["birth_year"].set(p.birth_year)
        self.vars["aliases"].set(_join(p.aliases))
        self.vars["emails"].set(_join(p.emails))
        self.vars["phones"].set(_join(p.phones))
        self.addr_text.delete("1.0", "end")
        self.addr_text.insert("1.0", _addrs_to_text(p.addresses))
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("1.0", p.notes)
        ok, missing = p.is_complete_enough()
        self.status_lbl.config(
            text="Looks complete." if ok else "Still needs: " + ", ".join(missing),
            foreground="#2a7" if ok else "#a60")

    def _new(self):
        if len(self.store.profiles) >= MAX_PROFILES:
            messagebox.showwarning(__app_name__, f"This program supports at most {MAX_PROFILES} people.")
            return
        self.current = Profile()
        for v in self.vars.values():
            v.set("")
        self.addr_text.delete("1.0", "end")
        self.notes_text.delete("1.0", "end")
        self.status_lbl.config(text="New person — fill in and Save.", foreground="#666")

    def _collect(self) -> Profile:
        p = self.current or Profile()
        p.label = self.vars["label"].get().strip()
        p.first_name = self.vars["first_name"].get().strip()
        p.middle_name = self.vars["middle_name"].get().strip()
        p.last_name = self.vars["last_name"].get().strip()
        p.birth_year = self.vars["birth_year"].get().strip()
        p.aliases = _split(self.vars["aliases"].get())
        p.emails = _split(self.vars["emails"].get())
        p.phones = _split(self.vars["phones"].get())
        p.addresses = _text_to_addrs(self.addr_text.get("1.0", "end"))
        p.notes = self.notes_text.get("1.0", "end").strip()
        return p

    def _save(self):
        p = self._collect()
        if not (p.first_name and p.last_name) and not p.label:
            messagebox.showwarning(__app_name__, "Give at least a first and last name.")
            return
        try:
            if self.store.get(p.id):
                self.store.update(p)
            else:
                self.store.add(p)
        except ValueError as e:
            messagebox.showwarning(__app_name__, str(e))
            return
        self.current = p
        self.refresh()
        self._load(p)

    def _delete(self):
        if not self.current or not self.store.get(self.current.id):
            return
        if messagebox.askyesno(__app_name__, f"Delete {self.current.display()} and their request history?"):
            self.store.delete(self.current.id)
            self.current = None
            self._new()
            self.refresh()


# --------------------------------------------------------------------------- Brokers tab
class BrokerDialog(tk.Toplevel):
    FIELDS = [
        ("id", "ID (slug)"), ("name", "Name"), ("category", "Category"),
        ("site", "Site URL"), ("opt_out_url", "Opt-out URL"),
        ("method", "Method (form / email / form+email / account / mail)"),
        ("privacy_email", "Privacy email"), ("privacy_phone", "Privacy phone"),
        ("mailing_address", "Mailing address"), ("confirmation", "Confirmation type"),
        ("typical_completion_days", "Typical completion (days)"),
        ("last_verified", "Last verified (YYYY-MM-DD)"),
    ]

    def __init__(self, master, broker: dict | None, on_save):
        super().__init__(master)
        self.title("Broker" if broker else "New broker")
        self.on_save = on_save
        self.resizable(False, False)
        self.vars = {}
        b = broker or {}
        for i, (key, label) in enumerate(self.FIELDS):
            ttk.Label(self, text=label).grid(row=i, column=0, sticky="w", padx=PAD, pady=3)
            v = tk.StringVar(value=str(b.get(key, "") or ""))
            ttk.Entry(self, textvariable=v, width=54).grid(row=i, column=1, padx=PAD, pady=3)
            self.vars[key] = v
        ttk.Label(self, text="Instructions").grid(row=len(self.FIELDS), column=0, sticky="nw", padx=PAD)
        self.instr = tk.Text(self, width=54, height=5, wrap="word")
        self.instr.insert("1.0", b.get("instructions", ""))
        self.instr.grid(row=len(self.FIELDS), column=1, padx=PAD, pady=3)
        bar = ttk.Frame(self)
        bar.grid(row=len(self.FIELDS) + 1, column=1, sticky="e", padx=PAD, pady=PAD)
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="left")
        ttk.Button(bar, text="Save", command=self._save,
                   style="Accent.TButton").pack(side="left", padx=4)
        self._existing = b
        theme.polish(self)

    def _save(self):
        data = dict(self._existing)
        for key, v in self.vars.items():
            data[key] = v.get().strip()
        data["instructions"] = self.instr.get("1.0", "end").strip()
        if not data.get("id") or not data.get("name") or not data.get("opt_out_url"):
            messagebox.showwarning("Broker", "id, name and opt-out URL are required.")
            return
        try:
            data["typical_completion_days"] = int(data.get("typical_completion_days") or 0)
        except ValueError:
            data["typical_completion_days"] = 0
        data.setdefault("regions", ["US"])
        data.setdefault("law_basis", ["CCPA"])
        self.on_save(data)
        self.destroy()


class BrokersTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=PAD)
        self.app = app
        top = ttk.Frame(self)
        top.pack(fill="x")
        self.count_lbl = ttk.Label(top, text="")
        self.count_lbl.pack(side="left")
        ttk.Button(top, text="Add", command=self._add).pack(side="right")
        ttk.Button(top, text="Edit", command=self._edit).pack(side="right", padx=4)
        ttk.Button(top, text="Delete", command=self._delete).pack(side="right")

        cols = ("name", "category", "method", "verified", "source")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=14)
        for c, w in zip(cols, (200, 150, 110, 100, 80)):
            self.tree.heading(c, text=c.title())
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=6)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self._edit())

        self.detail = tk.Text(self, height=8, wrap="word")
        self.detail.pack(fill="x")
        self.detail.config(state="disabled")

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(6, 0))
        ttk.Button(bar, text="Open opt-out page", command=self._open_page,
                   style="Accent.TButton").pack(side="left")
        ttk.Button(bar, text="Draft privacy email", command=self._open_mail).pack(side="left", padx=4)

        self.refresh()

    def _selected(self) -> dict | None:
        sel = self.tree.selection()
        if not sel:
            return None
        return brokers.get(sel[0])

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for b in brokers.list_brokers():
            self.tree.insert("", "end", iid=b["id"], values=(
                b.get("name", ""), b.get("category", ""), b.get("method", ""),
                b.get("last_verified", ""), b.get("source", "seed")))
        self.count_lbl.config(text=f"{len(brokers.list_brokers())} data-broker sites in catalogue")
        self.app.refresh_broker_dependents()

    def _on_select(self, _=None):
        b = self._selected()
        if not b:
            return
        lines = [
            f"{b.get('name')}  [{b.get('id')}]",
            f"Site:        {b.get('site','')}",
            f"Opt-out:     {b.get('opt_out_url','')}",
            f"Method:      {b.get('method','')}   Confirmation: {b.get('confirmation','')}",
            f"Privacy:     {b.get('privacy_email','')}   {b.get('privacy_phone','')}",
            f"Mail:        {b.get('mailing_address','') or '—'}",
            f"Typical:     {b.get('typical_completion_days','?')} days   "
            f"Needs ID: {'yes' if b.get('requires_id') else 'no'}   "
            f"Law basis: {', '.join(b.get('law_basis', []))}",
            "",
            b.get("instructions", ""),
        ]
        self.detail.config(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", "\n".join(lines))
        self.detail.config(state="disabled")

    def _open_page(self):
        b = self._selected()
        if b:
            open_url(b.get("opt_out_url", ""))

    def _open_mail(self):
        b = self._selected()
        if b and b.get("privacy_email"):
            open_url(mailto_link(b, "Privacy request", ""))
        elif b:
            messagebox.showinfo(__app_name__, "This broker has no privacy email on file; use the opt-out page.")

    def _add(self):
        BrokerDialog(self, None, self._persist)

    def _edit(self):
        b = self._selected()
        if b:
            BrokerDialog(self, b, self._persist)

    def _persist(self, data):
        brokers.upsert(data)
        self.refresh()

    def _delete(self):
        b = self._selected()
        if b and messagebox.askyesno(__app_name__, f"Remove {b['name']} from the catalogue?"):
            brokers.remove(b["id"])
            self.refresh()


# --------------------------------------------------------------------------- Requests tab
class RequestsTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=PAD)
        self.app = app
        self.rstore = app.rstore

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Person:").pack(side="left")
        self.person_var = tk.StringVar()
        self.person_cb = ttk.Combobox(top, textvariable=self.person_var, state="readonly", width=28)
        self.person_cb.pack(side="left", padx=6)
        self.person_cb.bind("<<ComboboxSelected>>", lambda e: self.refresh_rows())
        ttk.Label(top, text="Legal basis:").pack(side="left", padx=(12, 0))
        self.law_var = tk.StringVar(value=Settings()["default_law_basis"])
        ttk.Combobox(top, textvariable=self.law_var, values=LAW_BASES, state="readonly",
                     width=18).pack(side="left", padx=6)

        self.progress = ttk.Progressbar(self, length=380, mode="determinate")
        self.progress.pack(anchor="w", pady=(8, 0))
        self.progress_lbl = ttk.Label(self, text="")
        self.progress_lbl.pack(anchor="w")

        cols = ("broker", "method", "status", "due", "updated")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=13)
        for c, w in zip(cols, (200, 110, 170, 100, 140)):
            self.tree.heading(c, text=c.title())
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=6)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        lu = ttk.Frame(self)
        lu.pack(fill="x")
        ttk.Label(lu, text="Listing URL(s) for this person on the selected site (comma-separated):").pack(anchor="w")
        self.listing_var = tk.StringVar()
        ttk.Entry(lu, textvariable=self.listing_var).pack(fill="x")
        ttk.Button(lu, text="Save listing URLs", command=self._save_listing).pack(anchor="e", pady=2)

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(4, 0))
        ttk.Button(bar, text="Prepare request", command=self._prepare,
                   style="Accent.TButton").pack(side="left")
        ttk.Button(bar, text="Open last draft", command=self._open_draft).pack(side="left", padx=4)
        ttk.Button(bar, text="Copy email text", command=self._copy_text).pack(side="left")
        for label, status in [("Mark submitted", "submitted"),
                              ("Awaiting confirm", "awaiting_confirmation"),
                              ("Mark removed", "confirmed_removed"),
                              ("Mark rejected", "rejected")]:
            ttk.Button(bar, text=label, command=lambda s=status: self._set_status(s)).pack(side="left", padx=2)
        ttk.Button(bar, text="Add note", command=self._add_note).pack(side="left", padx=2)

        self._last = None
        self.refresh_people()

    # -- data helpers
    def _profiles(self):
        return self.app.pstore.profiles

    def _current_profile(self):
        idx = self.person_cb.current()
        profs = self._profiles()
        if 0 <= idx < len(profs):
            return profs[idx]
        return None

    def _current_broker_id(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def refresh_people(self):
        profs = self._profiles()
        self.person_cb["values"] = [p.display() for p in profs]
        if profs and self.person_cb.current() < 0:
            self.person_cb.current(0)
        elif not profs:
            self.person_var.set("")
        self.refresh_rows()

    def refresh_rows(self):
        self.tree.delete(*self.tree.get_children())
        p = self._current_profile()
        if not p:
            self.progress["value"] = 0
            self.progress_lbl.config(text="Add a person on the People tab first.")
            return
        recs = self.rstore.all_for_profile(p.id)
        for b in brokers.list_brokers():
            r = recs[b["id"]]
            self.tree.insert("", "end", iid=b["id"], values=(
                b.get("name", ""), b.get("method", ""),
                STATUS_LABEL.get(r["status"], r["status"]),
                r.get("next_action_due") or "",
                (r.get("updated_at") or "")[:16].replace("T", " ")))
        pr = progress_for_profile(self.rstore, p.id)
        self.progress["maximum"] = max(pr["total"], 1)
        self.progress["value"] = pr["removed"]
        self.progress_lbl.config(
            text=f"{p.display()}: {pr['removed']} of {pr['total']} sites confirmed removed "
                 f"({pr['pct']}%) · {pr['in_flight']} in progress · {pr['not_started']} not started")

    def _on_select(self, _=None):
        p, bid = self._current_profile(), self._current_broker_id()
        if not (p and bid):
            return
        rec = self.rstore.get(p.id, bid)
        self.listing_var.set(_join(rec.get("listing_urls")))

    # -- actions
    def _save_listing(self):
        p, bid = self._current_profile(), self._current_broker_id()
        if not (p and bid):
            return
        self.rstore.set_listing_urls(p.id, bid, _split(self.listing_var.get()))
        messagebox.showinfo(__app_name__, "Saved. It will be included in the next draft.")

    def _prepare(self):
        p, bid = self._current_profile(), self._current_broker_id()
        if not (p and bid):
            messagebox.showinfo(__app_name__, "Pick a person and a broker row first.")
            return
        ok, missing = p.is_complete_enough()
        if not ok and not messagebox.askyesno(
                __app_name__,
                "This person is missing: " + ", ".join(missing) +
                ".\nThe request may be rejected as unverifiable. Prepare it anyway?"):
            return
        b = brokers.get(bid)
        res = prepare_request(self.rstore, p, b, Settings(), law_basis=self.law_var.get())
        self._last = res
        self.refresh_rows()
        method = b.get("method", "")
        msg = [f"Draft written to:\n{res['draft_path']}", ""]
        if b.get("opt_out_url"):
            msg.append("Opened the opt-out page in your browser.")
        if "email" in method:
            msg.append("Opened the email draft in Mail — review it and press Send yourself.")
        else:
            msg.append("This broker uses a web form: paste the request text (Copy email text) "
                       "into their form. Nothing was sent by this app.")
        msg.append("\nWhen you have submitted it, select the row and click 'Mark submitted'.")
        messagebox.showinfo(__app_name__, "\n".join(msg))

    def _open_draft(self):
        p, bid = self._current_profile(), self._current_broker_id()
        if not (p and bid):
            return
        rec = self.rstore.get(p.id, bid)
        path = rec.get("last_draft_path")
        if path:
            open_path(path)
        else:
            messagebox.showinfo(__app_name__, "No draft yet — click 'Prepare request'.")

    def _copy_text(self):
        if not self._last:
            messagebox.showinfo(__app_name__, "Prepare a request first.")
            return
        self.clipboard_clear()
        self.clipboard_append(f"To: {self._last['mailto'].split('?')[0][7:]}\n"
                              f"Subject: {self._last['subject']}\n\n{self._last['body']}")
        messagebox.showinfo(__app_name__, "Request text copied to the clipboard.")

    def _set_status(self, status):
        p, bid = self._current_profile(), self._current_broker_id()
        if not (p and bid):
            return
        self.rstore.set_status(p.id, bid, status)
        if status in ("submitted", "awaiting_confirmation"):
            b = brokers.get(bid)
            self.rstore.schedule_followup(p.id, bid, max(7, int(b.get("typical_completion_days") or 14)))
        self.refresh_rows()

    def _add_note(self):
        p, bid = self._current_profile(), self._current_broker_id()
        if not (p and bid):
            return
        win = tk.Toplevel(self)
        win.title("Add note")
        txt = tk.Text(win, width=50, height=5)
        txt.pack(padx=PAD, pady=PAD)

        def save():
            note = txt.get("1.0", "end").strip()
            if note:
                self.rstore.add_note(p.id, bid, note)
                self.refresh_rows()
            win.destroy()
        ttk.Button(win, text="Save note", command=save,
                   style="Accent.TButton").pack(pady=(0, PAD))
        theme.polish(win)


# --------------------------------------------------------------------------- Updates tab
class UpdatesTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=PAD)
        self.app = app
        s = Settings()

        grid = ttk.Frame(self)
        grid.pack(fill="x")
        ttk.Label(grid, text="Update source URL (JSON, same shape as the seed list):").grid(
            row=0, column=0, sticky="w")
        self.url_var = tk.StringVar(value=s["update_source_url"])
        ttk.Entry(grid, textvariable=self.url_var, width=64).grid(row=1, column=0, sticky="we")
        ttk.Label(grid, text="Auto-update every N days:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.interval_var = tk.IntVar(value=int(s["update_interval_days"]))
        ttk.Spinbox(grid, from_=7, to=180, textvariable=self.interval_var, width=6).grid(
            row=3, column=0, sticky="w")
        self.auto_var = tk.BooleanVar(value=bool(s["auto_update_enabled"]))
        ttk.Checkbutton(grid, text="Enable automatic monthly update",
                        variable=self.auto_var).grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Button(grid, text="Save settings", command=self._save,
                   style="Accent.TButton").grid(row=5, column=0, sticky="w", pady=6)
        grid.columnconfigure(0, weight=1)

        self.info = ttk.Label(self, text="", foreground="#555", justify="left")
        self.info.pack(anchor="w", pady=(4, 0))

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=6)
        self.check_btn = ttk.Button(bar, text="Check for updates now (manual)",
                                    command=self._check_now, style="Accent.TButton")
        self.check_btn.pack(side="left")
        ttk.Button(bar, text="Install monthly auto-update (launchd)",
                   command=self._install).pack(side="left", padx=6)
        ttk.Button(bar, text="Remove auto-update", command=self._uninstall).pack(side="left")

        ttk.Label(self, text="Update log:").pack(anchor="w", pady=(8, 0))
        self.log = tk.Text(self, height=12, wrap="none")
        self.log.pack(fill="both", expand=True)
        self.log.config(state="disabled")
        ttk.Button(self, text="Refresh log", command=self._refresh_log).pack(anchor="e", pady=4)

        self._refresh_info()
        self._refresh_log()

    def _refresh_info(self):
        s = Settings()
        due = "yes" if updater.is_due(s) else "no"
        self.info.config(text=(
            f"Last check: {s['last_update_check'] or 'never'}    "
            f"Last applied: {s['last_update_applied'] or 'never'}\n"
            f"Last result: {s['last_update_summary'] or '—'}\n"
            f"Due now: {due}    Brokers in catalogue: {len(brokers.list_brokers())}"))

    def _refresh_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("1.0", updater.read_log())
        self.log.see("end")
        self.log.config(state="disabled")

    def _save(self):
        Settings().update(
            update_source_url=self.url_var.get().strip(),
            update_interval_days=int(self.interval_var.get()),
            auto_update_enabled=bool(self.auto_var.get()))
        self._refresh_info()
        messagebox.showinfo(__app_name__, "Saved.")

    def _check_now(self):
        self.check_btn.config(state="disabled", text="Checking…")

        def work():
            res = updater.run_update(force=True, source="manual-gui")
            self.after(0, lambda: done(res))

        def done(res):
            self.check_btn.config(state="normal", text="Check for updates now (manual)")
            self._refresh_info()
            self._refresh_log()
            self.app.refresh_broker_dependents()
            messagebox.showinfo(__app_name__, f"[{res['status']}] {res['detail']}")

        threading.Thread(target=work, daemon=True).start()

    def _install(self):
        from .cli import cmd_install_monthly
        import argparse
        ns = argparse.Namespace(day=1, hour=10, run_now=False)
        try:
            cmd_install_monthly(ns)
            messagebox.showinfo(
                __app_name__,
                "Monthly auto-update installed via launchd.\n"
                "It runs on the 1st of each month at 10:00 and calls:\n"
                "  python3 -m dbopt.cli update")
        except Exception as e:  # noqa
            messagebox.showerror(__app_name__, f"Install failed: {e}")
        self._refresh_info()

    def _uninstall(self):
        from .cli import cmd_uninstall_monthly
        import argparse
        cmd_uninstall_monthly(argparse.Namespace())
        messagebox.showinfo(__app_name__, "Auto-update agent removed.")
        self._refresh_info()


# --------------------------------------------------------------------------- About tab
ABOUT = f"""{__app_name__}  v{__version__}

What this program does
  • Keeps up to {MAX_PROFILES} people's identity details locally.
  • Holds a catalogue of data-broker sites and their opt-out routes.
  • For any (person, broker) pair it PREPARES a legally-grounded deletion /
    opt-out request (CCPA/CPRA, GDPR, or a generic US-state request), opens the
    broker's opt-out page, and writes an email draft for you to review and send.
  • Tracks the status of every request and reminds you when to follow up.
  • Updates the broker catalogue on demand and automatically once a month.

What it does NOT do
  • It never sends email, submits web forms, or solves CAPTCHAs by itself. You
    review and send every request. This is deliberate: unattended submissions to
    hundreds of third parties are how accounts get flagged and requests rejected.
  • It cannot force a broker to comply. It gives you the statute, the wording,
    the contact, and a paper trail.

Your data
  • Everything is stored on this Mac only, under
    ~/Library/Application Support/{__app_name__}/
  • Drafts are written to the outbox/ folder there. Nothing is uploaded.

Disclaimer
  This tool provides templates and organisation, not legal advice. Opt-out
  processes and URLs change often — always confirm the current process on the
  broker's own site. Only submit requests for people who have authorised you.
"""


class AboutTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=PAD)
        t = tk.Text(self, wrap="word")
        t.insert("1.0", ABOUT)
        t.config(state="disabled")
        t.pack(fill="both", expand=True)


# --------------------------------------------------------------------------- Settings tab
class SettingsTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=PAD)
        self.app = app
        s = Settings()

        g = ttk.Frame(self)
        g.pack(fill="x")
        g.columnconfigure(1, weight=1)

        ttk.Label(g, text="Your name (signs the requests):").grid(row=0, column=0, sticky="w", pady=3)
        self.sig = tk.StringVar(value=s["signature_name"])
        ttk.Entry(g, textvariable=self.sig).grid(row=0, column=1, sticky="we", pady=3)

        self.agent = tk.BooleanVar(value=bool(s["is_authorized_agent"]))
        ttk.Checkbutton(g, text="I am an authorized agent acting for the people above",
                        variable=self.agent).grid(row=1, column=1, sticky="w", pady=3)

        ttk.Label(g, text="Default legal basis:").grid(row=2, column=0, sticky="w", pady=3)
        self.law = tk.StringVar(value=s["default_law_basis"])
        ttk.Combobox(g, textvariable=self.law, values=LAW_BASES, state="readonly",
                     width=20).grid(row=2, column=1, sticky="w", pady=3)

        ttk.Label(g, text="Reply-to email (plain):").grid(row=3, column=0, sticky="w", pady=3)
        self.reply = tk.StringVar(value=s["reply_to_email"])
        ttk.Entry(g, textvariable=self.reply).grid(row=3, column=1, sticky="we", pady=3)

        ttk.Label(g, text="Masked / relay alias pattern:").grid(row=4, column=0, sticky="nw", pady=3)
        self.alias = tk.StringVar(value=s["email_alias_pattern"])
        ae = ttk.Entry(g, textvariable=self.alias)
        ae.grid(row=4, column=1, sticky="we", pady=3)
        self.alias.trace_add("write", lambda *_: self._preview())

        ttk.Label(g, text=(
            "When set, this is the From + Reply-To on every request instead of your real inbox.\n"
            "Tokens:  {broker} = broker id   {local}/{domain} = parts of the person's email   {email} = it in full\n"
            "Examples:   bogatyrov+{broker}@gmail.com     bogatyrov+optout@gmail.com     {local}.{broker}@duck.com\n"
            "Gmail/iCloud/DuckDuckGo aliases all forward to your inbox, so confirmation links still reach you."
        ), foreground="#666", justify="left").grid(row=5, column=1, sticky="w", pady=(0, 6))

        self.preview = ttk.Label(g, text="", foreground="#0a5bd3")
        self.preview.grid(row=6, column=1, sticky="w")

        ttk.Button(g, text="Save settings", command=self._save,
                   style="Accent.TButton").grid(row=7, column=1, sticky="e", pady=8)

        self._preview()

    def _preview(self):
        from .templates import contact_email
        p = self.app.pstore.profiles[0] if self.app.pstore.profiles else None
        if not p:
            self.preview.config(text="(add a person to preview the address)")
            return
        s = Settings()
        s["email_alias_pattern"] = self.alias.get().strip()
        s["reply_to_email"] = self.reply.get().strip()
        sample = contact_email(p, s, {"id": "spokeo"}) or "(the person's own email)"
        self.preview.config(text="Requests to Spokeo would come from:  " + sample)

    def _save(self):
        Settings().update(
            signature_name=self.sig.get().strip(),
            is_authorized_agent=bool(self.agent.get()),
            default_law_basis=self.law.get(),
            reply_to_email=self.reply.get().strip(),
            email_alias_pattern=self.alias.get().strip(),
        )
        messagebox.showinfo(__app_name__, "Saved. New drafts will use these settings.")


# --------------------------------------------------------------------------- App
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(__app_name__)
        self.geometry("1000x700")
        self.minsize(880, 600)

        theme.apply(self)

        self.pstore = ProfileStore()
        self.rstore = RequestStore()

        header = ttk.Frame(self, padding=(PAD * 2, PAD, PAD * 2, 0))
        header.pack(fill="x")
        ttk.Label(header, text=__app_name__, style="H1.TLabel").pack(side="left")
        ttk.Label(header, text=f"v{__version__}", style="Muted.TLabel").pack(side="left", padx=(8, 0), pady=(6, 0))
        ttk.Frame(self, height=2, style="Accentline.TFrame").pack(fill="x", padx=PAD * 2, pady=(6, 0))

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=PAD, pady=PAD)
        self.people_tab = PeopleTab(nb, self)
        self.brokers_tab = BrokersTab(nb, self)
        self.requests_tab = RequestsTab(nb, self)
        self.updates_tab = UpdatesTab(nb, self)
        self.settings_tab = SettingsTab(nb, self)
        nb.add(self.people_tab, text="People")
        nb.add(self.brokers_tab, text="Brokers")
        nb.add(self.requests_tab, text="Requests")
        nb.add(self.updates_tab, text="Updates")
        nb.add(self.settings_tab, text="Settings")
        nb.add(AboutTab(nb, self), text="About")

        theme.polish(self)
        self._followup_banner()

    def refresh_people_dependents(self):
        if hasattr(self, "requests_tab"):
            self.requests_tab.refresh_people()

    def refresh_broker_dependents(self):
        if hasattr(self, "requests_tab"):
            self.requests_tab.refresh_rows()
        if hasattr(self, "brokers_tab"):
            pass

    def _followup_banner(self):
        due = self.rstore.due_followups()
        if not due:
            return
        by_person = {}
        for r in due:
            p = self.pstore.get(r["profile_id"])
            if p:
                by_person.setdefault(p.display(), 0)
                by_person[p.display()] += 1
        lines = ", ".join(f"{k}: {v}" for k, v in by_person.items())
        messagebox.showinfo(__app_name__, f"Follow-ups due today — {lines}\n"
                                          "Open the Requests tab to review them.")


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
