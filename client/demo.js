'use strict';
/* Raks demo console: on-screen controller visualizer, input event log and a tiny twin-stick
 * shooter driven by the real on-screen controls. Needs no host and works fully offline. */
const RaksDemo = (() => {
  const NAMES = ['south', 'east', 'north', 'west', 'tl', 'tr', 'tl2', 'tr2', 'select', 'start', 'mode', 'thumbl', 'thumbr'];
  const SHORT = { south: 'A/✕', east: 'B/○', north: 'Y/△', west: 'X/□', tl: 'L1', tr: 'R1', tl2: 'L2', tr2: 'R2',
    select: 'SEL', start: 'STA', mode: 'MODE', thumbl: 'L3', thumbr: 'R3' };
  const FIRE = ['south', 'east', 'north', 'west', 'tr', 'tr2'];
  let cv, g, vizEl, logEl, vizCv, vg, chips = {};
  let st = zero(), prev = zero(), raf = 0, running = false, last = 0;
  let inT = 0, lagMs = 0, lines = [], color = '#4d9bff';
  let G;

  function zero() { return { buttons: 0, hx: 0, hy: 0, lx: 0, ly: 0, rx: 0, ry: 0, lt: 0, rt: 0 }; }
  const down = (s, n) => (s.buttons >> NAMES.indexOf(n)) & 1;

  function reset() {
    const w = cv.width, h = cv.height;
    G = { x: w / 2, y: h / 2, vx: 0, vy: 0, aim: 0, hp: 5, score: 0, bullets: [], foes: [], parts: [],
      cool: 0, spawn: 0, inv: 0, t: 0, flash: 0 };
  }

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    cv.width = Math.round(cv.clientWidth * dpr); cv.height = Math.round(cv.clientHeight * dpr);
    cv.dataset.dpr = dpr;
    if (G) { G.x = Math.min(G.x, cv.width); G.y = Math.min(G.y, cv.height); }
  }

  function start(opts) {
    cv = opts.canvas; g = cv.getContext('2d'); vizEl = opts.viz; logEl = opts.log;
    color = opts.color || color;
    vizEl.hidden = false; logEl.hidden = false; vizEl.innerHTML = ''; chips = {};
    vizCv = document.createElement('canvas'); vizCv.width = 144; vizCv.height = 72;
    vg = vizCv.getContext('2d'); vizEl.appendChild(vizCv);
    NAMES.forEach(n => { const c = document.createElement('span'); c.className = 'chip'; c.textContent = SHORT[n]; chips[n] = c; vizEl.appendChild(c); });
    lines = []; st = zero(); prev = zero();
    resize(); reset();
    window.addEventListener('resize', resize);
    running = true; last = performance.now(); raf = requestAnimationFrame(loop);
    log('demo started - use the on-screen controls');
  }

  function stop() {
    running = false; cancelAnimationFrame(raf);
    window.removeEventListener('resize', resize);
    if (vizEl) { vizEl.hidden = true; vizEl.innerHTML = ''; }
    if (logEl) { logEl.hidden = true; logEl.textContent = ''; }
  }

  function ts() { const d = new Date(); return d.toTimeString().slice(0, 8) + '.' + String(d.getMilliseconds()).padStart(3, '0'); }
  function log(msg) { lines.push(ts() + ' ' + msg); if (lines.length > 7) lines.shift(); if (logEl) logEl.textContent = lines.join('\n'); }

  /** Called with every state the real client would send to the host. */
  function onState(s) {
    inT = performance.now();
    const ch = s.buttons ^ prev.buttons;
    NAMES.forEach((n, i) => { if (ch >> i & 1) log(n + (s.buttons >> i & 1 ? ' DOWN' : ' up')); });
    if (s.hx !== prev.hx || s.hy !== prev.hy) log('dpad ' + s.hx + ',' + s.hy);
    if (Math.abs(s.lt - prev.lt) > 40 || Math.abs(s.rt - prev.rt) > 40) log('trig L' + s.lt + ' R' + s.rt);
    prev = st = s;
    NAMES.forEach((n, i) => chips[n].classList.toggle('on', !!(s.buttons >> i & 1)));
    drawViz();
  }

  function drawViz() {
    const c = vg, p = st; c.clearRect(0, 0, 144, 72);
    const stick = (cx, x, y) => {
      c.strokeStyle = '#3a424d'; c.lineWidth = 1.5; c.beginPath(); c.arc(cx, 38, 22, 0, 7); c.stroke();
      c.fillStyle = color; c.beginPath(); c.arc(cx + x / 32768 * 17, 38 + y / 32768 * 17, 6, 0, 7); c.fill();
    };
    stick(24, p.lx, p.ly); stick(120, p.rx, p.ry);
    c.fillStyle = '#3a424d'; c.fillRect(2, 2, 44, 4); c.fillRect(98, 2, 44, 4);
    c.fillStyle = color; c.fillRect(2, 2, 44 * p.lt / 255, 4); c.fillRect(98, 2, 44 * p.rt / 255, 4);
    const dp = (x, y, on) => { c.fillStyle = on ? color : '#3a424d'; c.fillRect(x, y, 9, 9); };
    dp(68, 24, p.hy < 0); dp(68, 42, p.hy > 0); dp(59, 33, p.hx < 0); dp(77, 33, p.hx > 0);
  }

  const rnd = (a, b) => a + Math.random() * (b - a);

  function step(dt) {
    const w = cv.width, h = cv.height, dpr = +cv.dataset.dpr || 1;
    const S = Math.min(w, h);
    let mx = st.lx / 32768, my = st.ly / 32768;
    if (!mx && !my) { mx = st.hx; my = st.hy; }
    const sp = S * 0.55;
    G.x = Math.max(12 * dpr, Math.min(w - 12 * dpr, G.x + mx * sp * dt));
    G.y = Math.max(12 * dpr, Math.min(h - 12 * dpr, G.y + my * sp * dt));
    let ax = st.rx / 32768, ay = st.ry / 32768;
    if (Math.hypot(ax, ay) > 0.25) G.aim = Math.atan2(ay, ax);
    else if (Math.hypot(mx, my) > 0.25) G.aim = Math.atan2(my, mx);
    G.cool -= dt; G.inv -= dt; G.t += dt;
    const fire = FIRE.some(n => down(st, n)) || st.rt > 80 || Math.hypot(ax, ay) > 0.6;
    if (fire && G.cool <= 0) {
      G.cool = 0.12;
      const sp2 = S * 1.4;
      G.bullets.push({ x: G.x, y: G.y, vx: Math.cos(G.aim) * sp2, vy: Math.sin(G.aim) * sp2, life: 1 });
    }
    G.spawn -= dt;
    if (G.spawn <= 0) {
      G.spawn = Math.max(0.25, 1.1 - G.score / 120);
      const a = Math.random() * 6.283, r = Math.hypot(w, h) / 2 + 20;
      G.foes.push({ x: w / 2 + Math.cos(a) * r, y: h / 2 + Math.sin(a) * r, r: rnd(9, 15) * dpr, sp: rnd(0.12, 0.22) * S });
    }
    G.bullets.forEach(b => { b.x += b.vx * dt; b.y += b.vy * dt; b.life -= dt; });
    G.bullets = G.bullets.filter(b => b.life > 0 && b.x > -20 && b.x < w + 20 && b.y > -20 && b.y < h + 20);
    G.foes.forEach(f => { const a = Math.atan2(G.y - f.y, G.x - f.x); f.x += Math.cos(a) * f.sp * dt; f.y += Math.sin(a) * f.sp * dt; });
    for (const f of G.foes) for (const b of G.bullets) {
      if (b.life > 0 && Math.hypot(f.x - b.x, f.y - b.y) < f.r + 3) {
        b.life = 0; f.dead = true; G.score++;
        for (let i = 0; i < 8; i++) G.parts.push({ x: f.x, y: f.y, vx: rnd(-1, 1) * S * .3, vy: rnd(-1, 1) * S * .3, life: .4 });
      }
    }
    G.foes = G.foes.filter(f => !f.dead);
    if (G.inv <= 0) for (const f of G.foes) {
      if (Math.hypot(f.x - G.x, f.y - G.y) < f.r + 9 * dpr) {
        G.hp--; G.inv = 1.2; f.dead = true; G.flash = .2;
        if (G.hp <= 0) { log('game over - score ' + G.score); const sc = G.score; reset(); G.score = 0; G.foes = []; G.flash = .5; G.last = sc; }
        break;
      }
    }
    G.foes = G.foes.filter(f => !f.dead);
    G.parts.forEach(p => { p.x += p.vx * dt; p.y += p.vy * dt; p.life -= dt; });
    G.parts = G.parts.filter(p => p.life > 0);
    G.flash = Math.max(0, G.flash - dt);
  }

  function draw() {
    const w = cv.width, h = cv.height, dpr = +cv.dataset.dpr || 1;
    g.clearRect(0, 0, w, h);
    g.strokeStyle = 'rgba(255,255,255,.04)'; g.lineWidth = 1;
    const gs = 40 * dpr;
    for (let x = 0; x < w; x += gs) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke(); }
    for (let y = 0; y < h; y += gs) { g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke(); }
    g.fillStyle = '#ff6b6b';
    G.foes.forEach(f => { g.beginPath(); g.arc(f.x, f.y, f.r, 0, 7); g.fill(); });
    g.fillStyle = '#ffe066';
    G.bullets.forEach(b => { g.beginPath(); g.arc(b.x, b.y, 3 * dpr, 0, 7); g.fill(); });
    G.parts.forEach(p => { g.globalAlpha = Math.max(0, p.life * 2); g.fillStyle = '#ffb3b3'; g.fillRect(p.x, p.y, 3 * dpr, 3 * dpr); });
    g.globalAlpha = 1;
    if (G.inv <= 0 || Math.floor(G.t * 20) % 2) {
      g.save(); g.translate(G.x, G.y); g.rotate(G.aim); g.fillStyle = color;
      g.beginPath(); g.moveTo(14 * dpr, 0); g.lineTo(-9 * dpr, 9 * dpr); g.lineTo(-5 * dpr, 0); g.lineTo(-9 * dpr, -9 * dpr); g.closePath(); g.fill(); g.restore();
    }
    g.fillStyle = '#c9d1d9'; g.font = (12 * dpr) + 'px ui-monospace,monospace'; g.textAlign = 'right';
    g.fillText('score ' + G.score + '   hp ' + '♥'.repeat(Math.max(0, G.hp)), w - 14 * dpr, h - 12 * dpr);
    g.fillStyle = '#6e7681'; g.textAlign = 'left';
    g.fillText('input→frame ' + lagMs.toFixed(1) + ' ms', 14 * dpr + 0, h - 12 * dpr);
    if (G.flash) { g.fillStyle = 'rgba(255,60,60,' + G.flash + ')'; g.fillRect(0, 0, w, h); }
  }

  function loop(now) {
    if (!running) return;
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    step(dt); draw();
    if (inT) { lagMs = lagMs * 0.9 + (performance.now() - inT) * 0.1; inT = 0; }
    raf = requestAnimationFrame(loop);
  }

  return { start, stop, onState, log, setColor: c => { color = c; } };
})();
