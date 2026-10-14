"""First screen of the app: host a game or join one."""
import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from . import __version__, app, viewer, winutil

BG, PANEL, TEXT, MUTED, ACCENT = "#14121f", "#1f1b33", "#f1eefc", "#a59fc4", "#7c6cff"


class Launcher:
    def __init__(self, root):
        self.root = root
        self.choice = None
        settings = app.load_settings()
        root.title("RPGMT")
        root.configure(bg=BG)
        root.resizable(False, False)

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=PANEL)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 20, "bold"))
        style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI", 13, "bold"))
        style.configure("Hint.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Big.TButton", font=("Segoe UI", 11, "bold"), padding=10, background=ACCENT,
                        foreground="white", borderwidth=0)
        style.map("Big.TButton", background=[("active", "#6a5af0")])
        style.configure("TEntry", fieldbackground="#2a2545", foreground=TEXT, insertcolor=TEXT)

        frm = ttk.Frame(root, padding=24)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="RPGMT", style="Title.TLabel").pack(anchor="w")
        ttk.Label(frm, text=f"Read RPG Maker games together  ·  v{__version__}", style="Sub.TLabel").pack(anchor="w", pady=(0, 16))

        host = ttk.Frame(frm, style="Card.TFrame", padding=16)
        host.pack(fill="x", pady=(0, 12))
        ttk.Label(host, text="Host a game", style="Card.TLabel").pack(anchor="w")
        ttk.Label(host, text="You play; friends watch your game live and press Read.",
                  style="Hint.TLabel").pack(anchor="w", pady=(2, 10))
        ttk.Button(host, text="Host", style="Big.TButton", command=self.host).pack(fill="x")

        join = ttk.Frame(frm, style="Card.TFrame", padding=16)
        join.pack(fill="x")
        ttk.Label(join, text="Join a game", style="Card.TLabel").pack(anchor="w")
        ttk.Label(join, text="Your name", style="Hint.TLabel").pack(anchor="w", pady=(8, 2))
        self.name_var = tk.StringVar(value=settings.get("join_name", ""))
        ttk.Entry(join, textvariable=self.name_var, width=42).pack(fill="x", ipady=4)
        ttk.Label(join, text="Link from the host (e.g. http://26.1.2.3:47800/?code=K7P2QX)",
                  style="Hint.TLabel").pack(anchor="w", pady=(8, 2))
        self.addr_var = tk.StringVar(value=settings.get("join_address", ""))
        addr = ttk.Entry(join, textvariable=self.addr_var, width=42)
        addr.pack(fill="x", ipady=4)
        addr.bind("<Return>", lambda e: self.join())
        ttk.Button(join, text="Join", style="Big.TButton", command=self.join).pack(fill="x", pady=(12, 0))

    def host(self):
        self.choice = ("host", None)
        self.root.destroy()

    def join(self):
        name = self.name_var.get().strip() or "Player"
        address = self.addr_var.get().strip()
        if not address:
            messagebox.showinfo("RPGMT", "Ask the host for their address and paste it here.")
            return
        url = viewer.lobby_url(address, name)
        self.root.configure(cursor="watch")
        self.root.update()
        problem = viewer.check_reachable(url)
        self.root.configure(cursor="")
        if problem:
            messagebox.showwarning("RPGMT", problem)
            return
        settings = app.load_settings()
        settings.update(join_name=name, join_address=address)
        app.save_settings(settings)
        self.choice = ("join", url)
        self.root.destroy()


def main():
    winutil.set_dpi_aware()
    args = sys.argv[1:]
    if args[:1] == ["--selftest"]:
        from . import selftest
        ok = selftest.run()
        if "--quiet" not in args:
            os.startfile(selftest.REPORT)  # noqa: S606 - show the report to the user
        sys.exit(0 if ok else 1)
    if args[:1] == ["--host"]:
        app.main()
        return
    if args[:1] == ["--join"] and len(args) >= 2:
        viewer.run(viewer.lobby_url(args[1], args[2] if len(args) > 2 else "Player"))
        return

    root = tk.Tk()
    launcher = Launcher(root)
    root.mainloop()
    if not launcher.choice:
        return
    mode, url = launcher.choice
    if mode == "host":
        app.main()
    else:
        viewer.run(url)
