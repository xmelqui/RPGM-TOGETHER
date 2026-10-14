"""Dark theme shared by the launcher, host window and pop-ups (matches the viewer page)."""
import tkinter as tk
from tkinter import ttk

BG = "#14121f"        # window background
PANEL = "#1f1b33"     # cards
FIELD = "#2a2545"     # inputs
BORDER = "#3b3363"
TEXT = "#f1eefc"
MUTED = "#a59fc4"
ACCENT = "#7c6cff"
ACCENT_HOVER = "#6a5af0"
OK = "#3ecf8e"
WARN = "#f2b84b"
DANGER = "#ff5c7a"
FONT = "Segoe UI"


def apply(root):
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=TEXT, font=(FONT, 10), bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, troughcolor=FIELD, focuscolor=ACCENT,
                    selectbackground=ACCENT, selectforeground="white", insertcolor=TEXT)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=PANEL, relief="flat")
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Card.TLabel", background=PANEL, foreground=TEXT)
    style.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=(FONT, 9))
    style.configure("Title.TLabel", background=BG, foreground=TEXT, font=(FONT, 18, "bold"))
    style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=(FONT, 10))
    style.configure("Section.TLabel", background=PANEL, foreground=MUTED, font=(FONT, 9, "bold"))
    style.configure("Big.TLabel", background=PANEL, foreground=TEXT, font=(FONT, 12))
    style.configure("Pill.TLabel", background=PANEL, foreground=MUTED, font=(FONT, 10, "bold"), padding=(12, 4))

    style.configure("TButton", background=FIELD, foreground=TEXT, borderwidth=0, padding=(12, 6),
                    font=(FONT, 10))
    style.map("TButton", background=[("active", BORDER), ("disabled", PANEL)],
              foreground=[("disabled", MUTED)])
    for name, bg, hover in (("Accent", ACCENT, ACCENT_HOVER), ("Danger", "#c2415a", "#a8364d")):
        style.configure(f"{name}.TButton", background=bg, foreground="white", font=(FONT, 11, "bold"),
                        padding=(14, 9))
        style.map(f"{name}.TButton", background=[("active", hover)])
    style.configure("Big.TButton", background=ACCENT, foreground="white", font=(FONT, 11, "bold"),
                    padding=10, borderwidth=0)
    style.map("Big.TButton", background=[("active", ACCENT_HOVER)])

    for widget in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(widget, fieldbackground=FIELD, background=FIELD, foreground=TEXT,
                        arrowcolor=MUTED, bordercolor=BORDER, padding=4)
        style.map(widget, fieldbackground=[("readonly", FIELD), ("disabled", PANEL)],
                  foreground=[("readonly", TEXT), ("disabled", MUTED)],
                  bordercolor=[("focus", ACCENT)])
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.font", (FONT, 10))

    for widget in ("TCheckbutton", "TRadiobutton"):
        style.configure(widget, background=PANEL, foreground=TEXT, indicatorbackground=FIELD,
                        indicatorforeground="white", padding=(0, 3))
        style.map(widget, background=[("active", PANEL)],
                  indicatorbackground=[("selected", ACCENT), ("active", BORDER)])

    style.configure("TNotebook", background=PANEL, borderwidth=0, tabmargins=(0, 0, 0, 0),
                    bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL)
    style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(16, 6), borderwidth=0,
                    font=(FONT, 10, "bold"), bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL)
    style.map("TNotebook.Tab", background=[("selected", FIELD)], foreground=[("selected", TEXT)],
              lightcolor=[("selected", FIELD)], bordercolor=[("selected", PANEL)])
    style.configure("Vertical.TScrollbar", background=FIELD, troughcolor=PANEL, arrowcolor=MUTED,
                    borderwidth=0)
    return style


def text_widget(parent, **kw):
    """A tk.Text that fits the theme (tk widgets don't follow ttk styles)."""
    return tk.Text(parent, bg=FIELD, fg=TEXT, insertbackground=TEXT, relief="flat", bd=0,
                   highlightthickness=0, padx=8, pady=6, font=(FONT, 10), selectbackground=ACCENT, **kw)


def card(parent, title=None, padding=14):
    """A rounded-looking panel with an optional small section title. Returns its body frame."""
    outer = ttk.Frame(parent, style="Card.TFrame", padding=padding)
    if title:
        ttk.Label(outer, text=title.upper(), style="Section.TLabel").pack(anchor="w", pady=(0, 8))
    body = ttk.Frame(outer, style="Card.TFrame")
    body.pack(fill="both", expand=True)
    return outer, body
