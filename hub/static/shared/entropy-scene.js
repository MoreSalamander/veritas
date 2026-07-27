/*
 * entropy-scene.js — the shared "center + orbit" WebGL hero scene.
 *
 * Generalized from the pattern already proven in Opportunity's scanfield
 * view and the three Hunter engines' own hero scenes: one glowing center
 * node, a ring of orbiting nodes tied back to it by curved, particle-lit
 * links. Opportunity's version is two-tier (engines orbit Opportunity,
 * opportunities orbit their own engine); this shared version is the
 * single-tier case — used by Veritas's own shell view to show every
 * registered production orbiting Veritas, the same visual grammar one
 * level further out.
 *
 * Depends on Three.js r128 + the EffectComposer/RenderPass/UnrealBloomPass
 * postprocessing scripts (same CDN scripts every existing hero scene already
 * loads — see README.md for the exact <script> tags).
 *
 * Usage:
 *   EntropyScene.init(document.querySelector('#scene'), {
 *     center: { color: 0xe8c468, label: 'Veritas' },
 *     nodes: [{ name: 'crypto_hunter', color: 0xf0a52c, pulse: true }, ...],
 *     onPing: 3400,               // ms between center pulses, optional
 *   });
 */
(function (global) {
  function EntropySceneInit(canvas, opts) {
    const host = canvas.parentElement;
    const W = () => host.clientWidth;
    const H = () => host.clientHeight;

    const rn = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    rn.setPixelRatio(Math.min(devicePixelRatio, 2));
    rn.setSize(W(), H());
    const sc = new THREE.Scene();
    sc.fog = new THREE.FogExp2(0x0a0e0c, 0.032);
    const cam = new THREE.PerspectiveCamera(50, W() / H(), 0.1, 100);
    cam.position.set(0, 0, 17);
    const grp = new THREE.Group();
    sc.add(grp);

    const composer = new THREE.EffectComposer(rn);
    composer.addPass(new THREE.RenderPass(sc, cam));
    const bloom = new THREE.UnrealBloomPass(new THREE.Vector2(W(), H()), 0.85, 0.42, 0.18);
    composer.addPass(bloom);
    const glowMat = (c, o) =>
      new THREE.MeshBasicMaterial({ color: c, transparent: true, opacity: o, blending: THREE.AdditiveBlending, depthWrite: false });

    // ambient dust, identical across every production's hero for a consistent house feel
    const dN = 460, dp = new Float32Array(dN * 3);
    for (let i = 0; i < dN; i++) {
      const r = 5 + Math.random() * 13, th = Math.random() * 6.283, ph = Math.acos(2 * Math.random() - 1);
      dp[i * 3] = r * Math.sin(ph) * Math.cos(th);
      dp[i * 3 + 1] = r * Math.sin(ph) * Math.sin(th);
      dp[i * 3 + 2] = r * Math.cos(ph);
    }
    const dg = new THREE.BufferGeometry();
    dg.setAttribute('position', new THREE.BufferAttribute(dp, 3));
    const dust = new THREE.Points(dg, new THREE.PointsMaterial({ color: 0x8aa38f, size: 0.055, transparent: true, opacity: 0.45, blending: THREE.AdditiveBlending, depthWrite: false }));
    grp.add(dust);

    const glowNodes = [], spinNodes = [], paths = [];
    function geom(shape, size) {
      if (shape === 'icosa') return new THREE.IcosahedronGeometry(size, 0);
      if (shape === 'octa') return new THREE.OctahedronGeometry(size, 0);
      if (shape === 'box') return new THREE.BoxGeometry(size * 1.4, size * 1.4, size * 1.4);
      return new THREE.SphereGeometry(size, 20, 20);
    }
    function mk(color, size, pos, glow, shape, spin) {
      const g0 = geom(shape, size);
      const core = new THREE.Mesh(g0, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.5 }));
      core.position.copy(pos);
      grp.add(core);
      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(geom(shape, size * 1.16)),
        new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.95, blending: THREE.AdditiveBlending })
      );
      edges.position.copy(pos);
      grp.add(edges);
      const g = new THREE.Mesh(new THREE.SphereGeometry(size * 2.7, 16, 16), glowMat(color, glow));
      g.position.copy(pos);
      grp.add(g);
      glowNodes.push({ g, base: glow, phase: Math.random() * 6.283 });
      core.userData.edges = edges;
      if (spin !== false && shape && shape !== 'sphere') spinNodes.push({ m: core, sx: (Math.random() - 0.5) * 0.009, sy: 0.005 + Math.random() * 0.008 });
      return core;
    }

    const centerColor = opts.center.color;
    const center = mk(centerColor, 0.62, new THREE.Vector3(0, 0, 0), 0.26, 'icosa', false);
    const ringA = new THREE.Mesh(new THREE.TorusGeometry(1.15, 0.028, 8, 60), glowMat(centerColor, 0.55));
    grp.add(ringA);
    const ringB = new THREE.Mesh(new THREE.TorusGeometry(1.55, 0.02, 8, 60), glowMat(centerColor, 0.32));
    ringB.rotation.x = 1.15;
    grp.add(ringB);

    const domeGrp = new THREE.Group();
    grp.add(domeGrp);
    const domeMat = new THREE.LineBasicMaterial({ color: 0x3d5346, transparent: true, opacity: 0.34, blending: THREE.AdditiveBlending });
    const DR = 10.6;
    for (let i = 0; i < 6; i++) {
      const y = DR * Math.cos((Math.PI * (i + 1)) / 7), r = DR * Math.sin((Math.PI * (i + 1)) / 7);
      const pts = [];
      for (let k = 0; k <= 64; k++) {
        const a = (k / 64) * 6.283;
        pts.push(new THREE.Vector3(Math.cos(a) * r, y, Math.sin(a) * r));
      }
      domeGrp.add(new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(pts), domeMat));
    }

    function curvedLink(a, b, color, op) {
      const mid = a.position.clone().add(b.position).multiplyScalar(0.5).multiplyScalar(1.18);
      const curve = new THREE.QuadraticBezierCurve3(a.position.clone(), mid, b.position.clone());
      grp.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(26)), new THREE.LineBasicMaterial({ color, transparent: true, opacity: op, blending: THREE.AdditiveBlending })));
      for (let k = 0; k < 2; k++) {
        const TAIL = 5, tail = [];
        for (let s = 0; s < TAIL; s++) {
          const pm = new THREE.Mesh(new THREE.SphereGeometry(0.09, 8, 8), glowMat(color, 0.9 * (1 - s / TAIL)));
          grp.add(pm);
          tail.push(pm);
        }
        paths.push({ curve, tail, t: k * 0.5 + Math.random() * 0.25, sp: 0.0045 + Math.random() * 0.005, hist: [] });
      }
    }

    const nodes = opts.nodes || [];
    const nN = nodes.length, nodeMeshes = [];
    nodes.forEach((n, i) => {
      const t = (i / nN) * 6.283, c = n.color;
      const size = n.pulse ? 0.44 : 0.34;
      const mesh = mk(c, size, new THREE.Vector3(Math.cos(t) * 4.6, 0, Math.sin(t) * 4.6), n.pulse ? 0.26 : 0.2, 'octa');
      nodeMeshes.push(mesh);
      curvedLink(mesh, center, c, n.pulse ? 0.32 : 0.22);
    });

    const pings = [];
    function ping(pos, color) {
      let p = pings.find((x) => !x.on);
      if (!p) {
        const m = new THREE.Mesh(new THREE.SphereGeometry(1, 20, 20), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.4, wireframe: true, blending: THREE.AdditiveBlending, depthWrite: false }));
        grp.add(m);
        p = { m, on: false };
        pings.push(p);
      }
      p.m.material.color.setHex(color);
      p.m.position.copy(pos);
      p.on = true;
      p.t = 0;
    }

    let dx = 0, dy = 0.12, down = false, px, py;
    canvas.addEventListener('pointerdown', (e) => { down = true; px = e.clientX; py = e.clientY; });
    addEventListener('pointerup', () => (down = false));
    addEventListener('pointermove', (e) => { if (!down) return; dx += (e.clientX - px) * 0.005; dy += (e.clientY - py) * 0.004; px = e.clientX; py = e.clientY; });
    addEventListener('resize', () => { cam.aspect = W() / H(); cam.updateProjectionMatrix(); rn.setSize(W(), H()); composer.setSize(W(), H()); });

    const v = new THREE.Vector3();
    let lastPing = -2000;
    const pingEvery = opts.onPing || 3400;
    (function loop() {
      requestAnimationFrame(loop);
      const tm = performance.now();
      grp.rotation.y = dx + tm * 0.00006;
      grp.rotation.x = dy;
      cam.position.x = Math.sin(tm * 0.00016) * 0.45;
      cam.position.y = Math.cos(tm * 0.00012) * 0.28;
      cam.lookAt(0, 0, 0);
      center.scale.setScalar(1 + Math.sin(tm * 0.003) * 0.11);
      center.rotation.y = tm * 0.0004;
      center.rotation.x = Math.sin(tm * 0.0003) * 0.5;
      center.userData.edges.rotation.copy(center.rotation);
      center.userData.edges.scale.copy(center.scale);
      domeGrp.rotation.y = tm * 0.00002;
      spinNodes.forEach((n) => { n.m.rotation.x += n.sx; n.m.rotation.y += n.sy; n.m.userData.edges.rotation.copy(n.m.rotation); });
      ringA.rotation.z = tm * 0.0006; ringA.rotation.y = tm * 0.0004;
      ringB.rotation.z = -tm * 0.0005; ringB.rotation.x = 1.15 + Math.sin(tm * 0.0005) * 0.3;
      dust.rotation.y = -tm * 0.00003;
      glowNodes.forEach((n) => { n.g.material.opacity = n.base * (0.65 + 0.55 * (0.5 + 0.5 * Math.sin(tm * 0.002 + n.phase))); });
      paths.forEach((p) => {
        p.t += p.sp;
        if (p.t > 1) { p.t = 0; p.hist.length = 0; }
        p.curve.getPoint(p.t, v);
        p.hist.unshift(v.clone());
        if (p.hist.length > p.tail.length) p.hist.pop();
        p.tail.forEach((pm, i) => {
          const pt = p.hist[i];
          if (pt) { pm.visible = true; pm.position.copy(pt); pm.scale.setScalar((1 - i / p.tail.length) * (0.7 + 0.7 * Math.sin(p.t * Math.PI))); }
          else pm.visible = false;
        });
      });
      if (tm - lastPing > pingEvery) { lastPing = tm; ping(center.position, centerColor); }
      pings.forEach((p) => { if (!p.on) return; p.t += 0.03; p.m.scale.setScalar(1 + p.t * 8); p.m.material.opacity = Math.max(0, 0.24 * (1 - p.t)); if (p.t >= 1) p.on = false; });
      composer.render();
    })();

    return { nodeMeshes, center };
  }

  global.EntropyScene = { init: EntropySceneInit };
})(window);
