// Crewship harbor: a first-person 3D scene ray cast into a grid of text, every frame.
// Plain JavaScript, no dependencies. The world is a list of convex solids (sets of planes)
// plus the water plane; the ship's solids live in a frame that bobs and rolls at the dock.
const stage = document.getElementById("stage");
const canvas = document.getElementById("scene");
const ctx = canvas.getContext("2d");
const card = document.getElementById("card");
stage.hidden = document.getElementById("help").hidden = false; // shown only when this script runs
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
// Eight-sided column around a vertical axis, optionally tapered from r0 at y0 to r1 at y1.
function column(list, cx, cz, r0, r1, y0, y1, mat, o) {
  const pl = [[0, 1, 0, 0, y1, 0], [0, -1, 0, 0, y0, 0]];
  const slope = (r0 - r1) / (y1 - y0);
  for (let i = 0; i < 8; i++) {
    const a = (i + 0.5) * Math.PI / 4, c = Math.cos(a), s = Math.sin(a);
    pl.push([c, slope, s, cx + c * r0, y0, cz + s * r0]);
  }
  const r = r0 * 1.09;
  return solid(list, pl, [cx - r, y0, cz - r, cx + r, y1, cz + r], mat, o);
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

// A 3x5 pixel font for the painted signs.
const FONT = { A: "010101111101101", B: "110101110101110", C: "011100100100011", E: "111100110100111",
  H: "101101111101101", I: "111010010010111", O: "010101101101010", P: "110101110100100",
  R: "110101110101101", S: "011100010001110", W: "101101101111101" };
// Paints `text` on the face whose outward normal is -z, inside the rectangle [u0,u1] x [v0,v1].
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
box(world, -70, -2, 14, 70, 1.2, 46, "t", { solid: false });
box(world, -46, -2, -36, -26, 1, 14, "t", { solid: false });
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
const signText = painted("CREWSHIP", 3.95, 6.65, 2.45, 3.45);
box(world, 4.1, 1.2, 12.55, 4.25, 2.5, 12.7, "o", { spot: "sign" });
box(world, 6.35, 1.2, 12.55, 6.5, 2.5, 12.7, "o", { spot: "sign" });
box(world, 3.85, 2.35, 12.5, 6.75, 3.55, 12.62, "o", { spot: "sign",
  tex: (x, y, z, nx, ny, nz) => (nz < -0.5 && signText(x, y) ? "l" : null) });
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

// Ship, in its own frame: hull, rails, cabin, helm, mast, sail, crow's nest, hatch, lantern.
const k = 1 / 3.2;
solid(ship, [[0, 1, 0, 0, DECK, 0], [0, -1, 0, 0, -1.2, 0], [0, 0, -1, 0, 0, -12],
  [1, -k, 0, 0.7, DECK, 0], [-1, -k, 0, -3.7, DECK, 0], [4, 0, 2.2, 0.7, 0, 6], [-4, 0, 2.2, -3.7, 0, 6]],
[-3.7, -1.2, -12, 0.7, DECK, 10], "o", { solid: false,
  tex: (x, y, z, nx, ny) => (ny > 0.5 ? seam(x) : y > 1.3 && y < 1.6 ? "s" : null) });
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
box(ship, -5, 5.6, -1.1, 2, 5.76, -0.9, "o", { spot: "mast" });
box(ship, -4.9, 5.8, -0.76, 1.9, 11.15, -0.66, "s", { spot: "sail", tex: (x, y) => ((y % 1.1) < 0.09 ? "-" : null) });
column(ship, SX, -1, 0.9, 0.95, 12.3, 13.2, "o", { spot: "nest", tex: (x, y) => (y < 12.5 ? "-" : null) });
box(ship, SX, 14.4, -1.03, SX + 1.2, 15.05, -0.97, "r");
box(ship, -2.7, DECK, 2.4, -0.3, 2.55, 4.8, "o", { spot: "hold",
  tex: (x, y, z, nx, ny) => (ny > 0.5 && ((x + 9) % 0.4 < 0.07 || (z + 9) % 0.4 < 0.07) ? "-" : null) });
box(ship, -3.3, DECK, 5, -2.5, 2.8, 5.8, "o", { spot: "hold" });
box(ship, SX - 0.08, DECK, 7.2, SX + 0.08, 3.3, 7.36, "o", { spot: "lantern" });
box(ship, SX - 0.22, 3.3, 7.07, SX + 0.22, 3.75, 7.5, "l", { spot: "lantern" });
box(ship, SX - 0.08, 2.2, 9.5, SX + 0.08, 2.35, 13, "o");

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
];
function floorAt(x, z) {
  const f = FLOORS.find(([x0, x1, z0, z1]) => x >= x0 && x < x1 && z >= z0 && z < z1);
  return f ? f[4](x) : null;
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

const me = { x: -0.3, z: -7.6, yaw: 0.42, pitch: 0.1 };
const keys = new Set();
const stick = { x: 0, y: 0 };
let moved = false;

// ---- Ray casting -------------------------------------------------------------------------
let hitT, hitS, hitK;
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
// Ray against one convex solid: the last plane it enters before it leaves any plane.
function enter(P, ox, oy, oz, dx, dy, dz) {
  let tn = -Infinity, tf = Infinity, kk = -1;
  for (let i = 0; i < P.length && tn <= tf; i += 4) {
    const den = P[i] * dx + P[i + 1] * dy + P[i + 2] * dz;
    const dist = P[i + 3] - (P[i] * ox + P[i + 1] * oy + P[i + 2] * oz), t = dist / den;
    if (den < 0) { if (t > tn) { tn = t; kk = i; } } else if (den > 0) tf = Math.min(tf, t);
    else if (dist < 0) tf = -Infinity; // parallel to the plane and outside it
  }
  if (tn <= tf && tn > 1e-3 && tn < hitT) { hitT = tn; hitK = kk; return true; }
  return false;
}
function trace(list, ox, oy, oz, dx, dy, dz) {
  const ix = 1 / dx, iy = 1 / dy, iz = 1 / dz;
  for (const s of list) {
    if (boxEntry(s.bb, ox, oy, oz, ix, iy, iz) <= hitT && enter(s.P, ox, oy, oz, dx, dy, dz)) hitS = s;
  }
}

const RAMP = " .:-=+*#%@";
const RANGE = { lighthouse: 400, nest: 30, office: 40, antenna: 50, containers: 40, sail: 20 };
const L = [-0.35, 0.8, -0.48];
const MOON = (() => { const v = [0.2, 0.3, 0.93], l = Math.hypot(...v); return v.map((c) => c / l); })();
const anchors = {};
for (const [list, lift] of [[world, 0], [ship, 1]]) {
  for (const s of list) {
    if (!s.spot) continue;
    const b = s.bb, a = (anchors[s.spot] ||= { x: 0, y: 0, z: 0, n: 0, ship: lift });
    a.x += (b[0] + b[3]) / 2; a.y += (b[1] + b[4]) / 2; a.z += (b[2] + b[5]) / 2; a.n++;
  }
}
for (const a of Object.values(anchors)) { a.x /= a.n; a.y /= a.n; a.z /= a.n; }

let cols = 0, rows = 0, cellW = 8, cellH = 13, scale = 1, target = null, padX = 0, padY = 0;
const MONO = getComputedStyle(document.documentElement).getPropertyValue("--mono");
const COLORS = { "": "#5c6a88", k: "#e9eefb", w: "#3f78b8", m: "#a9c8f0", o: "#b98a58", s: "#e9dfc4",
  t: "#8b95aa", l: "#ffd479", r: "#d9675a", b: "#5aa0d9", f: "#3a4562", h: "#7ee0c3" };
function measure() {
  const dpr = devicePixelRatio || 1, w = stage.clientWidth, h = stage.clientHeight;
  canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
  const px = Math.max(8, Math.min(14, innerWidth * 0.0095)) * scale;
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
  cam.x = me.x; cam.y = me.eye; cam.z = me.z;
  // Camera origin in the ship frame (rotate by -roll about the ship's long axis, after the bob).
  cam.lx = rc * (me.x - SX) + rs * (me.eye - bob) + SX; cam.ly = -rs * (me.x - SX) + rc * (me.eye - bob);
  for (let j = 0, c = 0; j < rows; j++) {
    const v = (1 - (2 * j + 1) / rows) * tanV;
    for (let i = 0; i < cols; i++, c++) {
      const h = ((2 * i + 1) / cols - 1) * tanH;
      const dx = fx + rx * h + ux * v, dy = fy + uy * v, dz = fz + rz * h + uz * v, n = Math.hypot(dx, dy, dz);
      cast(c, (i + j) & 1, dx / n, dy / n, dz / n);
    }
  }
  const mid = (rows >> 1) * cols + (cols >> 1);
  const spot = SP[mid];
  let aimed = spot && D[mid] < (RANGE[spot] || 12) ? spot : null;
  aimed = moved ? aimed || nearby() : null;
  show(aimed);
  draw(mid);
}

// One ray: the nearest of the solids, the water and the sky decides the cell.
function cast(c, odd, dx, dy, dz) {
  hitT = Infinity; hitS = null;
  trace(world, cam.x, cam.y, cam.z, dx, dy, dz);
  const wS = hitS;
  const ldx = rc * dx + rs * dy, ldy = -rs * dx + rc * dy;
  trace(ship, cam.lx, cam.ly, cam.z, ldx, ldy, dz);
  const tw = dy < 0 ? -cam.y / dy : Infinity;
  SP[c] = null;
  if (hitS && hitT < tw) shadeSolid(c, odd, hitS !== wS, dx, dy, dz, ldx, ldy);
  else if (tw < Infinity) shadeWater(c, tw, dx, dy, dz);
  else shadeSky(c, dx, dy, dz);
}
function shadeSolid(c, odd, onShip, dx, dy, dz, ldx, ldy) {
  const s = hitS, P = s.P, k = hitK, t = hitT;
  const lnx = P[k], lny = P[k + 1], nz = P[k + 2];
  const nx = onShip ? rc * lnx - rs * lny : lnx, ny = onShip ? rs * lnx + rc * lny : lny;
  const px = onShip ? cam.lx + ldx * t : cam.x + dx * t, py = onShip ? cam.ly + ldy * t : cam.y + dy * t;
  const tex = s.tex && s.tex(px, py, cam.z + dz * t, lnx, lny, nz);
  const mat = tex && tex !== "-" ? tex : s.mat, dim = tex === "-" ? 0.45 : 1;
  let ch;
  if (mat === "l") {
    const flash = s === beacon ? Math.cos(T * 2.2 + Math.atan2(dx, dz) * 2) > 0.3 : s !== antennaLamp || Math.sin(T * 3) > 0;
    ch = flash ? "@" : "o";
  } else if (ny > 0.7) {
    // Decks, dock and quay stay sparse so that what stands on them reads first.
    ch = dim < 1 ? ":" : odd ? " " : t < 9 ? "," : ".";
  } else {
    const lit = Math.max(0, nx * L[0] + ny * L[1] + nz * L[2]), face = Math.max(0, -(nx * dx + ny * dy + nz * dz));
    const b = (0.12 + 0.45 * lit + 0.38 * face) * dim * (0.3 + 0.7 * Math.exp(-t * 0.012));
    ch = RAMP[Math.max(1, Math.min(9, (b * 10) | 0))];
  }
  // Floors get a negative id: they outline what stands on them but draw no edges themselves.
  put(c, ch, s.spot && s.spot === target ? "h" : mat, (ny > 0.7 ? -1 : 1) * (s.id * 16 + (k >> 2)), t);
  SP[c] = s.spot;
}
function shadeWater(c, t, dx, dy, dz) {
  const wx = cam.x + dx * t, wz = cam.z + dz * t;
  const w = Math.sin(0.55 * wx + 1.2 * T) + 0.7 * Math.sin(0.8 * wz - 0.9 * T + 0.4 * wx) + 0.3 * Math.sin(1.9 * wx - 1.5 * wz + 2.3 * T);
  const v = ((w + 2) / 4) * (0.35 + 0.65 * Math.exp(-t * 0.025));
  if (dx * MOON[0] - dy * MOON[1] + dz * MOON[2] > 0.97 && w > 0.1) put(c, w > 0.8 ? "=" : "~", "m", -1, t);
  else put(c, v > 0.6 ? "~" : v > 0.44 ? "-" : v > 0.3 ? "." : " ", "w", -1, t);
}
function shadeSky(c, dx, dy, dz) {
  const m = dx * MOON[0] + dy * MOON[1] + dz * MOON[2], el = Math.asin(dy);
  const r = hash(Math.floor(Math.atan2(dx, dz) * 150), Math.floor(el * 150)) * 2.5;
  if (m > 0.9988) put(c, m > 0.99935 ? "@" : "o", "k", 0, Infinity);
  else if (el > 0.04 && r < 0.03) put(c, r < 0.006 ? "*" : ".", "k", 0, Infinity);
  else put(c, el < 0.035 ? "." : " ", "f", 0, Infinity);
}
function put(c, ch, cls, id, depth) { G[c] = ch; C[c] = cls; ID[c] = id; D[c] = depth; }

// Is neighbour n (inside the grid) another surface at least `min` away?
const beyond = (n, inside, id, min) => inside && ID[n] !== id && D[n] >= min;
// Outline glyph where a solid or face meets something farther away, else null.
function edge(c, i, j) {
  const id = ID[c], d = D[c];
  if (id <= 0 || d >= 70) return null;
  // Neighbours left and up must be farther, right and down at least as far, so each seam draws once.
  const l = beyond(c - 1, i > 0, id, d * 1.03), r = beyond(c + 1, i < cols - 1, id, d * 0.97);
  const u = beyond(c - cols, j > 0, id, d * 1.03), w = beyond(c + cols, j < rows - 1, id, d * 0.97);
  if ((l || r) && (u || w)) return (u && r) || (w && l) ? "\\" : "/";
  return l || r ? "|" : u ? "-" : w ? "_" : null;
}
// Draws each row as runs of one colour.
function draw(mid) {
  ctx.fillStyle = "#060a14";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  for (let j = 0; j < rows; j++) {
    let run = "", cur = C[j * cols], from = 0;
    for (let i = 0; i < cols; i++) {
      const c = j * cols + i, aim = c === mid;
      const cls = aim ? (target ? "h" : "k") : C[c];
      if (cls !== cur) { paint(run, cur, from, j); run = ""; cur = cls; from = i; }
      run += aim ? "+" : edge(c, i, j) || G[c];
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
  if (!id) {
    card.innerHTML = moved ? "" : "<h3>You are on the deck</h3><p>The ship is docked and ready to sail. Walk around to find what Crewship sets up.</p>" +
      `<p class="hint">${touchFirst.matches ? "The pad walks, a drag looks around." : "WASD or arrow keys to walk, click the scene to look with the mouse."}</p>`;
    return;
  }
  const s = spots[id];
  card.innerHTML = `<h3>${s.title}</h3><p>${s.body}</p><p class="hint"><a href="${s.href}">Open: ${s.title} \u2192</a>` +
    `${touchFirst.matches ? "" : " &middot; Enter or click opens it"}</p>`;
}

// ---- Input -------------------------------------------------------------------------------
const KEYS = { KeyW: "f", ArrowUp: "f", KeyS: "b", ArrowDown: "b", KeyA: "l", KeyD: "r", ArrowLeft: "tl", ArrowRight: "tr",
  KeyR: "u", KeyF: "d" };
const open = () => { if (target) location.href = spots[target].href; };
stage.addEventListener("keydown", (e) => {
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
  moved = true;
  dirty = true;
};
canvas.addEventListener("click", () => {
  if (document.pointerLockElement === stage) open();
  else if (!touchFirst.matches && stage.requestPointerLock) stage.requestPointerLock();
  stage.focus({ preventScroll: true });
});
document.addEventListener("mousemove", (e) => {
  if (document.pointerLockElement === stage) look(e.movementX, e.movementY, 0.0022);
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
stage.addEventListener("pointerdown", (e) => {
  if (e.pointerType === "mouse" || e.target.closest(".card")) return;
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
  if (!turn && !tilt && !fwd && !side) return false;
  moved = true;
  me.yaw += turn * 1.9 * dt;
  me.pitch = Math.max(-1.2, Math.min(1.2, me.pitch + tilt * 1.2 * dt));
  const c = Math.cos(me.yaw), s = Math.sin(me.yaw), v = 3.4 * dt;
  const here = floorAt(me.x, me.z);
  const go = (x, z) => {
    const fy = floorAt(x, z);
    if (fy === null || Math.abs(fy - here) > 0.6 || blocked(x, z, fy)) return;
    me.x = x; me.z = z;
  };
  go(me.x + (s * fwd + c * side) * v, me.z);
  go(me.x, me.z + (c * fwd - s * side) * v);
  return true;
}

// ---- Loop --------------------------------------------------------------------------------
let last = performance.now(), dirty = true, visible = true, slow = 0;
new IntersectionObserver(([e]) => { visible = e.isIntersecting; }).observe(stage);
new ResizeObserver(() => { measure(); dirty = true; }).observe(stage);
reduced.addEventListener("change", () => { dirty = true; });
function frame(now) {
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  const still = reduced.matches;
  if (!still) T += dt;
  bob = still ? 0 : 0.24 * Math.sin(T * 1.2);
  roll = still ? 0 : 0.028 * Math.sin(T * 0.8 + 1);
  rc = Math.cos(roll); rs = Math.sin(roll);
  const walked = step(dt);
  if (visible && cols && (walked || dirty || !still)) {
    dirty = false;
    setGangway();
    me.eye = floorAt(me.x, me.z) + 1.6;
    const t0 = performance.now();
    render();
    // Keep phones smooth: grow the glyphs (fewer cells) while frames take too long.
    slow = performance.now() - t0 > 28 ? slow + 1 : 0;
    if (slow > 20 && scale < 1.8) {
      scale *= 1.15;
      measure();
      slow = 0;
    }
  }
  requestAnimationFrame(frame);
}
measure();
requestAnimationFrame(frame);
