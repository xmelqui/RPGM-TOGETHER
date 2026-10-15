"""Host window: pick the game, create the lobby, share the link."""
import io
import json
import os
import queue
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from PIL import ImageTk

from . import __version__, netinfo, ocr, theme, wincap, winutil
from .detector import Detector, screen_text
from .gate import InputGate
from .lobby import HOST_ID, Lobby
from .overlay import Overlay, PingLayer, draw_overlays
from .stream import Streamer
from .tunnel import APP_DIR, Tunnel

SETTINGS = APP_DIR / "settings.json"
LOG_FILE = APP_DIR / "host.log"
DEFAULTS = {"name": "Host", "language": "", "network": "lan", "overlay": True, "clean": True, "pings": True, "blocking": False, "chat": True, "chat_ingame": True}
FRAME_INTERVAL = 0.3   # seconds between game pictures sent to the players' page
FRAME_WIDTH = 640


def load_settings():
    try:
        return {**DEFAULTS, **json.loads(SETTINGS.read_text("utf-8"))}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_settings(data):
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(data, indent=2), "utf-8")
    except OSError:
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()  # (callable,) posted from worker threads
        self.settings = load_settings()
        self.windows = []
        self._masks = []
        self._prev_state = None
        self._warned_screen_capture = False
        self._blocking = bool(self.settings["blocking"])  # read from worker threads
        self.lobby = None
        self.tunnel = None
        self.detector = None
        self.gate = InputGate(on_host_read=self._host_read)
        if self._blocking:
            self.gate.start()  # the keyboard/mouse hook is only needed for "hold the game"
        self._closing = False
        threading.Thread(target=self._watch_f8, daemon=True).start()
        self._build()
        self.ping_layer = PingLayer(root, self.selected_hwnd)
        self.ping_layer.chat_enabled = self.chat_ingame_var.get() and self.chat_var.get()
        self.overlay = Overlay(root, self.selected_hwnd)
        self.overlay.enabled = self.overlay_var.get()
        self.refresh_windows()
        self.root.after(100, self._pump)
        self.root.after(1000, self._watch_game)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # --- UI --------------------------------------------------------------
    def _build(self):
        r = self.root
        r.title("RPGMT - Host")
        r.minsize(1000, 700)
        theme.apply(r)
        main = ttk.Frame(r, padding=16)
        main.pack(fill="both", expand=True)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(1, weight=1)

        # --- header ---------------------------------------------------------
        head = ttk.Frame(main)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        head.columnconfigure(1, weight=1)
        ttk.Label(head, text="RPGMT", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(head, text=f"  Host  ·  v{__version__}", style="Sub.TLabel").grid(row=0, column=1, sticky="sw", pady=(0, 4))
        self.pill = tk.Label(head, text="●  Lobby closed", bg=theme.PANEL, fg=theme.MUTED,
                             font=(theme.FONT, 10, "bold"), padx=14, pady=5)
        self.pill.grid(row=0, column=2, sticky="e")

        left = ttk.Frame(main)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        right = ttk.Frame(main)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        # --- game -----------------------------------------------------------
        card, game = theme.card(left, "Game")
        card.pack(fill="x", pady=(0, 12))
        game.columnconfigure(1, weight=1)
        ttk.Label(game, text="Your name", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=3)
        self.name_var = tk.StringVar(value=self.settings["name"])
        ttk.Entry(game, textvariable=self.name_var).grid(row=0, column=1, columnspan=2, sticky="ew", pady=3)
        ttk.Label(game, text="Game window", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=3,
                                                                     padx=(0, 10))
        self.win_var = tk.StringVar()
        self.win_combo = ttk.Combobox(game, textvariable=self.win_var, state="readonly", width=28)
        self.win_combo.grid(row=1, column=1, sticky="ew", pady=3)
        self.win_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_window())
        ttk.Button(game, text="↻", width=3, command=self.refresh_windows).grid(row=1, column=2, padx=(6, 0))

        ttk.Label(game, text="Any text on the game screen counts as a line. Press F8 in menus.",
                  style="Muted.TLabel").grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 2))
        btns = ttk.Frame(game, style="Card.TFrame")
        btns.grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Button(btns, text="Test text reading", command=self.test_capture).pack(side="left")
        self.clean_var = tk.BooleanVar(value=self.settings["clean"])
        ttk.Checkbutton(game, text="Clean up text (white text on busy backgrounds)", variable=self.clean_var,
                        command=self._apply_clean).grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(game, text="OCR language", style="Card.TLabel").grid(row=6, column=0, sticky="w", pady=(6, 0))
        langs = ocr.available_languages()
        self.lang_var = tk.StringVar(value=self.settings["language"] if self.settings["language"] in langs
                                     else (langs[0] if langs else ""))
        ttk.Combobox(game, textvariable=self.lang_var, values=langs, state="readonly", width=10).grid(
            row=6, column=1, sticky="w", pady=(6, 0))

        # --- connection -----------------------------------------------------
        card, conn = theme.card(left, "Connection")
        card.pack(fill="x", pady=(0, 12))
        conn.columnconfigure(0, weight=1)
        self.network_var = tk.StringVar(value=self.settings["network"])
        ttk.Radiobutton(conn, text="Local network / VPN  (Hamachi, Radmin, ZeroTier...)",
                        value="lan", variable=self.network_var).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(conn, text="Online link through Cloudflare  (no VPN needed)",
                        value="online", variable=self.network_var).grid(row=1, column=0, columnspan=3, sticky="w")
        self.lobby_btn = ttk.Button(conn, text="Create Lobby", style="Accent.TButton", command=self.toggle_lobby)
        self.lobby_btn.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 8))
        self.link_var = tk.StringVar(value="")
        ttk.Entry(conn, textvariable=self.link_var, state="readonly").grid(row=3, column=0, sticky="ew")
        ttk.Button(conn, text="Copy", width=6, command=self.copy_link).grid(row=3, column=1, padx=(6, 0))
        ttk.Button(conn, text="Open", width=6, command=self.open_link).grid(row=3, column=2, padx=(6, 0))

        # --- options --------------------------------------------------------
        card, opts = theme.card(left, "Options")
        card.pack(fill="x")
        self.pings_var = tk.BooleanVar(value=self.settings["pings"])
        ttk.Checkbutton(opts, text="Let friends ping and draw", variable=self.pings_var,
                        command=self._apply_pings).grid(row=0, column=0, sticky="w", padx=(0, 16))
        self.overlay_var = tk.BooleanVar(value=self.settings["overlay"])
        ttk.Checkbutton(opts, text="Show status in-game", variable=self.overlay_var,
                        command=self._apply_overlay).grid(row=1, column=0, sticky="w", padx=(0, 16))
        self.chat_var = tk.BooleanVar(value=self.settings["chat"])
        ttk.Checkbutton(opts, text="Enable chat", variable=self.chat_var,
                        command=self._apply_chat).grid(row=0, column=1, sticky="w")
        self.chat_ingame_var = tk.BooleanVar(value=self.settings["chat_ingame"])
        ttk.Checkbutton(opts, text="Show chat in-game", variable=self.chat_ingame_var,
                        command=self._apply_chat_ingame).grid(row=1, column=1, sticky="w")
        self.blocking_var = tk.BooleanVar(value=self.settings["blocking"])
        ttk.Checkbutton(opts, text="Hold the game until everyone has read", variable=self.blocking_var,
                        command=self._apply_blocking).grid(row=2, column=0, columnspan=2, sticky="w")

        # --- now reading ----------------------------------------------------
        card, now = theme.card(right, "Now")
        card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        now.columnconfigure(0, weight=1)
        self.msg_label = ttk.Label(now, text="No dialogue yet", style="Big.TLabel", wraplength=480,
                                   justify="left")
        self.msg_label.grid(row=0, column=0, columnspan=3, sticky="w")
        self.players_label = ttk.Label(now, text="Nobody here yet", style="Muted.TLabel")
        self.players_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.status_label = ttk.Label(now, text="Detection: off", style="Muted.TLabel")
        self.status_label.grid(row=2, column=0, sticky="w", pady=(2, 0))
        self.pause_btn = ttk.Button(now, text="Pause (F8)", command=self.toggle_pause)
        self.pause_btn.grid(row=2, column=1, padx=(6, 0))
        ttk.Button(now, text="Force advance", command=self.force_advance).grid(row=2, column=2, padx=(6, 0))

        # --- chat / log -----------------------------------------------------
        card, box = theme.card(right, padding=8)
        card.grid(row=1, column=0, sticky="nsew")
        tabs = ttk.Notebook(box)
        tabs.pack(fill="both", expand=True)
        chat = ttk.Frame(tabs, style="Card.TFrame", padding=(0, 8, 0, 0))
        tabs.add(chat, text="Chat")
        chat.columnconfigure(0, weight=1)
        chat.rowconfigure(0, weight=1)
        self.chat_box = theme.text_widget(chat, height=8, state="disabled", wrap="word")
        self.chat_box.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.chat_entry = ttk.Entry(chat)
        self.chat_entry.grid(row=1, column=0, sticky="ew", pady=(8, 0), ipady=3)
        self.chat_entry.bind("<Return>", lambda e: self.send_chat())
        ttk.Button(chat, text="Send", style="Accent.TButton", command=self.send_chat).grid(
            row=1, column=1, padx=(8, 0), pady=(8, 0))
        log = ttk.Frame(tabs, style="Card.TFrame", padding=(0, 8, 0, 0))
        tabs.add(log, text="Log")
        log.columnconfigure(0, weight=1)
        log.rowconfigure(0, weight=1)
        self.log_box = theme.text_widget(log, height=8, state="disabled", wrap="word")
        self.log_box.grid(row=0, column=0, sticky="nsew")

    def log(self, text):
        self.events.put(lambda: self._log(text))

    def _log(self, text):
        line = f"{time.strftime('%H:%M:%S')}  {text}"
        try:
            if LOG_FILE.exists() and LOG_FILE.stat().st_size > 5 * 1024 * 1024:
                LOG_FILE.replace(LOG_FILE.with_suffix(".old.log"))  # keep one previous log
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _pump(self):
        try:
            while True:
                self.events.get_nowait()()
        except queue.Empty:
            pass
        # Our own windows must never be read as game text (refreshed here, on the UI thread).
        masks = [self.overlay.bbox] if self.overlay.bbox else []
        if self.root.state() == "normal":
            masks.append(winutil.window_rect(winutil.root_of(self.root.winfo_id())))
        self._masks = masks
        if self.detector:
            paused = " (paused)" if self.detector.paused else ""
            self.status_label.configure(text=f"Detection: {self.detector.last_reason or 'starting'}{paused}")
        self.root.after(100, self._pump)

    # --- settings -> components -----------------------------------------
    def refresh_windows(self):
        own = self.root.winfo_id()
        self.windows = [(h, t) for h, t in winutil.list_windows()
                        if winutil.root_of(h) != winutil.root_of(own) and t != "Program Manager"]
        self.win_combo["values"] = [t for _, t in self.windows]
        # Keep the selection by title; the combobox maps it to the new list.
        if self.win_var.get():
            self.win_var.set(self.win_var.get())

    def selected_hwnd(self):
        """The chosen game window. If the game was restarted (new window, same
        title), it's found again automatically."""
        idx = self.win_combo.current()
        hwnd = self.windows[idx][0] if 0 <= idx < len(self.windows) else None
        if hwnd and winutil.is_window(hwnd):
            return hwnd
        if not self.win_var.get():
            return None
        self.refresh_windows()
        idx = self.win_combo.current()
        hwnd = self.windows[idx][0] if 0 <= idx < len(self.windows) else None
        return hwnd if hwnd and winutil.is_window(hwnd) else None

    def _watch_game(self):
        """Follow the game across restarts while a lobby is running."""
        hwnd = self.selected_hwnd()
        if hwnd != self.gate.hwnd:
            if hwnd and self.gate.hwnd:
                self.log("Game window found again")
            self.gate.hwnd = hwnd
            if self.detector:
                self.detector.hwnd = hwnd
            if self.lobby and self.lobby.streamer and hwnd:
                self.lobby.streamer.set_game_process(hwnd)  # game restarted: follow its sound
        self.root.after(1000, self._watch_game)

    def _apply_window(self):
        hwnd = self.selected_hwnd()
        self.gate.hwnd = hwnd
        if self.detector:
            self.detector.hwnd = hwnd

    def test_capture(self):
        hwnd = self.selected_hwnd()
        if not hwnd:
            messagebox.showinfo("RPGMT", "Pick the game window first.")
            return
        self.root.withdraw()
        self.root.after(350, lambda: self._show_test(hwnd))

    def _show_test(self, hwnd):
        img = ocr.capture_region(hwnd, (0, 0, 1, 1))
        self.root.deiconify()
        if img is None:
            messagebox.showwarning("RPGMT", "Couldn't capture that window (is it minimized?).")
            return
        found = screen_text(ocr.Ocr(self.lang_var.get() or None, self.clean_var.get()).read_lines(img))
        text = (f"Counts as a line:  {found}" if found
                else "No line found (no sentence-like text on screen right now).")
        top = tk.Toplevel(self.root, bg=theme.BG)
        top.title("Text reading test")
        preview = img.copy()
        preview.thumbnail((800, 400))
        photo = ImageTk.PhotoImage(preview)
        lbl = ttk.Label(top, image=photo)
        lbl.image = photo
        lbl.pack(padx=8, pady=8)
        ttk.Label(top, text=text or "(no text found)", wraplength=780, justify="left").pack(padx=8, pady=(0, 8))

    # --- lobby -----------------------------------------------------------
    def toggle_lobby(self):
        if self.lobby:
            self.close_lobby()
        else:
            self.create_lobby()

    def create_lobby(self):
        hwnd = self.selected_hwnd()
        if not hwnd:
            messagebox.showinfo("RPGMT", "Pick the game window first.")
            return
        self.settings.update(name=self.name_var.get().strip() or "Host",
                             language=self.lang_var.get(), network=self.network_var.get(),
                             overlay=self.overlay_var.get(), clean=self.clean_var.get(),
                             pings=self.pings_var.get(), blocking=self.blocking_var.get(),
                             chat=self.chat_var.get(), chat_ingame=self.chat_ingame_var.get())
        save_settings(self.settings)

        self.lobby = Lobby(self.settings["name"], on_release=self._release,
                           on_change=lambda s: self.events.put(lambda: self._show_state(s)),
                           on_ping=lambda *a: self.events.put(lambda: self._on_ping(*a)),
                           on_chat=lambda m: self.events.put(lambda: self._on_chat(m)),
                           on_draw=lambda *a: self.events.put(lambda: self._on_draw(*a)))
        self.lobby.pings_enabled = self.pings_var.get()
        self.lobby.blocking = self._blocking
        self.lobby.chat_enabled = self.chat_var.get()
        online = self.network_var.get() == "online"
        self.gate.hwnd = hwnd
        self.lobby.streamer = Streamer(self._stream_image, use_stun=online, log=self.log)
        self.lobby.streamer.set_game_process(hwnd)
        threading.Thread(target=self._stream_frames, args=(self.lobby,), daemon=True).start()
        # LAN/VPN mode listens on every network adapter; online mode only for the tunnel.
        port = self.lobby.start(host="127.0.0.1" if online else "0.0.0.0")
        code = self.lobby.code
        local = f"http://127.0.0.1:{port}/?code={code}"
        self.log(f"Lobby code: {code}  (it's part of the link; friends typing the address need it)")

        self.detector = Detector(
            on_message=self._on_message,
            on_clear=self._on_clear,
            on_dialogue=self._on_dialogue,
            on_error=lambda e: self.log(f"OCR error: {e}"),
        )
        self.detector.hwnd = hwnd
        self.detector.language = self.lang_var.get() or None
        self.detector.clean = self.clean_var.get()
        self.detector.get_masks = lambda: self._masks
        self.detector.get_ping_boxes = lambda: self.ping_layer.boxes
        self.detector.start()

        if online:
            self.link_var.set("Creating online link...")
            self.tunnel = Tunnel(self.log)
            self.tunnel.start(
                port,
                on_url=lambda url: self.events.put(lambda: self._got_url(url)),
                on_error=lambda e: self.events.put(lambda: self._tunnel_failed(e, local)),
            )
        else:
            addresses = netinfo.join_addresses()
            if addresses:
                # Full http:// address: browsers otherwise try https and fail.
                self.link_var.set(f"http://{addresses[0][1]}:{port}/?code={code}")
                for name, ip in addresses:
                    self.log(f"Friends can join at http://{ip}:{port}/?code={code}  ({name})")
            else:
                self.link_var.set(local)
                self.log("No network adapter found - is your VPN connected?")
        self.lobby_btn.configure(text="Close Lobby", style="Danger.TButton")
        self._set_pill("●  Live", theme.OK)

    def _stream_image(self):           # stream threads
        """What viewers see: the game window's picture with pings and the bubble drawn in."""
        hwnd = self.gate.hwnd
        shot = ocr.capture_window(hwnd) if hwnd else None
        if shot is None:
            return None
        img, screen_left, _ = shot
        if screen_left is not None:
            if not self._warned_screen_capture:
                self._warned_screen_capture = True
                self.log("Game-only capture isn't available: viewers see this part of your SCREEN, "
                         "so keep other windows and notifications off the game")
            return img  # read from the screen: the overlay windows are already in it
        # No status bubble in the stream: viewers see who has read on their member list,
        # and the bubble would cover their chat. The host still sees it on screen.
        return draw_overlays(img, list(self.ping_layer.pings), list(self.ping_layer.emotes),
                             None, list(self.ping_layer.strokes.values()))

    def _got_url(self, url):
        self.link_var.set(f"{url}/?code={self.lobby.code}" if self.lobby else url)
        self.log("Online link ready - share it with your friends!")

    def _tunnel_failed(self, err, local):
        self.log(f"Couldn't create online link: {err}")
        self.link_var.set(local)

    def close_lobby(self):
        if self.detector:
            self.detector.stop()
        if self.tunnel:
            self.tunnel.stop()
        if self.lobby:
            self.lobby.stop()
        self.detector = self.tunnel = self.lobby = None
        self.gate.engaged = False
        self.link_var.set("")
        self.msg_label.configure(text="No dialogue yet")
        self.players_label.configure(text="Nobody here yet")
        self.overlay.set_state(None)
        self.status_label.configure(text="Detection: off")
        self.lobby_btn.configure(text="Create Lobby", style="Accent.TButton")
        self._set_pill("●  Lobby closed", theme.MUTED)
        self.log("Lobby closed")

    def open_link(self):
        link = self.link_var.get()
        if link and ":" in link:
            webbrowser.open(link if link.startswith("http") else f"http://{link}/")

    def copy_link(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.link_var.get())

    # --- glue between detector / gate / lobby ----------------------------
    def _on_dialogue(self):                # detector thread: text appeared, maybe still typing
        if self._blocking:
            self.gate.engaged = True

    def _on_message(self, text):          # detector thread
        if self._blocking:
            self.gate.engaged = True
        if self.lobby:
            self.lobby.call(self.lobby.new_message, text)

    def _on_clear(self):                   # detector thread
        self.gate.engaged = False
        if self.lobby:
            self.lobby.call(self.lobby.clear_message)

    def _host_read(self):                  # hook thread
        if self.lobby:
            self.lobby.call(self.lobby.mark_read, HOST_ID)

    def _release(self):                    # lobby loop: everyone has read
        # The gate stays engaged until the detector sees the next line (or none),
        # so a held/double-tapped key can't skip a line before players see it.
        detector = self.detector

        def sent():
            self.log("Enter sent to the game")
            if detector:
                # Only now can "the text didn't change" mean anything.
                detector.mark_advanced()

        self.gate.press_confirm(
            on_waiting=lambda: self.log("Everyone read - click the game window so RPGMT can press Enter"),
            on_sent=sent)

    def force_advance(self):
        if self.lobby:
            self.lobby.call(self.lobby.force_advance)

    def _watch_f8(self):                   # own thread
        """F8 (with the game in front) pauses / resumes. Polled rather than hooked:
        Windows can silently drop a keyboard hook when the app is busy streaming."""
        was_down = False
        while not self._closing:
            down = winutil.key_down(0x77)  # F8
            hwnd = self.gate.hwnd
            if down and not was_down and hwnd and winutil.is_foreground(hwnd):
                self.events.put(self.toggle_pause)
            was_down = down
            time.sleep(0.05)

    def toggle_pause(self):
        if not self.detector:
            return
        self.detector.paused = not self.detector.paused
        if self.detector.paused:
            self.gate.engaged = False
            self.overlay.flash("\u23f8 Paused  (F8 to resume)", theme.MUTED)
        else:
            self.overlay.flash("\u25b6 Resumed", theme.OK)
        self.pause_btn.configure(text="Resume (F8)" if self.detector.paused else "Pause (F8)")
        self.log("Paused - no reading status, game input is normal" if self.detector.paused else "Resumed")

    def _apply_clean(self):
        if self.detector:
            self.detector.clean = self.clean_var.get()

    def _apply_blocking(self):
        self._blocking = self.blocking_var.get()
        # The keyboard/mouse hook only runs while "hold the game" is on.
        if self._blocking:
            self.gate.start()
        else:
            self.gate.stop()  # hands the keys back right away
        if self.lobby:
            self.lobby.call(self.lobby.set_blocking, self._blocking)
        self.settings["blocking"] = self._blocking
        save_settings(self.settings)

    def _apply_pings(self):
        if self.lobby:
            self.lobby.call(self.lobby.set_pings, self.pings_var.get())

    def send_chat(self):
        text = self.chat_entry.get().strip()
        if not text:
            return
        if not self.chat_var.get():
            self._chat_line("RPGMT", "#777777", "Chat is turned off (Options > Enable chat).")
            return
        self.chat_entry.delete(0, "end")
        if self.lobby:
            self.lobby.call(self.lobby.send_chat, HOST_ID, text)
        else:
            self._chat_line("RPGMT", "#777777", "Create a lobby first to chat with friends.")

    def _on_chat(self, msg):
        self._chat_line(msg["name"], msg["color"], msg["text"])
        self.ping_layer.add_chat(msg["name"], msg["color"], msg["text"])

    def _chat_line(self, name, color, text):
        tag = f"name_{color}"
        self.chat_box.configure(state="normal")
        # The host window is light: draw white (host) names in the theme's purple instead.
        self.chat_box.tag_configure(tag, foreground=color,
                                    font=("Segoe UI", 9, "bold"))
        self.chat_box.insert("end", f"{time.strftime('%H:%M')} ", ("time",))
        self.chat_box.insert("end", name, (tag,))
        self.chat_box.insert("end", f": {text}\n")
        self.chat_box.tag_configure("time", foreground=theme.MUTED)
        self.chat_box.see("end")
        self.chat_box.configure(state="disabled")

    def _apply_chat_ingame(self):
        self.ping_layer.chat_enabled = self.chat_ingame_var.get() and self.chat_var.get()
        self._save_option("chat_ingame", self.chat_ingame_var.get())

    def _apply_chat(self):
        enabled = self.chat_var.get()
        self.ping_layer.chat_enabled = enabled and self.chat_ingame_var.get()
        if not enabled:
            self.ping_layer.chat = []
        if self.lobby:
            self.lobby.call(self.lobby.set_chat, enabled)
        self._save_option("chat", enabled)

    def _save_option(self, key, value):
        self.settings[key] = value
        save_settings(self.settings)

    def _on_draw(self, pid, name, color, stroke_id, points, done):
        if self.pings_var.get():
            self.ping_layer.add_stroke(pid, name, color, stroke_id, points, done)

    def _on_ping(self, name, color, kind, value):
        if not self.pings_var.get():
            return
        if kind == "ping":
            self.ping_layer.add_ping(name, color, *value)
        else:
            self.ping_layer.add_emote(name, color, value)

    def _stream_frames(self, lobby):
        """Low-fps JPEGs of the game for the players' page, so they can click on it."""
        while self.lobby is lobby:
            time.sleep(FRAME_INTERVAL)
            if not lobby.pings_enabled or not lobby.sockets:
                continue
            try:
                img = self._stream_image()
                if img is None:
                    continue
                if img.width > FRAME_WIDTH:
                    img = img.resize((FRAME_WIDTH, round(img.height * FRAME_WIDTH / img.width)))
                buf = io.BytesIO()
                img.save(buf, "JPEG", quality=60)
                lobby.frame = buf.getvalue()
            except Exception:  # noqa: BLE001 - a missed frame doesn't matter
                pass

    def _apply_overlay(self):
        self.overlay.enabled = self.overlay_var.get()

    def _show_state(self, s):
        self.overlay.set_state(s)
        msg = s["message"]
        self._log_changes(s)
        self.msg_label.configure(text=(f"{msg['name']}: " if msg and msg.get("name") else "")
                                 + (msg["text"] if msg else "-"))
        # Only show read marks for the people who count (friends, or everyone when holding the game).
        counts = lambda p: s.get("blocking") or not p["host"]  # noqa: E731
        parts = [("✓ " if p["read"] else "… ") * bool(msg and counts(p)) + p["name"]
                 for p in s["players"]]
        self.players_label.configure(text=f"{len(s['players'])} in lobby:  " + "   ".join(parts))
        friends = len(s["players"]) - 1
        self._set_pill(f"●  Live · {friends} friend{'s' if friends != 1 else ''}", theme.OK)

    def _set_pill(self, text, color):
        self.pill.configure(text=text, fg=color)

    def _log_changes(self, s):
        """Write what happens in the lobby to the log, to see why a line is stuck."""
        prev, self._prev_state = self._prev_state, s
        msg, old = s["message"], prev and prev["message"]
        if msg and (not old or old["id"] != msg["id"]):
            self.log(f"New line #{msg['id']}: {msg['text'][:60]}")
        elif old and not msg:
            self.log("Dialogue over")
        if msg and old and old["id"] == msg["id"]:
            was_read = {p["id"] for p in prev["players"] if p["read"]}
            for p in s["players"]:
                if p["read"] and p["id"] not in was_read:
                    self.log(f"{p['name']} read line #{msg['id']}")
        if s.get("advancing") and not (prev and prev.get("advancing")):
            self.log("Everyone read - advancing")
        if prev:
            names = {p["id"]: p["name"] for p in s["players"]}
            old_names = {p["id"]: p["name"] for p in prev["players"]}
            for pid in names.keys() - old_names.keys():
                self.log(f"{names[pid]} joined")
            for pid in old_names.keys() - names.keys():
                self.log(f"{old_names[pid]} left")

    def on_close(self):
        self.close_lobby()
        wincap.stop_all()
        self._closing = True
        self.gate.stop()
        self.root.destroy()


def main():
    winutil.set_dpi_aware()
    root = tk.Tk()
    App(root)
    root.mainloop()
    # Everything was closed above; end right away so no native helper thread
    # (video encoder, Windows audio) can trip up Python's final cleanup.
    os._exit(0)
