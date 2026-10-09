// Crewship harbor: a first-person 3D scene ray cast into a grid of text, every frame.
// Plain JavaScript, no dependencies. The world is a list of convex solids (sets of planes)
// plus the water plane; the ship's solids live in a frame that bobs and rolls at the dock.
const stage = document.getElementById("stage");
const canvas = document.getElementById("scene");
const ctx = canvas.getContext("2d");
const card = document.getElementById("card");
// With JavaScript the scene fills the screen and the plain page stays for screen readers only.
stage.hidden = false;
document.getElementById("page").classList.add("sr-only");
stage.focus({ preventScroll: true });
const pad = document.getElementById("pad");
const knob = pad.firstElementChild;
const reduced = matchMedia("(prefers-reduced-motion: reduce)");
const touchFirst = matchMedia("(pointer: coarse)");

// The features come from the plain list, so the scene and the list never disagree.
const spots = {};
for (const li of document.querySelectorAll("#manifest li[data-spot]")) {
  const a = li.querySelector("a");
  spots[li.dataset.spot] = { title: a.textContent, href: a.href, body: li.querySelector("p").innerHTML };
}

// ---- World -------------------------------------------------------------------------------
const SX = -1.5; // ship centre line (x) and roll axis
const DECK = 2; // deck height in the ship frame
const world = [];
const ship = [];

function solid(list, planes, bb, mat, o) {
  const P = [];
  for (const [nx, ny, nz, px, py, pz] of planes) {
    const l = Math.hypot(nx, ny, nz);
    P.push(nx / l, ny / l, nz / l, (nx * px + ny * py + nz * pz) / l);
  }
  const s = { id: world.length + ship.length + 1, P: new Float64Array(P), bb, mat, spot: null, solid: true, tex: null, ...o };
  list.push(s);
  return s;
}
function box(list, x0, y0, z0, x1, y1, z1, mat, o) {
  return solid(list, [[1, 0, 0, x1, 0, 0], [-1, 0, 0, x0, 0, 0], [0, 1, 0, 0, y1, 0],
    [0, -1, 0, 0, y0, 0], [0, 0, 1, 0, 0, z1], [0, 0, -1, 0, 0, z0]], [x0, y0, z0, x1, y1, z1], mat, o);
}
// A round column around a vertical axis, tapered from r0 at y0 to r1 at y1: masts, barrels, trunks, the lighthouse.
// Rays hit the true cone (smooth normals); the eight planes only serve the walking test and the culling box.
function column(list, cx, cz, r0, r1, y0, y1, mat, o) {
  const pl = [[0, 1, 0, 0, y1, 0], [0, -1, 0, 0, y0, 0]];
  const slope = (r0 - r1) / (y1 - y0);
  for (let i = 0; i < 8; i++) {
    const a = (i + 0.5) * Math.PI / 4, c = Math.cos(a), s = Math.sin(a);
    pl.push([c, slope, s, cx + c * r0, y0, cz + s * r0]);
  }
  const r = Math.max(r0, r1) * 1.09, b = (r1 - r0) / (y1 - y0);
  return solid(list, pl, [cx - r, y0, cz - r, cx + r, y1, cz + r], mat, { cone: [cx, cz, r0 - b * y0, b, y0, y1, r0, r1], ...o });
}
// Eight-sided disc facing along z (the helm wheel).
function disc(list, cx, cy, z0, z1, r, mat, o) {
  const pl = [[0, 0, 1, 0, 0, z1], [0, 0, -1, 0, 0, z0]];
  for (let i = 0; i < 8; i++) {
    const a = (i + 0.5) * Math.PI / 4, c = Math.cos(a), s = Math.sin(a);
    pl.push([c, s, 0, cx + c * r, cy + s * r, 0]);
  }
  return solid(list, pl, [cx - r * 1.09, cy - r * 1.09, z0, cx + r * 1.09, cy + r * 1.09, z1], mat, o);
}

// Rope or spar from a to b: a box of half-width r aligned with the segment.
function beam(list, a, b, mat, o = {}, r = 0.03) {
  const unit = (p) => { const l = Math.hypot(...p); return p.map((c) => c / l); };
  const cross = (p, q) => [p[1] * q[2] - p[2] * q[1], p[2] * q[0] - p[0] * q[2], p[0] * q[1] - p[1] * q[0]];
  const u = unit(b.map((c, i) => c - a[i]));
  const v = unit(cross(u, Math.abs(u[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0])), w = cross(u, v);
  const side = (n, s) => [...n.map((c) => c * s), ...a.map((c, i) => c + n[i] * s * r)];
  const planes = [[...u.map((c) => -c), ...a], [...u, ...b], side(v, 1), side(v, -1), side(w, 1), side(w, -1)];
  const bb = [...a.map((c, i) => Math.min(c, b[i]) - r), ...a.map((c, i) => Math.max(c, b[i]) + r)];
  return solid(list, planes, bb, mat, { solid: false, ...o });
}
// A 3x5 pixel font for the painted signs.
const FONT = { A: "010101111101101", B: "110101110101110", C: "011100100100011", E: "111100110100111",
  H: "101101111101101", I: "111010010010111", O: "010101101101010", P: "110101110100100",
  R: "110101110101101", S: "011100010001110", W: "101101101111101" };
// Paints `text` inside the rectangle [u0,u1] x [v0,v1] of a face, u running left to right as seen from the front.
function painted(text, u0, u1, v0, v1) {
  const cols = text.length * 4 - 1;
  const px = Math.min((u1 - u0) / cols, (v1 - v0) / 5);
  const left = (u0 + u1 - cols * px) / 2, top = (v0 + v1 + 5 * px) / 2;
  return (x, y) => {
    const c = Math.floor((x - left) / px), r = Math.floor((top - y) / px);
    if (c < 0 || r < 0 || c >= cols || r > 4 || c % 4 === 3) return false;
    return FONT[text[(c / 4) | 0]][r * 3 + (c % 4)] === "1";
  };
}
const hash = (a, b) => { const h = Math.sin(a * 127.1 + b * 311.7) * 43758.5453; return h - Math.floor(h); };

// Harbor: quay, breakwater, the dock and what stands on them.
// The road network: junctions and the links between them. It is drawn on the island and is the route
// the mini map walks you along (deck, gangway, dock, avenue, plaza, breakwater path).
const NODES = [[-0.3, -6], [-0.3, -1.2], [-0.3, 5.5], [1.9, -1.2], [4.2, -1.2], [5, 13.5], [5, 19.6], [5, 24.6], [-5, 19.6],
  [-16, 19.6], [-28, 19.6], [-30, 10], [-30, -14], [14, 19.6], [20, 19.6]];
const LINKS = [[0, 1], [1, 2], [1, 3], [3, 4], [4, 5], [5, 6], [6, 7], [6, 8], [8, 9], [9, 10], [10, 11], [11, 12], [6, 13], [13, 14]];
// Island ways (the links past the dock): concrete from the dock head to the plaza and along the centre of
// the avenue, narrow dirt trails beyond. [ax, az, dx, dz, length², concrete]
const CONCRETE = new Set(["5,6", "6,7", "6,8", "6,13"]);
const ROADS = LINKS.slice(5).map(([a, b]) => {
  const [ax, az] = NODES[a], dx = NODES[b][0] - ax, dz = NODES[b][1] - az;
  return [ax, az, dx, dz, dx * dx + dz * dz, CONCRETE.has(`${a},${b}`)];
});
// Distance from (x, z) to the nearest way, how far along it you are, and whether it is concrete.
function roadAt(x, z) {
  let best = Infinity, along = 0, concrete = false;
  for (const [ax, az, dx, dz, l2, c] of ROADS) {
    const t = Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / l2)), ex = x - ax - t * dx, ez = z - az - t * dz;
    const d = ex * ex + ez * ez;
    if (d < best) { best = d; along = t * Math.sqrt(l2); concrete = c; }
  }
  return [Math.sqrt(best), along, concrete];
}
// Island ground as material and glyph: a 3 m concrete road with kerbs and joints every 3 m, a tiled plaza,
// a 1 m dirt trail with uneven edges, ruts and footprints, and grass, bare earth and flowers elsewhere.
function ground(x, y, z, nx, ny) {
  if (ny < 0.5) return null;
  const [d, along, concrete] = roadAt(x, z), plaza = Math.hypot(x - 5, z - 24.6);
  if (plaza < 3.2) return plaza > 3.05 ? "t_" : (x + 99) % 1.5 < 0.09 || (z + 99) % 1.5 < 0.09 ? "t:" : "t.";
  if (concrete && d < 1.5) return d > 1.38 ? "s_" : along % 3 < 0.12 ? "t:" : "t.";
  if (!concrete && d < 0.5 + 0.12 * Math.sin(along * 1.7) + 0.08 * hash(Math.floor(along * 3), 7)) {
    if (Math.abs(d - 0.22) < 0.06) return "o:";
    return hash(Math.floor(along * 2.5), Math.floor(d * 6)) < 0.18 ? "o," : "o.";
  }
  const h = hash(Math.floor(x * 2), Math.floor(z * 2));
  if (h < 0.025) return ["r*", "b*", "s*"][Math.floor(h * 120)];
  if (hash(Math.floor(x / 4), Math.floor(z / 4)) < 0.2) return h < 0.5 ? "o:" : "o.";
  return "g" + "\"',.;`"[Math.floor(h * 6)];
}
box(world, -70, -2, 14, 70, 1.2, 46, "t", { solid: false, tex: ground });
box(world, -46, -2, -36, -26, 1, 14, "t", { solid: false, tex: ground });
// Beaches slope from the quay and the breakwater down into the water, except where the dock needs deep water.
// Dry sand is light and dotted, wet sand darker by the waterline, where the wash comes and goes.
function sand(x, y, z, nx, ny) {
  if (ny < 0.5) return null;
  const wash = 0.12 + 0.08 * Math.sin(T * 0.9 + x * 0.3);
  if (y < wash) return hash(Math.floor(x * 3), Math.floor(z * 3 + T)) < 0.4 ? "k:" : "n:";
  if (y < wash + 0.25) return hash(Math.floor(x * 2), Math.floor(z * 2)) < 0.06 ? "w~" : "n:";
  return hash(Math.floor(x * 3), Math.floor(z * 3)) < 0.5 ? "y." : "y,";
}
for (const [x0, x1] of [[-70, -6], [8, 70]]) {
  solid(world, [[0, 1, -0.3, 0, 1.2, 14], [0, -1, 0, 0, -0.6, 0], [0, 0, 1, 0, 0, 14], [0, 0, -1, 0, 0, 9], [1, 0, 0, x1, 0, 0], [-1, 0, 0, x0, 0, 0]],
    [x0, -0.6, 9, x1, 1.2, 14], "y", { solid: false, tex: sand });
}
solid(world, [[0.3, 1, 0, -26, 1, 0], [0, -1, 0, 0, -0.6, 0], [-1, 0, 0, -26, 0, 0], [1, 0, 0, -21.5, 0, 0], [0, 0, 1, 0, 0, 12], [0, 0, -1, 0, 0, -36]],
  [-26, -0.6, -36, -21.5, 1, 12], "y", { solid: false, tex: sand });
for (const [x, z] of [[-14, 11.5], [-9, 10.6], [15, 11], [-23.6, -4], [-23, -20]]) column(world, x, z, 0.7, 0.3, 0, 0.9, "t");
const seam = (u) => ((u + 99) % 0.45 < 0.07 ? "-" : null);
box(world, 3, 0.85, -16, 7, 1.2, 14, "t", { solid: false, tex: (x, y, z, nx, ny) => (ny > 0.5 ? seam(z) : null) });
for (const z of [-15.6, -11, -6, 3, 8, 13.4]) {
  box(world, 3.05, -1, z, 3.35, 1.55, z + 0.3, "o");
  box(world, 6.65, -1, z, 6.95, 1.55, z + 0.3, "o");
}
column(world, 3.55, -8, 0.18, 0.15, 1.2, 1.65, "t");
column(world, 3.55, 5, 0.18, 0.15, 1.2, 1.65, "t");
for (const z of [-4, 9]) {
  box(world, 6.4, 1.2, z, 6.56, 4.2, z + 0.16, "t");
  box(world, 6.24, 4.2, z - 0.14, 6.72, 4.65, z + 0.3, "l");
}
const ribs = (x, y, z, nx, ny, nz) => (Math.sin((Math.abs(nz) > 0.5 ? x : z) * 10) > 0.45 ? "-" : null);
box(world, 9, 1.2, 16, 15, 3.8, 18.5, "r", { spot: "containers", tex: ribs });
box(world, 9.4, 3.8, 16.2, 15.4, 6.4, 18.7, "b", { spot: "containers", tex: ribs });
box(world, 16.2, 1.2, 15.6, 22.2, 3.8, 18.1, "b", { spot: "containers", tex: ribs });
const officeText = painted("HARBOR", -7.6, -2.4, 4.15, 5.05);
const pane = (u, y, spans) => y > 2.4 && y < 3.6 && spans.some(([a, b]) => u > a && u < b);
box(world, -9, 1.2, 21, -1, 5.4, 28, "s", { spot: "office", tex: (x, y, z, nx, ny, nz) => {
  if (nx > 0.5) return pane(z, y, [[22.5, 24], [25, 26.5]]) ? "l" : null;
  if (nz > -0.5) return null;
  if (officeText(x, y)) return "r";
  if (x > -5.6 && x < -4.4 && y < 3.5) return "o";
  return pane(x, y, [[-8.2, -6.6], [-3.4, -1.8]]) ? "l" : null;
} });
solid(world, [[0, -1, 0, 0, 5.4, 0], [0, 0, 1, 0, 0, 28.4], [0, 0, -1, 0, 0, 20.6],
  [-2, 4.4, 0, -9.4, 5.4, 0], [2, 4.4, 0, -0.6, 5.4, 0]], [-9.4, 5.4, 20.6, -0.6, 7.4, 28.4], "r", { spot: "office" });
box(world, -2.6, 6, 24, -2.45, 10.5, 24.15, "t", { spot: "antenna" });
box(world, -3.3, 9.4, 24, -1.75, 9.52, 24.15, "t", { spot: "antenna" });
box(world, -3, 8.5, 24, -2.05, 8.62, 24.15, "t", { spot: "antenna" });
const antennaLamp = box(world, -2.68, 10.5, 23.93, -2.37, 10.8, 24.22, "l", { spot: "antenna" });
// Lighthouse on the breakwater, striped, with a lamp that turns.
column(world, -36, -24, 1.9, 1.15, 1, 13, "s", { spot: "lighthouse",
  tex: (x, y) => (Math.floor((y - 1) / 2.4) % 2 ? "r" : null) });
const beacon = column(world, -36, -24, 1.2, 1.2, 13, 14.6, "l", { spot: "lighthouse" });
column(world, -36, -24, 1.5, 0.2, 14.6, 16, "r", { spot: "lighthouse" });
// A town on the far shore.
for (let i = 0; i < 16; i++) {
  const x = -95 + i * 12.5, w = 6 + hash(i, 1) * 5, h = 4 + hash(i, 2) * 14, z = 95 + hash(i, 3) * 12;
  box(world, x, 0, z, x + w, h, z + 8, "f", { solid: false, tex: (x, y, z, nx, ny, nz) =>
    (nz < -0.5 && (y % 2.2) > 1 && (x % 2) > 0.9 && hash(Math.floor(x / 2), Math.floor(y / 2.2)) < 0.3 ? "l" : null) });
}

// Harbor detail, kept to the edges so the walk stays clear: cargo, rope, boats, rocks, palms, lamps.
for (const [x, z, h] of [[6.2, -9.5, 0.8], [6.2, -8.6, 0.8], [6.25, -9.1, 1.6], [12, 21.2, 0.9], [13, 21.3, 0.9], [12.5, 21.2, 1.8]]) {
  box(world, x, h - 0.8 + 1.2, z, x + 0.75, h + 1.2, z + 0.75, "o", { tex: (x, y, z, nx, ny, nz) => (Math.abs(nx) + Math.abs(nz) > 0.5 && ((x + z + y) * 4 + 99) % 1 < 0.15 ? "-" : null) });
}
for (const [x, z] of [[6.5, 0.6], [6.5, 1.3], [5.9, 0.9], [6.5, 10.8], [15.5, 21.4], [16.2, 21.3]]) {
  column(world, x, z, 0.3, 0.27, 1.2, 2.1, "o", { spot: "barrels", tex: (x, y) => (Math.abs(y - 1.42) < 0.06 || Math.abs(y - 1.88) < 0.06 ? "-" : null) });
}
for (const [x, z] of [[3.6, -4.6], [3.6, 6.4], [6.4, -13]]) column(world, x, z, 0.38, 0.38, 1.2, 1.36, "s", { solid: false });
// Small boats ride the waves: each frame their planes are lifted and tilted to the sea surface under them.
const boats = [];
function boat(cx, z0, w, len, mat, spot = null) {
  const z1 = z0 + len, zb = z1 - w, top = 0.45;
  const s = solid(world, [[0, 1, 0, 0, top, 0], [0, -1, 0, 0, -0.3, 0], [0, 0, -1, 0, 0, z0], [1, -0.4, 0, cx + w / 2, top, 0],
    [-1, -0.4, 0, cx - w / 2, top, 0], [w, 0, w / 2, cx + w / 2, 0, zb], [-w, 0, w / 2, cx - w / 2, 0, zb]],
  [cx - w / 2 - 0.5, -0.8, z0 - 0.3, cx + w / 2 + 0.5, top + 0.5, z1 + 0.3], mat, { spot, solid: false, tex: (x, y) => (y - s.dy > 0.25 && y - s.dy < 0.35 ? "s" : null) });
  Object.assign(s, { base: Float64Array.from(s.P), c: [cx, 0, (z0 + z1) / 2], dy: 0 });
  boats.push(s);
}
function floatBoats() {
  for (const s of boats) {
    const [cx, , cz] = s.c;
    s.dy = seaHeight(cx, cz) * 0.9;
    seaNormal(cx, cz);
    const az = -Math.atan2(seaN[0], seaN[1]) * 0.8, ax = Math.atan2(seaN[2], seaN[1]) * 0.8;
    const cz1 = Math.cos(az), sz1 = Math.sin(az), cx1 = Math.cos(ax), sx1 = Math.sin(ax);
    for (let i = 0; i < s.P.length; i += 4) {
      const n0 = s.base[i], n1 = s.base[i + 1], n2 = s.base[i + 2], off = s.base[i + 3] - (n0 * cx + n2 * cz);
      // Tilt the normal: about z (roll), then about x (pitch).
      const r0 = cz1 * n0 - sz1 * n1, r1 = sz1 * n0 + cz1 * n1, q1 = cx1 * r1 - sx1 * n2, q2 = sx1 * r1 + cx1 * n2;
      s.P[i] = r0; s.P[i + 1] = q1; s.P[i + 2] = q2; s.P[i + 3] = off + r0 * cx + q1 * s.dy + q2 * cz;
    }
  }
}
boat(-8, 3.6, 1.3, 3.6, "r", "lifeboat");
boat(-11.5, 3, 1.2, 3.2, "b", "tender");
boat(9.5, 3, 1.4, 4, "o");
for (let z = -32; z < 12; z += 5.5) column(world, -26.6, z + hash(z, 4) * 2, 0.9 + hash(z, 5) * 0.5, 0.35, 0.2, 1.3 + hash(z, 6) * 0.8, "t");
for (const [x, z] of [[21, 24], [-16, 23.5], [-30, 2]]) {
  column(world, x, z, 0.28, 0.16, z > 10 ? 1.2 : 1, 7, "o");
  for (let a = 0; a < 6; a++) beam(world, [x, 7, z], [x + 2.6 * Math.cos(a * 1.05), 5.6, z + 2.6 * Math.sin(a * 1.05)], "g");
}
for (const x of [-4, 12]) {
  box(world, x, 1.2, 14.4, x + 0.16, 4.2, 14.56, "t");
  box(world, x - 0.16, 4.2, 14.26, x + 0.32, 4.65, 14.7, "l");
}
// A mailbox by the office and a notice board on the quay that leads to how this page is built.
box(world, -0.55, 1.2, 21.4, -0.45, 2.2, 21.5, "t", { spot: "mailbox" });
box(world, -0.8, 2.2, 21.2, -0.2, 2.7, 21.7, "r", { spot: "mailbox" });
// Landscaping: hedges round the plaza, round trees, lamps along the avenue, a fence on the quay front.
for (const [x0, x1, z0, z1] of [[1, 2.2, 22, 27.4], [7.8, 9, 22, 27.4], [2.2, 3.4, 27.6, 28.4], [6.6, 7.8, 27.6, 28.4]]) {
  box(world, x0, 1.2, z0, x1, 1.9, z1, "g", { tex: (x, y, z) => (hash(Math.floor(x * 3), Math.floor(z * 3 + y * 3)) < 0.3 ? "-" : null) });
}
for (const [x, z] of [[-10, 23], [0, 25], [11, 24], [17, 27], [-22, 24]]) {
  column(world, x, z, 0.22, 0.18, 1.2, 3, "o");
  column(world, x, z, 1.6, 0.3, 2.6, 6.2, "g", { tex: (x, y) => (Math.sin(y * 6 + x * 3) > 0.6 ? "-" : null) });
}
for (const x of [-20, -10, 0, 10, 18]) {
  box(world, x, 1.2, 20.9, x + 0.14, 4, 21.04, "t");
  box(world, x - 0.14, 4, 20.76, x + 0.28, 4.4, 21.18, "l");
}
for (let x = -25; x < -6; x += 2.5) box(world, x, 1.2, 14.2, x + 0.12, 2.1, 14.32, "o");
box(world, -25, 1.75, 14.22, -6.3, 1.85, 14.3, "o");
box(world, -25, 1.45, 14.22, -6.3, 1.53, 14.3, "o");
const howText = painted("HOW", 7.4, 8.7, 2.45, 3.25);
for (const x of [7.35, 8.6]) box(world, x, 1.2, 16.72, x + 0.15, 2.4, 16.85, "o", { spot: "how" });
box(world, 7.2, 2.35, 16.6, 8.9, 3.35, 16.72, "o", { spot: "how", tex: (x, y, z, nx, ny, nz) => (nz < -0.5 ? (howText(x, y) ? "l" : "-") : null) });

// Ship, in its own frame: hull, rails, cabin, helm, mast, sail, crow's nest, hatch, lantern.
const k = 1 / 3.2;
solid(ship, [[0, 1, 0, 0, DECK, 0], [0, -1, 0, 0, -1.2, 0], [0, 0, -1, 0, 0, -12],
  [1, -k, 0, 0.7, DECK, 0], [-1, -k, 0, -3.7, DECK, 0], [4, 0, 2.2, 0.7, 0, 6], [-4, 0, 2.2, -3.7, 0, 6]],
[-3.7, -1.2, -12, 0.7, DECK, 10], "o", { solid: false,
  tex: (x, y, z, nx, ny) => (ny > 0.5 ? seam(x) : y > 1.3 && y < 1.6 ? "s" : null) });
// Low bulwarks along the deck edge, open at the gangway; the deck's walkable area keeps you aboard.
for (const [x0, x1, z0, z1] of [[-3.7, -3.55, -12, 6], [0.55, 0.7, -12, -2], [0.55, 0.7, -0.4, 6], [-3.7, 0.7, -12, -11.85]]) {
  box(ship, x0, DECK, z0, x1, 2.5, z1, "o", { solid: false });
}
// The ship's name on a board on the starboard bow, facing the dock.
const nameText = painted("CREWSHIP", 0.2, 6, 0.75, 1.8);
box(ship, 0.6, 0.7, 0.1, 0.74, 1.85, 6, "o", { spot: "sign", tex: (x, y, z, nx) => (nx > 0.5 ? (nameText(z, y) ? "l" : "-") : null) });
box(ship, -3.3, DECK, -11.6, 0.1, 4.3, -8.2, "s", { spot: "cabin", tex: (x, y, z, nx, ny, nz) => {
  if (nz < 0.5) return null;
  if (x > -1.9 && x < -1.1 && y < 3.8) return "o";
  return y > 3 && y < 3.6 && ((x > -3 && x < -2.4) || (x > -0.6 && x < 0)) ? "l" : null;
} });
box(ship, -3.5, 4.3, -11.8, 0.3, 4.55, -8, "o", { spot: "cabin" });
box(ship, SX - 0.1, DECK, -7.05, SX + 0.1, 3.1, -6.85, "o", { spot: "helm" });
disc(ship, SX, 3.3, -6.85, -6.72, 0.62, "o", { spot: "helm", tex: (x, y) => {
  const dx = x - SX, dy = y - 3.3, rr = Math.hypot(dx, dy);
  return rr > 0.42 || rr < 0.12 || Math.abs(Math.sin(4 * Math.atan2(dy, dx))) < 0.25 ? null : "-";
} });
column(ship, SX, -1, 0.22, 0.17, DECK, 14.6, "o", { spot: "mast" });
box(ship, -5.2, 11.2, -1.1, 2.2, 11.4, -0.9, "o", { spot: "mast" });
// Docked, so the sail is furled on the yard; the shrouds and stays make the rig read as a ship.
box(ship, -4.9, 11.4, -1.25, 1.9, 11.85, -0.75, "s", { tex: (x) => ((x + 9) % 0.8 < 0.1 ? "-" : null) });
for (const x of [-3.6, 0.6]) beam(ship, [SX, 12.3, -1], [x, 2.5, 1.5], "o");
beam(ship, [SX, 14.2, -1], [SX, 2.3, 13], "o");
beam(ship, [SX, 14.2, -1], [SX, 4.55, -11.6], "o");
column(ship, SX, -1, 0.9, 0.95, 12.3, 13.2, "o", { spot: "nest", tex: (x, y) => (y < 12.5 ? "-" : null) });
box(ship, SX, 14.4, -1.03, SX + 1.2, 15.05, -0.97, "r");
box(ship, -2.7, DECK, 2.4, -0.3, 2.55, 4.8, "o", { spot: "hold",
  tex: (x, y, z, nx, ny) => (ny > 0.5 && ((x + 9) % 0.4 < 0.07 || (z + 9) % 0.4 < 0.07) ? "-" : null) });
box(ship, -3.3, DECK, 5, -2.5, 2.8, 5.8, "o", { spot: "hold" });
box(ship, SX - 0.08, DECK, 7.2, SX + 0.08, 3.3, 7.36, "o", { spot: "lantern" });
box(ship, SX - 0.22, 3.3, 7.07, SX + 0.22, 3.75, 7.5, "l", { spot: "lantern" });
box(ship, SX - 0.08, 2.2, 9.5, SX + 0.08, 2.35, 13, "o");
// A spyglass on the cabin roof, the ship's bell at the bow, a strongbox on the port deck.
beam(ship, [-2.8, 4.55, -10.6], [-2.8, 5.3, -10.6], "o", { spot: "spyglass" }, 0.05);
beam(ship, [-3.1, 5.2, -11.2], [-2.3, 5.55, -9.9], "t", { spot: "spyglass" }, 0.1);
box(ship, -2.95, DECK, 6, -2.8, 3.6, 6.15, "o", { spot: "bell" });
column(ship, -2.87, 6.07, 0.3, 0.12, 2.85, 3.45, "r", { spot: "bell" });
box(ship, -3.35, DECK, 0.3, -2.85, 2.5, 0.9, "t", { spot: "strongbox", tex: (x, y) => (Math.abs(y - 2.3) < 0.05 ? "-" : null) });

// The gangway hinges between the rocking deck and the dock, so its planes are rebuilt per frame.
const gangway = solid(world, [[0, 1, 0, 0, 0, 0], [0, -1, 0, 0, 0, 0], [1, 0, 0, 3.1, 0, 0],
  [-1, 0, 0, 0.55, 0, 0], [0, 0, 1, 0, 0, -0.6], [0, 0, -1, 0, 0, -1.8]], [0.55, 0, -1.8, 3.1, 0, -0.6], "o",
{ spot: "gangway", solid: false, tex: (x) => ((x + 9) % 0.5 < 0.07 ? "-" : null) });

// ---- Motion state ------------------------------------------------------------------------
let T = 0, bob = 0, roll = 0, rc = 1, rs = 0;
const deckAt = (x) => bob + DECK * rc + rs * (x - SX);
function setGangway() {
  const y0 = deckAt(0.7), y1 = 1.2, dx = 3.1 - 0.7, dy = y1 - y0, l = Math.hypot(dx, dy);
  const nx = -dy / l, ny = dx / l, P = gangway.P;
  P[0] = nx; P[1] = ny; P[3] = nx * 0.7 + ny * y0;
  P[4] = -nx; P[5] = -ny; P[7] = -(nx * 0.7 + ny * (y0 - 0.12));
  gangway.bb[1] = Math.min(y0, y1) - 0.2; gangway.bb[4] = Math.max(y0, y1) + 0.05;
}
// Walkable areas [x0, x1, z0, z1, height at x]: deck, gangway, dock, quay, breakwater.
const FLOORS = [
  [-3.45, 0.45, -11.55, 6.6, deckAt],
  [0.45, 3.1, -1.8, -0.6, (x) => deckAt(0.7) + (1.2 - deckAt(0.7)) * Math.min(1, Math.max(0, (x - 0.7) / 2.4))],
  [3, 7, -16, 14, () => 1.2],
  [-70, 70, 14, 46, () => 1.2],
  [-46, -26, -36, 14, () => 1],
  [-70, -6, 10.6, 14, (x, z) => 1.2 - (14 - z) * 0.3],
  [8, 70, 10.6, 14, (x, z) => 1.2 - (14 - z) * 0.3],
  [-26, -23, -36, 12, (x) => 1 - (x + 26) * 0.3],
];
function floorAt(x, z) {
  const f = FLOORS.find(([x0, x1, z0, z1]) => x >= x0 && x < x1 && z >= z0 && z < z1);
  return f ? f[4](x, z) : null;
}
function blocked(x, z, fy) {
  for (const list of [world, ship]) {
    const lift = list === ship ? bob : 0;
    for (const s of list) {
      const b = s.bb;
      if (s.solid && x > b[0] - 0.25 && x < b[3] + 0.25 && z > b[2] - 0.25 && z < b[5] + 0.25 &&
        b[1] + lift < fy + 1.7 && b[4] + lift > fy + 0.3) return true;
    }
  }
  return false;
}

const me = { x: 0, z: -7.4, yaw: 0.2, pitch: 0.03 };
const keys = new Set();
const stick = { x: 0, y: 0 };
let moved = false;

// ---- Ray casting -------------------------------------------------------------------------
let hitT, hitS, hitK;
const hitN = [0, 1, 0], entryN = [0, 1, 0];
// Entry distance of the ray into a bounding box, or Infinity when it misses.
function boxEntry(b, ox, oy, oz, ix, iy, iz) {
  let a = (b[0] - ox) * ix, c = (b[3] - ox) * ix;
  let t0 = Math.min(a, c), t1 = Math.max(a, c);
  a = (b[1] - oy) * iy; c = (b[4] - oy) * iy;
  t0 = Math.max(t0, Math.min(a, c)); t1 = Math.min(t1, Math.max(a, c));
  a = (b[2] - oz) * iz; c = (b[5] - oz) * iz;
  t0 = Math.max(t0, Math.min(a, c)); t1 = Math.min(t1, Math.max(a, c));
  return t1 < 0 || t0 > t1 ? Infinity : t0;
}
// Ray against one convex solid: the last plane it enters before it leaves any plane, or Infinity.
let entryK = -1;
function entry(P, ox, oy, oz, dx, dy, dz) {
  let tn = -Infinity, tf = Infinity;
  for (let i = 0; i < P.length && tn <= tf; i += 4) {
    const den = P[i] * dx + P[i + 1] * dy + P[i + 2] * dz;
    const dist = P[i + 3] - (P[i] * ox + P[i + 1] * oy + P[i + 2] * oz), t = dist / den;
    if (den < 0) { if (t > tn) { tn = t; entryK = i; } } else if (den > 0) tf = Math.min(tf, t);
    else if (dist < 0) tf = -Infinity; // parallel to the plane and outside it
  }
  return tn <= tf && tn > 1e-3 ? tn : Infinity;
}
// Ray against a round column: the side of the cone or one of its caps. Sets entryK (-1 side, -2 top,
// -3 bottom) and entryN (the normal).
function coneEntry(cone, ox, oy, oz, dx, dy, dz) {
  const cx = cone[0], cz = cone[1], a = cone[2], b = cone[3], y0 = cone[4], y1 = cone[5], r0 = cone[6], r1 = cone[7];
  const X = ox - cx, Z = oz - cz, R = a + b * oy, bd = b * dy;
  const A = dx * dx + dz * dz - bd * bd, B = 2 * (X * dx + Z * dz - R * bd), C = X * X + Z * Z - R * R, disc = B * B - 4 * A * C;
  let best = Infinity;
  if (disc >= 0 && Math.abs(A) > 1e-9) {
    const sq = Math.sqrt(disc);
    for (let n = 0; n < 2; n++) {
      const t = (-B + (n ? sq : -sq)) / (2 * A), y = oy + t * dy;
      if (t > 1e-3 && t < best && y >= y0 && y <= y1 && R + t * bd >= 0) {
        const nx = X + t * dx, nz = Z + t * dz, ny = -b * (a + b * y), l = Math.sqrt(nx * nx + ny * ny + nz * nz);
        best = t; entryK = -1; entryN[0] = nx / l; entryN[1] = ny / l; entryN[2] = nz / l;
      }
    }
  }
  for (let n = 0; n < 2 && dy !== 0; n++) {
    const yc = n ? y0 : y1, rr = n ? r0 : r1, t = (yc - oy) / dy, x = X + t * dx, z = Z + t * dz;
    if (t > 1e-3 && t < best && x * x + z * z <= rr * rr) { best = t; entryK = n ? -3 : -2; entryN[0] = 0; entryN[1] = n ? -1 : 1; entryN[2] = 0; }
  }
  return best;
}
const hit = (s, ox, oy, oz, dx, dy, dz) => (s.cone ? coneEntry(s.cone, ox, oy, oz, dx, dy, dz) : entry(s.P, ox, oy, oz, dx, dy, dz));
function trace(list, col, ox, oy, oz, dx, dy, dz) {
  const ix = 1 / dx, iy = 1 / dy, iz = 1 / dz;
  for (const s of list) {
    if (col < s.i0 || col > s.i1 || boxEntry(s.bb, ox, oy, oz, ix, iy, iz) > hitT) continue;
    const t = hit(s, ox, oy, oz, dx, dy, dz);
    if (t < hitT) { hitT = t; hitK = entryK; hitS = s; if (entryK < 0) { hitN[0] = entryN[0]; hitN[1] = entryN[1]; hitN[2] = entryN[2]; } }
  }
}

// ---- Night lighting ----------------------------------------------------------------------
// Lamps, lit windows, the ship's lantern and portholes, and the beacon light what is near them, falling off
// with distance, and the solids near each light cast its shadows. The moon adds a dim, soft fill; the
// lighthouse beam sweeps the harbor. Phones drop the shadow rays first when frames run long.
let shadows = !touchFirst.matches;
function casters(list, x, y, z, r) {
  return list.filter(({ bb: b }) => {
    const ex = Math.max(b[0] - x, 0, x - b[3]), ey = Math.max(b[1] - y, 0, y - b[4]), ez = Math.max(b[2] - z, 0, z - b[5]);
    return ex + ey + ez > 0 && ex * ex + ey * ey + ez * ez < r * r; // near the light but not around it
  });
}
function lamp(x, y, z, i, r, inShip = false) {
  return { x, y, z, i, r2: r * r, inShip, near: casters(inShip ? ship : world, x, y, z, r), wx: x, wy: y, wz: z };
}
const centre = ({ bb: b }) => [(b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2];
const LIGHTS = [
  ...world.filter((s) => s.mat === "l" && s !== beacon && s !== antennaLamp).map((s) => lamp(...centre(s), 1, 10)),
  ...ship.filter((s) => s.mat === "l").map((s) => lamp(...centre(s), 0.9, 9, true)),
  lamp(-7.4, 3, 20.5, 0.6, 6), lamp(-2.6, 3, 20.5, 0.6, 6), lamp(-0.5, 3, 23.2, 0.45, 5), lamp(-0.5, 3, 25.7, 0.45, 5),
  lamp(-2.7, 3.3, -8, 0.45, 5, true), lamp(-0.3, 3.3, -8, 0.45, 5, true), lamp(...centre(beacon), 1.1, 16),
];
const BEAM = { x: -36, y: 13.8, z: -24, reach: 95 };
// Lights reaching each 8 m tile of the ground plan, so a point checks only the few lamps near it.
const TILE = 8, LIGHTGRID = new Map();
for (const L of LIGHTS) {
  const r = Math.sqrt(L.r2) + 1;
  for (let i = Math.floor((L.x - r) / TILE); i <= Math.floor((L.x + r) / TILE); i++) {
    for (let k = Math.floor((L.z - r) / TILE); k <= Math.floor((L.z + r) / TILE); k++) {
      const key = i * 1000 + k;
      if (!LIGHTGRID.has(key)) LIGHTGRID.set(key, []);
      LIGHTGRID.get(key).push(L);
    }
  }
}
const NONE = [];
// Moves the ship's lights with the ship and turns the beam, once per frame.
function moveLights() {
  for (const L of LIGHTS) {
    if (!L.inShip) continue;
    const lx = L.x - SX;
    L.wx = SX + rc * lx - rs * L.y; L.wy = rs * lx + rc * L.y + bob; L.wz = L.z;
  }
  BEAM.a = T * 0.5; BEAM.dx = Math.cos(BEAM.a); BEAM.dz = Math.sin(BEAM.a);
}
// Light reaching a point with normal n: [brightness, share of it from lamps].
function lightAt(x, y, z, nx, ny, nz) {
  const moon = 0.035 + 0.17 * Math.max(0, nx * MOON[0] + ny * MOON[1] + nz * MOON[2]) + 0.04 * Math.max(0, ny);
  let warm = 0;
  for (const L of LIGHTGRID.get(Math.floor(x / TILE) * 1000 + Math.floor(z / TILE)) || NONE) {
    const lx = L.wx - x, ly = L.wy - y, lz = L.wz - z, d2 = lx * lx + ly * ly + lz * lz;
    if (d2 > L.r2) continue;
    const d = Math.sqrt(d2), ndl = (nx * lx + ny * ly + nz * lz) / d, f = 1 - d2 / L.r2;
    const add = ndl > 0 ? L.i * f * f * (0.35 + 0.65 * ndl) : 0;
    if (add > 0.02 && !(shadows && shadowed(L, x + nx * 0.03, y + ny * 0.03, z + nz * 0.03, lx / d, ly / d, lz / d, d))) warm += add;
  }
  const beam = beamOn(x, z) * Math.max(0.3, ny + 0.5);
  return [moon + warm + beam, (warm + beam) / (moon + warm + beam)];
}
// Is the way from a point to a light blocked by one of the solids near the light?
function shadowed(L, ox, oy, oz, dx, dy, dz, dist) {
  if (L.inShip) {
    const x = ox - SX, y = oy - bob;
    [ox, oy, dx, dy] = [rc * x + rs * y + SX, -rs * x + rc * y, rc * dx + rs * dy, -rs * dx + rc * dy];
  }
  const ix = 1 / dx, iy = 1 / dy, iz = 1 / dz;
  for (const s of L.near) if (boxEntry(s.bb, ox, oy, oz, ix, iy, iz) < dist && hit(s, ox, oy, oz, dx, dy, dz) < dist) return true;
  return false;
}
// Brightness of the sweeping beam where it falls on the ground at (x, z).
function beamOn(x, z) {
  const hx = x - BEAM.x, hz = z - BEAM.z, d = Math.sqrt(hx * hx + hz * hz);
  if (d < 3 || d > BEAM.reach) return 0;
  const off = Math.abs(hx * BEAM.dz - hz * BEAM.dx) / d, ahead = hx * BEAM.dx + hz * BEAM.dz;
  return ahead > 0 && off < 0.07 ? 0.8 * (1 - off / 0.07) * (1 - d / BEAM.reach) : 0;
}

// Seventy shades from empty to dense, so light reads as gradients rather than steps.
const RAMP = " .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$";
const RANGE = { lighthouse: 400, nest: 30, office: 40, antenna: 50, containers: 40, lifeboat: 25, tender: 25 };
const MOON = (() => { const v = [0.2, 0.3, 0.93], l = Math.hypot(...v); return v.map((c) => c / l); })();
// Objects whose feature is not in the page's list are scenery.
for (const s of [...world, ...ship]) if (s.spot && !spots[s.spot]) s.spot = null;
const anchors = {};
for (const [list, lift] of [[world, 0], [ship, 1]]) {
  for (const s of list) {
    if (!s.spot) continue;
    const b = s.bb, a = (anchors[s.spot] ||= { x: 0, y: 0, z: 0, n: 0, r: 0, ship: lift });
    a.x += (b[0] + b[3]) / 2; a.y += (b[1] + b[4]) / 2; a.z += (b[2] + b[5]) / 2; a.n++;
    a.r = Math.max(a.r, (b[3] - b[0]) / 2, (b[5] - b[2]) / 2, (b[4] - b[1]) / 3);
  }
}
for (const a of Object.values(anchors)) { a.x /= a.n; a.y /= a.n; a.z /= a.n; }

let cols = 0, rows = 0, cellW = 8, cellH = 13, scale = 1, target = null, padX = 0, padY = 0;
const MONO = getComputedStyle(document.documentElement).getPropertyValue("--mono");
const BASE = { "": "#5c6a88", k: "#e9eefb", w: "#3f78b8", d: "#22406a", m: "#a9c8f0", o: "#dba66b", s: "#efe6cf",
  t: "#a3adc2", l: "#ffd479", r: "#e0705f", b: "#62a8e0", f: "#3a4562", h: "#7ee0c3", g: "#6fbf73", y: "#e3d3a3", n: "#9b8a62" };
// Each colour in four tiers for the night lighting: dark, dim, bright, and warmed by lamplight.
const mix = (a, b, f) => "#" + [1, 3, 5].map((i) => Math.round(parseInt(a.slice(i, i + 2), 16) * (1 - f) + parseInt(b.slice(i, i + 2), 16) * f).toString(16).padStart(2, "0")).join("");
const COLORS = {};
for (const [k, c] of Object.entries(BASE)) {
  Object.assign(COLORS, { [k]: c, [k + "w"]: mix(c, "#ffd479", 0.45) });
  // Eight levels from near black to full colour (and a little past it for the brightest), plus warm ones.
  for (let i = 0; i < 8; i++) {
    const lv = i < 7 ? mix("#060a14", c, Math.min(1, 0.12 + (i + 1) * 0.15)) : mix(c, "#ffffff", 0.25);
    Object.assign(COLORS, { [k + i]: lv, [k + "w" + i]: mix(lv, "#ffd479", 0.45) });
  }
}
function measure() {
  const dpr = devicePixelRatio || 1, w = stage.clientWidth, h = stage.clientHeight;
  canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
  const px = Math.max(6.5, Math.min(11, innerWidth * 0.0068)) * scale;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.font = `${px}px ${MONO}`;
  ctx.textBaseline = "top";
  cellW = ctx.measureText("M").width; cellH = px;
  cols = Math.max(20, Math.floor(w / cellW));
  rows = Math.max(12, Math.floor(h / cellH));
  padX = (w - cols * cellW) / 2; padY = (h - rows * cellH) / 2;
  G = new Array(cols * rows); C = new Array(cols * rows);
  ID = new Int32Array(cols * rows); D = new Float32Array(cols * rows); SP = new Array(cols * rows);
}

// Per-cell glyph, colour class, surface id (solid and face) and depth; the edge pass reads them.
let G, C, ID, D, SP;
const cam = {};
function render() {
  const aspect = (cols * cellW) / (rows * cellH), tanV = 0.62, tanH = tanV * aspect;
  const cy = Math.cos(me.yaw), sy = Math.sin(me.yaw), cp = Math.cos(me.pitch), sp = Math.sin(me.pitch);
  const fx = sy * cp, fy = sp, fz = cy * cp, rx = cy, rz = -sy, ux = -sp * sy, uy = cp, uz = -sp * cy;
  Object.assign(cam, { x: me.x, y: me.eye, z: me.z, f: [fx, fy, fz], r: [rx, 0, rz], u: [ux, uy, uz], tanH, tanV });
  // Camera origin in the ship frame (rotate by -roll about the ship's long axis, after the bob).
  cam.lx = rc * (me.x - SX) + rs * (me.eye - bob) + SX; cam.ly = -rs * (me.x - SX) + rc * (me.eye - bob);
  cull(world, false); cull(ship, true);
  for (let j = 0, c = 0; j < rows; j++) {
    const v = (1 - (2 * j + 1) / rows) * tanV;
    rowWorld = world.filter((s) => s.j0 <= j && j <= s.j1); rowShip = ship.filter((s) => s.j0 <= j && j <= s.j1);
    for (let i = 0; i < cols; i++, c++) {
      const h = ((2 * i + 1) / cols - 1) * tanH;
      const dx = fx + rx * h + ux * v, dy = fy + uy * v, dz = fz + rz * h + uz * v, n = Math.sqrt(dx * dx + dy * dy + dz * dz);
      cast(c, i, (i + j) & 1, dx / n, dy / n, dz / n);
    }
  }
  gulls();
  const mid = (rows >> 1) * cols + (cols >> 1);
  const spot = SP[mid], looked = spot && D[mid] < (RANGE[spot] || 12);
  show(moved ? jumped || (looked ? spot : nearby()) : null);
  // The label floats by what you look at (the crosshair) or, when you walk up to it, by its centre.
  label(looked && spot === target ? [cols >> 1, rows >> 1] : target && project(anchors[target]));
  minimap();
  draw(mid);
}

// Screen rectangle of each solid's bounding box this frame, so a ray only tests solids that can cover its cell.
let rowWorld = [], rowShip = [];
function cull(list, inShip) {
  const [f0, f1, f2] = cam.f, [r0, , r2] = cam.r, [u0, u1, u2] = cam.u;
  for (const s of list) {
    const b = s.bb;
    let i0 = Infinity, i1 = -Infinity, j0 = Infinity, j1 = -Infinity, behind = 0;
    for (let k = 0; k < 8; k++) {
      let x = k & 1 ? b[3] : b[0], y = k & 2 ? b[4] : b[1];
      const z = k & 4 ? b[5] : b[2];
      if (inShip) { const lx = x - SX; x = SX + rc * lx - rs * y; y = rs * lx + rc * y + bob; }
      const px = x - cam.x, py = y - cam.y, pz = z - cam.z, d = px * f0 + py * f1 + pz * f2;
      if (d < 0.2) { behind++; continue; }
      const si = ((px * r0 + pz * r2) / d / cam.tanH + 1) * cols / 2, sj = (1 - (px * u0 + py * u1 + pz * u2) / d / cam.tanV) * rows / 2;
      i0 = Math.min(i0, si); i1 = Math.max(i1, si); j0 = Math.min(j0, sj); j1 = Math.max(j1, sj);
    }
    if (behind === 8) { s.i0 = s.j0 = 1; s.i1 = s.j1 = 0; } // wholly behind you
    else if (behind) { s.i0 = s.j0 = -1; s.i1 = cols; s.j1 = rows; } // around you: test everywhere
    else { s.i0 = Math.floor(i0) - 1; s.i1 = Math.ceil(i1) + 1; s.j0 = Math.floor(j0) - 1; s.j1 = Math.ceil(j1) + 1; }
  }
}

// A few gulls circle over the harbor, drawn only where they are against the sky.
function gulls() {
  for (let g = 0; g < 5; g++) {
    const a = T * 0.22 + g * 1.3, r = 10 + g * 4;
    const p = project({ x: Math.cos(a) * r - 4, y: 13 + g * 1.6 + Math.sin(T + g), z: 6 + Math.sin(a) * r });
    const c = p && p[0] >= 0 && p[0] < cols && p[1] >= 0 && p[1] < rows ? p[1] * cols + p[0] : -1;
    if (c >= 0 && ID[c] === 0) { G[c] = "v"; C[c] = "k"; }
  }
}

// Screen cell of an anchor (possibly off screen), or null when it is behind you.
function project(a) {
  const p = [a.x - cam.x, a.y + (a.ship ? bob : 0) - cam.y, a.z - cam.z];
  const dot = (v) => v[0] * p[0] + v[1] * p[1] + v[2] * p[2], z = dot(cam.f);
  if (z < 0.3) return null;
  return [Math.round(((dot(cam.r) / z / cam.tanH + 1) / 2) * cols), Math.round(((1 - dot(cam.u) / z / cam.tanV) / 2) * rows)];
}

// Places the label up and to the side of the object, inside the screen, with a leader line drawn in text.
const LINE = new Map();
function label(at) {
  LINE.clear();
  card.hidden = mapMode === 2; // the full-screen map covers the scene, so no label floats over it
  if (!target || !at) { card.style.transform = ""; return; }
  at = [Math.max(0, Math.min(cols - 1, at[0])), Math.max(0, Math.min(rows - 1, at[1]))];
  // On a phone the label stays above the move pad in the bottom corner.
  const W = stage.clientWidth, H = stage.clientHeight - (pad.offsetParent ? pad.offsetHeight + 12 : 0), w = card.offsetWidth, h = card.offsetHeight;
  const px = padX + (at[0] + 0.5) * cellW, py = padY + (at[1] + 0.5) * cellH, gap = 56;
  let left = px + gap + w > W - 8 ? px - gap - w : px + gap, top = py - gap - h < 8 ? py + gap : py - gap - h;
  left = Math.max(8, Math.min(W - w - 8, left)); top = Math.max(8, Math.min(H - h - 8, top));
  // Keep clear of the mini map in the top right corner.
  const mapLeft = mapBox ? padX + mapBox.oi * cellW - 8 : W, mapBottom = mapBox ? padY + (mapBox.oj + mapBox.h) * cellH + 8 : 0;
  if (mapMode !== 2 && left + w > mapLeft && top < mapBottom) {
    if (mapBottom + h < H - 8) top = mapBottom; else left = Math.max(8, mapLeft - w);
  }
  card.style.transform = `translate(${left}px, ${top}px)`;
  // Leader from the object to the nearest point of the label's edge, one glyph per cell.
  const ex = Math.max(left, Math.min(left + w, px)), ey = Math.max(top, Math.min(top + h, py));
  let i = at[0], j = at[1];
  const i1 = Math.round((ex - padX) / cellW - 0.5), j1 = Math.round((ey - padY) / cellH - 0.5);
  const di = Math.abs(i1 - i), dj = Math.abs(j1 - j), si = Math.sign(i1 - i), sj = Math.sign(j1 - j);
  LINE.set(j * cols + i, "*");
  for (let err = di - dj, n = Math.max(di, dj); n > 1; n--) {
    const e2 = 2 * err, mi = e2 > -dj, mj = e2 < di;
    if (mi) { err -= dj; i += si; }
    if (mj) { err += di; j += sj; }
    LINE.set(j * cols + i, mi && mj ? (si === sj ? "\\" : "/") : mi ? "-" : "|");
  }
}

// ---- Mini map: the island in text, every point of interest, and you; M picks, M again fills the screen.
const ORDER = Object.keys(spots);
const WORLD = { x0: -46, x1: 24, z0: -36, z1: 30 };
const MAPCELLS = new Map();
let mapMode = 0, pick = 0, jumped = null, mapBox = null; // mapMode: 0 idle, 1 picking, 2 full screen
function minimap() {
  MAPCELLS.clear();
  const full = mapMode === 2, w = full ? cols - 2 : Math.min(30, cols - 2), h = full ? rows - 2 : Math.min(15, rows - 2);
  mapBox = { oi: full ? 1 : cols - w - 1, oj: 1, w, h, iw: w - 2, ih: h - 3 };
  mapFrame();
  mapTerrain();
  mapMarks();
}
// Puts a glyph at (i, j) of the map box, frame included.
const mapPut = (i, j, ch, cls) => MAPCELLS.set((mapBox.oj + j) * cols + mapBox.oi + i, [ch, cls]);
function mapFrame() {
  const { w, h, iw } = mapBox, full = mapMode === 2;
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) mapPut(i, j, j === 0 || j === h - 1 ? "-" : i === 0 || i === w - 1 ? "|" : " ", "t");
  const tip = mapMode ? `< ${spots[ORDER[pick]].title} > Enter` : touchFirst.matches ? "tap: map" : "M: map";
  [...(full ? tip + "   M or Esc closes" : tip).slice(0, iw)].forEach((ch, i) => mapPut(i + 1, h - 2, ch, "h"));
  if (touchFirst.matches) mapPut(w - 2, 0, full ? "x" : "+", "h");
}
// Water, land and the ship's deck, sampled from the walkable areas.
function mapTerrain() {
  for (let j = 0; j < mapBox.ih; j++) {
    for (let i = 0; i < mapBox.iw; i++) {
      const [x, z] = fromMap(i + 0.5, j + 0.5), f = FLOORS.findIndex(([x0, x1, z0, z1]) => x >= x0 && x < x1 && z >= z0 && z < z1);
      if (f < 0) mapPut(i + 1, j + 1, (i + j) % 5 ? " " : "~", "d");
      else mapPut(i + 1, j + 1, f === 0 ? "#" : f > 1 && roadAt(x, z)[0] < 1.4 ? "+" : ".", f === 0 ? "o" : f > 1 && roadAt(x, z)[0] < 1.4 ? "s" : "t");
    }
  }
}
// Points of interest (the pick in the highlight colour) and you, pointing the way you face.
function mapMarks() {
  const inside = ([i, j]) => i >= 0 && i < mapBox.iw && j >= 0 && j < mapBox.ih;
  ORDER.forEach((id, n) => {
    const p = toMap(anchors[id].x, anchors[id].z), picked = mapMode && n === pick;
    if (inside(p)) mapPut(p[0] + 1, p[1] + 1, picked ? "@" : "*", picked ? "h" : "l");
  });
  const p = toMap(me.x, me.z);
  if (inside(p)) mapPut(p[0] + 1, p[1] + 1, "^>v<"[Math.round(((me.yaw % 6.283) + 6.283) / 1.5708) % 4], "k");
}
const toMap = (x, z) => [Math.floor(((x - WORLD.x0) / (WORLD.x1 - WORLD.x0)) * mapBox.iw), Math.floor(((WORLD.z1 - z) / (WORLD.z1 - WORLD.z0)) * mapBox.ih)];
const fromMap = (i, j) => [WORLD.x0 + (i / mapBox.iw) * (WORLD.x1 - WORLD.x0), WORLD.z1 - (j / mapBox.ih) * (WORLD.z1 - WORLD.z0)];
// A free spot 2.5 to 8 m from an object, on the same level (deck or land), to stand and look at it from.
function standFor(a) {
  for (const r of [2.5, 4, 6, 8, 12, 16].filter((r) => r >= Math.min(a.r * 2.5, a.ship ? 6 : 16))) {
    for (let k = 0; k < 8; k++) {
      const x = a.x + r * Math.sin(k * 0.785), z = a.z - r * Math.cos(k * 0.785), fy = floorAt(x, z);
      if (fy !== null && (fy > 1.6) === !!a.ship && !blocked(x, z, fy)) return [x, z];
    }
  }
  return [me.x, me.z];
}
// Walks to a point of interest along the roads (or jumps there with reduced motion), then faces it.
let walkPath = [], walkTo = null;
function go(id) {
  const stand = standFor(anchors[id]);
  setMap(0); moved = true; dirty = true; jumped = null;
  if (reduced.matches) { me.x = stand[0]; me.z = stand[1]; me.eye = floorAt(...stand) + 1.6; face(id); return; }
  walkPath = [...route(nearestNode(me.x, me.z), nearestNode(...stand)), stand];
  walkTo = id;
}
function face(id) {
  const a = anchors[id];
  me.yaw = Math.atan2(a.x - me.x, a.z - me.z);
  me.pitch = Math.max(-1.1, Math.min(1.1, Math.atan2(a.y + (a.ship ? bob : 0) - me.eye, Math.hypot(a.x - me.x, a.z - me.z))));
  jumped = id;
}
const nearestNode = (x, z) => NODES.reduce((b, n, i) => (Math.hypot(n[0] - x, n[1] - z) < Math.hypot(NODES[b][0] - x, NODES[b][1] - z) ? i : b), 0);
// Shortest road route between two junctions (Dijkstra over a handful of nodes).
function route(from, to) {
  const dist = NODES.map(() => Infinity), prev = [], todo = new Set(NODES.keys());
  dist[from] = 0;
  while (todo.size) {
    const u = [...todo].reduce((a, b) => (dist[a] < dist[b] ? a : b));
    todo.delete(u);
    for (const [a, b] of LINKS) {
      const v = a === u ? b : b === u ? a : -1, d = v < 0 ? 0 : dist[u] + Math.hypot(NODES[v][0] - NODES[u][0], NODES[v][1] - NODES[u][1]);
      if (v >= 0 && todo.has(v) && d < dist[v]) { dist[v] = d; prev[v] = u; }
    }
  }
  const path = [];
  for (let v = to; v !== undefined; v = prev[v]) path.unshift(NODES[v]);
  return path;
}
// One frame of the auto-walk: head for the next waypoint, turning smoothly; face the object on arrival.
function autoStep(dt) {
  const [tx, tz] = walkPath[0], dx = tx - me.x, dz = tz - me.z, d = Math.hypot(dx, dz), v = 4.5 * dt;
  if (d <= v) {
    me.x = tx; me.z = tz; walkPath.shift();
    if (!walkPath.length) face(walkTo);
    return true;
  }
  me.x += (dx / d) * v; me.z += (dz / d) * v;
  const turn = Math.atan2(dx, dz) - me.yaw;
  me.yaw += Math.atan2(Math.sin(turn), Math.cos(turn)) * Math.min(1, dt * 6);
  me.pitch *= 0.9;
  return true;
}
// An open map frees the mouse (no pointer lock, a normal cursor) so you can point at it; walking hides it again.
function setMap(mode) {
  mapMode = mode;
  if (mode && document.pointerLockElement) document.exitPointerLock();
  stage.classList.toggle("mapping", mode > 0);
}
// M picks on the map, M again fills the screen, M or Escape closes; arrows or the mouse choose, Enter goes.
function mapKey(e) {
  if (e.code === "KeyM") setMap((mapMode + 1) % 3);
  else if (!mapMode) return false;
  else if (e.key === "Escape") setMap(0);
  else if (e.key === "Enter") go(ORDER[pick]);
  else if (/^Arrow/.test(e.key)) pick = (pick + (/Right|Down/.test(e.key) ? 1 : ORDER.length - 1)) % ORDER.length;
  else return false;
  moved = true; // using the map folds the intro away
  return true;
}
// Map cell under a screen point, or null outside the map.
function mapCell(cx, cy) {
  const b = mapBox, i = b && Math.floor((cx - padX) / cellW) - b.oi, j = b && Math.floor((cy - padY) / cellH) - b.oj;
  return b && i >= 0 && j >= 0 && i < b.w && j < b.h ? [i, j] : null;
}
// Points of interest nearest to a map cell, the closest first (several when they share a cell).
function nearestPoints(i, j) {
  const d = (id) => { const [pi, pj] = toMap(anchors[id].x, anchors[id].z); return Math.hypot(pi - i + 1, (pj - j + 1) * 2); };
  const all = ORDER.map((id, n) => [d(id), n]).sort((p, q) => p[0] - q[0]);
  return all.filter((p) => p[0] <= all[0][0] + 0.01).map(([, n]) => n);
}
// Hovering the open map with the mouse picks the nearest point.
function hoverMap(cx, cy) {
  const at = mapMode && mapCell(cx, cy);
  if (!at || at[1] === 0 || at[1] >= mapBox.h - 2) return;
  const near = nearestPoints(...at);
  if (!near.includes(pick)) { pick = near[0]; dirty = true; }
}
// A tap or click on the map: the corner mark resizes it, the caption goes to the pick, elsewhere picks the nearest point.
function tapMap(cx, cy) {
  const at = mapCell(cx, cy);
  if (!at) return false;
  if (at[1] === 0) setMap(mapMode === 2 ? 0 : 2);
  else if (at[1] >= mapBox.h - 2) go(ORDER[pick]);
  else {
    const near = nearestPoints(...at);
    pick = near[(near.indexOf(pick) + 1) % near.length];
    if (mapMode === 0) setMap(1);
  }
  dirty = true;
  return true;
}

// One ray: the nearest of the solids, the moving sea surface and the sky decides the cell.
function cast(c, i, odd, dx, dy, dz) {
  hitT = Infinity; hitS = null;
  trace(rowWorld, i, cam.x, cam.y, cam.z, dx, dy, dz);
  const wS = hitS;
  const ldx = rc * dx + rs * dy, ldy = -rs * dx + rc * dy;
  trace(rowShip, i, cam.lx, cam.ly, cam.z, ldx, ldy, dz);
  const tw = seaHit(dx, dy, dz, hitT);
  SP[c] = null;
  if (hitS && hitT < tw) shadeSolid(c, odd, hitS !== wS, dx, dy, dz, ldx, ldy);
  else if (tw < Infinity) shadeWater(c, tw, dx, dy, dz);
  else shadeSky(c, dx, dy, dz);
}
// Brightness changes the ground textures ask for: kerbs and flowers brighter, joints, ruts and wet sand darker.
const GRAIN = { _: 1.35, "=": 1.3, "*": 1.5, "~": 1.25, "+": 1.1, "-": 1.1, ".": 1, ",": 0.85, ":": 0.7, ";": 0.8, '"': 0.9, "'": 0.95, "`": 0.9, " ": 1 };
function shadeSolid(c, odd, onShip, dx, dy, dz, ldx, ldy) {
  const s = hitS, P = s.P, k = hitK, t = hitT;
  const lnx = k >= 0 ? P[k] : hitN[0], lny = k >= 0 ? P[k + 1] : hitN[1], nz = k >= 0 ? P[k + 2] : hitN[2];
  const nx = onShip ? rc * lnx - rs * lny : lnx, ny = onShip ? rs * lnx + rc * lny : lny;
  const px = onShip ? cam.lx + ldx * t : cam.x + dx * t, py = onShip ? cam.ly + ldy * t : cam.y + dy * t, pz = cam.z + dz * t;
  const tex = s.tex && s.tex(px, py, pz, lnx, lny, nz);
  const mat = tex && tex !== "-" ? tex[0] : s.mat, grain = tex && tex.length === 2 ? GRAIN[tex[1]] || 1 : 1;
  const dim = (tex === "-" ? 0.55 : 1) * (s.dim || 1) * grain;
  let ch, cls = mat;
  if (mat === "l") {
    const flash = s === beacon ? Math.cos(T * 2.2 + Math.atan2(dx, dz) * 2) > 0.3 : s !== antennaLamp || Math.sin(T * 3) > 0;
    ch = flash ? "@" : "o"; cls = "l7";
  } else {
    const wx = onShip ? SX + rc * (px - SX) - rs * py : px, wy = onShip ? rs * (px - SX) + rc * py + bob : py;
    const [lit, warm] = lightAt(wx, wy, pz, nx, ny, nz);
    // Contact shadow: walls darken toward the ground they stand on.
    const ao = ny > 0.7 ? 1 : Math.min(1, 0.55 + 0.5 * (wy - (onShip ? bob + DECK : floorAt(wx, pz) ?? 0)));
    const fog = Math.exp(-t * 0.016), b = (lit * dim * ao * (0.8 + 0.2 * Math.max(0, -(nx * dx + ny * dy + nz * dz)))) * fog + 0.02 * (1 - fog);
    cls = mat + tier(b, warm);
    ch = glyph(b, odd);
  }
  // Floors get a negative id: they outline what stands on them but draw no edges themselves.
  put(c, ch, cls, (ny > 0.7 ? -1 : 1) * (s.id * 16 + (k >= 0 ? k >> 2 : 12 - k)), t);
  SP[c] = s.spot;
}
// Glyph for a brightness from the long ramp; the darkest cells thin out to a dither.
const glyph = (b, odd) => (b < 0.035 ? (odd ? " " : b > 0.02 ? "." : " ") : RAMP[Math.min(RAMP.length - 1, 1 + Math.floor(b * (RAMP.length - 2)))]);
// Colour level (0 to 7) for a brightness, warmed when lamplight dominates.
const tier = (b, warm) => (warm > 0.55 && b > 0.2 ? "w" : "") + Math.min(7, Math.floor(b * 9));
// How close water at (x, z) is to a beach, from 0 (deep) to 1 (the waterline).
function shallows(x, z) {
  const north = z < 10 && (x < -6 || x > 8) ? 1 - (10 - z) / 5 : 0, east = z < 12 && x > -22.7 && x < -14 ? 1 - (x + 22.7) / 5 : 0;
  return Math.max(0, north, east);
}

// ---- The sea: a height field of summed travelling waves (amplitude, direction, wave number, speed, phase),
// ray marched per cell, with analytic normals for Fresnel reflection, moon and lamp highlights, and foam.
const WAVES = new Float64Array([0.17, 0.8, 0.6, 0.7, 2.6, 0, 0.11, -0.3, 0.95, 1.14, 3.3, 1.7, 0.07, 0.95, -0.3, 1.96, 4.4, 4.1, 0.035, 0.2, 0.98, 3.5, 5.8, 2.3]);
const SEA = 0.17 + 0.11 + 0.07 + 0.035;
const seaN = [0, 1, 0];
function seaHeight(x, z) {
  let h = 0;
  for (let i = 0; i < 24; i += 6) h += WAVES[i] * Math.sin(WAVES[i + 3] * (WAVES[i + 1] * x + WAVES[i + 2] * z) - WAVES[i + 4] * T + WAVES[i + 5]);
  return h * (1 - 0.6 * shallows(x, z));
}
function seaNormal(x, z) {
  let hx = 0, hz = 0;
  for (let i = 0; i < 24; i += 6) {
    const c = WAVES[i] * WAVES[i + 3] * Math.cos(WAVES[i + 3] * (WAVES[i + 1] * x + WAVES[i + 2] * z) - WAVES[i + 4] * T + WAVES[i + 5]);
    hx += c * WAVES[i + 1]; hz += c * WAVES[i + 2];
  }
  const l = Math.sqrt(hx * hx + 1 + hz * hz);
  seaN[0] = -hx / l; seaN[1] = 1 / l; seaN[2] = -hz / l;
}
// Distance along the ray to the sea surface, or Infinity if a solid at `limit` comes first.
function seaHit(dx, dy, dz, limit) {
  if (dy > -1e-4) return Infinity;
  const t0 = Math.max(0, (SEA - cam.y) / dy), t1 = Math.min(limit, (-SEA - cam.y) / dy, 400);
  if (t0 >= t1) return Infinity;
  if (t0 > 60) { const t = -cam.y / dy; return t < limit ? t : Infinity; } // far out the surface is flat enough
  const n = 14, step = (t1 - t0) / n;
  let a = t0;
  for (let i = 1; i <= n; i++) {
    let b = t0 + i * step;
    if (cam.y + b * dy < seaHeight(cam.x + b * dx, cam.z + b * dz)) {
      for (let k = 0; k < 4; k++) { const m = (a + b) / 2; if (cam.y + m * dy < seaHeight(cam.x + m * dx, cam.z + m * dz)) b = m; else a = m; }
      return b;
    }
    a = b;
  }
  return Infinity;
}
function shadeWater(c, t, dx, dy, dz) {
  const x = cam.x + dx * t, z = cam.z + dz * t, h = seaHeight(x, z), near = shallows(x, z);
  seaNormal(x, z);
  const [nx, ny, nz] = seaN, dn = dx * nx + dy * ny + dz * nz, rx = dx - 2 * dn * nx, ry = dy - 2 * dn * ny, rz = dz - 2 * dn * nz;
  const fresnel = 0.04 + 0.96 * Math.pow(1 - Math.min(1, -dn), 5);
  const moonSpec = Math.pow(Math.max(0, rx * MOON[0] + ry * MOON[1] + rz * MOON[2]), 90) * 1.4;
  let lampSpec = 0;
  for (const L of LIGHTS) {
    const lx = L.wx - x, ly = L.wy - h, lz = L.wz - z, d2 = lx * lx + ly * ly + lz * lz;
    if (d2 > 3600) continue;
    const d = Math.sqrt(d2), s = (rx * lx + ry * ly + rz * lz) / d;
    if (s > 0.985) lampSpec += L.i * Math.pow(s, 300) * 1.4 / (1 + d2 * 0.006);
  }
  // Foam on the highest crests, and a broken line of it where the waves wash onto the beaches.
  const foam = Math.max(0, (h - SEA * 0.7) / (SEA * 0.3)) * 0.6 + (near > 0.9 && Math.sin(x * 1.3 + z + T * 1.8) > 0.55 ? 0.5 : 0);
  const body = (0.03 + 0.12 * Math.max(0, nx * MOON[0] + ny * MOON[1] + nz * MOON[2])) * (1 + near);
  const fog = Math.exp(-t * 0.014), lum = ((body * (1 - fresnel) + 0.03 * fresnel + moonSpec + lampSpec + foam * 0.35 + beamOn(x, z) * 0.6) * fog) + 0.015 * (1 - fog);
  const mat = foam > 0.4 ? "k" : lampSpec > moonSpec && lampSpec > 0.1 ? "l" : moonSpec > 0.1 ? "m" : near > 0.2 ? "w" : "d";
  put(c, glyph(lum, (c ^ Math.floor(t)) & 1), mat + tier(lum, 0), -1, t);
}
// How close a sky ray passes to the lighthouse beam, as a glow from 0 to 1.
function beamGlow(dx, dy, dz) {
  const ux = BEAM.dx, uy = -0.02, uz = BEAM.dz, wx = cam.x - BEAM.x, wy = cam.y - BEAM.y, wz = cam.z - BEAM.z;
  const b = dx * ux + dy * uy + dz * uz, d = dx * wx + dy * wy + dz * wz, e = ux * wx + uy * wy + uz * wz, den = 1 - b * b;
  const sc = (b * e - d) / den, tc = (e - b * d) / den;
  if (sc < 0 || tc < 2 || tc > BEAM.reach) return 0;
  const gx = wx + sc * dx - tc * ux, gy = wy + sc * dy - tc * uy, gz = wz + sc * dz - tc * uz;
  return Math.max(0, 1 - Math.sqrt(gx * gx + gy * gy + gz * gz) / (0.4 + tc * 0.012)) * (1 - tc / BEAM.reach);
}
function shadeSky(c, dx, dy, dz) {
  const m = dx * MOON[0] + dy * MOON[1] + dz * MOON[2], el = Math.asin(dy);
  const r = hash(Math.floor(Math.atan2(dx, dz) * 150), Math.floor(el * 150)) * 2.5;
  if (m > 0.9988) put(c, m > 0.99935 ? "@" : "o", "k", 0, Infinity);
  else if (el > 0.04 && r < 0.03) put(c, r < 0.006 ? "*" : ".", "k", 0, Infinity);
  else if (beamGlow(dx, dy, dz) > 0.15) put(c, glyph(beamGlow(dx, dy, dz) * 0.8, 0), "l" + Math.min(7, 2 + Math.floor(beamGlow(dx, dy, dz) * 6)), 0, Infinity);
  else put(c, el < 0.035 ? "." : " ", "f", 0, Infinity);
}
function put(c, ch, cls, id, depth) { G[c] = ch; C[c] = cls; ID[c] = id; D[c] = depth; }

// Is neighbour n (inside the grid) another surface at least `min` away?
const beyond = (n, inside, id, min) => inside && ID[n] !== id && D[n] >= min;
const slope = (l, r, u, w) => ((l || r) && (u || w) ? ((u && r) || (w && l) ? "\\" : "/") : l || r ? "|" : u ? "-" : w ? "_" : null);
// Outline glyph where a solid or face meets something farther away, else null.
function edge(c, i, j) {
  const id = ID[c], d = D[c];
  if (id <= 0 || d >= 70) return null;
  // Neighbours left and up must be farther, right and down at least as far, so each seam draws once.
  return slope(beyond(c - 1, i > 0, id, d * 1.03), beyond(c + 1, i < cols - 1, id, d * 0.97),
    beyond(c - cols, j > 0, id, d * 1.03), beyond(c + cols, j < rows - 1, id, d * 0.97));
}
// Silhouette glyph of the object you point at: its cells next to any cell that is not part of it.
function outline(c, i, j) {
  if (!target || SP[c] !== target) return null;
  const off = (n, inside) => !inside || SP[n] !== target;
  return slope(off(c - 1, i > 0), off(c + 1, i < cols - 1), off(c - cols, j > 0), off(c + cols, j < rows - 1));
}
// Draws each row as runs of one colour.
function draw(mid) {
  ctx.fillStyle = "#060a14";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  for (let j = 0; j < rows; j++) {
    let run = "", cur = C[j * cols], from = 0;
    for (let i = 0; i < cols; i++) {
      const c = j * cols + i, aim = c === mid;
      const map = MAPCELLS.get(c), mark = map ? map[0] : aim ? "+" : LINE.get(c) || outline(c, i, j);
      const cls = map ? map[1] : aim ? (target ? "h" : "k") : mark ? "h" : C[c];
      if (cls !== cur) { paint(run, cur, from, j); run = ""; cur = cls; from = i; }
      run += mark || edge(c, i, j) || G[c];
    }
    paint(run, cur, from, j);
  }
}
function paint(run, cls, i, j) {
  if (run.trim()) { ctx.fillStyle = COLORS[cls]; ctx.fillText(run, padX + i * cellW, padY + j * cellH); }
}

function nearby() {
  let best = null, bd = 2.2;
  for (const [id, a] of Object.entries(anchors)) {
    const d = Math.hypot(a.x - me.x, a.z - me.z);
    if (d < bd && Math.abs(a.y + (a.ship ? bob : 0) - me.eye) < 5) { bd = d; best = id; }
  }
  return best;
}

let shown;
function show(id) {
  const key = id || (moved ? "" : "welcome");
  if (key === shown) return;
  shown = key;
  target = id;
  card.classList.toggle("intro", !id);
  if (!id) {
    // The intro folds away on the first step, tap or click; its text and links come from the page header.
    const hint = touchFirst.matches ? "The pad walks, a drag looks around, the map in the corner jumps to any point."
      : "WASD or arrows walk, R and F look up and down, the mouse looks around, Enter opens what you point at, M opens the map.";
    card.innerHTML = moved ? "" : `<h3>${document.querySelector(".top h1").textContent}</h3>` +
      `<p>${document.querySelector(".tagline").textContent}</p><p class="hint">${hint}</p>` +
      `<p class="links">${document.querySelector(".top nav").innerHTML}</p>`;
    return;
  }
  const s = spots[id];
  card.innerHTML = `<h3>${s.title}</h3><p>${s.body}</p><p class="hint"><a target="_blank" rel="noopener" href="${s.href}">Open: ${s.title} \u2192</a>` +
    `${touchFirst.matches ? " &middot; tap to open" : " &middot; Enter opens it"}</p>`;
}

// ---- Input -------------------------------------------------------------------------------
const KEYS = { KeyW: "f", ArrowUp: "f", KeyS: "b", ArrowDown: "b", KeyA: "l", KeyD: "r", ArrowLeft: "tl", ArrowRight: "tr",
  KeyR: "u", KeyF: "d" };
const open = () => { if (target) window.open(spots[target].href, "_blank", "noopener"); };
stage.addEventListener("keydown", (e) => {
  if (mapKey(e)) { e.preventDefault(); dirty = true; return; }
  if (e.key === "Enter" && target && !e.target.closest("a")) { e.preventDefault(); open(); return; }
  const k = KEYS[e.code];
  if (!k || e.altKey || e.ctrlKey || e.metaKey) return;
  e.preventDefault();
  keys.add(k);
});
stage.addEventListener("keyup", (e) => keys.delete(KEYS[e.code]));
stage.addEventListener("blur", () => keys.clear());
const look = (dx, dy, k) => {
  me.yaw += dx * k;
  me.pitch = Math.max(-1.2, Math.min(1.2, me.pitch - dy * k));
  moved = true; jumped = null; walkPath = [];
  dirty = true;
};
// A click only starts mouse look; Enter opens what you point at. On a phone a tap on the label opens it.
canvas.addEventListener("click", () => {
  if (!mapMode && !touchFirst.matches && stage.requestPointerLock) stage.requestPointerLock();
  stage.focus({ preventScroll: true });
});
card.addEventListener("click", (e) => { if (touchFirst.matches && !e.target.closest("a")) open(); });
document.addEventListener("mousemove", (e) => {
  if (document.pointerLockElement === stage) look(e.movementX, e.movementY, 0.0022);
  else hoverMap(e.clientX, e.clientY);
});
let padId = null, lookId = null, lastX = 0, lastY = 0;
function steer(e) {
  const r = pad.getBoundingClientRect(), half = r.width / 2;
  let x = (e.clientX - r.left - half) / half, y = (e.clientY - r.top - half) / half;
  const l = Math.hypot(x, y);
  if (l > 1) { x /= l; y /= l; }
  stick.x = x; stick.y = -y;
  knob.style.transform = `translate(${x * half * 0.6}px, ${y * half * 0.6}px)`;
}
// The intro card folds away on the first tap or click, as it does on the first step.
stage.addEventListener("pointerdown", (e) => { if (!e.target.closest(".card")) { moved = true; dirty = true; } });
stage.addEventListener("pointerdown", (e) => {
  if (e.target.closest(".card") || tapMap(e.clientX, e.clientY)) return;
  if (e.pointerType === "mouse") return;
  if (pad.contains(e.target)) {
    padId = e.pointerId; steer(e);
  } else { lookId = e.pointerId; lastX = e.clientX; lastY = e.clientY; }
  stage.setPointerCapture(e.pointerId);
  e.preventDefault();
});
stage.addEventListener("pointermove", (e) => {
  if (e.pointerId === padId) steer(e);
  else if (e.pointerId === lookId) { look(e.clientX - lastX, e.clientY - lastY, 0.006); lastX = e.clientX; lastY = e.clientY; }
});
const release = (e) => {
  if (e.pointerId === padId) { padId = null; stick.x = stick.y = 0; knob.style.transform = ""; }
  if (e.pointerId === lookId) lookId = null;
};
stage.addEventListener("pointerup", release);
stage.addEventListener("pointercancel", release);

function step(dt) {
  const turn = (keys.has("tr") ? 1 : 0) - (keys.has("tl") ? 1 : 0);
  const tilt = (keys.has("u") ? 1 : 0) - (keys.has("d") ? 1 : 0);
  const fwd = (keys.has("f") ? 1 : 0) - (keys.has("b") ? 1 : 0) + stick.y;
  const side = (keys.has("r") ? 1 : 0) - (keys.has("l") ? 1 : 0) + stick.x;
  if (!turn && !tilt && !fwd && !side) return walkPath.length ? autoStep(dt) : false;
  moved = true; jumped = null; walkPath = [];
  me.yaw += turn * 1.9 * dt;
  me.pitch = Math.max(-1.2, Math.min(1.2, me.pitch + tilt * 1.2 * dt));
  const c = Math.cos(me.yaw), s = Math.sin(me.yaw), v = 3.4 * dt;
  const here = floorAt(me.x, me.z);
  const walk = (x, z) => {
    const fy = floorAt(x, z);
    if (fy === null || Math.abs(fy - here) > 0.6 || blocked(x, z, fy)) return;
    me.x = x; me.z = z;
  };
  walk(me.x + (s * fwd + c * side) * v, me.z);
  walk(me.x, me.z + (c * fwd - s * side) * v);
  return true;
}

// ---- Loop --------------------------------------------------------------------------------
let last = performance.now(), dirty = true, visible = true, slow = 0, fast = 0;
new IntersectionObserver(([e]) => { visible = e.isIntersecting; }).observe(stage);
new ResizeObserver(() => { measure(); dirty = true; }).observe(stage);
reduced.addEventListener("change", () => { dirty = true; });
function frame(now) {
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  const still = reduced.matches;
  if (!still) T += dt;
  // The ship rides the swell too, gently: it is heavy, so half the wave height and a slow roll.
  if (still) { bob = 0; roll = 0; } else { seaNormal(SX, -2); bob = 0.5 * seaHeight(SX, -2) + 0.08 * Math.sin(T * 0.7); roll = -0.35 * Math.atan2(seaN[0], seaN[1]); }
  rc = Math.cos(roll); rs = Math.sin(roll);
  const walked = step(dt);
  if (visible && cols && (walked || dirty || !still)) {
    dirty = false;
    setGangway();
    moveLights();
    floatBoats();
    me.eye = floorAt(me.x, me.z) + 1.6;
    const t0 = performance.now();
    render();
    const ms = performance.now() - t0;
    slow = ms > 20 ? slow + 1 : 0;
    fast = ms < 9 ? fast + 1 : 0;
    // Adaptive resolution: when frames run long drop the shadow rays, then grow the glyphs (fewer cells);
    // when they run short for a while, shrink the glyphs again (more cells), down to the finest grid.
    if (slow > 20 && (shadows || scale < 2.2)) {
      if (shadows) shadows = false;
      else { scale *= 1.15; measure(); }
      slow = 0;
    } else if (fast > 90 && scale > 1) {
      scale = Math.max(1, scale / 1.1); measure(); fast = 0;
    }
  }
  requestAnimationFrame(frame);
}
measure();
requestAnimationFrame(frame);
