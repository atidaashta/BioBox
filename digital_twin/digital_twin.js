'use strict';

(() => {
  const id = name => document.getElementById(name);
  const canvas = id('plant'), stage = canvas?.parentElement;
  if (!stage) return;

  const ctx = canvas.getContext('2d'), slider = id('days'), tray = id('leaf-tray');
  const toggle = id('leaves-button'), list = id('leaf-list'), status = id('twin-empty');
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const mix = (a, b, t) => a + (b - a) * t;
  const between = (a, b, t) => a.map((v, i) => mix(v, b[i], t));
  const pair = a => Array.isArray(a) && a.length === 2 && a.every(Number.isFinite);
  const color = (rgb, light = 1) => 'rgb(' + rgb.map(v => Math.round(clamp(v * light, 0, 255))).join(',') + ')';
  const pi = Math.PI, rad = pi / 180;

  // Small 3D vector helpers.
  const plus = (a, b) => a.map((v, i) => v + b[i]);
  const times = (a, k) => a.map(v => v * k);
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const unit = a => times(a, 1 / (Math.hypot(...a) || 1));
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

  const reset = id('reset-view') || document.createElement('button');
  reset.id = 'reset-view';
  reset.type = 'button';
  reset.textContent = 'Ansicht zurücksetzen';
  reset.style.cssText = 'position:absolute;top:12px;left:12px;z-index:2;padding:8px 10px;border:1px solid #cbd9ce;border-radius:10px;background:#fbfdf9;color:#203328;font:600 13px system-ui;cursor:pointer';
  stage.append(reset);
  reset.hidden = true;

  let leaves = [], blades = [], shoots = [], viewer;
  let homePitch = 0, roll = 0, pitch = 0, yaw = 0;
  let radius, potHeight, potColor, midY, span, drag, zoom = 1, queued = false;
  let size = 1, startSize = 1, goal = 1, started = 0;

  function makeModel(record) {
    const cam = record.camera || {}, rim = cam.rim || {};
    const rows = (record.leaves || []).filter(s => pair(s.center) && pair(s.axis) &&
      Math.hypot(...s.axis) > 0 && Number.isFinite(s.length) && s.length > 0 &&
      Array.isArray(s.profile) && s.profile.length >= 3 && s.profile.every(pair));

    if (!rows.length) throw Error('Diese Aufnahme enthält keine auswertbaren Blattkonturen.');

    homePitch = clamp(cam.elevation_deg ?? (record.view === 'top' ? 85 : 0), -90, 90) * rad;
    roll = (cam.roll_deg || 0) * rad;
    const cr = Math.cos(roll), sr = Math.sin(roll);
    const cp = Math.cos(homePitch), sp = Math.sin(homePitch);
    const level = ([x, y]) => [x * cr + y * sr, -x * sr + y * cr];

    const projectEnds = rows.flatMap(s => [-0.5, 0.5].map(k =>
      level(s.center.map((v, i) => v + k * s.axis[i] * s.length))));
    const xs = projectEnds.map(p => p[0]), ys = projectEnds.map(p => p[1]);
    const low = Math.max(...ys), high = Math.min(...ys);
    const width = Math.max(...xs) - Math.min(...xs);

    const origin = pair(rim.center) ? level(rim.center) :
      [(Math.min(...xs) + Math.max(...xs)) / 2, mix(low + .035, (low + high) / 2, sp * sp)];

    radius = rim.diameter > 0 ? rim.diameter / 2 : clamp(width * .30, .12, .43);
    potHeight = rim.drop > 0 && cp > .35 ? clamp(rim.drop / cp, .35 * radius, 3 * radius) : 1.4 * radius;
    potColor = rim.rgb?.length === 3 ? rim.rgb : [63, 65, 61];

    const halfWidth = Math.max(.025, width / 2);
    const centerX = (Math.min(...xs) + Math.max(...xs)) / 2 - origin[0];

    // The measured blades, kept flat in the camera plane. They drive the leaf
    // count, the leaf tray and the outline the grown plant has to fill.
    leaves = rows.map(s => {
      const len = s.length, axisNorm = Math.hypot(...s.axis);
      const [ax, ay] = s.axis.map(v => v / axisNorm);
      const [cx, cy] = s.center;
      const n = s.profile.length - 1;

      const ribs = s.profile.map((p, j) => {
        const u = j / n;
        const before = s.profile[Math.max(0, j - 1)], after = s.profile[Math.min(n, j + 1)];
        const [lo, hi] = p.map((v, k) => .20 * before[k] + .60 * v + .20 * after[k]);
        const mid = (lo + hi) / 2, half = j && j < n ? Math.max(0, (hi - lo) / 2) : 0;

        return [-1, 0, 1].map(side => {
          const offset = mid + half * side, along = (u - .5) * len;
          const [lx, ly] = level([cx + ax * along - ay * offset, cy + ay * along + ax * offset]);
          const up = origin[1] - ly;
          return [lx - origin[0], up * cp, -up * sp];
        });
      });

      return {ribs, len, area: s.visible_pixels || 0, rgb: s.rgb?.length === 3 ? s.rgb : [76, 119, 54]};
    });

    const canopy = record.canopy || {};
    const extent = Math.max(canopy.width_px || 0, canopy.height_px || 0);
    const grown = growPlant(record.capture_identity || record.file_name || 'basil', {centerX, halfWidth, cp, sp, extent});
    blades = grown.blades;
    shoots = grown.shoots;

    const points = blades.flatMap(l => l.ribs.flat()).concat(shoots.flatMap(s => s.pts));
    const bottom = Math.min(-potHeight, ...points.map(p => p[1]));
    const top = Math.max(0, ...points.map(p => p[1]));
    midY = (top + bottom) / 2;
    span = Math.max(.1, ...points.map(p => Math.hypot(p[0], p[1] - midY, p[2])),
      Math.hypot(radius * 1.17, midY + potHeight), Math.hypot(radius, midY));
  }

  // Repeatable random numbers: the same capture always grows the same plant.
  function seeded(text) {
    let h = 2166136261;
    for (const c of String(text)) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
    return () => {
      h = h + 0x6D2B79F5 | 0;
      let t = Math.imul(h ^ h >>> 15, 1 | h);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }

  // Cartoon colours: a little more saturated than the photo, never grey.
  function richer(rgb, amount = 1.35) {
    const lum = .3 * rgb[0] + .59 * rgb[1] + .11 * rgb[2];
    return rgb.map(v => clamp(lum + (v - lum) * amount, 0, 255));
  }

  // Grows a basil plant into the measured canopy: stems fan out of the soil,
  // carry opposite leaf pairs (each pair turned 90° to the last) and end in
  // a small cluster of young leaves. Size, outline, leaf count, leaf length
  // and colour all come from the capture.
  function growPlant(seed, frame) {
    const {centerX, halfWidth, cp, sp, extent} = frame;
    const rand = seeded(seed), jitter = k => (rand() - .5) * 2 * k;
    const halfDepth = halfWidth * .9;
    const screenUp = p => p[1] * cp - p[2] * sp;

    // Highest foliage per column of the capture: the outline the plant fills.
    const bins = 18, left = centerX - halfWidth, roof = new Array(bins).fill(0);
    for (const p of leaves.flatMap(l => l.ribs.flat())) {
      const b = clamp(Math.floor((p[0] - left) / (2 * halfWidth) * bins), 0, bins - 1);
      roof[b] = Math.max(roof[b], screenUp(p));
    }
    const filled = roof.map((v, i) => Math.max(v, .85 * Math.min(roof[i - 1] ?? v, roof[i + 1] ?? v)));
    const fromAbove = cp < .5;
    const peak = fromAbove ? halfWidth * 1.05 : Math.max(...filled) / cp;
    const heightAt = x => {
      if (fromAbove) return peak * Math.sqrt(Math.max(.1, 1 - ((x - centerX) / halfWidth) ** 2));
      const t = clamp((x - left) / (2 * halfWidth) * bins - .5, 0, bins - 1), i = Math.floor(t);
      return Math.max(.08, mix(filled[i], filled[Math.min(bins - 1, i + 1)], t - i) / cp);
    };

    // Each grown leaf borrows the colour of the nearest measured blade.
    const samples = leaves.map(l => {
      const c = l.ribs[l.ribs.length >> 1][1];
      return [c[0], screenUp(c), l.rgb];
    });
    const tint = (x, y) => samples.reduce((best, s) =>
      (s[0] - x) ** 2 + (s[1] - y) ** 2 < (best[0] - x) ** 2 + (best[1] - y) ** 2 ? s : best)[2];

    const sizes = leaves.map(l => l.len).sort((a, b) => a - b);
    const typical = sizes[Math.floor(sizes.length * .75)] || .06;
    // The measured outlines in the dense middle are patches holding several
    // leaves, so the count comes from the leaf area: visible area divided by
    // the area of one typical leaf. Doubled, because leaves are seen at an
    // angle (about half their area faces the camera) and some hide behind others.
    const area = extent > 0 ? leaves.reduce((sum, l) => sum + l.area, 0) / extent ** 2 : 0;
    const perLeaf = .62 * typical * typical * .56;
    const target = Math.round(clamp(area ? 2 * area / perLeaf : leaves.length, leaves.length, 3 * leaves.length));
    const count = clamp(Math.round(target / 22), 5, 30);

    // Stem tops are spread over the canopy, their feet gather in the pot.
    const plan = Array.from({length: count}, (_, i) => {
      const u = clamp(-1 + 2 * (i + .5) / count + jitter(.7 / count), -1, 1);
      const v = jitter(1) * Math.sqrt(1 - u * u);
      const tip = [centerX + u * halfWidth * .9, 0, v * halfDepth * .88];
      tip[1] = heightAt(tip[0]) * (.35 + .65 * Math.sqrt(rand())) * Math.sqrt(1 - .3 * v * v) * .93;
      let foot = [(u * .75 + jitter(.12)) * radius, -.012, (v * .7 + jitter(.12)) * radius];
      const reach = Math.hypot(foot[0], foot[2]);
      if (reach > .82 * radius) foot = [foot[0] * .82 * radius / reach, -.012, foot[2] * .82 * radius / reach];
      return {tip, foot, length: Math.hypot(...plus(tip, times(foot, -1)))};
    });
    const total = plan.reduce((sum, s) => sum + s.length, 0);
    const blades = [], shoots = [];

    // One shoot: a curved stem with leaf pairs at its nodes, ending in young leaves.
    // Lower nodes of a main stem also sprout a side shoot, as basil does.
    function branch(foot, bend, tip, nodes, scale, side) {
      const at = s => [0, 1, 2].map(k => (1 - s) ** 2 * foot[k] + 2 * (1 - s) * s * bend[k] + s * s * tip[k]);
      const phase = rand() * pi, thick = (side ? .55 : .8) + .4 * rand();
      const stops = [0];

      for (let k = 0; k <= nodes; k++) {
        const apex = k === nodes;
        const s = apex ? 1 : side ? .35 + .5 * (k + 1) / (nodes + 1) : .1 + .82 * ((k + .5) / (nodes + .5)) ** .85;
        const node = at(s);
        if (!apex) stops.push(s);

        // Each entry is [turn, size, rise]. A main stem tip carries two crossed
        // pairs (a star of young leaves), a side shoot tip one pair.
        const crown = apex && !side
          ? [[0, .62, .7], [pi, .62, .7], [pi / 2, .42, 1.05], [-pi / 2, .42, 1.05]]
          : apex ? [[0, .5, .9], [pi, .5, .9]] : [[0], [pi]];
        for (const [turn, small, rise] of crown) {
          const az = phase + k * pi / 2 + turn + jitter(.3);
          const lower = clamp(node[1] / peak, 0, 1);
          const leaf = blade(node, {
            az,
            lift: apex ? rise + jitter(.2) : mix(-.95, .75, lower) + jitter(.5),
            len: typical * scale * (apex ? small : 1.45 - .45 * lower * lower) * (.85 + .3 * rand()),
            roll: jitter(.8), rand
          });
          const rgb = richer(tint(node[0], node[1] * cp), 1.6);
          const young = apex ? .5 : .28 * lower * lower;
          leaf.rgb = between(between(rgb, [132, 186, 70], .3), [170, 210, 92], young).map(v => v * (.94 + .12 * rand()));
          leaf.under = between(leaf.rgb, [200, 216, 170], .45);
          const outer = Math.hypot((node[0] - centerX) / halfWidth, node[2] / halfDepth);
          leaf.ao = .76 + .24 * clamp(Math.max(outer, .3 + .7 * lower), 0, 1);
          blades.push(leaf);

          if (!side && !apex && s < .85 && rand() < .35) {
            const out = az + pi / 4 * (rand() < .5 ? 1 : -1);
            const reach = (1 - s) * Math.hypot(...plus(tip, times(foot, -1))) * (.25 + .25 * rand());
            const end = plus(node, [Math.cos(out) * reach * .55, reach * .85, Math.sin(out) * reach * .55]);
            const mid = plus(between(node, end, .5), [0, -reach * .12, 0]);
            branch(node, mid, end, 1 + (rand() < .5 ? 1 : 0), .72, true);
          }
        }
      }

      // Stem pieces between leaf nodes, so leaves can sit in front of or behind them.
      stops.push(1);
      for (let i = 1; i < stops.length; i++) {
        const s0 = stops[i - 1], s1 = stops[i];
        shoots.push({
          pts: [0, .25, .5, .75, 1].map(t => at(mix(s0, s1, t))),
          r: mix(.0027, .0011, (s0 + s1) / 2) * thick
        });
      }
    }

    // A main stem carries 4 crown leaves plus 2 leaves per node, and each of
    // those leaves has a 35 % chance of a side shoot (~5 leaves): ~5.5 per node.
    const nodes = Math.max(count, Math.round((target - 4 * count) / 5.5));
    for (const {tip, foot, length} of plan) {
      const bend = [mix(foot[0], tip[0], .22), tip[1] * .5, mix(foot[2], tip[2], .22)];
      branch(foot, bend, tip, Math.max(1, Math.round(nodes * length / total)), 1, false);
    }
    return {blades, shoots};
  }

  // One basil leaf: short petiole, ovate blade with a pointed tip, the midrib
  // arching so the tip droops, and the edges curled down (basil leaves are cupped).
  function blade(node, {az, lift, len, roll, rand}) {
    const forward = [Math.cos(az) * Math.cos(lift), Math.sin(lift), Math.sin(az) * Math.cos(lift)];
    let side = unit(cross(forward, [0, 1, 0]));
    let up = cross(side, forward);
    [side, up] = [plus(times(side, Math.cos(roll)), times(up, Math.sin(roll))),
      plus(times(up, Math.cos(roll)), times(side, -Math.sin(roll)))];

    const half = len * (.27 + .06 * rand()), droop = .16 + .22 * rand(), cup = .2 + .14 * rand();
    const start = plus(node, plus(times(forward, .16 * len), times(up, -.03 * len)));
    const steps = 12;
    const ribs = Array.from({length: steps + 1}, (_, j) => {
      const u = j / steps;
      const mid = plus(start, plus(times(forward, u * len), times(up, -droop * len * u * u)));
      const w = half * Math.max(0, Math.sin(pi * u ** .72)) ** 1.1;
      return [-1, 0, 1].map(k => plus(mid, plus(times(side, k * w), times(up, -cup * w * Math.abs(k)))));
    });

    return {
      ribs, len, petiole: [node, start],
      normals: [unit(plus(up, times(side, -cup * 1.6))), unit(plus(up, times(side, cup * 1.6)))]
    };
  }

  function stroke(g, pts, ink, thickness) {
    g.beginPath();
    g.moveTo(...pts[0].slice(0, 2));
    for (const p of pts.slice(1)) g.lineTo(p[0], p[1]);
    g.strokeStyle = ink;
    g.lineWidth = thickness;
    g.stroke();
  }

  // Draws a projected leaf in cartoon style: each half in one flat tone,
  // light veins, a dark green ink outline.
  function drawLeaf(g, ribs, look) {
    const last = ribs.length - 1, vein = ribs.map(r => r[1]);

    function edge(points) {
      for (let k = 1; k < points.length - 1; k++) {
        const p = points[k], q = points[k + 1];
        g.quadraticCurveTo(p[0], p[1], (p[0] + q[0]) / 2, (p[1] + q[1]) / 2);
      }
      const p = points.at(-1);
      g.lineTo(p[0], p[1]);
    }

    for (const [side, tone] of [[0, look.left], [2, look.right]]) {
      g.beginPath();
      g.moveTo(vein[0][0], vein[0][1]);
      edge(ribs.map(r => r[side]));
      edge(vein.slice().reverse());
      g.closePath();
      g.fillStyle = tone;
      g.fill();
    }

    const length = Math.hypot(vein[last][0] - vein[0][0], vein[last][1] - vein[0][1]);
    if (length > 16) {
      for (const u of [.2, .4, .6]) {
        const j = Math.round(u * last), k = Math.min(last, j + 2);
        for (const side of [0, 2]) {
          stroke(g, [vein[j], between(ribs[k][1], ribs[k][side], .7)], look.vein, look.width * .45);
        }
      }
    }
    if (length > 6) stroke(g, vein.slice(0, last), look.vein, look.width * .7);

    g.beginPath();
    g.moveTo(vein[0][0], vein[0][1]);
    edge(ribs.map(r => r[0]));
    edge(ribs.map(r => r[2]).reverse());
    g.closePath();
    g.strokeStyle = look.ink;
    g.lineWidth = look.width;
    g.stroke();
  }

  function paint() {
    queued = false;
    if (!leaves.length || canvas.hidden) return;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.lineCap = ctx.lineJoin = 'round';

    const t = clamp((performance.now() - started) / 380, 0, 1);
    size = mix(startSize, goal, t * t * (3 - 2 * t));
    const scale = Math.min(w * .47, h * .44) * zoom / span;
    const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
    const cr = Math.cos(roll), sr = Math.sin(roll);

    function project([x, y, z], growth = 1) {
      const right = (x * cy + z * sy) * growth;
      const depth = (z * cy - x * sy) * growth, up = y * growth - midY;
      const down = depth * sp - up * cp;
      return [
        w / 2 + (right * cr - down * sr) * scale,
        h / 2 + (right * sr + down * cr) * scale,
        up * sp + depth * cp
      ];
    }

    // A direction as seen by the viewer: [right, up, towards the viewer].
    function view([x, y, z]) {
      const right = x * cy + z * sy, depth = z * cy - x * sy;
      return [right, y * cp - depth * sp, y * sp + depth * cp];
    }

    const queue = [];
    const add = (pts, draw) => queue.push({
      z: pts.reduce((sum, p) => sum + p[2], 0) / pts.length, draw
    });
    const ring = (r, y, k) => project([r * Math.cos(k * pi / 24), y, r * Math.sin(k * pi / 24)]);

    function fill(pts, ink) {
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (const p of pts.slice(1)) ctx.lineTo(p[0], p[1]);
      ctx.closePath();
      ctx.fillStyle = ink;
      ctx.fill();
      ctx.strokeStyle = ink;
      ctx.lineWidth = .45;
      ctx.stroke();
    }

    const floor = project([0, -potHeight, 0]);
    if (pitch >= 0) {
      ctx.save();
      ctx.translate(floor[0], floor[1]);
      ctx.rotate(roll);
      ctx.scale(radius * scale * 1.38, radius * scale * Math.max(.07, sp));
      const shadow = ctx.createRadialGradient(0, 0, 0, 0, 0, 1);
      shadow.addColorStop(0, 'rgba(43,53,40,.26)');
      shadow.addColorStop(1, 'rgba(43,53,40,0)');
      ctx.fillStyle = shadow;
      ctx.fillRect(-1, -1, 2, 2);
      ctx.restore();
    } else {
      const base = Array.from({length: 48}, (_, k) => ring(1.08 * radius, -potHeight, k));
      add(base, () => fill(base, color(potColor, .67)));
    }

    // Pot shape traced from the capture: tapered body, three grooves,
    // a tall rim band and a saucer. Each entry is [radius, height, light].
    const body = y => mix(.68, .885, (y + .93) / .685);
    const pot = [[body(-.965), -.965, 1]];
    for (const g of [-.47, -.44, -.41]) {
      pot.push([body(g - .012), g - .012, 1], [body(g) - .012, g, .55], [body(g + .012), g + .012, 1.25]);
    }
    pot.push([.885, -.245, 1], [.975, -.24, .8], [1, 0, 1.08], [.95, 0, 1.35]);
    const saucer = [[1.08, -1, 1], [1.17, -.875, 1.05], [1.13, -.87, 1.3], [1.07, -.965, .7], [body(-.965), -.965, .8]];
    const soil = project([0, -.012, 0]);

    for (let k = 0; k < 48; k++) {
      const surface = [soil, ring(.94 * radius, -.012, k), ring(.94 * radius, -.012, k + 1)];
      add(surface, () => fill(surface, '#514134'));
      const facing = Math.cos(k * pi / 24 + yaw + .8);
      const sheen = .2 * Math.max(0, facing) ** 6;

      for (const shape of [pot, saucer]) {
        for (let j = 1; j < shape.length; j++) {
          const [r, y] = shape[j - 1], [rr, yy, light] = shape[j];
          const pts = [
            ring(r * radius, y * potHeight, k), ring(r * radius, y * potHeight, k + 1),
            ring(rr * radius, yy * potHeight, k + 1), ring(rr * radius, yy * potHeight, k)
          ];
          const ink = between(potColor.map(v => v * (.82 + .3 * facing) * light), [150, 152, 158], sheen);
          add(pts, () => fill(pts, color(ink)));
        }
      }
    }

    const line = clamp(scale * .0016, .5, 1.5);
    const sun = unit([-.35, .8, .55]);

    function tube(pts, width, body, rim) {
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (const p of pts.slice(1)) ctx.lineTo(p[0], p[1]);
      ctx.strokeStyle = rim;
      ctx.lineWidth = width + 1.2 * line;
      ctx.stroke();
      ctx.strokeStyle = body;
      ctx.lineWidth = width;
      ctx.stroke();
    }

    for (const shoot of shoots) {
      const pts = shoot.pts.map(p => project(p, size));
      add(pts, () => tube(pts, Math.max(.9, 2 * shoot.r * scale * size), '#9cba68', '#5d7a3f'));
    }

    // Cel shading: each leaf half is lit by a fixed light from the upper left.
    // Three tones only, plus a darker tint deep inside the bush.
    for (const leaf of blades) {
      const ribs = leaf.ribs.map(r => r.map(p => project(p, size)));
      const stalk = leaf.petiole.map(p => project(p, size));
      const [left, right] = leaf.normals.map(n => {
        let v = view(n);
        const under = v[2] < 0;
        if (under) v = times(v, -1);
        const d = dot(v, sun);
        const band = d > .62 ? 1.1 : d > .25 ? .93 : .76;
        return color(under ? leaf.under : leaf.rgb, band * leaf.ao);
      });
      const look = {
        left, right, width: line,
        ink: color(leaf.rgb, .4 * leaf.ao), vein: color(leaf.rgb, 1.2 * leaf.ao)
      };
      add(ribs.map(r => r[1]), () => {
        tube(stalk, Math.max(.7, .0026 * scale * size), '#9cba68', '#5d7a3f');
        drawLeaf(ctx, ribs, look);
      });
    }

    queue.sort((a, b) => a.z - b.z).forEach(item => item.draw());
    if (t < 1 && size !== goal) redraw();
  }

  function redraw() {
    if (!queued) {
      queued = true;
      requestAnimationFrame(paint);
    }
  }

  function setTray(open) {
    if (tray) tray.hidden = !open;
    canvas.hidden = open;
    toggle?.setAttribute('aria-pressed', String(open));
    if (id('count-text')) id('count-text').textContent = open ? 'Zur Pflanze' : 'Blätter zählen';

    if (open && list && !list.childElementCount) {
      leaves.forEach((l, i) => {
        const tile = document.createElement('canvas'), item = document.createElement('li');
        tile.width = 104;
        tile.height = 70;
        const points = l.ribs.flat(), xs = points.map(p => p[0]);
        const ys = points.map(p => p[1] * Math.cos(homePitch) - p[2] * Math.sin(homePitch));
        const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
        const s = Math.min(88 / Math.max(.001, x1 - x0), 56 / Math.max(.001, y1 - y0));
        const g = tile.getContext('2d'), rgb = richer(l.rgb);
        g.lineCap = g.lineJoin = 'round';

        drawLeaf(g, l.ribs.map(r => r.map(([x, y, z]) => [
          52 + (x - (x0 + x1) / 2) * s,
          35 - (y * Math.cos(homePitch) - z * Math.sin(homePitch) - (y0 + y1) / 2) * s,
          z
        ])), {
          left: color(rgb, 1.06), right: color(rgb, .88), width: 1.2,
          ink: color(rgb, .4), vein: color(rgb, 1.2)
        });

        item.append(tile, String(i + 1));
        list.append(item);
      });
    }
    redraw();
  }

  function updateDay() {
    const day = Number(slider?.value || 0);
    const point = viewer.growth?.trajectory?.find(p => p.day === day);
    const rate = Number.isFinite(viewer.rate) ? viewer.rate / 100 : .02;
    const ratio = point?.area_ratio > 0 ? point.area_ratio : Math.pow(1 + clamp(rate, -.5, 1), day);
    goal = day ? clamp(Math.sqrt(ratio), .55, 1.50) : 1;
    startSize = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? goal : size;
    started = performance.now();

    if (id('day-text')) {
      id('day-text').textContent = day
        ? (point ? 'Prognose' : 'Szenario') + ' · +' + day + (day === 1 ? ' Tag' : ' Tage')
        : 'Aufnahme';
    }
    redraw();
  }

  function home() {
    yaw = 0;
    pitch = homePitch;
    zoom = 1;
    drag = null;
    if (slider) slider.value = '0';
    size = 1;
    setTray(false);
    updateDay();
  }

  reset.onclick = home;
  canvas.ondblclick = home;
  if (slider) slider.oninput = updateDay;
  if (toggle && tray) toggle.onclick = () => setTray(tray.hidden);

  canvas.onpointerdown = e => {
    if (e.button !== 0 || drag) return;
    drag = [e.pointerId, e.clientX, e.clientY];
    canvas.setPointerCapture(e.pointerId);
  };

  canvas.onpointermove = e => {
    if (drag?.[0] !== e.pointerId) return;
    yaw += (e.clientX - drag[1]) * .01;
    pitch = clamp(pitch + (e.clientY - drag[2]) * .009, -pi / 2, pi / 2);
    drag = [e.pointerId, e.clientX, e.clientY];
    redraw();
  };

  canvas.onpointerup = canvas.onpointercancel = canvas.onlostpointercapture = e => {
    if (drag?.[0] === e.pointerId) drag = null;
  };

  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    zoom = clamp(zoom * Math.exp(-e.deltaY * .001), .55, 2.5);
    redraw();
  }, {passive: false});

  canvas.onkeydown = e => {
    if (e.key === 'Home') home();
    else if (e.key === 'ArrowLeft') yaw -= .12;
    else if (e.key === 'ArrowRight') yaw += .12;
    else if (e.key === 'ArrowUp') pitch = Math.min(pi / 2, pitch + .08);
    else if (e.key === 'ArrowDown') pitch = Math.max(-pi / 2, pitch - .08);
    else return;
    e.preventDefault();
    redraw();
  };

  new ResizeObserver(redraw).observe(stage);

  function show(data) {
    viewer = data?.viewer || data;
    if (!ctx || !viewer?.latest) throw Error('Für diese Aufnahme liegen keine 3D-Daten vor.');
    makeModel(viewer.latest);

    if (status) status.hidden = true;
    if (id('data-load')) id('data-load').hidden = true;
    if (slider) slider.disabled = false;
    if (toggle) toggle.hidden = !tray;
    if (id('count-badge')) {
      id('count-badge').textContent = (viewer.latest.count_estimated ? '≈' : '') + leaves.length;
    }
    list?.replaceChildren();

    const date = new Date(viewer.latest.captured_at || NaN), time = id('capture-time');
    if (time) {
      time.hidden = !Number.isFinite(+date);
      if (!time.hidden) {
        time.dateTime = date.toISOString();
        time.textContent = date.toLocaleString('de-DE', {
          dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/Berlin'
        });
      }
    }
    reset.hidden = false;
    home();
  }

  function error(message) {
    if (status) {
      status.textContent = message;
      status.hidden = false;
    }
    if (id('data-load')) id('data-load').hidden = false;
  }

  const input = id('data-file');
  if (input) input.onchange = async () => {
    if (!input.files[0]) return;
    try {
      show(JSON.parse(await input.files[0].text()));
    } catch (e) {
      error(e.message);
    }
    input.value = '';
  };

  (async () => {
    const embedded = (id('biobox-snapshot') || id('digital-twin-data'))?.textContent.trim();
    try {
      if (location.protocol === 'file:') {
        if (!embedded) {
          throw Error('Die Aufnahme fehlt in dieser HTML-Datei. Bitte die BioBox-Auswertung aktualisieren.');
        }
        show(JSON.parse(embedded));
      } else {
        const response = await fetch('digital_twin.json', {cache: 'no-store'});
        if (!response.ok) throw Error('Die Auswertung digital_twin.json fehlt.');
        show(await response.json());
      }
    } catch (e) {
      error(e.message);
    }
  })();
})();