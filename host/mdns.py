"""Best-effort minimal mDNS responder: answers A queries for <hostname>.local."""
import asyncio
import logging
import socket
import struct

log = logging.getLogger("raks.mdns")
MCAST = "224.0.0.251"
PORT = 5353


def parse_questions(packet: bytes):
    """Return [(name, qtype)] for a DNS query packet (empty for responses/garbage)."""
    try:
        _, flags, qd = struct.unpack("!HHH", packet[:6])
        if flags & 0x8000:
            return []
        pos, out = 12, []
        for _ in range(qd):
            labels = []
            jumps = 0
            p = pos
            end = None
            while True:
                n = packet[p]
                if n == 0:
                    p += 1
                    break
                if n & 0xC0 == 0xC0:
                    if end is None:
                        end = p + 2
                    p = ((n & 0x3F) << 8) | packet[p + 1]
                    jumps += 1
                    if jumps > 8:
                        return []
                    continue
                labels.append(packet[p + 1:p + 1 + n].decode("ascii", "replace"))
                p += 1 + n
            pos = end if end is not None else p
            qtype, _qclass = struct.unpack("!HH", packet[pos:pos + 4])
            pos += 4
            out.append((".".join(labels).lower(), qtype))
        return out
    except (IndexError, struct.error):
        return []


def build_response(name: str, ip: str, ttl=120) -> bytes:
    qname = b"".join(bytes([len(l)]) + l.encode() for l in name.split(".")) + b"\0"
    header = struct.pack("!HHHHHH", 0, 0x8400, 0, 1, 0, 0)
    rr = qname + struct.pack("!HHIH", 1, 0x8001, ttl, 4) + socket.inet_aton(ip)
    return header + rr


class MDNSResponder(asyncio.DatagramProtocol):
    def __init__(self, name, ip):
        self.name = name.lower()
        self.ip = ip
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        for qname, qtype in parse_questions(data):
            if qname == self.name and qtype in (1, 255):
                self.transport.sendto(build_response(self.name, self.ip), (MCAST, PORT))
                return

    def announce(self):
        if self.transport:
            self.transport.sendto(build_response(self.name, self.ip), (MCAST, PORT))


async def start_mdns(hostname, ip):
    """Start the responder; returns it, or None if it cannot (best effort)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.bind(("", PORT))
        mreq = struct.pack("4s4s", socket.inet_aton(MCAST), socket.inet_aton(ip))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        sock.setblocking(False)
        loop = asyncio.get_running_loop()
        proto = MDNSResponder("%s.local" % hostname, ip)
        await loop.create_datagram_endpoint(lambda: proto, sock=sock)
        proto.announce()
        return proto
    except OSError as e:
        log.info("mDNS disabled (%s); use the IP address instead", e)
        return None
