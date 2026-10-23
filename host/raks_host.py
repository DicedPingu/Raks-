#!/usr/bin/env python3
"""Raks host: turn phones into virtual gamepads on Batocera / Linux.

Usage:  python3 host/raks_host.py [--demo] [--mock] [--pin 1234] [--port 8080] ...
"""
import argparse
import asyncio
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
    """Best-effort LAN IP (no packets are actually sent)."""
    for target in ("10.255.255.255", "192.168.255.255", "8.8.8.8"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((target, 1))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            pass
        finally:
            s.close()
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


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


def banner(srv, mode, mdns_on):
    big = "\n".join(["", "  ____       _        ", " |  _ \\ __ _| | _____ ", " | |_) / _` | |/ / __|",
                     " |  _ < (_| |   <\\__ \\", " |_| \\_\\__,_|_|\\_\\___/", ""])
    lines = [big, "  Raks %s - phones as wireless gamepads" % VERSION, "  Mode: %s" % mode, "",
             "  Scan with your phone, or open:", "      %s" % srv.url]
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
    ip = args.ip or detect_ip()
    srv = RaksServer(cfg, ROOT, mock=mock, ip=ip)
    await srv.start()
    responder = await mdns.start_mdns(cfg["hostname"], ip) if cfg["mdns"] else None
    banner(srv, mode, responder is not None)

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
