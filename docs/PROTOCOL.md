# Raks wire protocol (v1)

Transport: one WebSocket per phone (`ws://HOST:PORT/ws`), TCP_NODELAY on both ends.
Hand-written RFC 6455 server (`host/ws.py`): client frames are masked, server frames are not;
text, binary, ping/pong and close are supported. Messages from clients are capped at 4096 bytes.

* **Text frames** carry JSON objects with a string field `t` (message type).
* **Binary frames** carry controller state (high-rate, only sent on change, at most ~60 Hz).

A read-only viewer socket `ws://HOST:PORT/ws/view` (used by `/` and `/debug`) receives
`{"t":"snap",...}` snapshots (max 20/s, only on change) and `players` roster updates.

## Handshake

1. Client opens `/ws` and immediately sends
   `{"t":"hello","id":"<stable random id>","name":"Optional","pin":"1234","v":1}`.
   `id` is stored in `localStorage` and is how a reconnect gets the same slot back.
2. Host answers `{"t":"welcome","v":1,"slot":N,"name":..,"color":"#rrggbb","max":4,"resumed":bool,"features":{..},"info":{..},"default_preset":"snes"}`
   or `{"t":"error","code":"pin"|"full"|"uinput","msg":".."}` and closes.

A hello must arrive within 8 s. Idle sockets (no message for 20 s) are dropped; clients ping every 2 s.

## Binary: gamepad state (type `0x01`, 15 bytes, little-endian, `<BHbbhhhhBB`)

| offset | type | field | range |
|---|---|---|---|
| 0 | u8 | type = 1 | |
| 1 | u16 | buttons bitmask | bits below |
| 3 | i8 | hat X | -1 left, 0, +1 right |
| 4 | i8 | hat Y | -1 **up**, 0, +1 down |
| 5 | i16 | left stick X | -32768..32767 |
| 7 | i16 | left stick Y | up is negative |
| 9 | i16 | right stick X | |
| 11 | i16 | right stick Y | up is negative |
| 13 | u8 | left trigger (ABS_Z) | 0..255 |
| 14 | u8 | right trigger (ABS_RZ) | 0..255 |

Button bits (0 = LSB): `0 south, 1 east, 2 north, 3 west, 4 tl, 5 tr, 6 tl2, 7 tr2, 8 select, 9 start, 10 mode, 11 thumbl, 12 thumbr`.
They become `BTN_SOUTH, BTN_EAST, BTN_NORTH, BTN_WEST, BTN_TL, BTN_TR, BTN_TL2, BTN_TR2, BTN_SELECT, BTN_START, BTN_MODE, BTN_THUMBL, BTN_THUMBR`.
The frame is a full state; the host diffs it against the previous one and emits only the changed `EV_KEY`/`EV_ABS` events plus `SYN_REPORT`.
A digital `tl2`/`tr2` with trigger value 0 is reported as an analog value of 255.

## Binary: mouse (type `0x02`, 7 bytes, `<BhhbB`)

`type, dx:i16, dy:i16, wheel:i8, buttons:u8` (bit0 left, bit1 right, bit2 middle). Relative deltas.
Needs `actions.mouse` enabled; creates the shared "Raks Mouse" uinput device on first use.

## JSON messages

Client → host

| `t` | fields | meaning |
|---|---|---|
| `hello` | `id, name?, pin?, v` | first message |
| `ping` | `ts, lat?` | answered by `pong` with the same `ts`; `lat` is the client's last RTT in ms |
| `name` | `name` | rename self |
| `info` | | ask for host info/roster |
| `action` | `name` | whitelisted host action (see below) |
| `key` | `text` or `code` | type text (max 64 chars) / press one key on "Raks Keyboard" |
| `admin` | `op: kick\|rename\|assign`, `slot`, `name?`, `to?` | roster management (needs `allow_admin`) |

Host → client: `welcome`, `pong{ts}`, `players{players:[{slot,name,color,status,latency}]}`, `you{slot,name,color}` (slot changed),
`kicked`, `result{name,ok,msg}`, `info{info}`, `error{code,msg}`.

Host actions (fixed whitelist, each toggled in `config.json` → `actions`; no arbitrary shell):
`es_start, es_stop, es_restart, emukill, vol_up, vol_down, vol_mute, reboot, shutdown`.

## HTTP routes

`/` landing page (phones are redirected to `/play/`, add `?landing` to stay), `/play/*` the PWA, `/presets/*.json`,
`/debug` live controller states, `/api/info` JSON status, `/qr.svg` QR for the play URL.

## Preset / layout JSON

```json
{ "id": "snes", "name": "SNES", "version": 1,
  "controls": [
    {"id":"dpad","type":"dpad","x":0.16,"y":0.58,"size":0.4,"opacity":0.8,"visible":true,"maps":"hat"},
    {"id":"a","type":"button","code":"east","label":"A","shape":"circle","color":"#d33",...},
    {"id":"ls","type":"stick","stick":"left","mode":"fixed|floating", ...},
    {"id":"l2","type":"trigger","code":"tl2","analog":true, ...} ] }
```

`x`/`y` are the control centre as a fraction (0..1) of the play area, `size` is a fraction of the area height.
`code` is any of the button names above or `dpad_*`, `ls_*`, `rs_*` (stick directions), `lt`, `rt` (analog triggers).
