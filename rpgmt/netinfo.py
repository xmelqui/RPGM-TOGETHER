"""This PC's addresses that friends can join on (local network or a VPN like Hamachi)."""
import ipaddress
import socket

# Well-known ranges of the popular "virtual LAN" apps, most likely first.
KNOWN = [
    ("Hamachi", ipaddress.ip_network("25.0.0.0/8")),
    ("Radmin VPN", ipaddress.ip_network("26.0.0.0/8")),
    ("Tailscale", ipaddress.ip_network("100.64.0.0/10")),
]


def label(ip):
    addr = ipaddress.ip_address(ip)
    for name, net in KNOWN:
        if addr in net:
            return name
    if addr.is_private:
        return "Local network / VPN"
    return "Public"


def join_addresses():
    """[(label, ip)] sorted so VPN addresses come first, then the home network."""
    try:
        ips = {info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except OSError:
        ips = set()
    ips = [ip for ip in ips if not ip.startswith(("127.", "169.254."))]
    order = {name: i for i, (name, _) in enumerate(KNOWN)}
    return sorted(((label(ip), ip) for ip in ips), key=lambda x: (order.get(x[0], len(order)), x[1]))
