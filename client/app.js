'use strict';
/* Raks client: mobile-first PWA gamepad. No build step, no dependencies. */
(() => {
const BUTTONS = ['south', 'east', 'north', 'west', 'tl', 'tr', 'tl2', 'tr2', 'select', 'start', 'mode', 'thumbl', 'thumbr'];
const CODES = BUTTONS.concat(['dpad_up', 'dpad_down', 'dpad_left', 'dpad_right', 'ls_up', 'ls_down', 'ls_left', 'ls_right',
  'rs_up', 'rs_down', 'rs_left', 'rs_right', 'lt', 'rt']);
const CODE_NAMES = { south: 'South (A / Cross)', east: 'East (B / Circle)', north: 'North (Y / Triangle)', west: 'West (X / Square)',
  tl: 'L1 / LB', tr: 'R1 / RB', tl2: 'L2 / LT (digital+analog)', tr2: 'R2 / RT (digital+analog)', select: 'Select / Back', start: 'Start',
  mode: 'Mode / Guide / Home', thumbl: 'L3 (stick click)', thumbr: 'R3 (stick click)', dpad_up: 'D-pad up', dpad_down: 'D-pad down',
  dpad_left: 'D-pad left', dpad_right: 'D-pad right', ls_up: 'Left stick up', ls_down: 'Left stick down', ls_left: 'Left stick left',
  ls_right: 'Left stick right', rs_up: 'Right stick up', rs_down: 'Right stick down', rs_left: 'Right stick left',
  rs_right: 'Right stick right', lt: 'Left trigger (analog full)', rt: 'Right trigger (analog full)' };
const TYPES = ['button', 'trigger', 'stick', 'dpad'];
const PRESET_IDS_FALLBACK = ['nes', 'snes', 'n64', 'gamecube', 'playstation', 'generic'];
const CHORDS = [
  { label: 'Exit game', keys: ['H', 'start'] }, { label: 'RetroArch menu', keys: ['H', 'south'] },
  { label: 'Save state', keys: ['H', 'north'] }, { label: 'Load state', keys: ['H', 'west'] },
  { label: 'Reset', keys: ['H', 'east'] }, { label: 'Screenshot', keys: ['H', 'tl'] },
  { label: 'Fast-forward', keys: ['H', 'tr'] }, { label: 'Next slot', keys: ['H', 'dpad_up'] },
  { label: 'Prev slot', keys: ['H', 'dpad_down'] }, { label: 'Select+Start', keys: ['select', 'start'] },
  { label: 'Hotkey tap', keys: ['H'] }];
const ACTION_LABELS = [['es_start', 'Start EmulationStation'], ['es_stop', 'Stop EmulationStation'], ['es_restart', 'Restart EmulationStation'],
  ['emukill', 'Stop running game'], ['vol_down', 'Volume −'], ['vol_up', 'Volume +'], ['vol_mute', 'Mute'],
  ['reboot', 'Reboot'], ['shutdown', 'Shut down']];
const DANGEROUS = new Set(['reboot', 'shutdown', 'es_stop', 'es_restart', 'emukill']);
const COLORS = ['#ff4d4d', '#4d9bff', '#3ddc84', '#ffd24d', '#c77dff', '#ff9f43', '#2ee6d6', '#ff7ac8'];

const $ = s => document.querySelector(s);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const clone = o => JSON.parse(JSON.stringify(o));
const store = {
  get(k, d) { try { const v = localStorage.getItem('raks.' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('raks.' + k, JSON.stringify(v)); } catch (e) { /* private mode */ } },
};

/* ------------------------------------------------------------------ settings */
const settings = Object.assign({ host: '', name: '', haptics: true, hapticMs: 12, scale: 1, opacity: 1, deadzone: 0.1,
  mirror: false, latency: true, hotkey: 'mode', layout: 'preset:snes' }, store.get('settings', {}));
const saveSettings = () => store.set('settings', settings);
let clientId = store.get('id', null);
if (!clientId) { clientId = 'c' + Math.random().toString(36).slice(2, 12); store.set('id', clientId); }

/* ------------------------------------------------------------------ pad state */
const Pad = {
  held: {}, analog: { lt: 0, rt: 0 }, sticks: { left: null, right: null }, last: '',
  press(code) { this.held[code] = (this.held[code] || 0) + 1; this.changed(); },
  release(code) { if (this.held[code] > 0) this.held[code]--; this.changed(); },
  setStick(side, v) { this.sticks[side] = v; this.changed(); },
  setAnalog(side, v) { this.analog[side] = v; this.changed(); },
  releaseAll() { this.held = {}; this.analog = { lt: 0, rt: 0 }; this.sticks = { left: null, right: null }; this.changed(); },
  compute() {
    const h = c => (this.held[c] > 0 ? 1 : 0);
    let b = 0;
    BUTTONS.forEach((n, i) => { if (h(n)) b |= 1 << i; });
    let lt = h('tl2') || h('lt') ? 255 : 0, rt = h('tr2') || h('rt') ? 255 : 0;
    lt = Math.max(lt, Math.round(this.analog.lt * 255)); rt = Math.max(rt, Math.round(this.analog.rt * 255));
    if (h('lt') || this.analog.lt >= 0.9) b |= 1 << 6;
    if (h('rt') || this.analog.rt >= 0.9) b |= 1 << 7;
    const axis = (side, p) => {
      const s = this.sticks[side];
      if (s) return [Math.round(s[0] * 32767), Math.round(s[1] * 32767)];
      return [(h(p + 'right') - h(p + 'left')) * 32767, (h(p + 'down') - h(p + 'up')) * 32767];
    };
    const [lx, ly] = axis('left', 'ls_'), [rx, ry] = axis('right', 'rs_');
    return { buttons: b, hx: h('dpad_right') - h('dpad_left'), hy: h('dpad_down') - h('dpad_up'), lx, ly, rx, ry, lt, rt };
  },
  changed(force) {
    const s = this.compute(), key = JSON.stringify(s);
    if (key === this.last && !force) return;
    this.last = key;
    Link.sendState(s);
  },
};

function packState(s) {
  const b = new ArrayBuffer(15), v = new DataView(b);
  v.setUint8(0, 1); v.setUint16(1, s.buttons, true); v.setInt8(3, s.hx); v.setInt8(4, s.hy);
  v.setInt16(5, s.lx, true); v.setInt16(7, s.ly, true); v.setInt16(9, s.rx, true); v.setInt16(11, s.ry, true);
  v.setUint8(13, s.lt); v.setUint8(14, s.rt);
  return b;
}
function packMouse(dx, dy, wheel, btn) {
  const b = new ArrayBuffer(7), v = new DataView(b);
  v.setUint8(0, 2); v.setInt16(1, dx, true); v.setInt16(3, dy, true); v.setInt8(5, wheel); v.setUint8(6, btn);
  return b;
}

/* ------------------------------------------------------------------ links (real host / demo) */
const Link = {
  mode: 'none', lastSend: 0, timer: 0, pending: null,
  sendState(s) {
    if (this.mode === 'demo') return RaksDemo.onState(s);
    if (this.mode !== 'net') return;
    this.pending = s;
    if (this.timer) return;
    const wait = Math.max(0, 16 - (performance.now() - this.lastSend));
    if (wait === 0) this.flush(); else this.timer = setTimeout(() => this.flush(), wait);
  },
  flush() {
    this.timer = 0;
    if (this.pending && Net.open()) { Net.ws.send(packState(this.pending)); this.lastSend = performance.now(); }
    this.pending = null;
  },
  sendMouse(dx, dy, wheel, btn) {
    if (this.mode === 'demo') { if (dx || dy || wheel) RaksDemo.log('mouse ' + dx + ',' + dy + (wheel ? ' wheel ' + wheel : '')); return; }
    if (Net.open()) Net.ws.send(packMouse(dx, dy, wheel, btn));
  },
  json(o) {
    if (this.mode === 'demo') return Demo.handle(o);
    if (Net.open()) Net.ws.send(JSON.stringify(o));
  },
};

const Net = {
  ws: null, wantOpen: false, backoff: 500, timer: 0, pingTimer: 0, rtt: 0, welcomed: false,
  features: {}, info: null, players: [], slot: 0, color: COLORS[0],
  open() { return this.ws && this.ws.readyState === 1; },
  url() {
    const h = settings.host.replace(/^\w+:\/\//, '').replace(/\/.*$/, '');
    return (location.protocol === 'https:' ? 'wss://' : 'ws://') + h + '/ws';
  },
  connect() {
    this.wantOpen = true; this.welcomed = false;
    clearTimeout(this.timer);
    ui.status('Connecting to ' + settings.host + '…', 'busy');
    let ws;
    try { ws = new WebSocket(this.url()); } catch (e) { ui.status('Invalid host address', 'err'); this.wantOpen = false; return; }
    this.ws = ws; ws.binaryType = 'arraybuffer';
    ws.onopen = () => {
      ws.send(JSON.stringify({ t: 'hello', v: 1, id: clientId, name: settings.name, pin: $('#pin').value || store.get('pin', '') }));
      clearInterval(this.pingTimer);
      this.pingTimer = setInterval(() => this.open() && ws.send(JSON.stringify({ t: 'ping', ts: performance.now(), lat: Math.round(this.rtt) })), 2000);
    };
    ws.onmessage = e => { if (typeof e.data === 'string') this.onMessage(JSON.parse(e.data)); };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      clearInterval(this.pingTimer); Pad.releaseAll();
      if (!this.wantOpen) return;
      if (this.welcomed) ui.reconnecting(true); else ui.status('Cannot reach the host. Retrying…', 'err');
      this.timer = setTimeout(() => this.connect(), this.backoff);
      this.backoff = Math.min(8000, this.backoff * 2);
    };
    ws.onerror = () => {};
  },
  disconnect() {
    this.wantOpen = false; clearTimeout(this.timer); clearInterval(this.pingTimer);
    if (this.ws) { try { this.ws.close(); } catch (e) { /* ignore */ } }
    this.ws = null; this.welcomed = false;
  },
  onMessage(m) {
    switch (m.t) {
      case 'welcome':
        this.welcomed = true; this.backoff = 500; this.features = m.features || {}; this.info = m.info; this.players = (m.info && m.info.players) || [];
        this.slot = m.slot; this.color = m.color; ui.reconnecting(false);
        store.set('pin', $('#pin').value || '');
        ui.enterStage('net'); ui.setPlayer(m.slot, m.color);
        if (!store.get('layoutChosen', false) && m.default_preset) Layouts.select('preset:' + m.default_preset, true);
        Pad.changed(true);
        if (m.mock) ui.toast('Host is in mock mode (no real gamepad)');
        break;
      case 'pong': this.rtt = performance.now() - m.ts; ui.latency(this.rtt); break;
      case 'error':
        this.wantOpen = false; ui.exitStage(); ui.status(m.msg || m.code, 'err');
        if (m.code === 'pin') { $('#pinrow').hidden = false; $('#pin').focus(); }
        break;
      case 'players': this.players = m.players; Menu.renderPlayers(); break;
      case 'you': this.slot = m.slot; this.color = m.color; ui.setPlayer(m.slot, m.color); ui.toast('You are now Player ' + m.slot); break;
      case 'kicked': this.wantOpen = false; ui.exitStage(); ui.status('You were removed by another player', 'err'); break;
      case 'result': ui.toast((m.ok ? '✓ ' : '✗ ') + m.name + (m.msg && m.msg !== 'ok' ? ': ' + m.msg : '')); break;
      case 'info': this.info = m.info; this.players = m.info.players; Menu.renderSystem(); break;
    }
  },
};

/* demo "host": answers system-menu requests locally */
const Demo = {
  slot: 1,
  features: { es_start: true, es_stop: true, es_restart: true, emukill: true, vol_up: true, vol_down: true, vol_mute: true, reboot: false, shutdown: false, keyboard: true, mouse: true, admin: true },
  players: [{ slot: 1, name: 'You', color: COLORS[0], status: 'connected', bot: false }, { slot: 2, name: 'Bot', color: COLORS[1], status: 'connected', bot: true },
    { slot: 3, name: '', color: COLORS[2], status: 'free', bot: false }, { slot: 4, name: '', color: COLORS[3], status: 'free', bot: false }],
  handle(m) {
    if (m.t === 'action') { ui.toast('Demo: ' + m.name + ' (simulated)'); RaksDemo.log('action ' + m.name); }
    else if (m.t === 'key') RaksDemo.log('key ' + (m.text || m.code));
    else if (m.t === 'admin') {
      const p = this.players.find(x => x.slot === m.slot);
      if (p && m.op === 'rename') p.name = m.name;
      if (p && m.op === 'kick') { p.status = 'free'; p.name = ''; }
      ui.toast('Demo: ' + m.op + ' (simulated)'); Menu.renderPlayers();
    } else if (m.t === 'name') { this.players[0].name = m.name || 'You'; Menu.renderPlayers(); }
  },
};
const sys = () => (Link.mode === 'demo' ? Demo : Net);

/* ------------------------------------------------------------------ layouts */
function validateLayout(o) {
  if (!o || typeof o !== 'object' || !Array.isArray(o.controls)) throw new Error('Not a Raks layout (missing "controls")');
  const out = { id: String(o.id || 'imported').slice(0, 40), name: String(o.name || 'Imported').slice(0, 32), version: 1,
    base: PRESETS[o.base] ? o.base : 'generic', controls: [] };
  const seen = new Set(), num = (v, a, b, d) => (typeof v === 'number' && isFinite(v) ? clamp(v, a, b) : d);
  o.controls.slice(0, 60).forEach((c, i) => {
    if (!c || !TYPES.includes(c.type)) throw new Error('Control ' + (i + 1) + ': unknown type ' + (c && c.type));
    let id = String(c.id || c.type + i).slice(0, 24); while (seen.has(id)) id += '_'; seen.add(id);
    const n = { id, type: c.type, x: num(c.x, 0, 1, .5), y: num(c.y, 0, 1, .5), size: num(c.size, .04, .8, .15),
      opacity: num(c.opacity, .1, 1, .8), visible: c.visible !== false };
    if (typeof c.label === 'string') n.label = c.label.slice(0, 6);
    if (/^#[0-9a-f]{6}$/i.test(c.color || '')) n.color = c.color;
    if (c.type === 'button' || c.type === 'trigger') {
      if (!CODES.includes(c.code)) throw new Error('Control ' + (i + 1) + ': unknown code ' + c.code);
      n.code = c.code; n.shape = c.shape === 'pill' || c.type === 'trigger' ? 'pill' : 'circle';
      if (c.type === 'trigger') n.analog = !!c.analog;
    } else if (c.type === 'stick') { n.stick = c.stick === 'right' ? 'right' : 'left'; n.mode = c.mode === 'fixed' ? 'fixed' : 'float'; }
    else n.maps = ['left', 'right'].includes(c.maps) ? c.maps : 'hat';
    out.controls.push(n);
  });
  return out;
}

const PRESETS = {};
let presetOrder = [];
const Layouts = {
  ref: settings.layout, layout: null,
  customs() { return store.get('layouts', {}); },
  saveCustoms(c) { store.set('layouts', c); },
  select(ref, auto) {
    let l = null;
    if (ref.startsWith('custom:')) l = this.customs()[ref.slice(7)];
    if (!l && PRESETS[ref.replace('preset:', '')]) { l = clone(PRESETS[ref.replace('preset:', '')]); ref = 'preset:' + l.id; }
    if (!l) { ref = 'preset:snes'; l = clone(PRESETS.snes); }
    this.ref = ref; this.layout = clone(l);
    settings.layout = ref; saveSettings(); if (!auto) store.set('layoutChosen', true);
    Stage.build();
  },
  commit() {
    const customs = this.customs();
    if (this.ref.startsWith('custom:')) customs[this.ref.slice(7)] = this.layout;
    else {
      const id = 'u' + Date.now().toString(36);
      this.layout = Object.assign(this.layout, { id, name: this.layout.name + ' (custom)', base: this.layout.id in PRESETS ? this.layout.id : 'generic' });
      customs[id] = this.layout; this.ref = 'custom:' + id; settings.layout = this.ref; saveSettings();
    }
    this.saveCustoms(customs);
  },
  saveAs(name) {
    const id = 'u' + Date.now().toString(36), customs = this.customs();
    const base = this.ref.startsWith('preset:') ? this.layout.id : (this.layout.base || 'generic');
    this.layout = Object.assign(this.layout, { id, name: name.slice(0, 32) || 'My layout', base });
    customs[id] = this.layout; this.saveCustoms(customs); this.ref = 'custom:' + id; settings.layout = this.ref; saveSettings();
  },
  remove() {
    if (!this.ref.startsWith('custom:')) return;
    const customs = this.customs(); delete customs[this.ref.slice(7)]; this.saveCustoms(customs);
    this.select('preset:' + (this.layout.base || 'generic'));
  },
  reset() {
    const base = this.ref.startsWith('custom:') ? this.layout.base : this.layout.id;
    const fresh = clone(PRESETS[base] || PRESETS.generic);
    if (this.ref.startsWith('custom:')) this.layout = Object.assign(fresh, { id: this.layout.id, name: this.layout.name, base });
    else this.layout = fresh;
    if (!editing) { if (this.ref.startsWith('custom:')) this.commit(); }
    Stage.build();
  },
};

async function loadPresets() {
  let ids = PRESET_IDS_FALLBACK;
  try { ids = await (await fetch('../presets/index.json')).json(); } catch (e) { /* use fallback */ }
  presetOrder = [];
  await Promise.all(ids.map(async id => {
    try {
      const j = await (await fetch('../presets/' + id + '.json')).json();
      PRESETS[id] = validateLayout(j); PRESETS[id].id = id;
    } catch (e) { console.warn('preset', id, e); }
  }));
  presetOrder = ids.filter(id => PRESETS[id]);
}

/* ------------------------------------------------------------------ stage: rendering + input */
const padEl = $('#pad');
let ctls = [], editing = false, selected = null, padRect = null;
const ptrs = new Map();   // play mode: pointerId -> control
const editPtrs = new Map();

const Stage = {
  build() {
    if (!Layouts.layout) return;
    Pad.releaseAll(); ptrs.clear(); padEl.innerHTML = ''; ctls = [];
    Layouts.layout.controls.forEach(c => {
      if (!c.visible && !editing) return;
      const o = { c, el: document.createElement('div'), pointers: new Set(), codes: [] };
      o.el.className = 'ctl ' + c.type + (c.visible ? '' : ' hidden');
      if (c.type === 'button' || c.type === 'trigger') {
        o.el.classList.add('btn'); if (c.shape === 'pill' || c.type === 'trigger') o.el.classList.add('pill');
        if (c.type === 'trigger' && c.analog) o.el.classList.add('analog');
        o.el.textContent = c.label != null ? c.label : c.code;
      } else if (c.type === 'stick') { o.el.classList.add('stick'); o.knob = document.createElement('div'); o.knob.className = 'knob'; o.el.appendChild(o.knob); }
      else if (c.type === 'dpad') { ['u', 'd', 'l', 'r'].forEach(k => { const a = document.createElement('div'); a.className = 'arm ' + k; o.el.appendChild(a); o['a' + k] = a; });
        const m = document.createElement('div'); m.className = 'm'; o.el.appendChild(m); }
      if (c.color) o.el.style.setProperty('--c', c.color);
      padEl.appendChild(o.el); ctls.push(o);
    });
    this.place();
    if (editing) Edit.refresh();
  },
  place() {
    padRect = padEl.getBoundingClientRect();
    const W = padRect.width, H = padRect.height;
    ctls.forEach(o => {
      const c = o.c, s = c.size * H * settings.scale, mirror = settings.mirror && !editing;
      o.w = (c.type === 'button' || c.type === 'trigger') && o.el.classList.contains('pill') ? s * 1.9 : s;
      o.h = o.el.classList.contains('pill') ? s * 0.62 : s;
      o.px = (mirror ? 1 - c.x : c.x) * W; o.py = c.y * H;
      Object.assign(o.el.style, { width: o.w + 'px', height: o.h + 'px', left: o.px + 'px', top: o.py + 'px' });
      o.el.style.setProperty('--s', Math.min(o.w, o.h * 1.6) + 'px');
      o.el.style.setProperty('--op', String(c.opacity * settings.opacity));
      if (o.knob) o.el.classList.add('idle');
      o.cx = o.px; o.cy = o.py;
    });
  },
  // pad-relative position of a client point
  rel(e) { return [e.clientX - padRect.left, e.clientY - padRect.top]; },
  /** Find the control under a point; lowest normalised distance wins. */
  hit(x, y, any) {
    let best = null, bn = 1;
    for (const o of ctls) {
      if (!o.c.visible && !any) continue;
      const dx = x - o.px, dy = y - o.py;
      let n;
      if (o.c.type === 'stick') n = Math.hypot(dx, dy) / (o.w / 2 * (any ? 1 : 1.8));
      else if (o.c.type === 'dpad') n = Math.max(Math.abs(dx), Math.abs(dy)) / (o.w / 2 * 1.05);
      else if (o.el.classList.contains('pill')) n = Math.max(Math.abs(dx) / (o.w / 2 * 1.1), Math.abs(dy) / (o.h / 2 * 1.3));
      else n = Math.hypot(dx, dy) / (o.w / 2 * 1.12);
      if (n <= bn) { best = o; bn = n; }
    }
    return best;
  },
};

function haptic() { if (settings.haptics && navigator.vibrate) navigator.vibrate(settings.hapticMs); }
const codesOf = c => c.codes || [c.code];

/* ---- play-mode control behaviours */
function attach(pid, o, e) {
  const t = o.c.type;
  if ((t === 'stick' || t === 'dpad') && o.pointers.size) return;
  ptrs.set(pid, o);
  if (t === 'button' || t === 'trigger') {
    o.pointers.add(pid);
    if (o.pointers.size === 1) {
      const analog = t === 'trigger' && o.c.analog && ['tl2', 'tr2', 'lt', 'rt'].includes(o.c.code);
      o.analogSide = analog ? (o.c.code === 'tl2' || o.c.code === 'lt' ? 'lt' : 'rt') : null;
      if (!o.analogSide) { o.codes = codesOf(o.c); o.codes.forEach(c => Pad.press(c)); }
      o.el.classList.add('down'); haptic();
    }
    if (o.analogSide) analogMove(o, e);
  } else if (t === 'dpad') { o.pointers.add(pid); haptic(); dpadMove(o, e); }
  else if (t === 'stick') { o.pointers.add(pid); stickDown(o, e); }
}
function detach(pid) {
  const o = ptrs.get(pid); if (!o) return;
  ptrs.delete(pid); o.pointers.delete(pid);
  const t = o.c.type;
  if (t === 'button' || t === 'trigger') {
    if (o.pointers.size === 0) {
      o.codes.forEach(c => Pad.release(c)); o.codes = [];
      if (o.analogSide) { Pad.setAnalog(o.analogSide, 0); o.analogSide = null; o.el.style.setProperty('--v', '0'); }
      o.el.classList.remove('down');
    }
  } else if (t === 'dpad') { if (o.pointers.size === 0) dpadSet(o, []); }
  else if (t === 'stick') { if (o.pointers.size === 0) stickUp(o); }
}
function analogMove(o, e) {
  const [, y] = Stage.rel(e);
  const v = clamp(0.35 + 0.65 * ((y - (o.py - o.h / 2)) / o.h), 0.1, 1);
  Pad.setAnalog(o.analogSide, v); o.el.style.setProperty('--v', v.toFixed(2));
}
function dpadSet(o, dirs) {
  const prefix = { hat: 'dpad_', left: 'ls_', right: 'rs_' }[o.c.maps || 'hat'];
  const want = new Set(dirs.map(d => prefix + d)), have = new Set(o.codes);
  have.forEach(c => { if (!want.has(c)) Pad.release(c); });
  want.forEach(c => { if (!have.has(c)) Pad.press(c); });
  o.codes = [...want];
  ['u', 'd', 'l', 'r'].forEach(k => o['a' + k].classList.toggle('on', dirs.includes({ u: 'up', d: 'down', l: 'left', r: 'right' }[k])));
}
function dpadMove(o, e) {
  const [x, y] = Stage.rel(e), dx = x - o.px, dy = y - o.py, d = Math.hypot(dx, dy), dirs = [];
  if (d > o.w * 0.09) {
    const ux = dx / d, uy = dy / d;
    if (ux > 0.38) dirs.push('right'); else if (ux < -0.38) dirs.push('left');
    if (uy > 0.38) dirs.push('down'); else if (uy < -0.38) dirs.push('up');
  }
  dpadSet(o, dirs);
}
function stickDown(o, e) {
  const [x, y] = Stage.rel(e);
  o.el.classList.remove('idle');
  if (o.c.mode !== 'fixed') {
    const r = o.w / 2;
    o.cx = clamp(x, r, padRect.width - r); o.cy = clamp(y, r, padRect.height - r);
    o.el.style.left = o.cx + 'px'; o.el.style.top = o.cy + 'px';
  } else { o.cx = o.px; o.cy = o.py; }
  haptic(); stickMove(o, e);
}
function stickMove(o, e) {
  const [x, y] = Stage.rel(e), r = o.w / 2;
  let dx = x - o.cx, dy = y - o.cy, d = Math.hypot(dx, dy);
  if (d > r) {
    if (o.c.mode !== 'fixed') { o.cx = clamp(o.cx + dx / d * (d - r), r, padRect.width - r); o.cy = clamp(o.cy + dy / d * (d - r), r, padRect.height - r);
      o.el.style.left = o.cx + 'px'; o.el.style.top = o.cy + 'px'; }
    dx = dx / d * r; dy = dy / d * r; d = r;
  }
  const dz = settings.deadzone, v = d / r, mag = v < dz ? 0 : (v - dz) / (1 - dz);
  const nx = d ? dx / d * mag : 0, ny = d ? dy / d * mag : 0;
  o.knob.style.transform = 'translate(' + dx + 'px,' + dy + 'px)';
  Pad.setStick(o.c.stick, [nx, ny]);
}
function stickUp(o) {
  o.knob.style.transform = ''; o.el.classList.add('idle');
  o.el.style.left = o.px + 'px'; o.el.style.top = o.py + 'px'; o.cx = o.px; o.cy = o.py;
  Pad.setStick(o.c.stick, null);
}

padEl.addEventListener('pointerdown', e => {
  e.preventDefault();
  try { padEl.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
  const [x, y] = Stage.rel(e);
  if (editing) return Edit.down(e, x, y);
  const o = Stage.hit(x, y, false);
  if (o) attach(e.pointerId, o, e);
});
padEl.addEventListener('pointermove', e => {
  e.preventDefault();
  const [x, y] = Stage.rel(e);
  if (editing) return Edit.move(e, x, y);
  const cur = ptrs.get(e.pointerId), t = cur && cur.c.type;
  if (!cur || t === 'button' || t === 'trigger') {
    // slide between face buttons (and pick up a button when sliding in from empty space)
    if (!cur && e.pressure === 0 && e.pointerType === 'mouse') return;
    if (!cur && !(e.buttons || e.pointerType === 'touch' || e.pointerType === 'pen')) return;
    const n = Stage.hit(x, y, false);
    if (n && n !== cur && (n.c.type === 'button' || n.c.type === 'trigger')) { if (cur) detach(e.pointerId); attach(e.pointerId, n, e); }
    else if (cur && !n) detach(e.pointerId);
    else if (cur && cur.analogSide) analogMove(cur, e);
  } else if (t === 'dpad') dpadMove(cur, e);
  else if (t === 'stick') stickMove(cur, e);
});
const upHandler = e => { if (editing) return Edit.up(e); detach(e.pointerId); };
padEl.addEventListener('pointerup', upHandler);
padEl.addEventListener('pointercancel', upHandler);
padEl.addEventListener('lostpointercapture', upHandler);
['touchstart', 'touchmove'].forEach(ev => padEl.addEventListener(ev, e => e.preventDefault(), { passive: false }));
document.addEventListener('contextmenu', e => e.preventDefault());
['gesturestart', 'gesturechange'].forEach(ev => document.addEventListener(ev, e => e.preventDefault()));
document.addEventListener('visibilitychange', () => { if (document.hidden) { Pad.releaseAll(); Stage.build(); } else ui.wake(); });
window.addEventListener('resize', () => { if (!$('#stage').hidden) Stage.place(); });
window.addEventListener('orientationchange', () => setTimeout(() => Stage.place(), 200));

/* ------------------------------------------------------------------ edit mode */
const Edit = {
  base: null,
  start() {
    editing = true; document.body.classList.add('editing'); $('#editbar').hidden = false;
    this.snap = JSON.stringify(Layouts.layout);
    selected = null; Stage.build(); this.refresh();
  },
  done() {
    editing = false; document.body.classList.remove('editing'); $('#editbar').hidden = true;
    if (JSON.stringify(Layouts.layout) !== this.snap) Layouts.commit();
    selected = null; Stage.build(); ui.toast('Layout saved: ' + Layouts.layout.name);
  },
  select(c) { selected = c; this.refresh(); },
  refresh() {
    const L = Layouts.layout, sel = $('#eb-select');
    sel.innerHTML = '';
    L.controls.forEach((c, i) => {
      const o = document.createElement('option');
      o.value = i; o.textContent = (i + 1) + '. ' + c.type + ' ' + (c.label || c.code || c.stick || '') + (c.visible ? '' : ' (hidden)');
      sel.appendChild(o);
    });
    $('#eb-props').hidden = !selected;
    ctls.forEach(o => o.el.classList.toggle('sel', o.c === selected));
    $('#eb-name').value = Layouts.ref.startsWith('custom:') ? L.name : '';
    if (!selected) return;
    sel.value = L.controls.indexOf(selected);
    $('#eb-label').value = selected.label != null ? selected.label : '';
    $('#eb-label').parentElement.hidden = !(selected.type === 'button' || selected.type === 'trigger');
    $('#eb-code-row').hidden = !(selected.type === 'button' || selected.type === 'trigger');
    if (selected.code) $('#eb-code').value = selected.code;
    $('#eb-size').value = Math.round(selected.size * 100); $('#eb-opacity').value = Math.round(selected.opacity * 100);
    $('#eb-visible').checked = selected.visible;
  },
  pick(e, x, y) { return Stage.hit(x, y, true); },
  baseline() {
    const mine = [...editPtrs.entries()].filter(([, p]) => p.o.c === selected);
    mine.forEach(([, p]) => { p.x0 = p.x; p.y0 = p.y; p.sx = selected.x; p.sy = selected.y; });
    this.pinch = mine.length >= 2 ? { d0: Math.hypot(mine[0][1].x - mine[1][1].x, mine[0][1].y - mine[1][1].y) || 1, s0: selected.size, a: mine[0][0], b: mine[1][0] } : null;
  },
  down(e, x, y) {
    const o = this.pick(e, x, y);
    if (!o) return;
    if (selected !== o.c) this.select(o.c);
    editPtrs.set(e.pointerId, { o, x, y }); this.baseline();
  },
  move(e, x, y) {
    const p = editPtrs.get(e.pointerId);
    if (!p || !selected) return;
    p.x = x; p.y = y;
    if (this.pinch) {
      const a = editPtrs.get(this.pinch.a), b = editPtrs.get(this.pinch.b);
      if (a && b) selected.size = clamp(this.pinch.s0 * Math.hypot(a.x - b.x, a.y - b.y) / this.pinch.d0, .05, .7);
    } else {
      selected.x = clamp(p.sx + (x - p.x0) / padRect.width, 0.02, 0.98);
      selected.y = clamp(p.sy + (y - p.y0) / padRect.height, 0.02, 0.98);
    }
    Stage.place();
    $('#eb-size').value = Math.round(selected.size * 100);
  },
  up(e) { editPtrs.delete(e.pointerId); if (selected) this.baseline(); },
  add(kind) {
    const L = Layouts.layout; let c;
    const id = kind + '_' + Date.now().toString(36);
    if (kind === 'button') c = { id, type: 'button', code: 'south', label: 'A', shape: 'circle', x: .5, y: .5, size: .16, opacity: .8, visible: true };
    else if (kind === 'trigger') c = { id, type: 'trigger', code: 'tl', label: 'L', shape: 'pill', analog: false, x: .5, y: .5, size: .15, opacity: .8, visible: true };
    else if (kind === 'stick-left' || kind === 'stick-right') c = { id, type: 'stick', stick: kind.slice(6), mode: 'float', x: .5, y: .5, size: .32, opacity: .8, visible: true };
    else c = { id, type: 'dpad', maps: 'hat', x: .5, y: .5, size: .4, opacity: .8, visible: true };
    L.controls.push(c); selected = c; Stage.build(); ui.toast('Added - drag it into place');
  },
};
function bindEdit() {
  const codeSel = $('#eb-code');
  CODES.forEach(c => { const o = document.createElement('option'); o.value = c; o.textContent = CODE_NAMES[c] || c; codeSel.appendChild(o); });
  const add = $('#eb-add');
  [['button', 'Button'], ['trigger', 'Shoulder / trigger'], ['stick-left', 'Left stick'], ['stick-right', 'Right stick'], ['dpad', 'D-pad']]
    .forEach(([v, t]) => { const o = document.createElement('option'); o.value = v; o.textContent = t; add.appendChild(o); });
  $('#eb-select').onchange = e => { Edit.select(Layouts.layout.controls[+e.target.value]); };
  const upd = fn => () => { if (selected) { fn(selected); Stage.build(); } };
  $('#eb-label').oninput = e => { if (selected) { selected.label = e.target.value; const o = ctls.find(x => x.c === selected); if (o && o.el.classList.contains('btn')) o.el.textContent = selected.label; } };
  codeSel.onchange = upd(c => { c.code = codeSel.value; if (c.label == null || c.label === '') c.label = c.code; });
  $('#eb-size').oninput = e => { if (selected) { selected.size = +e.target.value / 100; Stage.place(); } };
  $('#eb-opacity').oninput = e => { if (selected) { selected.opacity = +e.target.value / 100; Stage.place(); } };
  $('#eb-visible').onchange = upd(c => { c.visible = $('#eb-visible').checked; });
  $('#eb-delete').onclick = () => { if (selected) { const L = Layouts.layout; L.controls.splice(L.controls.indexOf(selected), 1); selected = null; Stage.build(); } };
  $('#eb-addbtn').onclick = () => Edit.add(add.value);
  $('#eb-saveas').onclick = () => { Layouts.saveAs($('#eb-name').value.trim()); Edit.refresh(); ui.toast('Saved as ' + Layouts.layout.name); };
  $('#eb-reset').onclick = () => { if (confirm('Reset this layout to its preset?')) { selected = null; Layouts.reset(); } };
  $('#eb-delete-layout').onclick = () => {
    if (!Layouts.ref.startsWith('custom:')) return ui.toast('Presets cannot be deleted');
    if (confirm('Delete layout "' + Layouts.layout.name + '"?')) { editing = false; document.body.classList.remove('editing'); $('#editbar').hidden = true; Layouts.remove(); }
  };
  $('#eb-done').onclick = () => Edit.done();
  $('#eb-side').onclick = () => $('#editbar').classList.toggle('left');
}

/* ------------------------------------------------------------------ menu */
const Menu = {
  open() { Pad.releaseAll(); $('#menu').hidden = false; this.renderAll(); },
  close() { $('#menu').hidden = true; },
  tab(name) {
    document.querySelectorAll('#tabs [data-tab]').forEach(b => b.classList.toggle('on', b.dataset.tab === name));
    document.querySelectorAll('.tab').forEach(t => { t.hidden = t.id !== 'tab-' + name; });
    if (name === 'system') { Link.json({ t: 'info' }); this.renderSystem(); }
  },
  renderAll() { this.renderLayouts(); this.renderSystem(); },
  chips(el, items, onClick, active) {
    el.innerHTML = '';
    items.forEach(([id, label]) => { const b = document.createElement('button'); b.textContent = label; if (id === active) b.classList.add('on'); b.onclick = () => onClick(id); el.appendChild(b); });
    return el;
  },
  renderLayouts() {
    this.chips($('#presets'), presetOrder.map(id => ['preset:' + id, PRESETS[id].name]), id => { Layouts.select(id); this.close(); }, Layouts.ref);
    const cs = Layouts.customs(), ids = Object.keys(cs);
    this.chips($('#customs'), ids.map(id => ['custom:' + id, cs[id].name]), id => { Layouts.select(id); this.close(); }, Layouts.ref);
    if (!ids.length) $('#customs').innerHTML = '<span class="hint">None yet - press "Edit layout", change something, then Done.</span>';
  },
  renderPlayers() {
    const box = $('#players'); if (!box) return; box.innerHTML = '';
    const S = sys(), feats = S.features || {};
    (S.players || []).forEach(p => {
      const row = document.createElement('div'); row.className = 'pl'; row.style.setProperty('--c', p.color);
      const n = document.createElement('b'); n.textContent = 'P' + p.slot; row.appendChild(n);
      if (p.status === 'free') { const t = document.createElement('span'); t.className = 'hint'; t.textContent = 'free'; row.appendChild(t); box.appendChild(row); return; }
      const inp = document.createElement('input'); inp.value = p.name; inp.maxLength = 24; inp.disabled = !feats.admin && p.slot !== S.slot;
      inp.onchange = () => Link.json({ t: 'admin', op: 'rename', slot: p.slot, name: inp.value });
      row.appendChild(inp);
      if (feats.admin) {
        const sl = document.createElement('select');
        (S.players || []).forEach(q => { const o = document.createElement('option'); o.value = q.slot; o.textContent = 'slot ' + q.slot; sl.appendChild(o); });
        sl.value = p.slot; sl.onchange = () => Link.json({ t: 'admin', op: 'assign', slot: p.slot, to: +sl.value });
        row.appendChild(sl);
        if (p.slot !== S.slot) { const k = document.createElement('button'); k.textContent = 'Kick'; k.onclick = () => confirm('Kick ' + p.name + '?') && Link.json({ t: 'admin', op: 'kick', slot: p.slot }); row.appendChild(k); }
      }
      box.appendChild(row);
    });
  },
  renderSystem() {
    const S = sys(), f = S.features || {};
    const info = Link.mode === 'demo' ? { url: 'demo mode (no host)', mock: true } : (Net.info || {});
    $('#sysinfo').textContent = (info.url || '') + (info.mock ? '  ·  mock/demo host' : '') + (info.uptime != null ? '  ·  up ' + Math.round(info.uptime / 60) + ' min' : '');
    this.renderPlayers();
    const box = $('#actions'); box.innerHTML = '';
    ACTION_LABELS.forEach(([id, label]) => {
      const b = document.createElement('button'); b.textContent = label; b.disabled = !f[id]; if (DANGEROUS.has(id)) b.classList.add('danger');
      b.title = f[id] ? '' : 'Disabled in the host config.json';
      b.onclick = () => { if (DANGEROUS.has(id) && !confirm(label + '?')) return; Link.json({ t: 'action', name: id }); };
      box.appendChild(b);
    });
    $('#btn-touchpad').disabled = !(f.mouse || f.keyboard);
  },
};

function bindMenu() {
  $('#btn-menu').onclick = () => Menu.open();
  $('#btn-menu-close').onclick = () => Menu.close();
  document.querySelectorAll('#tabs [data-tab]').forEach(b => { b.onclick = () => Menu.tab(b.dataset.tab); });
  $('#btn-edit').onclick = () => { Menu.close(); Edit.start(); };
  $('#btn-reset').onclick = () => { if (confirm('Reset to the preset layout?')) { Layouts.reset(); Menu.close(); } };
  const io = $('#io');
  $('#btn-export').onclick = () => { io.value = JSON.stringify(Layouts.layout, null, 1); };
  $('#btn-copy').onclick = async () => { io.value = JSON.stringify(Layouts.layout, null, 1); try { await navigator.clipboard.writeText(io.value); ui.toast('Copied'); } catch (e) { io.select(); document.execCommand && document.execCommand('copy'); ui.toast('Copied (selected)'); } };
  $('#btn-download').onclick = () => {
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(Layouts.layout, null, 1)], { type: 'application/json' }));
    a.download = 'raks-' + Layouts.layout.name.replace(/\W+/g, '-').toLowerCase() + '.json'; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  };
  const doImport = text => {
    try {
      const l = validateLayout(JSON.parse(text)), customs = Layouts.customs(), id = 'u' + Date.now().toString(36);
      l.id = id; customs[id] = l; Layouts.saveCustoms(customs); Layouts.select('custom:' + id); Menu.renderLayouts(); ui.toast('Imported "' + l.name + '"');
    } catch (e) { ui.toast('Import failed: ' + e.message); }
  };
  $('#btn-import').onclick = () => doImport(io.value);
  $('#file').onchange = e => { const f = e.target.files[0]; if (f) { const r = new FileReader(); r.onload = () => doImport(String(r.result)); r.readAsText(f); } e.target.value = ''; };

  const bindS = (id, key, kind, conv) => {
    const el = $(id); if (kind === 'check') el.checked = !!settings[key]; else el.value = conv ? conv.to(settings[key]) : settings[key];
    el.oninput = el.onchange = () => { settings[key] = kind === 'check' ? el.checked : (conv ? conv.from(el.value) : el.value); saveSettings(); Stage.place(); ui.latency(Net.rtt); };
  };
  bindS('#s-haptics', 'haptics', 'check'); bindS('#s-hapticms', 'hapticMs', 'v', { to: v => v, from: Number });
  bindS('#s-scale', 'scale', 'v', { to: v => Math.round(v * 100), from: v => v / 100 });
  bindS('#s-opacity', 'opacity', 'v', { to: v => Math.round(v * 100), from: v => v / 100 });
  bindS('#s-deadzone', 'deadzone', 'v', { to: v => Math.round(v * 100), from: v => v / 100 });
  bindS('#s-mirror', 'mirror', 'check'); bindS('#s-latency', 'latency', 'check'); bindS('#s-hotkey', 'hotkey', 'v');
  $('#btn-fs').onclick = () => ui.fullscreen();
  $('#btn-disconnect').onclick = () => {
    Menu.close();
    if (Link.mode === 'net') { Net.disconnect(); sessionStorage.setItem('raks.nogo', '1'); }
    ui.exitStage(); ui.status(Link.mode === 'none' ? 'Disconnected' : 'Ready', '');
  };

  const ch = $('#chords');
  CHORDS.forEach(c => { const b = document.createElement('button'); b.textContent = c.label; b.onclick = () => { runChord(c); Menu.close(); }; ch.appendChild(b); });
}

function runChord(c) {
  const codes = c.keys.map(k => (k === 'H' ? settings.hotkey : k));
  codes.forEach((k, i) => setTimeout(() => Pad.press(k), i * 60));
  setTimeout(() => codes.slice().reverse().forEach(k => Pad.release(k)), codes.length * 60 + 160);
  ui.toast(c.label);
}

/* ------------------------------------------------------------------ touchpad / keyboard */
const TouchPad = {
  btn: 0, dx: 0, dy: 0, wheel: 0, timer: 0,
  open() { Menu.close(); $('#touchpad').hidden = false; },
  close() { $('#touchpad').hidden = true; },
  flush() { this.timer = 0; if (this.dx || this.dy || this.wheel) { Link.sendMouse(clamp(this.dx, -32768, 32767), clamp(this.dy, -32768, 32767), clamp(this.wheel, -127, 127), this.btn); this.dx = this.dy = this.wheel = 0; } },
  queue() { if (!this.timer) this.timer = setTimeout(() => this.flush(), 16); },
  click(bit) { this.btn |= bit; Link.sendMouse(0, 0, 0, this.btn); setTimeout(() => { this.btn &= ~bit; Link.sendMouse(0, 0, 0, this.btn); }, 40); },
};
function bindTouchpad() {
  const area = $('#tp-area'), scroll = $('#tp-scroll');
  const tr = {};
  area.onpointerdown = e => { e.preventDefault(); area.setPointerCapture(e.pointerId); tr[e.pointerId] = { x: e.clientX, y: e.clientY, t: performance.now(), moved: 0 }; };
  area.onpointermove = e => {
    const p = tr[e.pointerId]; if (!p) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y; p.x = e.clientX; p.y = e.clientY; p.moved += Math.abs(dx) + Math.abs(dy);
    const k = 1.8; TouchPad.dx += Math.round(dx * k); TouchPad.dy += Math.round(dy * k); TouchPad.queue();
  };
  const end = e => { const p = tr[e.pointerId]; if (p && p.moved < 8 && performance.now() - p.t < 250) TouchPad.click(1); delete tr[e.pointerId]; };
  area.onpointerup = end; area.onpointercancel = e => { delete tr[e.pointerId]; };
  let sy = 0, acc = 0;
  scroll.onpointerdown = e => { e.preventDefault(); scroll.setPointerCapture(e.pointerId); sy = e.clientY; acc = 0; };
  scroll.onpointermove = e => { if (!scroll.hasPointerCapture(e.pointerId)) return; acc += sy - e.clientY; sy = e.clientY; const n = Math.trunc(acc / 14); if (n) { acc -= n * 14; TouchPad.wheel += n; TouchPad.queue(); } };
  [['#tp-left', 1], ['#tp-right', 2], ['#tp-mid', 4]].forEach(([id, bit]) => {
    const b = $(id);
    b.onpointerdown = e => { e.preventDefault(); TouchPad.btn |= bit; Link.sendMouse(0, 0, 0, TouchPad.btn); };
    const up = () => { TouchPad.btn &= ~bit; Link.sendMouse(0, 0, 0, TouchPad.btn); };
    b.onpointerup = up; b.onpointercancel = up; b.onpointerleave = up;
  });
  $('#tp-close').onclick = () => TouchPad.close();
  const txt = $('#tp-text');
  txt.addEventListener('input', () => { if (txt.value) { Link.json({ t: 'key', text: txt.value }); txt.value = ''; } });
  txt.addEventListener('keydown', e => {
    if (e.key === 'Enter') { Link.json({ t: 'key', code: 'enter' }); e.preventDefault(); }
    else if (e.key === 'Backspace' && !txt.value) Link.json({ t: 'key', code: 'backspace' });
  });
  const keys = $('#tp-keys');
  [['Esc', 'esc'], ['Tab', 'tab'], ['Enter', 'enter'], ['⌫', 'backspace'], ['←', 'left'], ['↑', 'up'], ['↓', 'down'], ['→', 'right'], ['Space', 'space'], ['Del', 'delete'], ['Home', 'home'], ['End', 'end']]
    .forEach(([l, c]) => { const b = document.createElement('button'); b.textContent = l; b.onclick = () => Link.json({ t: 'key', code: c }); keys.appendChild(b); });
  $('#btn-touchpad').onclick = () => TouchPad.open();
  ['touchstart', 'touchmove'].forEach(ev => [area, scroll].forEach(el => el.addEventListener(ev, e => e.preventDefault(), { passive: false })));
}

/* ------------------------------------------------------------------ ui helpers */
let wakeLock = null, toastTimer = 0, inStage = false;
const ui = {
  status(msg, cls) { const s = $('#status'); s.textContent = msg; s.className = 'status ' + (cls || ''); },
  toast(msg) { const t = $('#toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('show'), 1800); },
  latency(ms) { $('#lat').textContent = settings.latency && Link.mode === 'net' && ms ? Math.round(ms) + ' ms' : ''; },
  reconnecting(on) { $('#reconnect').hidden = !on; },
  setPlayer(slot, color) { $('#badge').textContent = 'P' + slot; document.documentElement.style.setProperty('--pc', color); RaksDemo.setColor(color); },
  enterStage(mode) {
    if (inStage && Link.mode === mode) return;
    inStage = true; Link.mode = mode;
    $('#connect').hidden = true; $('#stage').hidden = false;
    if (mode === 'demo') {
      $('#badge').textContent = 'DEMO'; document.documentElement.style.setProperty('--pc', COLORS[0]); $('#lat').textContent = '';
      RaksDemo.start({ canvas: $('#game'), viz: $('#viz'), log: $('#evlog'), color: COLORS[0] });
    } else RaksDemo.stop();
    Stage.build(); this.wake();
  },
  exitStage() {
    inStage = false; Link.mode = 'none'; Pad.releaseAll(); RaksDemo.stop();
    $('#stage').hidden = true; $('#connect').hidden = false; $('#menu').hidden = true; $('#touchpad').hidden = true; this.reconnecting(false);
    if (editing) { editing = false; document.body.classList.remove('editing'); $('#editbar').hidden = true; }
  },
  async wake() { try { if (inStage && 'wakeLock' in navigator && !document.hidden) wakeLock = await navigator.wakeLock.request('screen'); } catch (e) { /* denied */ } },
  fullscreen() {
    const el = document.documentElement;
    try {
      const p = el.requestFullscreen && el.requestFullscreen();
      if (p && p.then) p.then(() => screen.orientation && screen.orientation.lock && screen.orientation.lock('landscape')).catch(() => {});
    } catch (e) { /* iOS Safari has no fullscreen API: use Add to Home Screen */ }
  },
};

/* ------------------------------------------------------------------ boot */
async function boot() {
  await loadPresets();
  Layouts.select(settings.layout, true);
  bindEdit(); bindMenu(); bindTouchpad();
  const native = new URLSearchParams(location.search).has('app'); // packaged Android wrapper: no host behind this origin
  const served = !native && location.protocol.startsWith('http') && location.host;
  if (served) settings.host = location.host;
  $('#host').value = settings.host; $('#name').value = settings.name; $('#pin').value = store.get('pin', '');
  $('#pinrow').hidden = !$('#pin').value;
  $('#btn-connect').onclick = () => {
    settings.host = $('#host').value.trim(); settings.name = $('#name').value.trim(); saveSettings();
    if (!settings.host) return ui.status('Enter the host address shown on the Batocera screen', 'err');
    sessionStorage.removeItem('raks.nogo'); ui.fullscreen(); Net.backoff = 500; Net.connect();
  };
  $('#btn-demo').onclick = () => { ui.fullscreen(); ui.enterStage('demo'); };
  if ('serviceWorker' in navigator && window.isSecureContext) navigator.serviceWorker.register('sw.js').catch(() => {});
  const params = new URLSearchParams(location.search);
  if (params.has('demo')) ui.enterStage('demo');
  else if (served && !sessionStorage.getItem('raks.nogo')) { settings.name = settings.name || ''; Net.connect(); }
  window.Raks = { Pad, Layouts, Net, Link, Stage, validateLayout, PRESETS };
}
boot();
})();
