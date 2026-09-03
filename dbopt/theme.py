"""Vivid light theme for the Tkinter UI.

macOS's native `aqua` ttk theme ignores almost every colour option, so we switch
to `clam` and paint it by hand: a lavender canvas, saturated violet / green / red
action buttons, bold numerals, colour-coded status rows.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

PALETTE = {
    "bg":            "#E7E3F1",   # lavender canvas
    "surface":       "#FFFFFF",   # cards, tables, inputs
    "surface_alt":   "#EDEAF7",   # table headings, inactive tabs
    "border":        "#CBC3E4",
    "text":          "#191325",
    "muted":         "#6C6484",

    "accent":        "#6C47E6",   # violet  -> primary action
    "accent_hover":  "#5A38CC",
    "success":       "#1FC15E",   # green   -> positive / "removed"
    "success_hover": "#17A94F",
    "danger":        "#F0473F",   # red     -> delete / rejected
    "danger_hover":  "#D93A33",
    "on_color":      "#FFFFFF",

    "sel":           "#DED4FB",   # row / list selection
    "warn":          "#D97A00",
    "pink":          "#FBE0EC",   # "your info was found here" row tint
    "pink_text":     "#B21E63",
}
P = PALETTE

FONT = ("Helvetica Neue", 13)
FONT_BOLD = ("Helvetica Neue", 13, "bold")
FONT_H1 = ("Helvetica Neue", 18, "bold")


def apply(root: tk.Misc) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.configure(bg=P["bg"])
    try:
        root.option_add("*Font", FONT)
    except tk.TclError:
        pass

    style.configure(".", background=P["bg"], foreground=P["text"],
                    fieldbackground=P["surface"], font=FONT, bordercolor=P["border"],
                    lightcolor=P["border"], darkcolor=P["border"], focuscolor=P["accent"])

    style.configure("TFrame", background=P["bg"])
    style.configure("TLabelframe", background=P["bg"], bordercolor=P["border"])
    style.configure("TLabelframe.Label", background=P["bg"], foreground=P["muted"])
    style.configure("TLabel", background=P["bg"], foreground=P["text"])
    style.configure("Muted.TLabel", background=P["bg"], foreground=P["muted"])
    style.configure("H1.TLabel", background=P["bg"], foreground=P["accent"], font=FONT_H1)
    style.configure("OK.TLabel", background=P["bg"], foreground=P["success_hover"], font=FONT_BOLD)
    style.configure("Warn.TLabel", background=P["bg"], foreground=P["warn"], font=FONT_BOLD)
    style.configure("Accentline.TFrame", background=P["accent"])

    # --- buttons: flat, saturated, chunky ---------------------------------
    style.configure("TButton", background=P["surface"], foreground=P["text"],
                    bordercolor=P["border"], relief="flat", borderwidth=1,
                    padding=(14, 9), font=FONT_BOLD, anchor="center")
    style.map("TButton",
              background=[("pressed", P["surface_alt"]), ("active", "#F4F1FD"),
                         ("disabled", P["surface_alt"])],
              foreground=[("disabled", P["muted"])],
              bordercolor=[("focus", P["accent"]), ("active", P["accent"])])

    def _solid(name: str, fill: str, hover: str, disabled: str) -> None:
        style.configure(name, background=fill, foreground=P["on_color"],
                        bordercolor=fill, relief="flat", borderwidth=0,
                        padding=(17, 9), font=FONT_BOLD)
        style.map(name,
                  background=[("pressed", hover), ("active", hover), ("disabled", disabled)],
                  foreground=[("disabled", "#FFFFFFCC")])

    _solid("Accent.TButton", P["accent"], P["accent_hover"], "#B7A4F2")
    _solid("Success.TButton", P["success"], P["success_hover"], "#A7E7C2")
    _solid("Danger.TButton", P["danger"], P["danger_hover"], "#F3B3AF")

    # --- notebook -----------------------------------------------------
    style.configure("TNotebook", background=P["bg"], borderwidth=0, tabmargins=(6, 6, 6, 0))
    style.configure("TNotebook.Tab", background=P["surface_alt"], foreground=P["muted"],
                    padding=(18, 9), borderwidth=0, font=FONT_BOLD)
    style.map("TNotebook.Tab",
              background=[("selected", P["accent"])],
              foreground=[("selected", P["on_color"])])

    # --- tables -----------------------------------------------------
    style.configure("Treeview", background=P["surface"], fieldbackground=P["surface"],
                    foreground=P["text"], rowheight=27, borderwidth=1, relief="solid")
    style.configure("Treeview.Heading", background=P["accent"], foreground=P["on_color"],
                    relief="flat", padding=7, font=FONT_BOLD)
    style.map("Treeview",
              background=[("selected", P["sel"])], foreground=[("selected", P["text"])])
    style.map("Treeview.Heading", background=[("active", P["accent_hover"])])

    # --- inputs -----------------------------------------------------
    for el in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(el, fieldbackground=P["surface"], background=P["surface"],
                        foreground=P["text"], bordercolor=P["border"],
                        arrowcolor=P["accent"], padding=5)
        style.map(el, bordercolor=[("focus", P["accent"])])
    style.configure("TCheckbutton", background=P["bg"], foreground=P["text"])
    style.map("TCheckbutton", background=[("active", P["bg"])])

    style.configure("TProgressbar", background=P["success"], troughcolor=P["surface_alt"],
                    bordercolor=P["surface_alt"], lightcolor=P["success"],
                    darkcolor=P["success"], thickness=14)


def status_tags(tree: ttk.Treeview) -> None:
    """Colour-code Treeview rows by request status (call once per tree)."""
    tree.tag_configure("removed", foreground=P["success_hover"], font=FONT_BOLD)
    tree.tag_configure("rejected", foreground=P["danger_hover"], font=FONT_BOLD)
    tree.tag_configure("inflight", foreground=P["accent"])
    tree.tag_configure("idle", foreground=P["muted"])


def exposed_tags(tree: ttk.Treeview) -> None:
    """Pink tint for brokers a scan found the person's data on."""
    tree.tag_configure("exposed", background=P["pink"], foreground=P["pink_text"])


def status_tag(status: str) -> str:
    if status == "confirmed_removed":
        return "removed"
    if status == "rejected":
        return "rejected"
    if status in ("submitted", "awaiting_confirmation", "needs_followup", "in_progress"):
        return "inflight"
    return "idle"


def _walk(w):
    yield w
    for c in w.winfo_children():
        yield from _walk(c)


def polish(root: tk.Misc) -> None:
    """Colour the classic (non-ttk) tk widgets ttk styling can't reach."""
    for w in _walk(root):
        cls = w.winfo_class()
        try:
            if cls == "Text":
                w.configure(background=P["surface"], foreground=P["text"],
                            insertbackground=P["accent"], relief="solid", borderwidth=1,
                            highlightthickness=1, highlightbackground=P["border"],
                            highlightcolor=P["accent"], padx=8, pady=6, font=FONT)
            elif cls == "Listbox":
                w.configure(background=P["surface"], foreground=P["text"],
                            relief="solid", borderwidth=1, highlightthickness=1,
                            highlightbackground=P["border"], highlightcolor=P["accent"],
                            selectbackground=P["accent"], selectforeground=P["on_color"],
                            activestyle="none", font=FONT)
            elif cls in ("Toplevel", "Tk"):
                w.configure(background=P["bg"])
        except tk.TclError:
            pass
