"""Player slot management: one virtual gamepad per connected phone."""
import collections
import logging
import time

from protocol import BUTTONS, NEUTRAL, PadState
from uinput import diff_events, BTN_CODES

log = logging.getLogger("raks.players")

COLORS = ["#ff4d4d", "#4d9bff", "#3ddc84", "#ffd24d", "#c77dff", "#ff9f43", "#2ee6d6", "#ff7ac8"]
CODE_TO_BUTTON = {v: k for k, v in BTN_CODES.items()}


class Player:
    def __init__(self, slot, client_id, name, device, ws=None, bot=False):
        self.slot = slot
        self.client_id = client_id
        self.name = name
        self.device = device
        self.ws = ws
        self.bot = bot
        self.state = NEUTRAL
        self.latency = 0
        self.connected_at = time.time()

    @property
    def color(self):
        return COLORS[(self.slot - 1) % len(COLORS)]

    @property
    def pad_name(self):
        return "Raks Player %d" % self.slot


class PlayerManager:
    def __init__(self, max_players, device_factory, reserve_seconds=120, clock=time.monotonic):
        self.max_players = max_players
        self.device_factory = device_factory   # callable(pad_name) -> device with emit()/close()
        self.reserve_seconds = reserve_seconds
        self.clock = clock
        self.players = {}        # slot -> Player
        self.reservations = {}   # slot -> (client_id, expiry, name)
        self.events = collections.deque(maxlen=60)
        self.seq = 0
        self.dirty = True

    # ---- joining / leaving ------------------------------------------------
    def _expire(self):
        now = self.clock()
        for s in [s for s, (_, exp, _) in self.reservations.items() if exp <= now]:
            del self.reservations[s]

    def join(self, client_id, name="", ws=None, bot=False):
        """Return (player, resumed) or (None, False) if the server is full."""
        self._expire()
        for p in self.players.values():
            if p.client_id == client_id:           # reconnect while old socket still open
                p.ws = ws
                if name:
                    p.name = name
                self.dirty = True
                return p, True
        slot, resumed = None, False
        for s, (cid, _, rname) in self.reservations.items():
            if cid == client_id and s not in self.players:
                slot, resumed = s, True
                name = name or rname
                break
        if slot is None:
            free = [s for s in range(1, self.max_players + 1)
                    if s not in self.players and s not in self.reservations]
            if free:
                slot = free[0]
            else:  # steal the oldest reservation rather than turn a newcomer away
                stale = sorted((exp, s) for s, (_, exp, _) in self.reservations.items() if s not in self.players)
                if not stale:
                    return None, False
                slot = stale[0][1]
        self.reservations.pop(slot, None)
        player = Player(slot, client_id, name or "Player %d" % slot, None, ws, bot)
        player.device = self.device_factory(player.pad_name)
        self.players[slot] = player
        self.dirty = True
        log.info("slot %d <- %s (%s)", slot, player.name, "resumed" if resumed else "new")
        return player, resumed

    def leave(self, player, reserve=True):
        if self.players.get(player.slot) is not player:
            return
        del self.players[player.slot]
        player.device.close()
        if reserve and not player.bot:
            self.reservations[player.slot] = (player.client_id, self.clock() + self.reserve_seconds, player.name)
        self.dirty = True
        log.info("slot %d freed (%s)", player.slot, player.name)

    def close_all(self):
        for p in list(self.players.values()):
            self.leave(p, reserve=False)

    # ---- input ---------------------------------------------------------------
    def apply_state(self, player, new: PadState):
        old = player.state
        if new == old:
            return
        events = diff_events(old, new)
        player.state = new
        if not events:
            return
        player.device.emit(events)
        for etype, code, value in events:
            if etype == 1 and code in CODE_TO_BUTTON:
                self.seq += 1
                self.events.append((self.seq, player.slot, CODE_TO_BUTTON[code], value))
                if getattr(player.device, "mock", False) and not player.bot:
                    log.info("P%d %-6s %s", player.slot, CODE_TO_BUTTON[code], "DOWN" if value else "up")
        self.dirty = True

    # ---- admin ---------------------------------------------------------------
    def rename(self, slot, name):
        p = self.players.get(slot)
        if p and name:
            p.name = name
            self.dirty = True
        return p

    def assign(self, slot, new_slot):
        """Move a player to new_slot (swapping with whoever is there). Returns affected players."""
        p = self.players.get(slot)
        if not p or not 1 <= new_slot <= self.max_players or new_slot == slot:
            return []
        other = self.players.get(new_slot)
        moved = [p] + ([other] if other else [])
        for q in moved:
            q.device.close()
        del self.players[slot]
        self.players.pop(new_slot, None)
        self.reservations.pop(new_slot, None)
        p.slot = new_slot
        self.players[new_slot] = p
        if other:
            other.slot = slot
            self.players[slot] = other
        for q in moved:
            q.device = self.device_factory(q.pad_name)
            q.device.emit(diff_events(NEUTRAL, q.state))
        self.dirty = True
        return moved

    # ---- views ---------------------------------------------------------------
    def roster(self):
        self._expire()
        out = []
        for s in range(1, self.max_players + 1):
            p = self.players.get(s)
            if p:
                out.append({"slot": s, "color": p.color, "name": p.name, "status": "connected",
                            "bot": p.bot, "latency": p.latency})
            else:
                res = self.reservations.get(s)
                out.append({"slot": s, "color": COLORS[(s - 1) % len(COLORS)],
                            "name": res[2] if res else "", "status": "reserved" if res else "free",
                            "bot": False, "latency": 0})
        return out

    def snapshot(self):
        roster = self.roster()
        for r in roster:
            p = self.players.get(r["slot"])
            if p:
                s = p.state
                r.update(buttons=s.buttons, hx=s.hx, hy=s.hy, lx=s.lx, ly=s.ly,
                         rx=s.rx, ry=s.ry, lt=s.lt, rt=s.rt)
        evs = [{"seq": q, "slot": s, "button": b, "down": bool(v)} for q, s, b, v in list(self.events)[-20:]]
        return {"t": "snap", "players": roster, "events": evs, "buttons": BUTTONS}
