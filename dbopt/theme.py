"""A light, restrained visual theme for the Tkinter UI.

macOS's native `aqua` ttk theme ignores almost every colour option, so we switch
to `clam` and style it by hand: one blue accent used sparingly, soft neutral
surfaces, and buttons that actually look like buttons.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

PALETTE = {
    "bg":            "#f3f4f6",   # window background
    "surface":       "#ffffff",   # cards, tables, inputs
    "surface_alt":   "#eef0f3",   # table headings, inactive tabs
    "border":        "#d5d9df",
    "text":          "#1f2328",
    "muted":         "#66707b",
    "accent":        "#2f6feb",   # the one colour, used for primary actions
    "accent_hover":  "#255ad1",
    "accent_fg":     "#ffffff",
    "ok":            "#1a7f45",   # progress / "removed"
    "sel":           "#dbe7ff",   # row / list selection
}

FONT = ("Helvetica Neue", 12)
FONT_BOLD = ("Helvetica Neue", 12, "bold")
FONT_H1 = ("Helvetica Neue", 16, "bold")
FONT_MONO = ("Menlo", 11)

P = PALETTE


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
                    fieldbackground=P["surface"], font=FONT,
                    bordercolor=P["border"], lightcolor=P["border"],
                    darkcolor=P["border"], focuscolor=P["accent"])

    style.configure("TFrame", background=P["bg"])
    style.configure("TLabelframe", background=P["bg"], bordercolor=P["border"])
    style.configure("TLabelframe.Label", background=P["bg"], foreground=P["muted"])
    style.configure("TLabel", background=P["bg"], foreground=P["text"])
    style.configure("Muted.TLabel", background=P["bg"], foreground=P["muted"])
    style.configure("H1.TLabel", background=P["bg"], foreground=P["text"], font=FONT_H1)
    style.configure("Accentline.TFrame", background=P["accent"])

    # --- buttons: bordered, padded, obvious --------------------------------
    style.configure("TButton", background=P["surface"], foreground=P["text"],
                    bordercolor=P["border"], relief="raised", borderwidth=1,
                    padding=(13, 7), anchor="center")
    style.map("TButton",
              background=[("pressed", P["surface_alt"]), ("active", "#f6f8fb"),
                         ("disabled", P["bg"])],
              foreground=[("disabled", P["muted"])],
              bordercolor=[("focus", P["accent"]), ("active", P["accent"])])

    style.configure("Accent.TButton", background=P["accent"], foreground=P["accent_fg"],
                    bordercolor=P["accent"], relief="raised", borderwidth=1,
                    padding=(15, 7))
    style.map("Accent.TButton",
              background=[("pressed", P["accent_hover"]), ("active", P["accent_hover"]),
                         ("disabled", "#a9c2f5")],
              foreground=[("disabled", "#eef3fd")],
              bordercolor=[("!disabled", P["accent"])])

    # --- notebook --------------------------------------------------------
    style.configure("TNotebook", background=P["bg"], borderwidth=0, tabmargins=(6, 6, 6, 0))
    style.configure("TNotebook.Tab", background=P["surface_alt"], foreground=P["muted"],
                    padding=(16, 8), borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", P["surface"])],
              foreground=[("selected", P["text"])])

    # --- tables --------------------------------------------------------
    style.configure("Treeview", background=P["surface"], fieldbackground=P["surface"],
                    foreground=P["text"], rowheight=25, borderwidth=1, relief="solid")
    style.configure("Treeview.Heading", background=P["surface_alt"], foreground=P["muted"],
                    relief="flat", padding=6, font=FONT_BOLD)
    style.map("Treeview",
              background=[("selected", P["sel"])],
              foreground=[("selected", P["text"])])
    style.map("Treeview.Heading", background=[("active", P["border"])])

    # --- inputs --------------------------------------------------------
    for el in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(el, fieldbackground=P["surface"], background=P["surface"],
                        foreground=P["text"], bordercolor=P["border"],
                        arrowcolor=P["muted"], padding=4)
        style.map(el, bordercolor=[("focus", P["accent"])])
    style.configure("TCheckbutton", background=P["bg"], foreground=P["text"])
    style.map("TCheckbutton", background=[("active", P["bg"])])

    # --- progress ------------------------------------------------------
    style.configure("TProgressbar", background=P["ok"], troughcolor=P["surface_alt"],
                    bordercolor=P["surface_alt"], lightcolor=P["ok"], darkcolor=P["ok"],
                    thickness=10)


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
                            insertbackground=P["text"], relief="solid", borderwidth=1,
                            highlightthickness=1, highlightbackground=P["border"],
                            highlightcolor=P["accent"], padx=8, pady=6, font=FONT)
            elif cls == "Listbox":
                w.configure(background=P["surface"], foreground=P["text"],
                            relief="solid", borderwidth=1, highlightthickness=1,
                            highlightbackground=P["border"], highlightcolor=P["accent"],
                            selectbackground=P["sel"], selectforeground=P["text"],
                            activestyle="none", font=FONT)
            elif cls in ("Toplevel", "Tk"):
                w.configure(background=P["bg"])
        except tk.TclError:
            pass
