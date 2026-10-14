"""Live video + game sound for the players (WebRTC, peer to peer).

The game window's own picture (with pings and the status bubble drawn in) and
the game's own sound are sent to each viewer over WebRTC. The lobby's WebSocket
is only used to set the connection up.
"""
import asyncio
import fractions
import time

import av
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.codecs import h264, vpx
from aiortc.contrib.media import MediaRelay
from aiortc.mediastreams import MediaStreamTrack, VideoStreamTrack
from PIL import Image

from . import audio, winutil

MAX_WIDTH = 1280
AUDIO_PTIME = 0.02  # 20 ms audio packets
AUDIO_SAMPLES = int(audio.SAMPLE_RATE * AUDIO_PTIME)

# RPG Maker pixel art and text smear at aiortc's default ~1 Mbps; give it more room.
for codec in (h264, vpx):
    codec.DEFAULT_BITRATE = 3_000_000
    codec.MAX_BITRATE = 6_000_000


class ScreenTrack(VideoStreamTrack):
    """The game picture, ~30 fps."""

    def __init__(self, get_image):
        super().__init__()
        self.get_image = get_image  # -> PIL image of the game (overlays included), or None

    def _grab(self):
        img = self.get_image()
        if img is None:
            return Image.new("RGB", (640, 480))
        if img.width > MAX_WIDTH:
            img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)), Image.BILINEAR)
        if img.width % 2 or img.height % 2:  # video encoders need even sizes
            img = img.crop((0, 0, img.width - img.width % 2, img.height - img.height % 2))
        return img

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        img = await asyncio.get_running_loop().run_in_executor(None, self._grab)
        frame = av.VideoFrame.from_image(img)
        frame.pts, frame.time_base = pts, time_base
        return frame


class GameSoundTrack(MediaStreamTrack):
    """The game's sound (silence if capture isn't available)."""

    kind = "audio"

    def __init__(self):
        super().__init__()
        self.source = None  # audio.GameAudio
        self._start = None
        self._pts = 0

    async def recv(self):
        if self._start is None:
            self._start = time.monotonic()
        else:
            self._pts += AUDIO_SAMPLES
            wait = self._start + self._pts / audio.SAMPLE_RATE - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
        nbytes = AUDIO_SAMPLES * audio.BYTES_PER_FRAME
        data = self.source.read(nbytes) if self.source else b"\x00" * nbytes
        frame = av.AudioFrame(format="s16", layout="stereo", samples=AUDIO_SAMPLES)
        frame.planes[0].update(data)
        frame.sample_rate = audio.SAMPLE_RATE
        frame.pts = self._pts
        frame.time_base = fractions.Fraction(1, audio.SAMPLE_RATE)
        return frame


class Streamer:
    """One shared capture, fanned out to a peer connection per viewer."""

    def __init__(self, get_image, use_stun, log):
        self.log = log
        self.video = ScreenTrack(get_image)
        self.sound = GameSoundTrack()
        self.relay = MediaRelay()
        # LAN/VPN mode uses no outside servers at all; online mode needs STUN to find a route.
        self.ice_urls = ["stun:stun.l.google.com:19302"] if use_stun else []
        self.config = RTCConfiguration(iceServers=[RTCIceServer(u) for u in self.ice_urls])
        self.peers = {}
        self._pid = None

    def set_game_process(self, hwnd):
        """(Re)start sound capture for the game's process, e.g. after a game restart."""
        pid = winutil.process_id(hwnd) if hwnd else None
        if pid == self._pid:
            return
        self._pid = pid
        if self.sound.source:
            self.sound.source.stop()
        self.sound.source = audio.GameAudio(pid, on_error=lambda e: self.log(f"Game sound unavailable: {e}")) \
            if pid else None

    async def offer(self, viewer_id):
        await self.close(viewer_id)
        pc = RTCPeerConnection(self.config)
        self.peers[viewer_id] = pc
        pc.addTrack(self.relay.subscribe(self.video))
        pc.addTrack(self.relay.subscribe(self.sound))

        @pc.on("connectionstatechange")
        async def on_state():
            if pc.connectionState == "failed":
                await self.close(viewer_id)

        await pc.setLocalDescription(await pc.createOffer())  # waits for ICE gathering
        return {"sdp": pc.localDescription.sdp, "sdpType": pc.localDescription.type,
                "iceServers": self.ice_urls}

    async def answer(self, viewer_id, sdp, sdp_type):
        pc = self.peers.get(viewer_id)
        if pc is not None:
            await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=sdp_type))

    async def close(self, viewer_id):
        pc = self.peers.pop(viewer_id, None)
        if pc is not None:
            await pc.close()

    async def shutdown(self):
        for viewer_id in list(self.peers):
            await self.close(viewer_id)
        self.video.stop()
        self.sound.stop()
        if self.sound.source:
            self.sound.source.stop(wait=True)
