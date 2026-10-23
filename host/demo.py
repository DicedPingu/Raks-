"""Simulated bot players for --demo mode."""
import asyncio
import math
import random

from protocol import BUTTON_BIT, PadState


async def run_bot(manager, index):
    rnd = random.Random(index)
    player, _ = manager.join("bot-%d" % index, "Bot %d" % index, bot=True)
    if player is None:
        return
    phase = rnd.random() * 6.28
    buttons = 0
    next_press = 0.0
    t = 0.0
    try:
        while True:
            await asyncio.sleep(1 / 30)
            t += 1 / 30
            if t >= next_press:
                next_press = t + rnd.uniform(0.15, 0.7)
                bit = 1 << BUTTON_BIT[rnd.choice(["south", "east", "north", "west", "tl", "tr", "start"])]
                buttons ^= bit
                if rnd.random() < 0.3:
                    buttons = 0
            s = PadState(
                buttons=buttons,
                hx=rnd.choice([-1, 0, 0, 1]) if int(t * 2) % 5 == 0 else 0,
                hy=0,
                lx=int(math.sin(t * 1.3 + phase) * 30000), ly=int(math.cos(t * 1.3 + phase) * 30000),
                rx=int(math.sin(t * 0.7 + phase) * 22000), ry=int(math.cos(t * 1.9 + phase) * 22000),
                lt=int(max(0, math.sin(t + phase)) * 255), rt=int(max(0, math.cos(t * 0.8 + phase)) * 255))
            manager.apply_state(player, s)
    finally:
        manager.leave(player, reserve=False)
