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

  const reset = id('reset-view') || document.createElement('button');
  reset.id = 'reset-view';
  reset.type = 'button';
  reset.textContent = 'Ansicht zurücksetzen';
  reset.style.cssText = 'position:absolute;top:12px;left:12px;z-index:2;padding:8px 10px;border:1px solid #cbd9ce;border-radius:10px;background:#fbfdf9;color:#203328;font:600 13px system-ui;cursor:pointer';
  stage.append(reset);
  reset.hidden = true;

  let leaves = [], canopyLeaves = [], stems = [], viewer;
  let homePitch = 0, roll = 0, pitch = 0, yaw = 0;
  let radius, potHeight, potColor, midY, span, drag, zoom = 1, queued = false;
  let size = 1, startSize = 1, goal = 1, started = 0;

  function makeModel(record) {
    const cam = record.camera || {}, rim = cam.rim || {}, canopy = record.canopy || {};
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

    const depth = canopy.depth;
    const extent = Math.max(canopy.width_px || 1, canopy.height_px || 1);

    function measuredDepth(x, y) {
      if (!depth?.samples || !(depth.units > 0)) return null;
      const u = (.5 + x * extent / canopy.width_px) * depth.width - .5;
      const v = (.5 + y * extent / canopy.height_px) * depth.height - .5;
      let sum = 0, weight = 0;

      for (let j = Math.floor(v); j <= Math.floor(v) + 1; j++) {
        for (let i = Math.floor(u); i <= Math.floor(u) + 1; i++) {
          if (i < 0 || j < 0 || i >= depth.width || j >= depth.height) continue;
          const d = depth.samples[j * depth.width + i];
          if (!Number.isFinite(d) || d === depth.missing) continue;
          const w = (1 - Math.abs(i - u)) * (1 - Math.abs(j - v));
          sum += w * d / depth.units;
          weight += w;
        }
      }
      return weight > .15 ? sum / weight : null;
    }

    // Fit the depth estimate to the dimensions of this particular capture.
    const halfWidth = Math.max(.025, width / 2);
    const halfUp = Math.max(.025, (low - high) / 2);
    const centerX = (Math.min(...xs) + Math.max(...xs)) / 2 - origin[0];
    const centerUp = origin[1] - (low + high) / 2;
    const heightGuess = clamp(centerUp / Math.max(.2, cp), halfWidth * .48, halfWidth * 2.4);
    const centerHeight = mix(heightGuess, halfWidth * 1.05, sp ** 4);
    const halfDepth = halfWidth * mix(.95, .68, sp * sp);
    const centerRay = centerHeight * sp;

    leaves = rows.map((s, index) => {
      const len = s.length, axisNorm = Math.hypot(...s.axis);
      const [ax, ay] = s.axis.map(v => v / axisNorm);
      const [cx, cy] = s.center;
      const relX = level(s.center)[0] - origin[0];
      const height = origin[1] - level(s.center)[1];
      const nx = (relX - centerX) / halfWidth, ny = (height - centerUp) / halfUp;

      // The canopy is deepest near its middle and narrower near its outline.
      const shell = Math.sqrt(Math.max(.035, 1 - nx * nx)) *
        Math.sqrt(Math.max(.12, 1 - .82 * ny * ny));
      const layer = 2 * (((index + .5) * .61803398875) % 1) - 1;
      const depthOffset = halfDepth * shell * mix(layer, Math.sin(layer * pi / 2), .26);
      const turn = (index + .5) * 1.84030237;
      const tilt = .88 * Math.sin(turn), twist = .85 * Math.cos(turn);
      const baseDepth = measuredDepth(cx, cy);

      const n = s.profile.length - 1;
      const uv = [];
      const ribs = s.profile.map((p, j) => {
        const u = j / n, arc = Math.sin(pi * u);
        const before = s.profile[Math.max(0, j - 1)], after = s.profile[Math.min(n, j + 1)];
        const [lo, hi] = p.map((v, k) => .20 * before[k] + .60 * v + .20 * after[k]);
        const mid = (lo + hi) / 2, half = j && j < n ? Math.max(0, (hi - lo) / 2) : 0;
        uv.push([]);

        return [-1, 0, 1].map(side => {
          const offset = mid + half * side, along = (u - .5) * len;
          const x = cx + ax * along - ay * offset, y = cy + ay * along + ax * offset;
          uv[j].push([x, y]);

          const [lx, ly] = level([x, y]), up = origin[1] - ly;
          const d = measuredDepth(x, y) ?? baseDepth;
          let front;

          if (d === null) {
            front = centerRay + depthOffset + tilt * along + twist * half * side;
            front += .19 * len * arc - half * Math.abs(side) * .48;

            // Keep inferred foliage above the soil while preserving its image position.
            if (Math.abs(sp) > .15 && up * cp + front * sp < .012) {
              front = (.012 - up * cp) / sp;
            }
          } else {
            front = .28 * sp - d + .10 * len * arc - Math.abs(side) * half * .37;
          }

          return [lx - origin[0], up * cp + front * sp, -up * sp + front * cp];
        });
      });

      return {
        ribs, uv, rings: s.rings_q, root: ribs[0][1], len,
        rgb: s.rgb?.length === 3 ? s.rgb : [76, 119, 54]
      };
    });

    loadMaterial(canopy, leaves);
    canopyLeaves = leaves.slice();

    // In dense single-view captures, test whether a blade could be hidden
    // behind the measured foliage before including it in the rotating model.
    if (!depth?.samples && leaves.length >= 16) {
      const mask = document.createElement('canvas');
      const resolution = 192;
      mask.width = mask.height = resolution;
      const g = mask.getContext('2d');
      const sx = (resolution - 4) / (2 * halfWidth);
      const sy = (resolution - 4) / (2 * halfUp);
      const screen = ([x, y, z]) => [
        (x - centerX) * sx + resolution / 2,
        (centerUp - y * cp + z * sp) * sy + resolution / 2
      ];
      const viewDepth = ribs => ribs.reduce(
        (sum, row) => sum + row[1][1] * sp + row[1][2] * cp, 0
      ) / ribs.length;

      const ordered = leaves.map(leaf => ({leaf, d: viewDepth(leaf.ribs)}))
        .sort((a, b) => a.d - b.d);
      const near = ordered.at(-1).d, far = ordered[0].d;
      const encode = d => 1 + Math.round(253 * clamp((d - far) / Math.max(.001, near - far), 0, 1));

      for (const {leaf, d} of ordered) {
        g.fillStyle = 'rgb(' + encode(d) + ',0,0)';
        const outline = leaf.ribs.map(r => r[0]).concat(leaf.ribs.map(r => r[2]).reverse());
        g.beginPath();
        outline.forEach((p, i) => {
          const [x, y] = screen(p);
          if (i) g.lineTo(x, y);
          else g.moveTo(x, y);
        });
        g.closePath();
        g.fill();
      }

      const pixels = g.getImageData(0, 0, resolution, resolution).data;
      const covered = (p, d) => {
        const [x, y] = screen(p).map(Math.floor);
        if (x < 0 || x >= resolution || y < 0 || y >= resolution) return false;
        const k = (y * resolution + x) * 4;
        return pixels[k + 3] > 127 && pixels[k] >= d;
      };

      for (const [i, leaf] of leaves.entries()) {
        if (i % 3 === 2) continue;
        const angle = (i % 2 ? -1 : 1) * (1.45 + .50 * ((i * .618) % 1));
        const c = Math.cos(angle), s = Math.sin(angle);
        const rotate = ([x, y, z]) => [
          centerX + (x - centerX) * c + z * s, y, -(x - centerX) * s + z * c
        ];
        const ribs = leaf.ribs.map(row => row.map(rotate));
        const points = ribs.flat();
        const d = encode(viewDepth(ribs));
        if (points.filter(p => covered(p, d)).length < points.length * .90) continue;
        canopyLeaves.push({
          ribs, root: ribs[0][1], len: leaf.len, rgb: leaf.rgb, uv: leaf.uv, source: leaf
        });
      }
    }

    // Fit shared shoots to nearby leaf attachment points.
    const roots = canopyLeaves.map(l => l.root);
    const distance = (a, b) => (a[0] - b[0]) ** 2 + (a[2] - b[2]) ** 2;
    let centers = [roots.reduce((p, q) => distance(p, [0, 0, 0]) < distance(q, [0, 0, 0]) ? p : q)];
    const count = Math.min(7, Math.ceil(Math.sqrt(roots.length) / 1.8));

    while (centers.length < count) {
      const nearest = roots.map(p => Math.min(...centers.map(c => distance(c, p))));
      const far = Math.max(...nearest);
      if (far < .001) break;
      centers.push(roots[nearest.indexOf(far)]);
    }

    let groups;
    for (let pass = 0; pass < 4; pass++) {
      groups = centers.map(() => []);
      for (const leaf of canopyLeaves) {
        const ds = centers.map(c => distance(leaf.root, c));
        groups[ds.indexOf(Math.min(...ds))].push(leaf);
      }
      centers = groups.map((g, i) => g.length ? [0, 1, 2].map(k =>
        g.reduce((sum, l) => sum + l.root[k], 0) / g.length) : centers[i]);
    }

    stems = [];
    for (const group of groups.filter(g => g.length)) {
      group.sort((a, b) => a.root[1] - b.root[1]);
      const first = group[0].root;
      const foot = Math.min(.72 * radius / (Math.hypot(first[0], first[2]) || 1), .78);
      let last = [first[0] * foot, -.012, first[2] * foot];
      const levels = Math.min(4, group.length);

      for (let j = 0; j < levels; j++) {
        const bunch = group.slice(Math.floor(j * group.length / levels), Math.floor((j + 1) * group.length / levels));
        const node = [0, 1, 2].map(k => bunch.reduce((sum, l) => sum + l.root[k], 0) / bunch.length);
        node[1] -= .025;
        stems.push([last, node, .006 * (1 - .65 * j / levels)]);
        for (const l of bunch) stems.push([node, l.root, Math.min(.0026, l.len * .022)]);
        last = node;
      }
    }

    const points = canopyLeaves.flatMap(l => l.ribs.flat());
    const bottom = Math.min(-potHeight, ...points.map(p => p[1]));
    const top = Math.max(0, ...points.map(p => p[1]));
    midY = (top + bottom) / 2;
    span = Math.max(.1, ...points.map(p => Math.hypot(p[0], p[1] - midY, p[2])),
      Math.hypot(radius, midY + potHeight), Math.hypot(radius, midY));
  }

  function loadMaterial(canopy, model) {
    if (!canopy.masked_png || !(canopy.width_px > 0 && canopy.height_px > 0)) return;
    const img = new Image();

    img.onload = () => {
      if (leaves !== model) return;
      const extent = Math.max(canopy.width_px, canopy.height_px);
      const sx = img.width * extent / canopy.width_px, sy = img.height * extent / canopy.height_px;

      for (const leaf of model) {
        const uv = leaf.uv.flat(), xx = uv.map(p => p[0]), yy = uv.map(p => p[1]);
        const x = Math.floor(Math.min(...xx) * sx + img.width / 2);
        const y = Math.floor(Math.min(...yy) * sy + img.height / 2);
        const tile = document.createElement('canvas');
        tile.width = Math.max(1, Math.ceil(Math.max(...xx) * sx + img.width / 2) - x);
        tile.height = Math.max(1, Math.ceil(Math.max(...yy) * sy + img.height / 2) - y);
        const g = tile.getContext('2d');
        g.setTransform(sx, 0, 0, sy, img.width / 2 - x, img.height / 2 - y);

        if (leaf.rings?.some(r => r.length >= 6) && canopy.units > 0) {
          g.beginPath();
          for (const ring of leaf.rings) {
            if (ring.length < 6) continue;
            g.moveTo(ring[0] / canopy.units, ring[1] / canopy.units);
            for (let i = 2; i < ring.length; i += 2) {
              g.lineTo(ring[i] / canopy.units, ring[i + 1] / canopy.units);
            }
            g.closePath();
          }
          g.clip('evenodd');
        }

        g.setTransform(1, 0, 0, 1, 0, 0);
        g.drawImage(img, -x, -y);
        leaf.texture = {
          tile, x: (x - img.width / 2) / sx, y: (y - img.height / 2) / sy,
          w: tile.width / sx, h: tile.height / sy
        };
      }
      redraw();
    };

    img.src = canopy.masked_png.startsWith('data:image/png;')
      ? canopy.masked_png : 'data:image/png;base64,' + canopy.masked_png;
  }

  function stroke(g, pts, ink, thickness) {
    g.beginPath();
    g.moveTo(...pts[0].slice(0, 2));
    for (const p of pts.slice(1)) g.lineTo(p[0], p[1]);
    g.strokeStyle = ink;
    g.lineWidth = thickness;
    g.stroke();
  }

  function drawLeaf(g, ribs, leaf) {
    const rgb = leaf.rgb;
    const last = ribs.length - 1, mid = Math.floor(last / 2), [a, m, b] = ribs[mid];

    function edge(points) {
      for (let k = 1; k < points.length - 1; k++) {
        const p = points[k], q = points[k + 1];
        g.quadraticCurveTo(p[0], p[1], (p[0] + q[0]) / 2, (p[1] + q[1]) / 2);
      }
      const p = points.at(-1);
      g.lineTo(p[0], p[1]);
    }

    const vein = ribs.map(r => r[1]);
    for (const side of [0, 2]) {
      const outer = ribs.map(r => r[side]), tip = outer[mid];
      const shade = g.createLinearGradient(m[0], m[1], tip[0] + .001, tip[1]);
      const light = side === (a[2] > b[2] ? 2 : 0) ? 1.08 : .92;
      shade.addColorStop(0, color(rgb, light * .90));
      shade.addColorStop(.44, color(rgb, light * 1.06));
      shade.addColorStop(1, color(rgb, light * .85));
      g.beginPath();
      g.moveTo(vein[0][0], vein[0][1]);
      edge(outer);
      edge(vein.slice().reverse());
      g.closePath();
      g.fillStyle = shade;
      g.fill();
    }

    const tex = (leaf.source || leaf).texture;
    if (tex) {
      const [p, q, r] = [leaf.uv[0][1], leaf.uv[last][1], leaf.uv[mid][2]];
      const [base, tip, side] = [vein[0], vein[last], b];
      const u = q[0] - p[0], v = q[1] - p[1], s = r[0] - p[0], t = r[1] - p[1];
      const det = u * t - v * s;

      if (Math.abs(det) > 1e-9) {
        const axis = [0, 1].map(k => ((tip[k] - base[k]) * t - (side[k] - base[k]) * v) / det);
        const across = [0, 1].map(k => ((side[k] - base[k]) * u - (tip[k] - base[k]) * s) / det);
        g.save();
        g.beginPath();
        g.moveTo(vein[0][0], vein[0][1]);
        edge(ribs.map(row => row[0]));
        edge(ribs.map(row => row[2]).reverse());
        g.closePath();
        g.clip();
        g.transform(axis[0], axis[1], across[0], across[1],
          base[0] - axis[0] * p[0] - across[0] * p[1],
          base[1] - axis[1] * p[0] - across[1] * p[1]);
        g.globalAlpha = .62;
        g.drawImage(tex.tile, tex.x, tex.y, tex.w, tex.h);
        g.restore();
      }
    }

    const length = Math.hypot(vein[last][0] - vein[0][0], vein[last][1] - vein[0][1]);
    const ink = color(rgb.map((v, i) => mix(v, [197, 209, 147][i], .28)));
    if (length > 7) stroke(g, vein, ink, clamp(length * .010, .36, 1.05));
    if (length > 23) {
      for (let j = 2; j < last - 2; j += 3) {
        for (const side of [0, 2]) {
          const r = ribs[j + 2];
          stroke(g, [vein[j], between(r[1], r[side], .78)], color(rgb, 1.10), .48);
        }
      }
    }
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
      ctx.scale(radius * scale * 1.17, radius * scale * Math.max(.07, sp));
      const shadow = ctx.createRadialGradient(0, 0, 0, 0, 0, 1);
      shadow.addColorStop(0, 'rgba(43,53,40,.23)');
      shadow.addColorStop(1, 'rgba(43,53,40,0)');
      ctx.fillStyle = shadow;
      ctx.fillRect(-1, -1, 2, 2);
      ctx.restore();
    } else {
      const base = Array.from({length: 48}, (_, k) => ring(.77 * radius, -potHeight, k));
      add(base, () => fill(base, color(potColor, .67)));
    }

    const bands = [[.77, -potHeight], [.96, -potHeight * .13], [1.02, -potHeight * .12], [1.02, 0], [.94, 0]];
    const soil = project([0, -.012, 0]);

    for (let k = 0; k < 48; k++) {
      const surface = [soil, ring(.94 * radius, -.012, k), ring(.94 * radius, -.012, k + 1)];
      add(surface, () => fill(surface, '#514134'));
      for (let j = 1; j < bands.length; j++) {
        const [r, y] = bands[j - 1], [rr, yy] = bands[j];
        const pts = [
          ring(r * radius, y, k), ring(r * radius, y, k + 1),
          ring(rr * radius, yy, k + 1), ring(rr * radius, yy, k)
        ];
        const shade = .86 + .18 * Math.cos(k * pi / 24 + yaw + .8) + (j === 4 ? .18 : 0);
        add(pts, () => fill(pts, color(potColor, shade)));
      }
    }

    for (const [a, b, thick] of stems) {
      const c = between(a, b, .5);
      c[1] += Math.hypot(a[0] - b[0], a[2] - b[2]) * .12;
      const pts = [a, c, b].map(p => project(p, size));
      add(pts, () => {
        ctx.beginPath();
        ctx.moveTo(pts[0][0], pts[0][1]);
        ctx.quadraticCurveTo(pts[1][0], pts[1][1], pts[2][0], pts[2][1]);
        ctx.lineWidth = Math.max(.38, thick * scale * size);
        ctx.strokeStyle = '#657850';
        ctx.stroke();
      });
    }

    for (const leaf of canopyLeaves) {
      const ribs = leaf.ribs.map(r => r.map(p => project(p, size)));
      add(ribs.map(r => r[1]), () => drawLeaf(ctx, ribs, leaf));
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

        drawLeaf(tile.getContext('2d'), l.ribs.map(r => r.map(([x, y, z]) => [
          52 + (x - (x0 + x1) / 2) * s,
          35 - (y * Math.cos(homePitch) - z * Math.sin(homePitch) - (y0 + y1) / 2) * s,
          z
        ])), l);

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