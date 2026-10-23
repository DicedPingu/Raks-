"""Config loading with defaults and validation."""
import copy
import json
import os
import secrets

DEFAULTS = {
    "port": 8080,
    "bind": "0.0.0.0",
    "max_players": 4,
    "pin": "",                 # "" = off, "1234" = fixed PIN, "random" = new PIN every start
    "default_preset": "snes",
    "hostname": "raks",        # advertised as <hostname>.local via mDNS
    "mdns": True,
    "allow_admin": True,       # kick / rename / re-assign players from a phone
    "slot_reserve_seconds": 120,
    "uinput": {"path": "/dev/uinput", "vendor": 0x045E, "product": 0x028E},
    "actions": {
        "keyboard": True, "mouse": True, "volume": True,
        "es_start": True, "es_stop": True, "es_restart": True, "emukill": True,
        "reboot": False, "shutdown": False,
    },
}
MAX_PLAYERS_LIMIT = 8


class ConfigError(Exception):
    pass


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def validate(cfg):
    try:
        cfg["port"] = int(cfg["port"])
        cfg["max_players"] = int(cfg["max_players"])
        cfg["slot_reserve_seconds"] = float(cfg["slot_reserve_seconds"])
    except (TypeError, ValueError) as e:
        raise ConfigError("bad numeric setting: %s" % e)
    if not 1 <= cfg["port"] <= 65535:
        raise ConfigError("port must be 1-65535")
    cfg["max_players"] = max(1, min(MAX_PLAYERS_LIMIT, cfg["max_players"]))
    pin = str(cfg.get("pin") or "")
    if pin == "random":
        pin = "%04d" % secrets.randbelow(10000)
    elif pin and not (len(pin) == 4 and pin.isdigit()):
        raise ConfigError('pin must be "", "random" or exactly 4 digits')
    cfg["pin"] = pin
    cfg["actions"] = {k: bool(v) for k, v in cfg["actions"].items()}
    return cfg


def load_config(path=None):
    cfg = copy.deepcopy(DEFAULTS)
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                cfg = _merge(cfg, json.load(f))
        except (OSError, ValueError) as e:
            raise ConfigError("cannot read %s: %s" % (path, e))
    return validate(cfg)
