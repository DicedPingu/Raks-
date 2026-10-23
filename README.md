# Raks

Use your phones as wireless gamepads for Batocera/Linux. Up to 8 players (4 by default), Android and iOS, no app install.

Each phone opens a web page served by the host, and the host creates one virtual gamepad per phone through `/dev/uinput`
("Raks Player 1…N"). EmulationStation and RetroArch see them as ordinary Xbox-360-style controllers.

* Host: one Python 3 script, **standard library only** (own HTTP + WebSocket + QR + mDNS), nothing to `pip install`.
* Client: a PWA in vanilla HTML/CSS/JS, no build step, no CDN, works on a LAN with no internet.
* Presets: NES, SNES, N64, GameCube, PlayStation, Generic. Full layout editor, hotkeys, host tools, trackpad/keyboard.
* **Demo mode** on both sides: try it without a host or without any phones.

## Quick start: Batocera

1. Copy this repo to the box (USB stick, `scp`, or `git clone` over SSH) and run:
   ```sh
   cd Raks- && ./install.sh
   /userdata/system/raks/run.sh start
   ```
   `install.sh` copies everything to `/userdata/system/raks`, keeps an existing `config.json`, and adds an idempotent block
   to `/userdata/system/custom.sh` so Raks starts on boot (`custom.sh` is called with `start`/`stop`).
   `./install.sh uninstall` removes it again.
2. Open `http://<batocera-ip>:8080/` on a screen (or read the terminal banner / `/tmp/raks.log`): there is a QR code.
3. On the phone: scan the QR → it opens the controller → pick a preset → play. A name is optional.
   Android: menu → *Add to Home screen* for fullscreen. iOS: Share → *Add to Home Screen*. Rotate to landscape.

`run.sh` loads the `uinput` module if `/dev/uinput` is missing. Batocera runs everything as root, so no udev rules are needed.
Pads appear for as long as a phone is connected and disappear when it leaves (a slot stays reserved for the same phone for 2 minutes).

## Quick start: dev PC / generic Linux

```sh
git clone https://github.com/DicedPingu/Raks-.git && cd Raks-
python3 host/raks_host.py            # real uinput if available, otherwise mock mode automatically
python3 host/raks_host.py --demo     # simulated bot players, never touches uinput
python3 host/raks_host.py --pin 1234 --port 9000 --max-players 6
python3 -m unittest discover -s tests
```

If `/dev/uinput` is not usable (no permission, module not loaded, macOS/Windows), the host switches to **mock mode**: all
events are logged to the console and shown live on `http://HOST:PORT/debug`. To use real pads: `sudo modprobe uinput`, then
either run as root or install `contrib/99-raks-uinput.rules` (group `input`) and `contrib/uinput.conf` (load at boot).
A systemd unit is in `contrib/raks.service`.

Options are in `config.json` (`--config` for another file; CLI flags override it):

| key | default | meaning |
|---|---|---|
| `port`, `bind` | 8080, 0.0.0.0 | listen address |
| `max_players` | 4 | 1–8 |
| `pin` | `""` | `""` = off, 4 digits, or `"random"` (a new PIN each start, shown in the banner) |
| `default_preset` | `snes` | preset phones start with |
| `hostname`, `mdns` | `raks`, true | answer `raks.local` (best-effort) |
| `allow_admin` | true | kick / rename / reassign from the System tab |
| `slot_reserve_seconds` | 120 | how long a leaving phone's slot is held |
| `uinput.vendor/product` | 0x045e / 0x028e | Xbox-360 ids |
| `actions.*` | see file | per-feature switches; `reboot` and `shutdown` are **false** by default |

## Demo mode

* **No host needed:** open the client and press **Try Demo** (or add `?demo` to the URL). You get the full UI plus a tiny
  playable shooter driven by the real controls, a live controller visualisation and an input log. All presets and Edit mode work.
  Open the page through the host (`http://HOST:PORT/play/?demo`) or from `localhost`; the service worker
  (offline cache) needs a secure context, so plain `http://192.168.x.x` pages are not cached by the browser. Once installed from
  `localhost`/HTTPS it is fully offline.
* **No phones needed:** `python3 host/raks_host.py --demo [--bots N]` starts bot players that wiggle sticks and press buttons.
  Watch them on `/` (slot status) and `/debug` (live controller per player).

## Using the app

* **☰ menu (top centre)**: *Layout* (presets, your layouts, Edit, Reset, export/import JSON), *Settings* (haptics, button size, opacity,
  left-handed mirror, latency display, hotkey button), *Hotkeys* (chord macros), *System* (host tools).
* **Edit mode**: drag to move, pinch (two fingers) or slider to resize, opacity, show/hide, change what a control sends, add/remove controls,
  *Save as* for multiple layouts (kept in `localStorage`), export/import as text. ⇆ moves the edit panel to the other side. Layouts are expressed in screen fractions so they scale to any display and respect notches.
* Sticks can be fixed or **floating**; D-pad and face buttons support sliding between buttons; sticks have a deadzone.
* Reconnects automatically with exponential backoff; the player number/colour is shown top centre with the latency.

## Preset → virtual pad mapping

The virtual pad is Linux's standard layout (what Batocera maps for an Xbox 360 pad). Face buttons are placed by *position*, like a
RetroPad, so "bottom button" is always `BTN_SOUTH`.

| Control | NES | SNES | N64 | GameCube | PlayStation | Generic |
|---|---|---|---|---|---|---|
| bottom (`BTN_SOUTH`) | B | B | A | A | Cross | A |
| right (`BTN_EAST`) | A | A | – | B | Circle | B |
| left (`BTN_WEST`) | – | Y | B | X | Square | X |
| top (`BTN_NORTH`) | – | X | – | Y | Triangle | Y |
| `BTN_TL` / `BTN_TR` | – | L / R | L / R | – / Z | L1 / R1 | LB / RB |
| `BTN_TL2` / `BTN_TR2` (+ analog `ABS_Z`/`ABS_RZ`) | – | – | Z / – | L / R (analog) | L2 / R2 (analog) | LT / RT (analog) |
| `BTN_SELECT` / `BTN_START` | Select / Start | Select / Start | – / Start | – / Start | Select / Start | Select / Start |
| `BTN_THUMBL` / `BTN_THUMBR` | – | – | – | – | L3 / R3 | L3 / R3 |
| D-pad | `ABS_HAT0X/Y` | same | same | same | same | same |
| left stick | – | – | `ABS_X/Y` | `ABS_X/Y` | `ABS_X/Y` | `ABS_X/Y` |
| right stick | – | – | C-buttons (see below) | C-stick `ABS_RX/RY` | `ABS_RX/RY` | `ABS_RX/RY` |

Notes: N64 C-buttons send right-stick directions (`rs_up/down/left/right`, i.e. `ABS_RY/RX`), which most N64 cores bind to C-buttons; if
yours uses buttons, select a C-button in Edit mode and change *Sends* to any button. GameCube A is the big bottom button, so it is `BTN_SOUTH`;
the GameCube B is `BTN_EAST`, X is `BTN_WEST`, Y is `BTN_NORTH`. Everything is remappable per control.
Your emulator's own button mapping still applies (e.g. RetroArch's SNES "B" is the bottom button).

## Hotkeys and host tools (System menu)

Hotkey chords are button macros sent by the phone (Exit = Hotkey+Start, Menu = Hotkey+South, Save/Load state = Hotkey+North/West,
Reset = Hotkey+East, Screenshot = Hotkey+L, Fast-forward = Hotkey+R, …). The *Hotkey button* (Settings) is `mode` by default;
choose `select` if that is your Batocera hotkey. **These defaults come from general Batocera/RetroArch conventions and
should be verified on your version**; they live in the `CHORDS` array at the top of `client/app.js`.

Host actions run only from a **fixed whitelist** (`host/actions.py`; no shell, no user-supplied arguments):
start/stop/restart EmulationStation (`/etc/init.d/S31emulationstation`), stop the running game (`batocera-es-swissknife --emukill`),
volume ±/mute (`amixer`), reboot, shutdown. Also: player list, kick, rename, reassign slots, and a trackpad/mouse
(second uinput device "Raks Mouse") plus text input and special keys (uinput device "Raks Keyboard") for navigating Linux menus.
Each can be switched off in `config.json`; reboot/shutdown ship disabled. With `--demo`/mock mode actions are dry-run only.

## Protocol

See [`docs/PROTOCOL.md`](docs/PROTOCOL.md): a 15-byte binary state frame (only sent on change, ≤60 Hz), small JSON control messages, RTT pings every 2 s.

## Layout of the repo

```
host/       raks_host.py (entry), server.py, ws.py, protocol.py, uinput.py, players.py, actions.py, qr.py, mdns.py, demo.py, web/
client/     PWA: index.html, app.js, demo.js, styles.css, sw.js, manifest.webmanifest, icons/
presets/    six preset layouts (+ index.json)
tests/      unittest suite (protocol, WebSocket framing, uinput packing, presets, players, server integration)
docs/       PROTOCOL.md
contrib/    systemd unit, udev rule, modules-load file
```

## Troubleshooting

* **"uinput unavailable, mock mode"** – `sudo modprobe uinput`; check `ls -l /dev/uinput`; run as root or use the udev rule. Batocera: run `./run.sh start` as root.
* **Phone can't reach the page** – same Wi-Fi/subnet? Guest/"client isolation" Wi-Fi blocks it. Check the firewall for the port. Use the IP URL if `raks.local` does not resolve (Android often lacks mDNS).
* **Pad not recognised in a game** – EmulationStation: *Main menu → Controller settings* and configure "Raks Player N" once. Batocera may match controllers by GUID, and all Raks pads share the Xbox 360 GUID with different names; if a game maps it wrongly, configure it once in ES.
* **Buttons ghost / stick drifts** – raise the deadzone in Settings; make sure nothing else is touching the controller area.
* **No vibration on iOS** – iOS Safari has no `navigator.vibrate`; haptics only work on Android.
* **iOS fullscreen** – only via *Add to Home Screen*; Safari cannot lock orientation, so rotate manually (a hint appears in portrait).
* **Screen turns off** – the Wake Lock API is used where supported (iOS 16.4+ and Android); keep the phone's auto-lock long otherwise.
* **Wrong PIN loop** – 5 wrong PINs lock that IP for 30 s.

## Android app and releases

A thin Android wrapper (WebView) around the same client/presets lives in `android/`. It bundles the PWA, so **Try Demo works
fully offline**; real play still needs a Raks host reachable on your LAN (enter its `ip:port`, name and PIN as in the browser).

* Minimum Android 7.0 (API 24). Landscape, fullscreen, keeps the screen on, Back navigates inside the app. Permissions: INTERNET, VIBRATE, WAKE_LOCK.
* Plain `http`/`ws` to the LAN host is allowed (Android cannot restrict cleartext to private IPs); the app loads only its bundled pages,
  blocks other web requests/navigation, and exposes no JavaScript bridge. Host actions remain the host-side whitelist.
* **The APK is debug-signed with a throwaway key, not a production signature.** Each build uses a different key, so uninstall the old
  one before installing a build from another run. No store/secret signing is configured.

**Get it:** download `raks-<version>-debug.apk` from the latest GitHub Release (or the `raks-release-assets` artifact of a CI run), verify
with `sha256sum -c SHA256SUMS.txt --ignore-missing`, copy it to the phone (USB, `adb install raks-<version>-debug.apk`, or a download link),
allow "install unknown apps" for your file manager, and open it. Then start the host (Quick start above), enter the host as `ip:port`
(e.g. `192.168.1.50:8080`) and connect.

**Build locally:** `sh android/build.sh` (JDK 17 + Android SDK with platform 34+ and build-tools; set `ANDROID_HOME`). Output: `android/build/raks-<version>-debug.apk`.

**Host bundle:** `python3 scripts/package_release.py` creates `dist/raks-<version>.tar.gz`, `.zip` and `SHA256SUMS.txt` (no tests/caches; with README, LICENSE, docs,
config). Unpack, then `python3 host/raks_host.py` or `./install.sh` on Batocera.

**Versioning / releasing:** `VERSION` in `host/server.py` is the single source (APK versionName, bundle name). Release: bump it, commit, push tag
`v<VERSION>`; the `Android APK and release` workflow fails if the tag differs, then publishes the APK, bundle and checksums.

## Security notes

Raks is meant for a **trusted home LAN only**. Do not expose the port to the internet. Traffic is plain HTTP/WS. The PIN (`pin` in
config or `--pin`) is required to join, which also protects the host tools, and failed attempts are rate-limited. Host actions
are a whitelist with fixed arguments, and dangerous ones (reboot/shutdown) are off by default. Incoming messages are size-limited
and validated; static files are served only from `client/` and `presets/` (path traversal blocked). The keyboard/mouse devices are created lazily and only if enabled.

## Decisions and assumptions

* PWA over a native app; HTTP/WebSocket over Bluetooth so any phone works with no install.
* uinput is implemented directly via the legacy `uinput_user_dev` interface (ctypes-free `fcntl`/`struct`); `python-evdev` is not used.
* Pads imitate an Xbox 360 controller (vendor 0x045e, product 0x028e) because every emulator ships a mapping for it.
* The QR generator is written from scratch (byte mode, ECC level M, versions 1–10) so no dependency or license is needed.
* The service worker needs a secure context, so offline install only works from `localhost`/HTTPS; on a plain-HTTP LAN the app
  still works while the host is up.
* Hotkey chord defaults and the ES init script path are best-effort and not verified on real Batocera hardware (see above).

## License

MIT, see [LICENSE](LICENSE).
