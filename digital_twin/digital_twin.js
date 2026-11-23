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

      const [px, py] = level(s.center), [dx, dy] = level([ax, ay]);
      const half = Math.max(...s.profile.map(([lo, hi]) => hi - lo)) / 2;
      return {
        ribs, len, half, area: s.visible_pixels || 0,
        at: [px - origin[0], origin[1] - py], dir: [dx, -dy],
        rgb: s.rgb?.length === 3 ? s.rgb : [76, 119, 54]
      };
    });

    const canopy = record.canopy || {};
    const extent = Math.max(canopy.width_px || 0, canopy.height_px || 0);
    const grown = buildPlant(record.capture_identity || record.file_name || 'basil', {centerX, halfWidth, cp, sp, extent});
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

  // Rebuilds the captured plant: every measured leaf becomes a 3D leaf at its
  // measured position, direction, length and width. Only the depth is not
  // in the photo; it is spread so the canopy is deepest in the middle.
  // Stems are traced through the leaf attachment points down into the pot.
  function buildPlant(seed, frame) {
    const {centerX, halfWidth, cp, sp, extent} = frame;
    const rand = seeded(seed), jitter = k => (rand() - .5) * 2 * k;
    const halfDepth = halfWidth * .85;
    const tops = leaves.map(l => l.at[1]), low = Math.min(0, ...tops), high = Math.max(...tops);
    const fromCamera = ([right, up, front]) => [right, up * cp + front * sp, -up * sp + front * cp];
    const toward = fromCamera([0, 0, 1]);

    // A measured patch can hold several leaves (older captures merge dense
    // foliage). It gets as many basil-shaped leaves as it takes to cover its
    // measured area; a single measured leaf stays one leaf.
    const shrink = k => (k > 1 ? .85 : 1);
    const copiesFor = m => {
      if (!(m.area > 0 && extent > 0)) return 1;
      const area = m.area / extent ** 2, one = .62 * m.len * 2 * clamp(m.half, .2 * m.len, .3 * m.len);
      let best = 1;
      for (let k = 2; k <= 4; k++) {
        if (Math.abs(k * shrink(k) ** 2 * one - area) < Math.abs(best * shrink(best) ** 2 * one - area)) best = k;
      }
      return best;
    };

    const blades = [], index = {n: 0};
    for (const m of leaves) {
      const copies = copiesFor(m);
      for (let c = 0; c < copies; c++) {
        const i = index.n++;
        const spread = copies > 1;
        const turn = spread ? jitter(.55) : 0;
        const dir = [m.dir[0] * Math.cos(turn) - m.dir[1] * Math.sin(turn), m.dir[0] * Math.sin(turn) + m.dir[1] * Math.cos(turn)];
        const along = spread ? jitter(.3) * m.len : 0, across = spread ? jitter(.8) * m.half : 0;
        const at = [m.at[0] + m.dir[0] * along - m.dir[1] * across, m.at[1] + m.dir[1] * along + m.dir[0] * across];
        const shown = m.len * shrink(copies);

        // Depth: deepest in the middle of the canopy, layered front to back.
        const nx = (at[0] - centerX) / halfWidth, ny = 2 * (at[1] - low) / Math.max(.01, high - low) - 1;
        const shell = Math.sqrt(Math.max(.04, 1 - nx * nx)) * Math.sqrt(Math.max(.15, 1 - .7 * ny * ny));
        const layer = 2 * (((i + .5) * .61803398875) % 1) - 1;
        const front = halfDepth * shell * layer;

        // The leaf may lean towards or away from the camera; its length in the
        // photo stays exactly as measured.
        const lean = Math.tan(jitter(.6));
        const forward = unit(fromCamera([dir[0], dir[1], lean]));
        const len = shown * Math.hypot(1, lean);
        const centre = fromCamera([at[0], at[1], front]);
        const node = plus(centre, times(forward, -.66 * len));
        const leaf = blade(node, {
          forward, len, rand, facing: toward,
          side: fromCamera([-dir[1], dir[0], 0]),
          half: clamp(m.half * (spread ? .85 : 1), .2 * len, .3 * len)
        });

        const height = clamp((at[1] - low) / Math.max(.01, high - low), 0, 1);
        const rgb = richer(m.rgb, 1.3);
        leaf.rgb = between(between(rgb, [124, 178, 68], .25), [172, 210, 100], .28 * height * height)
          .map(v => v * (.95 + .1 * rand()));
        leaf.under = between(leaf.rgb, [188, 204, 168], .4);
        const outer = Math.hypot(nx, front / halfDepth);
        leaf.ao = .8 + .2 * clamp(Math.max(outer, .3 + .7 * height), 0, 1);
        blades.push(leaf);
      }
    }

    // Stems: group attachment points into shoots, each rising from the soil.
    const count = clamp(Math.round(blades.length / 4), 6, 90);
    const flat = (a, b) => (a[0] - b[0]) ** 2 + (a[2] - b[2]) ** 2;
    const nodes = blades.map(l => l.petiole[0]);
    let centres = [nodes.reduce((a, b) => (flat(a, [centerX, 0, 0]) < flat(b, [centerX, 0, 0]) ? a : b))];
    while (centres.length < count) {
      const gap = nodes.map(p => Math.min(...centres.map(c => flat(c, p))));
      const far = Math.max(...gap);
      if (far < 1e-6) break;
      centres.push(nodes[gap.indexOf(far)]);
    }
    let groups = [];
    for (let pass = 0; pass < 5; pass++) {
      groups = centres.map(() => []);
      blades.forEach(l => {
        const d = centres.map(c => flat(c, l.petiole[0]));
        groups[d.indexOf(Math.min(...d))].push(l);
      });
      centres = groups.map((g, i) => g.length
        ? [0, 1, 2].map(k => g.reduce((sum, l) => sum + l.petiole[0][k], 0) / g.length) : centres[i]);
    }

    const shoots = [];
    for (const group of groups.filter(g => g.length)) {
      group.sort((a, b) => a.petiole[0][1] - b.petiole[0][1]);
      const top = group.at(-1).petiole[0];
      const mean = [0, 2].map(k => group.reduce((sum, l) => sum + l.petiole[0][k], 0) / group.length);
      let foot = [mean[0] * .55, -.012, mean[1] * .55];
      const reach = Math.hypot(foot[0], foot[2]);
      if (reach > .8 * radius) foot = [foot[0] * .8 * radius / reach, -.012, foot[2] * .8 * radius / reach];
      // The stem passes the average position of the leaves at each height.
      const path = [foot];
      const steps = Math.min(7, group.length);
      for (let j = 1; j <= steps; j++) {
        const part = group.slice(Math.floor((j - 1) * group.length / steps), Math.floor(j * group.length / steps));
        const p = [0, 1, 2].map(k => part.reduce((sum, l) => sum + l.petiole[0][k], 0) / part.length);
        const prev = path.at(-1);
        p[1] = Math.max(p[1], prev[1] + .01);
        path.push(between(prev, p, .9));
      }
      path.push(top[1] > path.at(-1)[1] ? top : plus(path.at(-1), [0, .02, 0]));
      for (let j = 1; j < path.length; j++) {
        shoots.push({pts: [path[j - 1], between(path[j - 1], path[j], .5), path[j]],
          r: mix(.0028, .0012, j / path.length)});
      }
      // Each leaf stalk reaches from the stem at its height to the leaf.
      for (const l of group) {
        const y = l.petiole[0][1];
        let best = path[0];
        for (let j = 1; j < path.length; j++) {
          const a = path[j - 1], b = path[j];
          const t = clamp((y - a[1]) / Math.max(1e-6, b[1] - a[1]), 0, 1);
          const q = between(a, b, t);
          if (Math.abs(q[1] - y) < Math.abs(best[1] - y)) best = q;
        }
        l.petiole[0] = best;
      }
    }
    return {blades, shoots};
  }

  // One basil leaf along a given direction: short petiole, ovate blade with a
  // pointed tip, a slight droop and edges curled down (basil leaves are cupped).
  // The blade's flat side is turned towards `facing` (the camera at capture).
  function blade(node, {forward, len, half, side, facing, rand}) {
    side = unit(plus(side, times(forward, -dot(side, forward))));
    let up = cross(side, forward);
    if (dot(up, facing) < 0) [side, up] = [times(side, -1), times(up, -1)];
    const roll = (rand() - .5) * .7;
    [side, up] = [plus(times(side, Math.cos(roll)), times(up, Math.sin(roll))),
      plus(times(up, Math.cos(roll)), times(side, -Math.sin(roll)))];

    const droop = .06 + .14 * rand(), cup = .16 + .12 * rand();
    const start = plus(node, times(forward, .16 * len));
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

  // Draws a projected leaf. Each half is shaded from the midrib (where light
  // catches the fold) to the edge (curling away), with a faint darker rim.
  function drawLeaf(g, ribs, look) {
    const last = ribs.length - 1, mid = last >> 1, vein = ribs.map(r => r[1]);

    function edge(points) {
      for (let k = 1; k < points.length - 1; k++) {
        const p = points[k], q = points[k + 1];
        g.quadraticCurveTo(p[0], p[1], (p[0] + q[0]) / 2, (p[1] + q[1]) / 2);
      }
      const p = points.at(-1);
      g.lineTo(p[0], p[1]);
    }

    for (const [side, tone] of [[0, look.left], [2, look.right]]) {
      const from = vein[mid], to = ribs[mid][side];
      const shade = g.createLinearGradient(from[0], from[1], to[0] + .01, to[1]);
      shade.addColorStop(0, tone[0]);
      shade.addColorStop(.4, tone[1]);
      shade.addColorStop(1, tone[2]);
      g.beginPath();
      g.moveTo(vein[0][0], vein[0][1]);
      edge(ribs.map(r => r[side]));
      edge(vein.slice().reverse());
      g.closePath();
      g.fillStyle = shade;
      g.fill();
    }

    const length = Math.hypot(vein[last][0] - vein[0][0], vein[last][1] - vein[0][1]);
    g.globalAlpha = .55;
    if (length > 22) {
      for (const u of [.25, .45, .65]) {
        const j = Math.round(u * last), k = Math.min(last, j + 2);
        for (const side of [0, 2]) {
          stroke(g, [vein[j], between(ribs[k][1], ribs[k][side], .65)], look.vein, look.width * .35);
        }
      }
    }
    if (length > 8) stroke(g, vein.slice(0, last), look.vein, look.width * .6);

    g.globalAlpha = .35;
    g.beginPath();
    g.moveTo(vein[0][0], vein[0][1]);
    edge(ribs.map(r => r[0]));
    edge(ribs.map(r => r[2]).reverse());
    g.closePath();
    g.strokeStyle = look.ink;
    g.lineWidth = look.width * .6;
    g.stroke();
    g.globalAlpha = 1;
  }

  // Three gradient stops for one leaf half: gloss at the midrib, body, darker edge.
  function tones(rgb, light, gloss = 0) {
    return [
      color(between(rgb, [236, 244, 206], gloss), light * 1.04),
      color(rgb, light),
      color(rgb, light * .8)
    ];
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

    // A stem: a body stroke with a thin light streak, so it reads as round.
    function tube(pts, width) {
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (const p of pts.slice(1)) ctx.lineTo(p[0], p[1]);
      ctx.strokeStyle = '#86a35a';
      ctx.lineWidth = width;
      ctx.stroke();
      if (width > 2) {
        ctx.strokeStyle = 'rgba(214,232,170,.55)';
        ctx.lineWidth = width * .3;
        ctx.stroke();
      }
    }

    // Stems and leaf stalks sit just behind the foliage: they show through the
    // gaps between leaves, as in the photo, instead of crossing over them.
    const behind = (pts, draw) => queue.push({z: pts.reduce((sum, p) => sum + p[2], 0) / pts.length - .08 * span, draw});
    for (const shoot of shoots) {
      const pts = shoot.pts.map(p => project(p, size));
      behind(pts, () => tube(pts, Math.max(.9, 2 * shoot.r * scale * size)));
    }

    // Each leaf half is lit by a fixed light from the upper left; lit halves get
    // a soft gloss, leaves deep inside the bush are darker.
    for (const leaf of blades) {
      const ribs = leaf.ribs.map(r => r.map(p => project(p, size)));
      const stalk = leaf.petiole.map(p => project(p, size));
      const [left, right] = leaf.normals.map(n => {
        let v = view(n);
        const under = v[2] < 0;
        if (under) v = times(v, -1);
        const d = Math.max(0, dot(v, sun));
        const light = (.8 + .34 * d) * leaf.ao;
        return tones(under ? leaf.under : leaf.rgb, light, under ? 0 : .35 * d ** 3);
      });
      const look = {
        left, right, width: line,
        ink: color(leaf.rgb, .55 * leaf.ao), vein: color(leaf.rgb, 1.15 * leaf.ao)
      };
      behind(stalk, () => tube(stalk, Math.max(.7, .0022 * scale * size)));
      add(ribs.map(r => r[1]), () => drawLeaf(ctx, ribs, look));
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
        const g = tile.getContext('2d'), rgb = richer(l.rgb, 1.15);
        g.lineCap = g.lineJoin = 'round';

        drawLeaf(g, l.ribs.map(r => r.map(([x, y, z]) => [
          52 + (x - (x0 + x1) / 2) * s,
          35 - (y * Math.cos(homePitch) - z * Math.sin(homePitch) - (y0 + y1) / 2) * s,
          z
        ])), {
          left: tones(rgb, 1.02, .2), right: tones(rgb, .86), width: 1.4,
          ink: color(rgb, .55), vein: color(rgb, 1.15)
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
