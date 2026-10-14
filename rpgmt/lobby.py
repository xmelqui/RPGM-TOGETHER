"""Lobby state + the web server players connect to (aiohttp, runs on its own thread)."""
import asyncio
import collections
import hmac
import ipaddress
import itertools
import json
import pathlib
import secrets
import threading
import time
import unicodedata
import uuid

from aiohttp import WSMsgType, web

WEB_DIR = pathlib.Path(__file__).parent / "web"
HOST_ID = "host"
MAX_NAME = 24
PORT = 47800  # fixed so friends can type ip:port (any free port is used if it's taken)
COLORS = ["#ff5c8a", "#4cc9f0", "#ffd166", "#06d6a0", "#b388ff", "#ff9f43", "#f72585", "#90e0ef"]
HOST_COLOR = "#ffffff"
EMOTES = ["👍", "😂", "😮", "❤️", "👀", "❓"]
PING_BURST, PING_REFILL = 4, 0.6  # each player: up to 4 pings at once, then one every 0.6 s
CHAT_BURST, CHAT_REFILL = 5, 1.5  # up to 5 messages at once, then one every 1.5 s
DRAW_BURST, DRAW_REFILL = 40, 0.04  # drawing sends ~20 small updates a second while dragging
DRAW_POINTS_PER_MESSAGE = 64
DRAW_POINTS_PER_STROKE = 1500
MAX_CHAT = 200                    # characters per message
CHAT_HISTORY = 50                 # messages new players get when they join
MAX_PLAYERS = 16                  # friends per lobby (protects the host's PC and upload)
MAX_WS_MESSAGE = 64 * 1024        # bytes; the biggest real message (a WebRTC answer) is a few KB
STREAM_REQUEST_GAP = 3.0          # seconds between video (re)connections per player
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I mix-ups


def new_code():
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))


def clean_text(text, limit):
    """One line of visible text: drops control and invisible/format characters
    (zero-width spaces, right-to-left overrides...) that could fake names or messages."""
    text = "".join(" " if c.isspace() else c for c in str(text)
                   if c.isspace() or unicodedata.category(c) not in ("Cc", "Cf", "Cs", "Co"))
    return " ".join(text.split())[:limit]


def allowed_request(request):
    """Only pages served by this lobby may talk to it.

    - Host header must be an IP address, localhost or the Cloudflare link: stops
      "DNS rebinding" tricks where a website points its own name at this PC.
    - A browser's Origin header must match: stops other websites from silently
      joining in the background while a lobby is open.
    """
    hostname = (request.host or "").rsplit(":", 1)[0].strip("[]").lower()
    try:
        ipaddress.ip_address(hostname)
        host_ok = True
    except ValueError:
        host_ok = hostname == "localhost" or hostname.endswith(".trycloudflare.com")
    if not host_ok:
        return False
    origin = request.headers.get("Origin")
    if origin is None:
        return True  # not a browser (e.g. the RPGMT app's own checks)
    netloc = origin.split("://", 1)[-1].rstrip("/").lower()
    return netloc == (request.host or "").lower()


class RateLimit:
    def __init__(self, burst=PING_BURST, refill=PING_REFILL):
        self.burst, self.refill = burst, refill
        self.tokens, self.at = burst, time.monotonic()

    def allow(self):
        now = time.monotonic()
        self.tokens = min(self.burst, self.tokens + (now - self.at) / self.refill)
        self.at = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class Lobby:
    """All methods run on the lobby's asyncio loop; use the *_threadsafe helpers from elsewhere."""

    def __init__(self, host_name, on_release, on_change, on_ping=lambda *a: None, on_chat=lambda msg: None,
                 on_draw=lambda *a: None):
        self.on_release = on_release   # everyone has read -> advance the game
        self.on_change = on_change     # snapshot dict, for the host GUI
        self.on_ping = on_ping         # (name, color, kind, value): a viewer pinged or emoted
        self.on_chat = on_chat         # {"name", "color", "text", "host"}: a chat message
        self.on_draw = on_draw         # (player id, name, color, stroke id, [(x, y)...], done)
        self.chat = collections.deque(maxlen=CHAT_HISTORY)
        self.code = new_code()         # friends need it to join (it's in the link the host shares)
        self.tokens = {}               # player id -> secret for the still-picture endpoint
        self.players = {HOST_ID: {"name": host_name, "host": True, "color": HOST_COLOR}}
        self.pings_enabled = True
        self.chat_enabled = True
        # False: the host continues whenever they like; reads are only shown.
        # True: the game is held until everyone (host included) has read.
        self.blocking = False
        self.frame = None              # latest JPEG of the game (fallback when video can't connect)
        self.streamer = None           # stream.Streamer: live video + sound
        self.sockets = {}              # player id -> websocket
        self.message = None            # {"id", "text"}
        self.reads = set()
        self.advancing = False         # released, waiting for the game to show the next line
        self._ids = itertools.count(1)
        self._colors = itertools.count()
        self.loop = None
        self.port = None
        self._runner = None

    # --- state -----------------------------------------------------------
    def snapshot(self):
        return {
            "type": "state",
            "players": [
                {"id": pid, "name": p["name"], "host": p.get("host", False), "read": pid in self.reads,
                 "color": p["color"]}
                for pid, p in self.players.items()
            ],
            "message": self.message,
            "advancing": self.advancing,
            "blocking": self.blocking,
            "pings": self.pings_enabled,
            "chat": self.chat_enabled,
            "emotes": EMOTES,
        }

    async def broadcast(self):
        snap = self.snapshot()
        self.on_change(snap)
        # Players read on the host's stream: they only need to know a line is waiting.
        public = dict(snap, message={"id": snap["message"]["id"]} if snap["message"] else None)
        data = json.dumps(public)
        for ws in list(self.sockets.values()):
            try:
                await ws.send_str(data)
            except Exception:  # noqa: BLE001
                pass

    def _check_all_read(self):
        if not self.blocking:
            return  # the host advances on their own; reads are only displayed
        if self.message and not self.advancing and set(self.players) <= self.reads:
            self.advancing = True
            self.on_release()

    async def new_message(self, text):
        self.message = {"id": next(self._ids), "text": text}
        self.reads = set()
        self.advancing = False
        await self.broadcast()

    async def clear_message(self):
        self.message, self.reads, self.advancing = None, set(), False
        await self.broadcast()

    async def mark_read(self, pid, msg_id=None):
        if not self.message or pid not in self.players:
            return
        if msg_id is not None and msg_id != self.message["id"]:
            return  # stale click on an older line
        self.reads.add(pid)
        self._check_all_read()
        await self.broadcast()

    async def force_advance(self):
        if self.message and not self.advancing:
            self.reads = set(self.players)
            self._check_all_read()
            await self.broadcast()

    async def set_blocking(self, enabled):
        self.blocking = enabled
        self._check_all_read()
        await self.broadcast()

    async def set_chat(self, enabled):
        self.chat_enabled = enabled
        await self.broadcast()

    async def set_pings(self, enabled):
        self.pings_enabled = enabled
        await self.broadcast()

    async def send_chat(self, pid, text):
        """Post a chat message from a player (or the host) to everyone."""
        player = self.players.get(pid)
        text = clean_text(text, MAX_CHAT)
        if not player or not text or not self.chat_enabled:
            return
        if not player.get("host") and not player["chat_limit"].allow():
            return
        msg = {"type": "chat", "name": player["name"], "color": player["color"], "text": text,
               "host": bool(player.get("host"))}
        self.chat.append(msg)
        self.on_chat(msg)
        data = json.dumps(msg)
        for ws in list(self.sockets.values()):
            try:
                await ws.send_str(data)
            except Exception:  # noqa: BLE001
                pass

    def _handle_ping(self, pid, data):
        player = self.players.get(pid)
        if not self.pings_enabled or not player or not player["limit"].allow():
            return
        if data.get("type") == "ping":
            try:
                x, y = float(data["x"]), float(data["y"])
            except (KeyError, TypeError, ValueError):
                return
            if 0 <= x <= 1 and 0 <= y <= 1:
                self.on_ping(player["name"], player["color"], "ping", (x, y))
        elif data.get("emoji") in EMOTES:
            self.on_ping(player["name"], player["color"], "emote", data["emoji"])

    def _handle_draw(self, pid, data):
        """A piece of a line a viewer is drawing on the game picture."""
        player = self.players.get(pid)
        if not self.pings_enabled or not player or not player["draw_limit"].allow():
            return
        stroke = str(data.get("id", ""))[:16]
        raw = data.get("points")
        if not stroke or not isinstance(raw, list) or len(raw) > DRAW_POINTS_PER_MESSAGE:
            return
        points = []
        for pt in raw:
            try:
                x, y = float(pt[0]), float(pt[1])
            except (TypeError, ValueError, IndexError, KeyError):
                return
            if not (0 <= x <= 1 and 0 <= y <= 1):  # also rejects NaN
                return
            points.append((x, y))
        counts = player.setdefault("stroke_points", {})
        if len(counts) > 20:  # forget old strokes
            counts.clear()
        counts[stroke] = counts.get(stroke, 0) + len(points)
        if counts[stroke] > DRAW_POINTS_PER_STROKE:
            return
        self.on_draw(pid, player["name"], player["color"], stroke, points, bool(data.get("done")))

    async def kick(self, pid):
        ws = self.sockets.get(pid)
        if ws is not None:
            await ws.close()

    # --- thread-safe entry points ---------------------------------------
    def call(self, coro_fn, *args):
        if self.loop:
            asyncio.run_coroutine_threadsafe(coro_fn(*args), self.loop)

    # --- web server ------------------------------------------------------
    async def _index(self, request):
        if not allowed_request(request):
            raise web.HTTPForbidden()
        return web.FileResponse(WEB_DIR / "index.html", headers={
            "Content-Security-Policy": "default-src 'self'; img-src 'self' blob:; media-src 'self' blob:; "
                                       "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                                       "connect-src 'self' ws: wss:; frame-ancestors 'none'",
            "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})

    def _unique_name(self, wanted):
        taken = {p["name"].lower() for p in self.players.values()}
        name, n = wanted, 2
        while name.lower() in taken:  # nobody can pose as the host or as another friend
            name = f"{wanted[:MAX_NAME - 3]} {n}"
            n += 1
        return name

    async def _frame(self, request):
        if not allowed_request(request):
            raise web.HTTPForbidden()
        token = request.query.get("token", "")
        if not any(hmac.compare_digest(token, t) for t in self.tokens.values()):
            raise web.HTTPForbidden()
        if not self.pings_enabled or self.frame is None:
            return web.Response(status=204)
        return web.Response(body=self.frame, content_type="image/jpeg",
                            headers={"Cache-Control": "no-store"})

    async def _ws(self, request):
        if not allowed_request(request):
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=MAX_WS_MESSAGE)
        await ws.prepare(request)
        pid = None
        last_stream_request = 0.0
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                if not isinstance(data, dict):
                    continue
                kind = data.get("type")
                if kind == "join" and pid is None:
                    if not hmac.compare_digest(str(data.get("code", "")).strip().upper(), self.code):
                        await ws.send_str(json.dumps({"type": "join-error", "error": "code"}))
                        await asyncio.sleep(1)  # slows down guessing
                        break
                    if len(self.players) - 1 >= MAX_PLAYERS:
                        await ws.send_str(json.dumps({"type": "join-error", "error": "full"}))
                        break
                    name = self._unique_name(clean_text(data.get("name", ""), MAX_NAME) or "Player")
                    pid = uuid.uuid4().hex[:8]
                    color = COLORS[next(self._colors) % len(COLORS)]
                    self.players[pid] = {"name": name, "color": color, "limit": RateLimit(),
                                         "chat_limit": RateLimit(CHAT_BURST, CHAT_REFILL),
                                         "draw_limit": RateLimit(DRAW_BURST, DRAW_REFILL)}
                    self.sockets[pid] = ws
                    self.tokens[pid] = secrets.token_urlsafe(16)
                    await ws.send_str(json.dumps({"type": "welcome", "id": pid, "token": self.tokens[pid],
                                                  "name": name, "chat": list(self.chat)}))
                    await self.broadcast()
                elif kind == "read" and pid is not None:
                    await self.mark_read(pid, data.get("msgId"))
                elif kind == "chat" and pid is not None:
                    await self.send_chat(pid, data.get("text", ""))
                elif kind == "draw" and pid is not None:
                    self._handle_draw(pid, data)
                elif kind in ("ping", "emote") and pid is not None:
                    self._handle_ping(pid, data)
                elif kind == "stream-request" and pid is not None and self.streamer:
                    if time.monotonic() - last_stream_request < STREAM_REQUEST_GAP:
                        continue  # each request starts video encoding: don't let it be spammed
                    last_stream_request = time.monotonic()
                    try:
                        offer = await self.streamer.offer(pid)
                        await ws.send_str(json.dumps(dict(offer, type="offer")))
                    except Exception:  # noqa: BLE001 - viewer falls back to still pictures
                        await ws.send_str(json.dumps({"type": "stream-error", "error": "unavailable"}))
                elif kind == "answer" and pid is not None and self.streamer:
                    try:
                        await self.streamer.answer(pid, str(data.get("sdp", "")), "answer")
                    except Exception:  # noqa: BLE001 - a broken answer only affects that viewer
                        await ws.send_str(json.dumps({"type": "stream-error", "error": "bad answer"}))
        finally:
            if pid is not None:
                if self.streamer:
                    await self.streamer.close(pid)
                self.players.pop(pid, None)
                self.sockets.pop(pid, None)
                self.tokens.pop(pid, None)
                self.reads.discard(pid)
                self._check_all_read()  # a leaver shouldn't block everyone else
                await self.broadcast()
        return ws

    def start(self, port=PORT, host="127.0.0.1"):
        """Start the server on a background thread; returns the bound port.

        host "0.0.0.0" makes it reachable over the local network / a VPN like Hamachi."""
        started = threading.Event()

        def run():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            app = web.Application()
            app.router.add_get("/", self._index)
            app.router.add_get("/ws", self._ws)
            app.router.add_get("/frame", self._frame)
            self._runner = web.AppRunner(app, access_log=None)
            self.loop.run_until_complete(self._runner.setup())
            site = web.TCPSite(self._runner, host, port)
            try:
                self.loop.run_until_complete(site.start())
            except OSError:  # port taken (e.g. a second RPGMT): use any free one
                site = web.TCPSite(self._runner, host, 0)
                self.loop.run_until_complete(site.start())
            self.port = site._server.sockets[0].getsockname()[1]
            started.set()
            self.loop.run_forever()

        threading.Thread(target=run, daemon=True).start()
        started.wait(5)
        return self.port

    def stop(self):
        """Close everything and wait (up to a few seconds) until it's done."""
        if self.loop:
            async def shutdown():
                if self.streamer:
                    await self.streamer.shutdown()
                for ws in list(self.sockets.values()):
                    await ws.close()
                await self._runner.cleanup()
            try:
                asyncio.run_coroutine_threadsafe(shutdown(), self.loop).result(5)
            except Exception:  # noqa: BLE001 - shutting down anyway
                pass
            self.loop.call_soon_threadsafe(self.loop.stop)
