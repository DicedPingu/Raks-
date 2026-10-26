#!/usr/bin/env python3
"""Raks host: turn phones into virtual gamepads on Batocera / Linux.

Usage:  python3 host/raks_host.py [--demo] [--mock] [--pin 1234] [--port 8080] ...
"""
import argparse
import asyncio
import ipaddress
import logging
import os
import signal
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as config_mod  # noqa: E402
import demo  # noqa: E402
import mdns  # noqa: E402
import qr  # noqa: E402
import uinput  # noqa: E402
from server import RaksServer, VERSION  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def detect_ip():
    """Backward-compatible helper: return the first discovered local IPv4."""
    return discover_ips()[0]


def discover_ips(preferred=None):
    """Discover usable local IPv4 addresses in priority order."""
    out, seen = [], set()

    def add(ip):
        if not ip:
            return
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return
        if a.version != 4 or a.is_loopback or a.is_unspecified:
            return
        if ip in seen:
            return
        seen.add(ip)
        out.append(ip)

    add(preferred)
    for target in ("10.255.255.255", "192.168.255.255", "8.8.8.8"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((target, 1))
            add(s.getsockname()[0])
        except OSError:
            pass
        finally:
            s.close()

    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM)
        for info in infos:
            add(info[4][0])
    except OSError:
        pass
    return out or ["127.0.0.1"]


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Raks - phones as wireless gamepads")
    ap.add_argument("--config", default=os.path.join(ROOT, "config.json"))
    ap.add_argument("--port", type=int)
    ap.add_argument("--bind")
    ap.add_argument("--ip", help="IP to advertise (default: auto-detect)")
    ap.add_argument("--max-players", type=int)
    ap.add_argument("--pin", help='4-digit PIN, or "random"')
    ap.add_argument("--demo", action="store_true", help="simulated bot players, no uinput needed")
    ap.add_argument("--bots", type=int, default=2, help="number of bots in --demo mode")
    ap.add_argument("--mock", action="store_true", help="never touch /dev/uinput; just log events")
    ap.add_argument("--no-mdns", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap.parse_args(argv)


def banner(srv, mode, mdns_on, ips):
    big = "\n".join(["", "  ____       _        ", " |  _ \\ __ _| | _____ ", " | |_) / _` | |/ / __|",
                     " |  _ < (_| |   <\\__ \\", " |_| \\_\\__,_|_|\\_\\___/", ""])
    lines = [big, "  Raks %s - phones as wireless gamepads" % VERSION, "  Mode: %s" % mode, "",
             "  Open on your phone:", "      %s" % srv.url]
    if len(ips) > 1:
        lines.append("  Other local addresses (same host, same port):")
        for ip in ips[1:5]:
            lines.append("      http://%s:%d/play/" % (ip, srv.port))
        if len(ips) > 5:
            lines.append("      ...and %d more" % (len(ips) - 5))
    lines.append("  No Wi-Fi? Use Bluetooth/USB tethering, then pick the matching address above.")
    if mdns_on:
        lines.append("      http://%s.local:%d/play/   (if your phone supports mDNS)" % (srv.cfg["hostname"], srv.port))
    lines.append("  Landing page / debug: http://%s:%d/  and  /debug" % (srv.ip, srv.port))
    lines.append("  Players: up to %d" % srv.cfg["max_players"])
    lines.append("  PIN: %s" % (srv.pin if srv.pin else "off (set \"pin\" in config.json on shared networks)"))
    lines.append("")
    print("\n".join(lines))
    print(qr.to_ascii(qr.make_qr(srv.url), color=sys.stdout.isatty()))
    print("\n  Press Ctrl+C to stop.\n", flush=True)


async def amain(args):
    cfg = config_mod.load_config(args.config)
    if args.port is not None:
        cfg["port"] = args.port
    if args.bind:
        cfg["bind"] = args.bind
    if args.max_players:
        cfg["max_players"] = args.max_players
    if args.pin:
        cfg["pin"] = args.pin
    if args.no_mdns:
        cfg["mdns"] = False
    cfg = config_mod.validate(cfg)

    if args.demo or args.mock:
        mock, mode = True, "DEMO (simulated bots, no uinput)" if args.demo else "MOCK (events are only logged)"
    elif uinput.uinput_available(cfg["uinput"]["path"]):
        mock, mode = False, "REAL (virtual gamepads via %s)" % cfg["uinput"]["path"]
    else:
        mock, mode = True, ("MOCK - %s is not usable (try `modprobe uinput`, run as root); "
                            "events are only logged and shown on /debug" % cfg["uinput"]["path"])
    ips = discover_ips(args.ip)
    ip = ips[0]
    srv = RaksServer(cfg, ROOT, mock=mock, ip=ip)
    await srv.start()
    responder = await mdns.start_mdns(cfg["hostname"], ip) if cfg["mdns"] else None
    banner(srv, mode, responder is not None, ips)

    bots = []
    if args.demo:
        for i in range(1, min(args.bots, cfg["max_players"]) + 1):
            bots.append(asyncio.create_task(demo.run_bot(srv.manager, i)))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    try:
        await stop.wait()
    finally:
        for b in bots:
            b.cancel()
        await asyncio.gather(*bots, return_exceptions=True)
        await srv.stop()
        logging.getLogger("raks").info("bye")


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    try:
        asyncio.run(amain(args))
    except config_mod.ConfigError as e:
        sys.exit("config error: %s" % e)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
