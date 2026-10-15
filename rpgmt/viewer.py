"""The window friends watch in: the host's live game with sound, chat, pings and drawing."""
import os
import urllib.error
import urllib.parse
import urllib.request

from . import invite
from .lobby import PORT


def lobby_url(address, name):
    """'26.1.2.3' / '26.1.2.3:47800/?code=ABC123' / 'https://x.trycloudflare.com/?code=..'
    -> page URL with the name (and the lobby code, if the link had one)."""
    address = address.strip()
    found = invite.parse(address)  # invite page / rpgmt:// link
    if found:
        scheme, host, code = found
        return f"{scheme}://{host}/?{urllib.parse.urlencode({'name': name or 'Player', 'code': code})}"
    if "://" not in address:
        address = "http://" + address
    parts = urllib.parse.urlsplit(address)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("That doesn't look like an RPGMT link (it should start with http:// or https://).")
    netloc = parts.netloc
    if parts.scheme == "http" and parts.port is None:
        netloc = f"{netloc}:{PORT}"
    params = {"name": name or "Player"}
    code = urllib.parse.parse_qs(parts.query).get("code")
    if code:
        params["code"] = code[0]
    return f"{parts.scheme}://{netloc}/?{urllib.parse.urlencode(params)}"


def check_reachable(url):
    """None if the host answers, otherwise a friendly reason."""
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            if r.status == 200:
                return None
            return f"The host answered with an error ({r.status})."
    except urllib.error.URLError as e:
        return (f"Couldn't reach the host ({e.reason}).\n\n"
                "Check that the address is right, that you're both on the same network or VPN, "
                "that the host's lobby is open, and that the host allowed RPGMT through the Windows firewall.")
    except OSError as e:
        return f"Couldn't reach the host ({e})."


def run(url):
    # Game sound should start without an extra click inside our own window.
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"
    import webview  # imported late: only joiners need it

    from . import __version__
    webview.create_window(f"RPGMT {__version__} - Watching", url, width=1100, height=900, min_size=(480, 480),
                          background_color="#14121f")
    from .theme import ICON
    webview.start(private_mode=False, icon=str(ICON))
    os._exit(0)  # window closed: end now, don't wait on background streaming threads
