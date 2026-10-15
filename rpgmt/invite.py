"""Invite links: https://xmelqui.github.io/RPGM-TOGETHER/join/#<host>/<CODE>/<host name>

The part after "#" never leaves the friend's computer (browsers don't send it to
GitHub). The join page turns it into "Open in RPGMT" (an rpgmt:// link) and
"Watch in your browser" buttons. Only a VPN/LAN IP address or a Cloudflare tunnel
name is accepted, so invites can't point people at other websites.
"""
import re
import sys
import urllib.parse
import winreg

JOIN_PAGE = "https://xmelqui.github.io/RPGM-TOGETHER/join/"
SCHEME = "rpgmt"

_IPV4_PORT = re.compile(r"^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}:\d{2,5}$")
_TUNNEL = re.compile(r"^[a-z0-9-]{1,63}\.trycloudflare\.com$")
_CODE = re.compile(r"^[A-HJ-NP-Z2-9]{6}$")


def make(host, code, name=""):
    """Invite link for a lobby at host ("26.1.2.3:47800" or "x.trycloudflare.com")."""
    parts = [host, code] + ([name] if name else [])
    return JOIN_PAGE + "#" + "/".join(urllib.parse.quote(p, safe=":.") for p in parts)


def _check(host, code):
    host, code = host.lower(), code.upper()
    if not _CODE.match(code):
        return None
    if _IPV4_PORT.match(host) and 0 < int(host.rsplit(":", 1)[1]) < 65536:
        return "http", host, code
    if _TUNNEL.match(host):
        return "https", host, code
    return None


def parse(text):
    """(scheme, host, code) from an invite or rpgmt:// link, None if it isn't one,
    or raise ValueError if it is one but looks broken."""
    text = text.strip()
    if text.lower().startswith(SCHEME + "://"):
        parts = [p for p in urllib.parse.unquote(text[len(SCHEME) + 3:]).split("/") if p]
        if len(parts) < 3 or parts[0] != "join":
            raise ValueError("That RPGMT link looks broken. Ask the host to copy it again.")
        found = _check(parts[1], parts[2])
    elif text.startswith(JOIN_PAGE) or "github.io/RPGM-TOGETHER/join" in text:
        fragment = urllib.parse.unquote(urllib.parse.urlsplit(text).fragment)
        parts = fragment.split("/")
        found = _check(parts[0], parts[1]) if len(parts) >= 2 else None
    else:
        return None
    if found is None:
        raise ValueError("That invite link looks broken. Ask the host to copy it again.")
    return found


def register_protocol(exe):
    """Make rpgmt:// links open this RPGMT (current Windows user only, no admin needed)."""
    command = f'"{exe}" --open "%1"'
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{SCHEME}") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:RPGMT invite")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{SCHEME}\DefaultIcon") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{exe}",0')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{SCHEME}\shell\open\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
    except OSError:
        pass  # links just won't open the app; the browser option still works


def register_if_frozen():
    if getattr(sys, "frozen", False):
        register_protocol(sys.executable)
