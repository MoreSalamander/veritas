/*
 * nerve-viz.js — "every one of the tests, not a summary of them."
 *
 * Every real pytest result, laid out as a three-tier radial nervous system
 * (category -> module -> individual test), pulsing inward toward Entropy AI's
 * own core. Ported from a standalone visualization built to answer "can we
 * see all N tests, not just a module-level rollup" — same layout math, same
 * pulse-relay mechanics, adapted to run embedded in Veritas's own homepage
 * instead of as a standalone page. Depends on window.NERVE_VIZ_DATA /
 * window.NERVE_VIZ_COLORS (see nerve-viz-data.js, generated from a real
 * `pytest -v` run — never hand-authored) and, optionally, window.entropyMedallion
 * (set by index.html's own loadShell(), for the core's embedded 3D scene).
 */
(function () {
  const DATA = window.NERVE_VIZ_DATA;
  const COLORS = window.NERVE_VIZ_COLORS;
  const GOLD = '#e8c468';
  if (!DATA || !DATA.length) return;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const stage = document.getElementById('nerveStage');
  const canvas = document.getElementById('nerve');
  const ctx = canvas.getContext('2d');
  const DPR = Math.min(window.devicePixelRatio || 1, 2);
  const ringSvg = document.getElementById('nerveRing');
  const ringPath = document.getElementById('nerveRingPath');
  const ringTextPath = document.getElementById('nerveRingTextPath');
  const ringAnim = document.getElementById('nerveRingAnim');

  function resize() {
    const w = stage.clientWidth, h = stage.clientHeight;
    canvas.width = w * DPR; canvas.height = h * DPR;
    canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    ringSvg.setAttribute('viewBox', `0 0 ${w} ${h}`);
    return { w, h };
  }
  let { w: W, h: H } = resize();
  window.addEventListener('resize', () => { const r = resize(); W = r.w; H = r.h; layout(); });

  // The outer rim: "Veritas Dynamics" repeated around a ring outside the diagram
  // itself, slowly rotating — the credit line made literal, orbiting the thing
  // it powers.
  function setupRing(cx, cy, ringR) {
    // Two proper semicircles, not a near-degenerate single arc between
    // almost-identical points — that does NOT reliably center on (cx,cy).
    ringPath.setAttribute('d', `M ${cx+ringR},${cy} A ${ringR},${ringR} 0 1,1 ${cx-ringR},${cy} A ${ringR},${ringR} 0 1,1 ${cx+ringR},${cy} Z`);
    const unit = 'VERITAS DYNAMICS  •  ';
    ringTextPath.textContent = unit;
    const unitLen = ringTextPath.getComputedTextLength() || (unit.length * 13);
    const circumference = 2 * Math.PI * ringR;
    const repeats = Math.max(1, Math.ceil(circumference / unitLen) + 1);
    ringTextPath.textContent = Array(repeats).fill(unit).join('');
    ringAnim.setAttribute('from', `0 ${cx} ${cy}`);
    ringAnim.setAttribute('to', `360 ${cx} ${cy}`);
    if (reduceMotion) {
      ringAnim.setAttribute('repeatCount', '0');
    } else if (typeof ringAnim.beginElement === 'function') {
      try { ringAnim.beginElement(); } catch (e) { /* Safari lacks SMIL beginElement; the declarative repeatCount="indefinite" still animates it */ }
    }
  }

  // ---------- deterministic pseudo-random per name — stable chaos, not a flicker ----------
  function hash(str) {
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
    return ((h >>> 0) % 10000) / 10000;
  }

  // ---------- three-tier radial layout: center -> category (even wheel) ->
  // module (real proportion within its category) -> individual test (one node
  // each). The wheel is the order; every branch's own sway is the chaos. ----------
  let cx, cy, trunkR, modRMin, modRMax, leafRMin, leafRMax;

  function layout() {
    cx = W / 2; cy = H / 2;
    const base = Math.min(W, H, 640);
    trunkR = base * 0.14;
    modRMin = base * 0.25;
    modRMax = base * 0.34;
    leafRMin = base * 0.38;
    leafRMax = base * 0.49;

    let angle = -Math.PI / 2;
    const catTestLists = [];
    DATA.forEach((cat, ci) => {
      const sectorWidth = (Math.PI * 2) / DATA.length;
      const h1 = hash(cat.category);
      cat._color = COLORS[ci % COLORS.length];
      const trunkRJ = trunkR * (0.82 + h1 * 0.32);
      cat._angleMid = angle + sectorWidth / 2 + (h1 - 0.5) * 0.06;
      cat._tx = cx + Math.cos(cat._angleMid) * trunkRJ;
      cat._ty = cy + Math.sin(cat._angleMid) * trunkRJ;
      cat._bend = (h1 - 0.5) * 78;
      cat._skew = (hash(cat.category + 's') - 0.5) * 0.9;

      let a = angle;
      const myTests = [];
      cat.modules.forEach(mod => {
        const mw = (mod.total / cat.total) * sectorWidth;
        const hm = hash(mod.module), hm2 = hash(mod.module + 'r'), hm3 = hash(mod.module + 'b');
        const modMid = a + mw / 2 + (hm - 0.5) * sectorWidth * 0.6;
        const modR = modRMin + (modRMax - modRMin) * (0.5 + hm2 * 0.5);
        mod._x = cx + Math.cos(modMid) * modR;
        mod._y = cy + Math.sin(modMid) * modR;
        mod._color = cat._color;
        mod._bend = (hm3 - 0.5) * 50;
        mod._skew = (hash(mod.module + 'k') - 0.5) * 0.9;
        mod._radius = 2 + Math.sqrt(mod.total) * 0.9;
        mod.tests.forEach(t => { t._color = cat._color; myTests.push({ mod, t }); });
        a += mw;
      });
      catTestLists.push(myTests);
      angle += sectorWidth;
    });

    // Round-robin one test per category (keeps colors interleaved) and give the
    // resulting order a perfectly even angle all the way around.
    const globalOrder = [];
    let more = true;
    while (more) {
      more = false;
      for (const list of catTestLists) {
        if (list.length) { globalOrder.push(list.shift()); more = true; }
      }
    }
    const n = globalOrder.length;
    globalOrder.forEach(({ mod, t }, i) => {
      const hj = hash(mod.module + t.name + 'j'), hr = hash(mod.module + t.name + 'rr');
      const baseAngle = -Math.PI / 2 + (i / n) * Math.PI * 2;
      const tAngle = baseAngle + (hj - 0.5) * (Math.PI * 2 / n) * 1.6;
      const tR = leafRMin + (leafRMax - leafRMin) * (0.4 + hr * 0.55);
      t._x = cx + Math.cos(tAngle) * tR;
      t._y = cy + Math.sin(tAngle) * tR;
      t._bend = (hash(mod.module + t.name + 'b') - 0.5) * 46;
      t._skew = (hash(mod.module + t.name + 'k') - 0.5) * 1.1;
    });

    setupRing(cx, cy, leafRMax + 22);
  }
  layout();

  function hexToRgb(hex) { const n = parseInt(hex.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
  function rgba(hex, a) { const [r, g, b] = hexToRgb(hex); return `rgba(${r},${g},${b},${a})`; }

  function curve(x0, y0, x1, y1, bend, skew) {
    skew = skew || 0;
    const dx = x1 - x0, dy = y1 - y0; const len = Math.hypot(dx, dy) || 1;
    const mx = (x0 + x1) / 2 + (dx / len) * skew * len * 0.5, my = (y0 + y1) / 2 + (dy / len) * skew * len * 0.5;
    const nx = -dy, ny = dx;
    return { cx: mx + (nx / len) * bend, cy: my + (ny / len) * bend };
  }

  function drawBranch(x0, y0, x1, y1, color, width, glow, bend, dashed, skew, lineAlpha) {
    const c = curve(x0, y0, x1, y1, bend, skew);
    ctx.save();
    if (dashed) ctx.setLineDash([2, 3]);
    ctx.strokeStyle = rgba(color, lineAlpha != null ? lineAlpha : (dashed ? 0.4 : 0.55));
    ctx.lineWidth = width;
    ctx.lineCap = 'round';
    ctx.shadowColor = rgba(color, glow);
    ctx.shadowBlur = dashed ? 2 : 6;
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.quadraticCurveTo(c.cx, c.cy, x1, y1);
    ctx.stroke();
    ctx.restore();
  }

  function drawNode(x, y, r, color, glowMul) {
    ctx.save();
    ctx.shadowColor = rgba(color, 0.9);
    ctx.shadowBlur = r * 2.2 * glowMul;
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
  }

  // ---------- pulses: traveling dots along a branch ----------
  let pulses = [];
  function spawnPulse(x0, y0, x1, y1, color, bend, duration, onArrive, skew) {
    pulses.push({ x0, y0, x1, y1, color, bend, skew: skew || 0, t0: performance.now(), duration, onArrive, done: false });
  }
  function stepPulses(now) {
    // NOT pulses.filter(...): an onArrive callback here can spawn a brand-new
    // pulse (that's how the test->module->trunk->core relay works) — Array#filter
    // never visits elements pushed to the array mid-traversal, so a naive
    // filter reassignment silently drops any pulse spawned during this same
    // pass. Snapshot the length first instead, so late arrivals are kept.
    const originalLen = pulses.length;
    const survivors = [];
    for (let i = 0; i < originalLen; i++) {
      const p = pulses[i];
      const t = (now - p.t0) / p.duration;
      if (t >= 1) { if (p.onArrive) p.onArrive(); continue; }
      const c = curve(p.x0, p.y0, p.x1, p.y1, p.bend, p.skew);
      const it = 1 - t;
      const x = it * it * p.x0 + 2 * it * t * c.cx + t * t * p.x1;
      const y = it * it * p.y0 + 2 * it * t * c.cy + t * t * p.y1;
      ctx.save();
      ctx.shadowColor = rgba(p.color, 1); ctx.shadowBlur = 10;
      ctx.fillStyle = '#fff';
      ctx.beginPath(); ctx.arc(x, y, 2.2, 0, Math.PI * 2); ctx.fill();
      ctx.restore();
      survivors.push(p);
    }
    for (let i = originalLen; i < pulses.length; i++) survivors.push(pulses[i]);
    pulses = survivors;
  }

  // ---------- flashes: a node lights up the instant its own comet departs, for
  // exactly as long as that signal still has left to travel — the glow IS the
  // journey. ----------
  let flashes = new Map();
  function flash(key, life) { flashes.set(key, { t0: performance.now(), life: life || 420 }); }
  function flashMul(key, now) {
    const f = flashes.get(key);
    if (f == null) return 1;
    const dt = now - f.t0;
    const life = f.life;
    if (dt > life) { flashes.delete(key); return 1; }
    return 1 + 1.6 * (1 - dt / life);
  }

  // ---------- fan-out: every color, every module, every individual test gets
  // its own pulse. `doTally` only true on the first run. ----------
  const counterEl = document.getElementById('nerveCounter');
  let tally = 0;
  function bumpCounter(by) { tally += by; counterEl.textContent = tally; }

  const TEST_HOP = 620, MOD_HOP = 780, TRUNK_HOP = 950;

  function fanOut(doTally) {
    // Inward, not outward: Entropy AI is powered BY Veritas, not the source
    // radiating out to it. A test fires toward its own module; a module relays
    // inward to its category trunk only once all its own tests have reported;
    // a trunk relays inward to the core only once every one of its modules has.
    let catDelay = 0;
    DATA.forEach((cat) => {
      setTimeout(() => {
        let modsRemaining = cat.modules.length;
        let modDelay = 0;
        cat.modules.forEach(mod => {
          setTimeout(() => {
            let testsRemaining = mod.tests.length;
            let testDelay = 0;
            mod.tests.forEach(t => {
              setTimeout(() => {
                const skipped = t.status !== 'passed';
                flash('t:' + mod.module + t.name, TEST_HOP + MOD_HOP + TRUNK_HOP);
                spawnPulse(t._x, t._y, mod._x, mod._y, t._color, t._bend, TEST_HOP, () => {
                  if (doTally && !skipped) bumpCounter(1);
                  testsRemaining--;
                  if (testsRemaining === 0) {
                    flash('mod:' + mod.module, MOD_HOP + TRUNK_HOP);
                    spawnPulse(mod._x, mod._y, cat._tx, cat._ty, mod._color, mod._bend, MOD_HOP, () => {
                      modsRemaining--;
                      if (modsRemaining === 0) {
                        flash('cat:' + cat.category, TRUNK_HOP);
                        spawnPulse(cat._tx, cat._ty, cx, cy, cat._color, cat._bend, TRUNK_HOP, () => {
                          heartStart = performance.now();
                          window.entropyMedallion?.ping(); // same event lights the medallion too
                        }, cat._skew);
                      }
                    }, mod._skew);
                  }
                }, t._skew);
              }, testDelay);
              testDelay += reduceMotion ? 0 : 5;
            });
          }, modDelay);
          modDelay += reduceMotion ? 0 : 22;
        });
      }, catDelay);
      catDelay += reduceMotion ? 0 : 30;
    });
  }
  const FANOUT_INTERVAL_MS = 2900;
  function scheduleFanOut() {
    if (reduceMotion) return;
    setTimeout(() => { fanOut(false); scheduleFanOut(); }, FANOUT_INTERVAL_MS);
  }

  const BEAT_MS = 860;
  let heartStart = null;

  // ---------- hover: category trunk, module node, or individual test leaf ----------
  const tooltip = document.getElementById('nerveTooltip');
  let hoverKey = null;
  canvas.addEventListener('mousemove', e => {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    let hit = null, best = 1e9;
    DATA.forEach(cat => {
      const dCat = Math.hypot(mx - cat._tx, my - cat._ty);
      if (dCat < 14 && dCat < best) { best = dCat; hit = { kind: 'cat', cat }; }
      cat.modules.forEach(mod => {
        const dMod = Math.hypot(mx - mod._x, my - mod._y);
        if (dMod < Math.max(9, mod._radius + 3) && dMod < best) { best = dMod; hit = { kind: 'mod', cat, mod }; }
        mod.tests.forEach(t => {
          const dT = Math.hypot(mx - t._x, my - t._y);
          if (dT < 7 && dT < best) { best = dT; hit = { kind: 'test', cat, mod, t }; }
        });
      });
    });
    if (hit) {
      if (hit.kind === 'test') {
        hoverKey = 't:' + hit.mod.module + hit.t.name;
        const status = hit.t.status === 'passed' ? 'passed' : (hit.t.status === 'skipped' ? 'skipped (needs Docker)' : 'failed');
        tooltip.innerHTML = `<b>${hit.t.name}</b><div class="m">${status} &middot; ${hit.mod.module} &middot; ${hit.cat.category}</div>`;
      } else if (hit.kind === 'mod') {
        hoverKey = 'mod:' + hit.mod.module;
        tooltip.innerHTML = `<b>${hit.mod.module}</b><div class="m">${hit.mod.passed} passed${hit.mod.skipped ? ', ' + hit.mod.skipped + ' skipped' : ''} &middot; ${hit.cat.category}</div>`;
      } else {
        hoverKey = 'cat:' + hit.cat.category;
        tooltip.innerHTML = `<b>${hit.cat.category}</b><div class="m">${hit.cat.passed} passed${hit.cat.skipped ? ', ' + hit.cat.skipped + ' skipped' : ''} &middot; ${hit.cat.modules.length} modules</div>`;
      }
      tooltip.classList.add('show');
      const pad = 14;
      let left = e.clientX + pad, top = e.clientY + pad;
      if (left + 260 > window.innerWidth) left = e.clientX - 260 - pad;
      tooltip.style.left = left + 'px'; tooltip.style.top = top + 'px';
    } else {
      hoverKey = null;
      tooltip.classList.remove('show');
    }
  });
  canvas.addEventListener('mouseleave', () => { hoverKey = null; tooltip.classList.remove('show'); });

  // ---------- main draw loop ----------
  function draw(now) {
    ctx.clearRect(0, 0, W, H);

    DATA.forEach(cat => {
      const catHover = hoverKey === 'cat:' + cat.category;
      drawBranch(cx, cy, cat._tx, cat._ty, cat._color, 3, catHover ? 0.9 : 0.4, cat._bend, false, cat._skew);
      cat.modules.forEach(mod => {
        const modHover = hoverKey === 'mod:' + mod.module;
        const w = 0.9 + Math.sqrt(mod.total) * 0.22;
        drawBranch(cat._tx, cat._ty, mod._x, mod._y, mod._color, modHover ? w + 1 : w, modHover ? 0.8 : 0.24, mod._bend, false, mod._skew);
        mod.tests.forEach(t => {
          const tHover = hoverKey === 't:' + mod.module + t.name;
          const skipped = t.status !== 'passed';
          drawBranch(mod._x, mod._y, t._x, t._y, t._color, tHover ? 2.2 : 0.7, tHover ? 0.85 : (skipped ? 0.08 : 0.20), t._bend, skipped, t._skew);
        });
      });
    });

    DATA.forEach(cat => {
      const fmC = flashMul('cat:' + cat.category, now) * (hoverKey === 'cat:' + cat.category ? 1.3 : 1);
      drawNode(cat._tx, cat._ty, 6.5 * Math.min(fmC, 2), cat._color, fmC);
      cat.modules.forEach(mod => {
        const fmM = flashMul('mod:' + mod.module, now) * (hoverKey === 'mod:' + mod.module ? 1.3 : 1);
        drawNode(mod._x, mod._y, mod._radius * Math.min(fmM, 1.8) / 1.8, mod._color, fmM);
        mod.tests.forEach(t => {
          const skipped = t.status !== 'passed';
          const fmT = flashMul('t:' + mod.module + t.name, now) * (hoverKey === 't:' + mod.module + t.name ? 1.4 : 1);
          drawNode(t._x, t._y, (skipped ? 0.9 : 1.7) * Math.min(fmT, 1.9), t._color, skipped ? fmT * 0.4 : fmT);
        });
      });
    });

    stepPulses(now);

    // center core — a hollow, layered corona. It beats exactly once per
    // fan-out cycle, not on a separate timer.
    let coreFlash = 1;
    if (heartStart != null) {
      const t = (now - heartStart) / BEAT_MS;
      const gauss = (mu, sigma) => Math.exp(-((t - mu) * (t - mu)) / (2 * sigma * sigma));
      coreFlash = 1 + 0.55 * gauss(0.02, 0.028) + 0.30 * gauss(0.16, 0.032);
    }
    const coreR = 66 * coreFlash;

    ctx.save();
    const aura = ctx.createRadialGradient(cx, cy, coreR * 0.7, cx, cy, coreR * 1.55);
    aura.addColorStop(0, rgba(GOLD, 0.45));
    aura.addColorStop(1, rgba(GOLD, 0));
    ctx.fillStyle = aura;
    ctx.beginPath(); ctx.arc(cx, cy, coreR * 1.55, 0, Math.PI * 2); ctx.fill();
    ctx.restore();

    ctx.save();
    ctx.fillStyle = '#000000';
    ctx.beginPath(); ctx.arc(cx, cy, coreR, 0, Math.PI * 2); ctx.fill();
    ctx.restore();

    [0, 0.4].forEach((phase, i) => {
      const rr = coreR * (i === 0 ? 1 : 1.16) * (1 + 0.02 * Math.sin(now / 500 + phase * 6));
      ctx.save();
      ctx.strokeStyle = rgba(GOLD, i === 0 ? 0.85 : 0.35);
      ctx.lineWidth = i === 0 ? 2.2 : 1.2;
      ctx.shadowColor = rgba(GOLD, 0.7); ctx.shadowBlur = 10;
      ctx.beginPath(); ctx.arc(cx, cy, rr, 0, Math.PI * 2); ctx.stroke();
      ctx.restore();
    });

    requestAnimationFrame(draw);
  }
  requestAnimationFrame(draw);

  if (reduceMotion) {
    tally = DATA.reduce((a, c) => a + c.passed, 0);
    counterEl.textContent = tally;
    DATA.forEach(cat => {
      flash('cat:' + cat.category);
      cat.modules.forEach(mod => { flash('mod:' + mod.module); mod.tests.forEach(t => flash('t:' + mod.module + t.name)); });
    });
  } else {
    fanOut(true);
    setTimeout(scheduleFanOut, FANOUT_INTERVAL_MS);
  }

  // ---------- legend ----------
  document.getElementById('nerveLegend').innerHTML = DATA.map((c, i) => `
    <div class="item"><span class="sw" style="background:${COLORS[i % COLORS.length]};color:${COLORS[i % COLORS.length]}"></span><b>${c.category}</b>&nbsp;${c.total}</div>
  `).join('');

  // ---------- table ----------
  let rows = `<table class="nerve-viz-table"><thead><tr><th>Module</th><th class="num">Passed</th><th class="num">Skipped</th><th class="num">Total</th></tr></thead><tbody>`;
  DATA.forEach((cat, i) => {
    rows += `<tr class="cat-row"><td><span class="nerve-dot" style="background:${COLORS[i % COLORS.length]};color:${COLORS[i % COLORS.length]}"></span>${cat.category}</td><td class="num">${cat.passed}</td><td class="num">${cat.skipped}</td><td class="num">${cat.total}</td></tr>`;
    cat.modules.forEach(mod => {
      rows += `<tr><td style="padding-left:24px">${mod.module}</td><td class="num">${mod.passed}</td><td class="num">${mod.skipped}</td><td class="num">${mod.total}</td></tr>`;
    });
  });
  rows += `</tbody></table>`;
  document.getElementById('nerveTablehost').innerHTML = rows;
})();
