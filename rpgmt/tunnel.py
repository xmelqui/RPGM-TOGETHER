"""Gives the local lobby a public https link with zero setup.

Uses a Cloudflare "quick tunnel": no account, no port forwarding, no router
config. cloudflared.exe is downloaded from Cloudflare's official GitHub
releases on first use and cached next to the app's settings.
"""
import os
import pathlib
import re
import subprocess
import threading
import urllib.request

DOWNLOAD_URL = ("https://github.com/cloudflare/cloudflared/releases/latest/download/"
                "cloudflared-windows-amd64.exe")
# RPGMT_DATA_DIR lets tests (or a portable setup) keep settings somewhere else.
APP_DIR = pathlib.Path(os.environ.get("RPGMT_DATA_DIR")
                       or pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home())) / "RPGMT")
EXE = APP_DIR / "cloudflared.exe"
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def signed_by_cloudflare(path):
    """True if Windows says the file has a valid digital signature from Cloudflare."""
    script = ("$s = Get-AuthenticodeSignature -LiteralPath $env:RPGMT_CHECK_FILE; "
              "if ($s.Status -eq 'Valid' -and $s.SignerCertificate.Subject -match 'O=\"?Cloudflare') "
              "{ 'ok' } else { 'bad' }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, timeout=30,
                             env={**os.environ, "RPGMT_CHECK_FILE": str(path)},
                             creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.stdout.strip() == "ok"


def ensure_cloudflared(log):
    """Download cloudflared once; refuse to run it unless it's genuinely signed by Cloudflare."""
    if EXE.exists() and signed_by_cloudflare(EXE):
        return EXE
    APP_DIR.mkdir(parents=True, exist_ok=True)
    log("Downloading cloudflared (one-time, ~60 MB)...")
    tmp = EXE.with_suffix(".part")
    urllib.request.urlretrieve(DOWNLOAD_URL, tmp)
    if not signed_by_cloudflare(tmp):
        tmp.unlink(missing_ok=True)
        raise RuntimeError("the downloaded cloudflared.exe isn't signed by Cloudflare - not running it")
    tmp.replace(EXE)
    return EXE


class Tunnel:
    def __init__(self, log):
        self.log = log
        self.proc = None

    def start(self, port, on_url, on_error):
        def run():
            try:
                exe = ensure_cloudflared(self.log)
                self.proc = subprocess.Popen(
                    [str(exe), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                found = False
                for line in self.proc.stdout:
                    m = URL_RE.search(line)
                    if m and not found:
                        found = True
                        on_url(m.group(0))
                if not found:
                    on_error(RuntimeError("cloudflared exited without giving a link"))
            except Exception as e:  # noqa: BLE001
                on_error(e)

        threading.Thread(target=run, daemon=True).start()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
