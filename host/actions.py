"""Whitelisted host actions. No shell, no arbitrary commands: only the argv lists below."""
import asyncio
import logging
import shutil

log = logging.getLogger("raks.actions")

ES_INIT = "/etc/init.d/S31emulationstation"

# name -> (config switch, argv)
ACTIONS = {
    "es_start":   ("es_start",   [ES_INIT, "start"]),
    "es_stop":    ("es_stop",    [ES_INIT, "stop"]),
    "es_restart": ("es_restart", [ES_INIT, "restart"]),
    "emukill":    ("emukill",    ["batocera-es-swissknife", "--emukill"]),
    "vol_up":     ("volume",     ["amixer", "-q", "sset", "Master", "5%+", "unmute"]),
    "vol_down":   ("volume",     ["amixer", "-q", "sset", "Master", "5%-", "unmute"]),
    "vol_mute":   ("volume",     ["amixer", "-q", "sset", "Master", "toggle"]),
    "reboot":     ("reboot",     ["reboot"]),
    "shutdown":   ("shutdown",   ["poweroff"]),
}


class HostActions:
    def __init__(self, enabled: dict, dry_run=False):
        self.enabled = enabled
        self.dry_run = dry_run   # mock mode: log instead of running

    def features(self):
        """Which actions the UI should offer: {action: bool}."""
        return {name: bool(self.enabled.get(sw)) for name, (sw, _) in ACTIONS.items()}

    async def run(self, name):
        spec = ACTIONS.get(name)
        if spec is None:
            return False, "unknown action"
        switch, argv = spec
        if not self.enabled.get(switch):
            return False, "disabled in config.json"
        if self.dry_run:
            log.info("[dry-run] would run %s", " ".join(argv))
            return True, "dry-run (mock mode)"
        if shutil.which(argv[0]) is None:
            return False, "%s not found on this system" % argv[0]
        log.warning("running host action %s: %s", name, " ".join(argv))
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            try:
                rc = await asyncio.wait_for(proc.wait(), 15)
            except asyncio.TimeoutError:
                proc.kill()
                return False, "timed out"
            return rc == 0, "ok" if rc == 0 else "exit code %d" % rc
        except OSError as e:
            return False, str(e)
