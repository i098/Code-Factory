// Crewship harbor: a first-person 3D scene ray cast into a grid of text, every frame.
// Plain JavaScript, no dependencies. The world is a list of convex solids (sets of planes)
// plus the water plane; the ship's solids live in a frame that bobs and rolls at the dock.
const stage = document.getElementById("stage");
const canvas = document.getElementById("scene");
const ctx = canvas.getContext("2d");
const card = document.getElementById("card");
// With JavaScript the scene fills the screen and the plain page stays for screen readers only.
stage.hidden = false;
const plain = document.getElementById("page");
plain.classList.add("sr-only");
// An uncaught error shows the plain page again instead of a frozen or blank scene.
addEventListener("error", () => { stage.hidden = true; plain.classList.remove("sr-only"); });
stage.focus({ preventScroll: true });
const pad = document.getElementById("pad");
const knob = pad.firstElementChild;
const reduced = matchMedia("(prefers-reduced-motion: reduce)");
const touchFirst = matchMedia("(pointer: coarse)");

// The features come from the plain list, so the scene and the list never disagree.
const spots = {};
for (const li of document.querySelectorAll("#manifest li[data-spot]")) {
  const a = li.querySelector("a");
  spots[li.dataset.spot] = { title: a.textContent, href: a.href, body: li.querySelector("p") };
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
// An ellipsoid: rocks, pebbles and leafy canopies. Rays hit the true surface; the box planes serve walking and culling.
function blob(list, cx, cy, cz, rx, ry, rz, mat, o) {
  const s = box(list, cx - rx, cy - ry, cz - rz, cx + rx, cy + ry, cz + rz, mat, o);
  s.blob = [cx, cy, cz, rx, ry, rz];
  return s;
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
  return solid(list, planes, bb, mat, { solid: false, thin: true, ...o });
}
// A 3x5 pixel font for the painted signs.
const FONT = { A: "010101111101101", B: "110101110101110", C: "011100100100011", D: "110101101101110", E: "111100110100111",
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
const NODES = [[-0.3, -6], [-0.3, -1.2], [0.3, 5.5], [1.9, -1.2], [4.2, -1.2], [5, 13.5], [5, 19.6], [7.1, 24.6], [-5, 19.6],
  [-16, 19.6], [-28, 19.6], [-30, 10], [-30, -14], [14, 19.6], [20, 19.6], [7.1, 21.7]];
const LINKS = [[0, 1], [1, 2], [1, 3], [3, 4], [4, 5], [5, 6], [6, 15], [6, 8], [8, 9], [9, 10], [10, 11], [11, 12], [6, 13], [13, 14], [15, 7]];
// Island ways (the links past the dock): concrete from the dock head to the plaza and along the centre of
// the avenue, narrow dirt trails beyond. [ax, az, dx, dz, length², concrete, length]
const CONCRETE = new Set(["5,6", "6,15", "15,7", "6,8", "6,13"]);
const ROADS = LINKS.slice(5).map(([a, b]) => {
  const [ax, az] = NODES[a], dx = NODES[b][0] - ax, dz = NODES[b][1] - az;
  const l2 = dx * dx + dz * dz;
  return [ax, az, dx, dz, l2, CONCRETE.has(`${a},${b}`), Math.sqrt(l2)];
});
// Distance from (x, z) to the nearest way, how far along it you are, and whether it is concrete.
function roadAt(x, z) {
  let best = Infinity, along = 0, concrete = false;
  for (const [ax, az, dx, dz, l2, c, length] of ROADS) {
    const t = Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / l2)), ex = x - ax - t * dx, ez = z - az - t * dz;
    const d = ex * ex + ez * ez;
    if (d < best) { best = d; along = t * length; concrete = c; }
  }
  return [Math.sqrt(best), along, concrete];
}
// Staggered paving joints and individually divided stones around the round plaza.
function plazaCurb(x, z) {
  return (Math.atan2(z - 24.6, x - 5) + Math.PI) * 12 % 1 < 0.12 ? "t:" : "s=";
}
function plazaStone(x, z) {
  const row = Math.floor((z + 99) / 0.9), u = x + 99 + (row % 2) * 0.6;
  if (u % 1.2 < 0.09) return "s|";
  if ((z + 99) % 0.9 < 0.075) return "s-";
  return hash(Math.floor(u / 1.2), row) < 0.3 ? "t," : "t.";
}
function plazaPaving(x, z, radius) {
  return radius > 2.96 ? plazaCurb(x, z) : plazaStone(x, z);
}
// Island ground as material and glyph: a 3 m concrete road with kerbs and joints every 3 m, a tiled plaza,
// a 1 m dirt trail with uneven edges, ruts and footprints, and grass with a few flowers elsewhere.
function ground(x, y, z, nx, ny) {
  if (ny < 0.5) return null;
  const [d, along, concrete] = roadAt(x, z), plaza = Math.hypot(x - 5, z - 24.6);
  if (plaza < 3.2) return plazaPaving(x, z, plaza);
  if (concrete && d < 1.5) return d > 1.38 ? along % 0.8 < 0.08 ? "t:" : "s_" : along % 3 < 0.12 ? "t:" : "t.";
  if (!concrete && d < 0.5 + 0.12 * Math.sin(along * 1.7) + 0.08 * hash(Math.floor(along * 3), 7)) {
    if (Math.abs(d - 0.22) < 0.06) return "o:";
    return hash(Math.floor(along * 2.5), Math.floor(d * 6)) < 0.18 ? "o," : "o.";
  }
  const cx = Math.floor(x * 2), cz = Math.floor(z * 2), h = hash(cx, cz);
  if (h < 0.025 && Math.hypot(x * 2 - cx - 0.5, z * 2 - cz - 0.5) < 0.18) return ["r*", "b*", "s*"][Math.floor(h * 120)];
  if (h >= 0.025 && h < 0.13) {
    const dx = x * 2 - cx - 0.3 - h * 3, dz = z * 2 - cz - 0.3 - hash(cz, cx) * 0.4;
    if (dx * dx * 1.6 + dz * dz < 0.025 + h * 0.2) return h < 0.08 ? "t_" : "G'";
  }
  // Grass in three greens mixed blade by blade; shadeSolid draws it as blades swaying in the wind.
  const v = hash(Math.floor(x * 5), Math.floor(z * 5) + 50);
  return (v < 0.3 ? "M" : v < 0.65 ? "G" : "g") + "'";
}
// The island is one height field: a plateau at 1.2 m whose edges slope down through sand beaches into the sea
// all the way round, with a wobbly coastline, and a steep stone harbour wall only where the dock needs deep water.
const smooth = (t) => (t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t));
function landDistance(x, z) {
  const box = (cx, cz, hx, hz, r) => {
    const qx = Math.abs(x - cx) - hx + r, qz = Math.abs(z - cz) - hz + r;
    return Math.hypot(Math.max(qx, 0), Math.max(qz, 0)) + Math.min(Math.max(qx, qz), 0) - r;
  };
  return Math.min(box(-8, 31, 53, 23, 12), box(-36, -11, 16, 31, 9)) + 0.6 * Math.sin(x * 0.19 + z * 0.07) + 0.45 * Math.sin(z * 0.23 - x * 0.13);
}
function terrainY(x, z) {
  const h = 1.2 - 2.8 * smooth((landDistance(x, z) + 6) / 7.5);
  const wall = smooth((x + 8) / 1.5) * smooth((9 - x) / 1.5), wallY = 1.2 - (14 - z) * 1.6;
  return Math.max(-1.6, wall > 0 && wallY < h ? h + (wallY - h) * wall : h);
}
// Ground texture by where you are: the stone harbour wall, sand on the beaches, ground on the plateau.
function landTex(x, y, z, nx, ny) {
  if (x > -8.5 && x < 9.5 && z < 14.3 && y < 1.15) return "t:";
  return y < 1.12 ? sand(x, y, z, nx, ny) : ground(x, y, z, nx, ny);
}
const TERRAIN = { id: 4000, P: new Float64Array(0), bb: [-70, -1.6, -50, 60, 1.2, 60], mat: "g", spot: null, solid: false, tex: landTex };
// Sand: light and dotted when dry, darker and wet by the waterline, where the wash comes and goes, with a few shells.
function wetSand(x, y, z) {
  const wash = 0.12 + 0.08 * Math.sin(T * 0.9 + x * 0.3 + z * 0.2);
  if (Math.abs(y - wash) < 0.09) return "k~";
  return y < wash + 0.25 ? "n:" : null;
}
function sand(x, y, z, nx, ny) {
  if (ny < 0.5) return null;
  const wet = wetSand(x, y, z);
  if (wet) return wet;
  if (hash(Math.floor(x * 5), Math.floor(z * 5)) < 0.02) return "s*"; // a shell
  return hash(Math.floor(x * 6), Math.floor(z * 6)) < 0.15 ? "y:" : hash(Math.floor(x * 3), Math.floor(z * 3)) < 0.5 ? "y." : "y,";
}
// Rounded, weathered rocks with pebbles at their feet, and driftwood, on the sand.
const beachY = terrainY;
for (const [x, z, r] of [[-14, 10.1, 0.8], [-9, 10.8, 0.5], [-18, 10.4, 0.6], [15, 11, 0.9], [19, 10.4, 0.5], [26, 10.1, 0.7], [-23.6, -4, 0.8], [-23, -20, 0.6], [-24.4, 5, 0.5]]) {
  const y = beachY(x, z);
  blob(world, x, y + r * 0.25, z, r, r * 0.6, r * 0.85, "t", { dim: 2.2, tex: (x, y) => (hash(Math.floor(x * 6), Math.floor(y * 6)) < 0.25 ? "-" : null) });
  for (let k = 0; k < 3; k++) {
    const a = k * 2.1 + r, px = x + Math.cos(a) * (r + 0.4), pz = z + Math.sin(a) * (r + 0.3), pr = 0.08 + 0.06 * hash(k, r);
    blob(world, px, beachY(px, pz) + pr * 0.3, pz, pr, pr * 0.6, pr, "t", { solid: false });
  }
}
for (const [a, b] of [[[-11, 12.6], [-8.8, 12.2]], [[17, 12.9], [19.6, 13.3]], [[-24.7, -12], [-24.1, -9.8]]]) {
  beam(world, [a[0], beachY(...a) + 0.1, a[1]], [b[0], beachY(...b) + 0.1, b[1]], "o", {}, 0.11);
}
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
const officeFrontWindows = [[-8.2, -6.6], [-3.4, -1.8]];
const officeSideWindows = [[22.5, 24], [25, 26.5]];
function officeWindow(u, y, spans) {
  if (y < 2.28 || y > 3.72) return null;
  for (const [a, b] of spans) {
    if (u < a - 0.12 || u > b + 0.12) continue;
    // The frame and crossbars stay dark; only the four inset panes emit light.
    if (u < a || u > b || y < 2.4 || y > 3.6 || Math.abs(u - (a + b) / 2) < 0.055 || Math.abs(y - 3) < 0.055) return "o";
    return "l";
  }
  return null;
}
function officeWall(x, y, z, nx, ny, nz) {
  if (ny > 0.5) return null;
  const front = nz < -0.5, u = Math.abs(nz) > 0.5 ? x : z;
  if (front && officeText(x, y)) return "r";
  if (front && x > -5.6 && x < -4.4 && y < 3.6) {
    if (Math.hypot(x + 4.6, y - 2.35) < 0.07) return "t";
    return Math.abs(x + 5) > 0.46 || Math.abs(y - 2.35) < 0.08 || y < 1.55 || y > 3.35 ? "o" : "o:";
  }
  const window = officeWindow(u, y, Math.abs(nz) > 0.5 ? officeFrontWindows : officeSideWindows);
  if (window) return window;
  return (y - 1.2) % 0.32 < 0.025 ? "-" : null;
}
box(world, -9, 1.2, 21, -1, 5.4, 28, "s", { spot: "office", tex: officeWall });
solid(world, [[0, -1, 0, 0, 5.4, 0], [0, 0, 1, 0, 0, 28.4], [0, 0, -1, 0, 0, 20.6],
  [-2, 4.4, 0, -9.4, 5.4, 0], [2, 4.4, 0, -0.6, 5.4, 0]], [-9.4, 5.4, 20.6, -0.6, 7.4, 28.4], "r", { spot: "office",
  tex: (x, y, z, nx, ny, nz) => {
    if (Math.abs(nz) > 0.5) return (y - 5.4) % 0.25 < 0.035 ? "o:" : "o";
    const row = Math.floor((y - 5.4) / 0.22);
    return (y - 5.4) % 0.22 < 0.035 || (z + 99 + (row % 2) * 0.25) % 0.5 < 0.035 ? "-" : null;
  } });
// Raised details do not change the walking bounds, map footprint or feature anchor.
const officeDetail = { spot: "office", anchor: false, solid: false, thin: true };
for (const x of [-9, -1]) {
  for (const z of [21, 28]) beam(world, [x, 1.25, z], [x, 5.4, z], "o", officeDetail, 0.12);
  for (const y of [1.4, 3.95, 5.3]) beam(world, [x, y, 21], [x, y, 28], "o", officeDetail, 0.09);
  beam(world, [x < -5 ? -9.4 : -0.6, 5.4, 20.6], [x < -5 ? -9.4 : -0.6, 5.4, 28.4], "s", officeDetail, 0.1);
  for (const [a, b] of officeSideWindows) box(world, x - 0.2, 2.23, a - 0.18, x + 0.2, 2.4, b + 0.18, "o", officeDetail);
}
for (const z of [21, 28]) {
  for (const y of [1.4, 3.95, 5.3]) beam(world, [-9, y, z], [-1, y, z], "o", officeDetail, 0.09);
  for (const [a, b] of officeFrontWindows) box(world, a - 0.18, 2.23, z - 0.2, b + 0.18, 2.4, z + 0.2, "o", officeDetail);
}
for (const z of [20.6, 28.4]) {
  beam(world, [-9.4, 5.4, z], [-5, 7.4, z], "s", officeDetail, 0.1);
  beam(world, [-5, 7.4, z], [-0.6, 5.4, z], "s", officeDetail, 0.1);
}
beam(world, [-5, 7.4, 20.6], [-5, 7.4, 28.4], "o", officeDetail, 0.1);
for (const x of [-5.72, -4.28]) beam(world, [x, 1.4, 20.92], [x, 3.72, 20.92], "o", officeDetail, 0.1);
beam(world, [-5.82, 3.72, 20.92], [-4.18, 3.72, 20.92], "o", officeDetail, 0.1);
box(world, -5.85, 1.2, 20.55, -4.15, 1.4, 21.05, "t", officeDetail);
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
// Palms: curved-looking trunks (two leaning segments) with drooping fronds, on the quay and along the beaches.
for (const [x, z, y0] of [[21, 24, 1.2], [-16, 23.5, 1.2], [-30, 2, 1], [-20, 12.6, beachY(-20, 12.6)], [23, 12.4, beachY(23, 12.4)], [-24, -14, beachY(-24, -14)]]) {
  const lean = 0.6 * hash(x, z) - 0.3, tx = x + lean * 1.4, top = y0 + 6;
  const rings = (px, py) => (py * 4 + 99) % 1 < 0.18 ? "-" : "o.";
  beam(world, [x, y0, z], [x + lean * 0.5, y0 + 3.2, z], "o", { tex: rings }, 0.2);
  beam(world, [x + lean * 0.5, y0 + 3.2, z], [tx, top, z + 0.2], "o", { tex: rings }, 0.15);
  for (let a = 0; a < 7; a++) {
    const c = Math.cos(a * 0.9), s = Math.sin(a * 0.9);
    beam(world, [tx, top, z + 0.2], [tx + 1.5 * c, top + 0.5, z + 0.2 + 1.5 * s], "g");
    beam(world, [tx + 1.5 * c, top + 0.5, z + 0.2 + 1.5 * s], [tx + 2.8 * c, top - 0.7, z + 0.2 + 2.8 * s], "G");
  }
}
for (const x of [-4, 12]) {
  box(world, x, 1.2, 14.4, x + 0.16, 4.2, 14.56, "t");
  box(world, x - 0.16, 4.2, 14.26, x + 0.32, 4.65, 14.7, "l");
}
// A mailbox by the office and a notice board on the quay that leads to how this page is built.
box(world, -0.55, 1.2, 21.4, -0.45, 2.2, 21.5, "t", { spot: "mailbox" });
box(world, -0.8, 2.2, 21.2, -0.2, 2.7, 21.7, "r", { spot: "mailbox" });

// Plaza fountain: an octagonal stone basin, a raised rim, and four falling streams.
// Water changes texture with the existing clock; reduced motion freezes that clock.
function fountainWater(x, y, z) {
  if (y > 1.75) return Math.sin(y * 14 - T * 5) > 0.7 ? "m:" : "w|";
  const ripple = Math.sin(Math.hypot(x - 5, z - 24.6) * 16 - T * 3);
  return ripple > 0.65 ? "m~" : "w.";
}
function fountain() {
  const basin = column(world, 5, 24.6, 1.5, 1.5, 1.2, 1.64, "s",
    { tex: (x, y, z, nx, ny) => ny < 0.5 && y < 1.38 ? "-" : null });
  column(world, 5, 24.6, 1.29, 1.29, 1.64, 1.7, "w",
    { solid: false, dim: 2.4, tex: fountainWater });
  for (let i = 0; i < 8; i++) {
    const a = i * Math.PI / 4, b = (i + 1) * Math.PI / 4;
    const end = (angle, y) => [5 + 1.42 * Math.cos(angle), y, 24.6 + 1.42 * Math.sin(angle)];
    beam(world, end(a, 1.73), end(b, 1.73), "s", {}, 0.17);
    beam(world, end(a, 1.94), end(b, 1.94), "t", {}, 0.09);
  }
  column(world, 5, 24.6, 0.4, 0.24, 1.7, 2.55, "s",
    { tex: (x, y) => Math.abs(y - 1.95) < 0.06 || Math.abs(y - 2.4) < 0.04 ? "-" : null });
  column(world, 5, 24.6, 0.24, 0.5, 2.55, 2.75, "t");
  column(world, 5, 24.6, 0.065, 0.04, 2.75, 3.35, "m", { solid: false, dim: 2.4, tex: fountainWater });
  for (let i = 0; i < 4; i++) {
    const a = i * Math.PI / 2, c = Math.cos(a), s = Math.sin(a);
    const crest = [5 + c * 0.48, 3.1, 24.6 + s * 0.48];
    beam(world, [5, 3.35, 24.6], crest, "m", { dim: 2.4, tex: fountainWater }, 0.04);
    beam(world, crest, [5 + c * 0.95, 1.73, 24.6 + s * 0.95], "m",
      { dim: 2.4, tex: fountainWater }, 0.04);
  }
  return basin;
}
const fountainBasin = fountain();
// Landscaping: hedges round the plaza, round trees, lamps along the avenue, a fence on the quay front.
const plazaHedges = [];
for (const [x0, x1, z0, z1] of [[1, 2.2, 22, 27.4], [7.8, 9, 22, 27.4], [2.2, 3.4, 27.6, 28.4], [6.6, 7.8, 27.6, 28.4]]) {
  const hedge = box(world, x0, 1.2, z0, x1, 1.9, z1, "g", { tex: (x, y, z) => (hash(Math.floor(x * 3), Math.floor(z * 3 + y * 3)) < 0.3 ? "-" : null) });
  plazaHedges.push(hedge);
}
// Broadleaf trees: a barked trunk, three branches and a layered canopy of leafy ellipsoids that sway.
const canopies = [];
const leaves = (x, y, z) => { const h = hash(Math.floor(x * 4), Math.floor(y * 4 + z * 4)); return h < 0.3 ? "-" : h > 0.88 ? "G" : null; };
for (const [x, z, h] of [[-10, 23, 6.5], [0, 25, 5.5], [11, 24, 6], [17, 27, 7], [-22, 24, 6.2]]) {
  const width = h / 6 * (0.85 + hash(x, z) * 0.3), angle = hash(z, x) * 6.28, c = Math.cos(angle), sn = Math.sin(angle);
  const bark = (px, py, pz) => Math.sin(Math.atan2(pz - z, px - x) * 13 + Math.sin(py * 2) * 0.6) > 0.25 ? "-" : "o,";
  column(world, x, z, 0.3 * width, 0.17 * width, 1.2, 1.2 + h * 0.72, "o", { tex: bark });
  for (let a = 0; a < 3; a++) beam(world, [x, 1.2 + h * 0.45, z], [x + 1.3 * width * Math.cos(a * 2.1 + angle), 1.2 + h * 0.72, z + 1.3 * width * Math.sin(a * 2.1 + angle)], "o", { tex: bark }, 0.07);
  for (const [ox, oy, oz, r] of [[0, 0.85, 0, 1.7], [1, 0.72, 0.4, 1.1], [-0.8, 0.75, 0.7, 1.15], [0.2, 0.74, -1, 1.05], [0, 1.02, 0.1, 1]]) {
    const cx = x + (ox * c - oz * sn) * width, cz = z + (ox * sn + oz * c) * width, radius = r * width;
    const s = blob(world, cx, 1.2 + h * oy, cz, radius, radius * (0.6 + hash(x, oy) * 0.25), radius * (0.8 + hash(z, oy) * 0.35), oy < 0.8 ? "M" : oy > 1 ? "G" : "g", { dim: oy < 0.8 ? 0.8 : 1.25, tex: leaves });
    s.bb[0] -= 0.25; s.bb[3] += 0.25; s.bb[2] -= 0.25; s.bb[5] += 0.25;
    canopies.push({ s, x: cx, z: cz, phase: hash(x, oz) * 6 });
  }
}
// Canopies sway in the wind, higher leaves more.
function swayTrees() {
  for (const { s, x, z, phase } of canopies) {
    s.blob[0] = x + 0.18 * Math.sin(T * 1.1 + phase);
    s.blob[2] = z + 0.12 * Math.sin(T * 0.9 + phase * 1.7);
  }
}
for (const x of [-20, -10, 0, 10, 18]) {
  box(world, x, 1.2, 20.9, x + 0.14, 4, 21.04, "t");
  box(world, x - 0.14, 4, 20.76, x + 0.28, 4.4, 21.18, "l");
}
for (let x = -25; x < -6; x += 2.5) box(world, x, 1.2, 15.6, x + 0.12, 2.1, 15.72, "o");
box(world, -25, 1.75, 15.62, -6.3, 1.85, 15.7, "o");
box(world, -25, 1.45, 15.62, -6.3, 1.53, 15.7, "o");
const howText = painted("HOW", 7.4, 8.7, 2.45, 3.25);
for (const x of [7.35, 8.6]) box(world, x, 1.2, 16.72, x + 0.15, 2.4, 16.85, "o", { spot: "how" });
box(world, 7.2, 2.35, 16.6, 8.9, 3.35, 16.72, "o", { spot: "how", tex: (x, y, z, nx, ny, nz) => (nz < -0.5 ? (howText(x, y) ? "l" : "-") : null) });
const docsText = painted("DOCS", -1.9, 0.3, 2.45, 3.25);
for (const x of [-1.95, 0.25]) box(world, x, 1.2, 16.72, x + 0.15, 2.4, 16.85, "o", { spot: "docsboard" });
box(world, -2.1, 2.35, 16.6, 0.5, 3.35, 16.72, "o", { spot: "docsboard", tex: (x, y, z, nx, ny, nz) => (nz < -0.5 ? (docsText(x, y) ? "l" : "-") : null) });

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
// Walkable areas [x0, x1, z0, z1, height at x]: deck, gangway and dock; elsewhere the island above the waterline.
const FLOORS = [
  [-3.45, 0.45, -11.55, 6.6, deckAt],
  [0.45, 3.1, -1.8, -0.6, (x) => deckAt(0.7) + (1.2 - deckAt(0.7)) * Math.min(1, Math.max(0, (x - 0.7) / 2.4))],
  [3, 7, -16, 14, () => 1.2],
];
function floorAt(x, z) {
  const f = FLOORS.find(([x0, x1, z0, z1]) => x >= x0 && x < x1 && z >= z0 && z < z1);
  if (f) return f[4](x, z);
  const y = terrainY(x, z);
  return y > 0.1 ? y : null;
}
const walkBound = (b, k) => b[k] + (k < 3 ? -0.25 : 0.25);
const walkingSolid = (s, fy, lift = 0) => s.solid && s.bb[1] + lift < fy + 1.7 && s.bb[4] + lift > fy + 0.3;
function blocked(x, z, fy) {
  for (const list of [world, ship]) {
    const lift = list === ship ? bob : 0;
    for (const s of list) {
      const b = s.bb;
      if (walkingSolid(s, fy, lift) && x > walkBound(b, 0) && x < walkBound(b, 3) &&
        z > walkBound(b, 2) && z < walkBound(b, 5)) return true;
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
const hit = (s, ox, oy, oz, dx, dy, dz) => (s.blob ? blobEntry(s.blob, ox, oy, oz, dx, dy, dz) : s.cone ? coneEntry(s.cone, ox, oy, oz, dx, dy, dz) : entry(s.P, ox, oy, oz, dx, dy, dz));
// Ray against an ellipsoid: solve in the space where it is a unit sphere. Sets entryK -4 and entryN.
function blobEntry(e, ox, oy, oz, dx, dy, dz) {
  const qx = (ox - e[0]) / e[3], qy = (oy - e[1]) / e[4], qz = (oz - e[2]) / e[5], vx = dx / e[3], vy = dy / e[4], vz = dz / e[5];
  const A = vx * vx + vy * vy + vz * vz, B = 2 * (qx * vx + qy * vy + qz * vz), C = qx * qx + qy * qy + qz * qz - 1, disc = B * B - 4 * A * C;
  if (disc < 0) return Infinity;
  const sq = Math.sqrt(disc), t = (-B - sq) / (2 * A) > 1e-3 ? (-B - sq) / (2 * A) : (-B + sq) / (2 * A);
  if (t <= 1e-3) return Infinity;
  const nx = (qx + t * vx) / e[3], ny = (qy + t * vy) / e[4], nz = (qz + t * vz) / e[5], l = Math.sqrt(nx * nx + ny * ny + nz * nz);
  entryK = -4; entryN[0] = nx / l; entryN[1] = ny / l; entryN[2] = nz / l;
  return t;
}
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
  lamp(-7.4, 3, 20.8, 0.22, 2.3), lamp(-2.6, 3, 20.8, 0.22, 2.3), lamp(-0.8, 3, 23.2, 0.22, 2.3), lamp(-0.8, 3, 25.7, 0.22, 2.3),
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

// Density ramp of shading glyphs, from empty to solid; letters stay for labels and signs only.
const RAMP = " .`',:;~-=+*#%@▒▓█";
const RANGE = { lighthouse: 400, nest: 30, office: 40, antenna: 50, containers: 40, lifeboat: 25, tender: 25 };
const MOON = (() => { const v = [0.2, 0.3, 0.93], l = Math.hypot(...v); return v.map((c) => c / l); })();
// Objects whose feature is not in the page's list are scenery.
for (const s of [...world, ...ship]) if (s.spot && !spots[s.spot]) s.spot = null;
const anchors = {};
for (const [list, lift] of [[world, 0], [ship, 1]]) {
  for (const s of list) {
    if (!s.spot || s.anchor === false) continue;
    const b = s.bb, a = (anchors[s.spot] ||= { x: 0, y: 0, z: 0, n: 0, r: 0, ship: lift });
    a.x += (b[0] + b[3]) / 2; a.y += (b[1] + b[4]) / 2; a.z += (b[2] + b[5]) / 2; a.n++;
    a.r = Math.max(a.r, (b[3] - b[0]) / 2, (b[5] - b[2]) / 2, (b[4] - b[1]) / 3);
  }
}
for (const a of Object.values(anchors)) { a.x /= a.n; a.y /= a.n; a.z /= a.n; }

let cols = 0, rows = 0, cellW = 8, cellH = 13, scale = 1, target = null, padX = 0, padY = 0;
const MONO = getComputedStyle(document.documentElement).getPropertyValue("--mono");
const BASE = { "": "#5c6a88", k: "#e9eefb", w: "#3f78b8", d: "#22406a", m: "#a9c8f0", o: "#dba66b", s: "#efe6cf",
  t: "#a3adc2", l: "#ffd479", r: "#e0705f", b: "#62a8e0", f: "#3a4562", h: "#7ee0c3", g: "#6fbf73", y: "#e3d3a3", n: "#9b8a62",
  G: "#a5d36e", M: "#4f8a4a" };
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
  // Phones and tablets draw at most 2 device pixels per CSS pixel: a 3x canvas costs more memory than it shows.
  const dpr = touchFirst.matches ? Math.min(2, devicePixelRatio || 1) : devicePixelRatio || 1, w = stage.clientWidth, h = stage.clientHeight;
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
    if (c >= 0 && ID[c] === 0) { G[c] = "^"; C[c] = "k"; }
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
const ORDER = Object.keys(spots).filter((id) => anchors[id]);
if (ORDER.length < Object.keys(spots).length) console.warn("harbor: no scene object for", Object.keys(spots).filter((id) => !anchors[id]).join(", "));
const WORLD = { x0: -62, x1: 48, z0: -44, z1: 56 };
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
// The island seen from above: plateau with roads and grass, beach and shallow-water bands, deep sea.
function mapTerrain() {
  for (let j = 0; j < mapBox.ih; j++) {
    for (let i = 0; i < mapBox.iw; i++) {
      const [x, z] = fromMap(i + 0.5, j + 0.5), y = terrainY(x, z);
      let cell = [(i + j) % 6 ? " " : "~", "d"];
      if (y > 1.12) cell = roadAt(x, z)[0] < 1.4 || Math.hypot(x - 5, z - 24.6) < 3.2 ? ["+", "s"] : [",", "g"];
      else if (y > 0) cell = [".", "y"];
      else if (y > -1.2) cell = ["~", "w"];
      mapPut(i + 1, j + 1, ...cell);
    }
  }
}
// Every landmark at its true footprint: buildings and boxes, round things, canopies, rocks, the dock, boats and
// the ship with its deck details; then the points of interest, their names on the big map, and you.
function mapMarks() {
  for (const s of world) footprint(s, s.mat === "l" ? "l" : s.mat);
  for (const s of ship) footprint(s, s.mat === "l" ? "l" : "o");
  const f = toMap(5, 24.6);
  if (mapInside(f)) mapPut(f[0] + 1, f[1] + 1, "O", "w");
  ORDER.forEach(mapPoint);
  if (mapMode === 2) mapLabels();
  const p = toMap(me.x, me.z);
  if (mapInside(p)) mapPut(p[0] + 1, p[1] + 1, "^>v<"[Math.round(((me.yaw % 6.283) + 6.283) / 1.5708) % 4], "k");
}
const mapInside = ([i, j]) => i >= 0 && i < mapBox.iw && j >= 0 && j < mapBox.ih;
function footprint(s, cls) {
  const b = s.bb;
  if (s.thin || s === gangway || b[3] - b[0] > 40 || b[4] < 0.5) return;
  const [i0, j0] = toMap(b[0], b[5]), [i1, j1] = toMap(b[3], b[2]);
  const ch = s.blob ? (s.mat === "t" ? "@" : "%") : s.cone ? "@" : s.mat === "o" ? "=" : "#";
  for (let j = Math.max(0, j0); j <= Math.min(mapBox.ih - 1, j1); j++) {
    for (let i = Math.max(0, i0); i <= Math.min(mapBox.iw - 1, i1); i++) mapPut(i + 1, j + 1, ch, cls);
  }
}
function mapPoint(id, n) {
  const p = toMap(anchors[id].x, anchors[id].z), picked = mapMode && n === pick;
  if (mapInside(p)) mapPut(p[0] + 1, p[1] + 1, picked ? "@" : "*", picked ? "h" : "l");
}
// Names on the big map, right of their point, else left of it, else left out where the ship crowds them.
function mapLabels() {
  const taken = new Set(ORDER.map((id) => toMap(anchors[id].x, anchors[id].z).join()));
  const f = toMap(5, 24.6);
  taken.add(f.join());
  ORDER.forEach((id, n) => {
    const p = toMap(anchors[id].x, anchors[id].z), text = spots[id].title.slice(0, 16);
    const free = (i0) => i0 >= 0 && i0 + text.length < mapBox.iw && [...text].every((_, k) => !taken.has(`${i0 + k},${p[1]}`));
    const places = [p[0] + 2, p[0] - 1 - text.length];
    if (p[1] === f[1]) {
      if (places[0] <= f[0] && f[0] < places[0] + text.length) places[0] = f[0] + 1;
      if (places[1] <= f[0] && f[0] < places[1] + text.length) places[1] = f[0] - text.length;
    }
    const i0 = places.find(free);
    if (!mapInside(p) || i0 === undefined) return;
    [...text].forEach((ch, k) => { taken.add(`${i0 + k},${p[1]}`); mapPut(i0 + k + 1, p[1] + 1, ch, mapMode && n === pick ? "h" : "k"); });
  });
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
  walkPath = []; walkTo = null;
  if (reduced.matches) { me.x = stand[0]; me.z = stand[1]; me.eye = floorAt(...stand) + 1.6; face(id); return; }
  const path = route(nearestNode(me.x, me.z), nearestNode(...stand));
  if (!path.length) return;
  const points = [[me.x, me.z], ...path, stand], steps = [];
  for (let i = 1; i < points.length; i++) {
    const leg = approach(points[i - 1], points[i]);
    if (!leg.length) return;
    steps.push(...leg);
  }
  walkPath = steps;
  walkTo = id;
}
function face(id) {
  const a = anchors[id];
  me.yaw = Math.atan2(a.x - me.x, a.z - me.z);
  me.pitch = Math.max(-1.1, Math.min(1.1, Math.atan2(a.y + (a.ship ? bob : 0) - me.eye, Math.hypot(a.x - me.x, a.z - me.z))));
  jumped = id;
}
const nearestNode = (x, z) => NODES.reduce((b, n, i) => (Math.hypot(n[0] - x, n[1] - z) < Math.hypot(NODES[b][0] - x, NODES[b][1] - z) ? i : b), 0);
// Exact slab test against the same open walking bounds used by blocked().
function segmentBlocked(a, c, b) {
  let enter = 0, exit = 1;
  for (const k of [0, 2]) {
    const p = a[k / 2], d = c[k / 2] - p, low = walkBound(b, k), high = walkBound(b, k + 3);
    if (d === 0) {
      if (p <= low || p >= high) return false;
    } else {
      const t0 = (low - p) / d, t1 = (high - p) / d;
      enter = Math.max(enter, Math.min(t0, t1));
      exit = Math.min(exit, Math.max(t0, t1));
      if (enter >= exit) return false;
    }
  }
  return enter < exit;
}
function walkable([x, z]) {
  const fy = floorAt(x, z);
  return fy !== null && !blocked(x, z, fy);
}
function routeObstacles() {
  const obstacles = [];
  for (const list of [world, ship]) {
    for (const s of list) {
      const b = s.bb, fy = floorAt((b[0] + b[3]) / 2, (b[2] + b[5]) / 2);
      if (fy !== null && walkingSolid(s, fy, list === ship ? bob : 0)) obstacles.push(s);
    }
  }
  return obstacles;
}
function detourCorners(b) {
  const x0 = walkBound(b, 0), x1 = walkBound(b, 3), z0 = walkBound(b, 2), z1 = walkBound(b, 5);
  return [[x0, z0], [x1, z0], [x1, z1], [x0, z1]].filter(walkable);
}
function clear(a, c, obstacles) {
  if (!walkable(a) || !walkable(c) || obstacles.some(s => segmentBlocked(a, c, s.bb))) return false;
  const steps = Math.max(1, Math.ceil(Math.hypot(c[0] - a[0], c[1] - a[1]) / 0.1));
  for (let i = 0; i <= steps; i++) {
    if (floorAt(a[0] + (c[0] - a[0]) * i / steps, a[1] + (c[1] - a[1]) * i / steps) === null) return false;
  }
  return true;
}
function clearLinks(nodes, obstacles) {
  const links = [];
  for (let a = 0; a < nodes.length; a++) {
    for (let c = a + 1; c < nodes.length; c++) if (clear(nodes[a], nodes[c], obstacles)) links.push([a, c]);
  }
  return links;
}
let approachGraph;
function rebuildRoutes() {
  const obstacles = routeObstacles(), nodes = NODES.filter(walkable);
  for (const { bb } of obstacles) nodes.push(...detourCorners(bb));
  approachGraph = { obstacles, nodes, edges: routeEdges(nodes, clearLinks(nodes, obstacles)),
    worldCount: world.length, shipCount: ship.length };
  return approachGraph;
}
function detourGraph() {
  if (!approachGraph || approachGraph.worldCount !== world.length || approachGraph.shipCount !== ship.length) return rebuildRoutes();
  return approachGraph;
}
function nearestClear(point, nodes, obstacles) {
  const order = nodes.map((n, i) => [i, Math.hypot(point[0] - n[0], point[1] - n[1])]);
  order.sort((a, b) => a[1] - b[1]);
  for (const [i] of order) if (clear(point, nodes[i], obstacles)) return i;
  return -1;
}
function approach(from, to) {
  const { obstacles, nodes, edges } = detourGraph();
  if (clear(from, to, obstacles)) return [to];
  const a = nearestClear(from, nodes, obstacles), b = nearestClear(to, nodes, obstacles);
  if (a < 0 || b < 0) return [];
  const path = route(a, b, nodes, edges);
  return path.length ? [...path, to] : [];
}
function routeEdges(nodes, links) {
  const edges = nodes.map(() => []);
  for (const [a, b] of links) {
    const d = Math.hypot(nodes[b][0] - nodes[a][0], nodes[b][1] - nodes[a][1]);
    edges[a].push([b, d]); edges[b].push([a, d]);
  }
  return edges;
}
// Shortest route between two nodes (Dijkstra over the clear-link graph).
function route(from, to, nodes = NODES, edges = routeEdges(nodes, LINKS)) {
  const dist = nodes.map(() => Infinity), prev = [], todo = new Set(nodes.keys());
  dist[from] = 0;
  while (todo.size) {
    const u = [...todo].reduce((a, b) => (dist[a] < dist[b] ? a : b));
    todo.delete(u);
    if (u === to || dist[u] === Infinity) break;
    for (const [v, length] of edges[u]) {
      const d = dist[u] + length;
      if (todo.has(v) && d < dist[v]) { dist[v] = d; prev[v] = u; }
    }
  }
  if (dist[to] === Infinity) return [];
  const path = [];
  for (let v = to; v !== undefined; v = prev[v]) path.unshift(nodes[v]);
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
  const tw = surfaceHit(dx, dy, dz, hitT);
  SP[c] = null;
  if (hitS && hitT < tw) shadeSolid(c, odd, hitS !== wS, dx, dy, dz, ldx, ldy);
  else if (tw < Infinity && onLand) shadeLand(c, odd, tw, dx, dy, dz);
  else if (tw < Infinity) shadeWater(c, tw, dx, dy, dz);
  else shadeSky(c, dx, dy, dz);
}
// The island under a ray: its normal from the slope of the height field, then shaded like any solid.
function shadeLand(c, odd, t, dx, dy, dz) {
  const x = cam.x + dx * t, z = cam.z + dz * t, e = 0.15;
  const hx = (terrainY(x + e, z) - terrainY(x - e, z)) / (2 * e), hz = (terrainY(x, z + e) - terrainY(x, z - e)) / (2 * e), l = Math.sqrt(hx * hx + 1 + hz * hz);
  hitS = TERRAIN; hitK = -5; hitT = t; hitN[0] = -hx / l; hitN[1] = 1 / l; hitN[2] = -hz / l;
  shadeSolid(c, odd, false, dx, dy, dz, dx, dy);
}
// Brightness changes the ground textures ask for: kerbs and flowers brighter, joints, ruts and wet sand darker.
const GRAIN = { _: 1.35, "=": 1.3, "*": 1.5, "~": 1.25, "+": 1.1, "-": 1.1, ".": 1, ",": 0.85, ":": 0.7, ";": 0.8, '"': 0.9, "'": 0.95, "`": 0.9, " ": 1 };
const paleGroundMark = (tex) => tex === "s|" || tex === "s-" || tex === "s=" || tex === "k~";
function textureColor(s, tex, b, fog, warm) {
  if (s.tex === fountainWater) return tex[0] + tier(Math.max(0.34, b), 0);
  if (s === TERRAIN && paleGroundMark(tex)) {
    return tex[0] + tier(Math.max(b, (tex === "k~" ? 0.5 : 0.35) * fog), warm);
  }
  return null;
}
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
    ch = flash ? "@" : "*"; cls = "l7";
  } else {
    const wx = onShip ? SX + rc * (px - SX) - rs * py : px, wy = onShip ? rs * (px - SX) + rc * py + bob : py;
    const [lit, warm] = lightAt(wx, wy, pz, nx, ny, nz);
    // Contact shadow: walls darken toward the ground they stand on.
    const ao = ny > 0.7 ? 1 : Math.min(1, 0.55 + 0.5 * (wy - (onShip ? bob + DECK : floorAt(wx, pz) ?? 0)));
    const fog = Math.exp(-t * 0.016), b = (lit * dim * ao * (0.8 + 0.2 * Math.max(0, -(nx * dx + ny * dy + nz * dz)))) * fog + 0.02 * (1 - fog);
    cls = mat + tier(b, warm);
    // Grass blades lean with the wind; fountain water keeps its texture glyphs below.
    const grass = ny > 0.7 && (mat === "g" || mat === "G" || mat === "M") && s === TERRAIN;
    ch = grass && b > 0.03 ? blade(px, pz, odd) : glyph(b, odd);
    const texture = textureColor(s, tex, b, fog, warm);
    if (texture) {
      ch = tex[1];
      cls = texture;
    }
  }
  // Floors get a negative id: they outline what stands on them but draw no edges themselves.
  put(c, ch, cls, (ny > 0.7 ? -1 : 1) * (s.id * 16 + (k >= 0 ? k >> 2 : 12 - k)), t);
  SP[c] = s.spot;
}
// Glyph for a brightness from the long ramp; the darkest cells thin out to a dither.
const glyph = (b, odd) => (b < 0.035 ? (odd ? " " : b > 0.02 ? "." : " ") : RAMP[Math.min(RAMP.length - 1, 1 + Math.floor(b * (RAMP.length - 2)))]);
// A grass blade: short tufts and taller blades that lean left or right as gusts roll across the island.
function blade(x, z, odd) {
  const h = hash(Math.floor(x * 5), Math.floor(z * 5)), gust = Math.sin(T * 1.7 + x * 0.35 + z * 0.22) + 0.5 * Math.sin(T * 3.1 + x * 1.3);
  if (h < 0.18) return odd ? " " : ",";
  if (h < 0.55) return gust > 0.6 ? "/" : gust < -0.6 ? "\\" : "|";
  return h < 0.75 ? "'" : h < 0.9 ? '"' : ";";
}
// Colour level (0 to 7) for a brightness, warmed when lamplight dominates.
const tier = (b, warm) => (warm > 0.55 && b > 0.2 ? "w" : "") + Math.min(7, Math.floor(b * 9));
// How close water at (x, z) is to the shore, from 0 (deep, the bed 1.6 m down) to 1 (the waterline).
function shallows(x, z) {
  return Math.min(1, Math.max(0, (terrainY(x, z) + 1.6) / 1.6));
}

// ---- The sea: a height field of summed travelling waves (amplitude, direction, wave number, speed, phase),
// ray marched per cell, with analytic normals for Fresnel reflection, moon and lamp highlights, and foam.
const WAVES = new Float64Array([0.17, 0.8, 0.6, 0.7, 2.6, 0, 0.11, -0.3, 0.95, 1.14, 3.3, 1.7, 0.07, 0.95, -0.3, 1.96, 4.4, 4.1, 0.035, 0.2, 0.98, 3.5, 5.8, 2.3]);
const SEA = 0.17 + 0.11 + 0.07 + 0.035;
const seaN = [0, 1, 0];
function seaHeight(x, z) {
  let h = 0;
  for (let i = 0; i < 24; i += 6) h += WAVES[i] * Math.sin(WAVES[i + 3] * (WAVES[i + 1] * x + WAVES[i + 2] * z) - WAVES[i + 4] * T + WAVES[i + 5]);
  return h;
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
// Distance along the ray to the island or the sea, whichever it meets first (onLand says which), or
// Infinity if a solid at `limit` comes first. Steps grow with distance; a crossing is refined by bisection.
let onLand = false;
const surface = (x, z) => Math.max(terrainY(x, z), seaHeight(x, z));
function surfaceHit(dx, dy, dz, limit) {
  if (dy > -1e-4) return Infinity;
  let a = Math.max(0, (1.3 - cam.y) / dy);
  const end = Math.min(limit, 260);
  for (let i = 0; i < 56 && a < end; i++) {
    let b = Math.min(end, a + 0.25 + a * 0.08);
    if (cam.y + b * dy < surface(cam.x + b * dx, cam.z + b * dz)) {
      for (let k = 0; k < 5; k++) { const m = (a + b) / 2; if (cam.y + m * dy < surface(cam.x + m * dx, cam.z + m * dz)) b = m; else a = m; }
      const x = cam.x + b * dx, z = cam.z + b * dz;
      onLand = terrainY(x, z) >= seaHeight(x, z);
      return b;
    }
    a = b;
  }
  const t = -cam.y / dy; // beyond the march the sea is flat enough
  onLand = false;
  return t < limit && t >= end ? t : Infinity;
}
function waterLampSpec(x, h, z, rx, ry, rz) {
  let lampSpec = 0;
  for (const L of LIGHTS) {
    const lx = L.wx - x, ly = L.wy - h, lz = L.wz - z, d2 = lx * lx + ly * ly + lz * lz;
    if (d2 > 3600) continue;
    const d = Math.sqrt(d2), s = (rx * lx + ry * ly + rz * lz) / d;
    if (s > 0.985) lampSpec += L.i * Math.pow(s, 300) * 1.4 / (1 + d2 * 0.006);
  }
  return lampSpec;
}
// Foam on the highest crests, and a broken line where waves wash onto the beaches.
function waterFoam(x, z, h, near) {
  return Math.max(0, (h - SEA * 0.7) / (SEA * 0.3)) * 0.6 + (near > 0.82 && Math.sin(x * 1.3 + z + T * 0.9) > -0.25 ? 0.65 : 0);
}
function waterReflection(lampSpec, moonSpec) {
  if (lampSpec > moonSpec && lampSpec > 0.1) return "l";
  return moonSpec > 0.1 ? "m" : null;
}
function waterGlyph(c, t, foam, lum, fog, mat) {
  if (foam > 0.4) { put(c, "~", "k" + tier(Math.max(lum, 0.5 * fog), 0), -1, t); return; }
  const soft = Math.min(0.78, lum); // highlights stay sparkles, not solid blocks
  put(c, glyph(soft, (c ^ Math.floor(t)) & 1), mat + tier(lum, 0), -1, t);
}
function shadeWater(c, t, dx, dy, dz) {
  const x = cam.x + dx * t, z = cam.z + dz * t, h = seaHeight(x, z), near = shallows(x, z);
  seaNormal(x, z);
  const [nx, ny, nz] = seaN, dn = dx * nx + dy * ny + dz * nz, rx = dx - 2 * dn * nx, ry = dy - 2 * dn * ny, rz = dz - 2 * dn * nz;
  const fresnel = 0.04 + 0.96 * Math.pow(1 - Math.min(1, -dn), 5);
  const moonSpec = Math.pow(Math.max(0, rx * MOON[0] + ry * MOON[1] + rz * MOON[2]), 90) * 1.4;
  const lampSpec = waterLampSpec(x, h, z, rx, ry, rz), foam = waterFoam(x, z, h, near);
  const body = (0.03 + 0.12 * Math.max(0, nx * MOON[0] + ny * MOON[1] + nz * MOON[2])) * (1 + near);
  const fog = Math.exp(-t * 0.014), lum = ((body * (1 - fresnel) + 0.03 * fresnel + moonSpec + lampSpec + foam * 0.35 + beamOn(x, z) * 0.6) * fog) + 0.015 * (1 - fog);
  const mat = waterReflection(lampSpec, moonSpec) || (near > 0.2 ? "w" : "d");
  waterGlyph(c, t, foam, lum, fog, mat);
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
  if (m > 0.9988) put(c, m > 0.99935 ? "@" : "%", "k", 0, Infinity);
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
// Draws the scene as runs of one colour, then the mini map on its own backing above it.
function draw(mid) {
  ctx.fillStyle = "#060a14";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  for (let j = 0; j < rows; j++) {
    let run = "", cur = C[j * cols], from = 0;
    for (let i = 0; i < cols; i++) {
      const c = j * cols + i, aim = c === mid, hud = MAPCELLS.has(c);
      const mark = hud ? " " : aim ? "+" : LINE.get(c) || outline(c, i, j);
      const cls = hud ? "" : aim ? (target ? "h" : "k") : mark ? "h" : C[c];
      if (cls !== cur) { paint(run, cur, from, j); run = ""; cur = cls; from = i; }
      run += mark || edge(c, i, j) || G[c];
    }
    paint(run, cur, from, j);
  }
  drawMap();
}
function drawMap() {
  const b = mapBox;
  if (!b) return;
  ctx.fillStyle = "rgba(6, 10, 20, 0.94)";
  ctx.fillRect(padX + b.oi * cellW, padY + b.oj * cellH, b.w * cellW, b.h * cellH);
  for (let j = b.oj; j < b.oj + b.h; j++) {
    let run = "", cur = "", from = b.oi;
    for (let i = b.oi; i < b.oi + b.w; i++) {
      const [ch, cls] = MAPCELLS.get(j * cols + i);
      if (cls !== cur) { paint(run, cur, from, j); run = ""; cur = cls; from = i; }
      run += ch;
    }
    paint(run, cur, from, j);
  }
}
// WebKit keeps every distinct string fillText draws: on iOS Safari runs of glyphs grow the tab by
// about 10 MB a second until iOS kills it. Touch devices draw glyph by glyph, a set of strings that stays small.
function paint(run, cls, i, j) {
  if (!run.trim()) return;
  ctx.fillStyle = COLORS[cls];
  if (!touchFirst.matches) ctx.fillText(run, padX + i * cellW, padY + j * cellH);
  else for (let k = 0; k < run.length; k++) if (run[k] !== " ") ctx.fillText(run[k], padX + (i + k) * cellW, padY + j * cellH);
}

function nearby() {
  let best = null, bd = 2.2;
  for (const [id, a] of Object.entries(anchors)) {
    const d = Math.hypot(a.x - me.x, a.z - me.z);
    if (d < bd && Math.abs(a.y + (a.ship ? bob : 0) - me.eye) < 5) { bd = d; best = id; }
  }
  return best;
}

// Cards are built from DOM nodes and text, never parsed from strings.
function node(tag, content, cls) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  n.append(...(Array.isArray(content) ? content : [content]));
  return n;
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
    if (moved) { card.replaceChildren(); return; }
    card.replaceChildren(
      node("h3", document.querySelector(".top h1").textContent),
      node("p", document.querySelector(".tagline").textContent),
      node("p", hint, "hint"),
      node("p", [...document.querySelector(".top nav").cloneNode(true).childNodes], "links"));
    return;
  }
  const s = spots[id];
  const link = node("a", `Open: ${s.title} \u2192`);
  link.target = "_blank";
  link.rel = "noopener";
  link.href = s.href;
  card.replaceChildren(node("h3", s.title), s.body.cloneNode(true),
    node("p", [link, touchFirst.matches ? " \u00b7 tap to open" : " \u00b7 Enter opens it"], "hint"));
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
    swayTrees();
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
// Bob and roll change height, not walking topology. Build the corner graph before animation starts.
rebuildRoutes();
measure();
requestAnimationFrame(frame);
