"""Exercise the pirate ship's walking, ray hits, and map silhouette."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _run_ship_scene(checks):
    subprocess.run(
        ["node", "-", str(ROOT / "harbor/public/harbor.js"), checks],
        input=r"""
const fs = require('node:fs'), vm = require('node:vm');
const assert = require('node:assert/strict');
const element = {
  hidden: false, classList: { add() {}, toggle() {} }, focus() {}, addEventListener() {},
  firstElementChild: {}, clientWidth: 600, clientHeight: 400,
  style: {setProperty() {}},
  getContext: () => ({setTransform() {}, measureText: () => ({width: 6})})
};
const context = vm.createContext({
  document: {getElementById: () => element,
    querySelectorAll: () => ['how', 'spyglass'].map(id => ({
      dataset: {spot: id},
      querySelector: tag => tag === 'a' ? {textContent: id, href: '#'} : {}
    })),
    documentElement: {}, addEventListener() {},
    fonts: { load: () => Promise.resolve(), ready: Promise.resolve() }},
  matchMedia: () => ({matches: false, addEventListener() {}}),
  getComputedStyle: () => ({getPropertyValue: () => 'monospace'}),
  devicePixelRatio: 1, innerWidth: 600, performance: {now: () => 0},
  IntersectionObserver: class {observe() {}}, ResizeObserver: class {observe() {}},
  requestAnimationFrame() {}, console, window: {}, assert, addEventListener() {}
});
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8') + '\nmeasure();\n' + process.argv[3], context);
""",
        text=True,
        check=True,
        capture_output=True,
    )


def test_ship_deck_ports_and_map_match_the_hull():
    _run_ship_scene(
        r"""
const spawn = [me.x, me.z];
keys.add('f'); step(0.1); keys.clear();
assert(Math.hypot(me.x - spawn[0], me.z - spawn[1]) > 0.2, 'the default view must start on clear walking ground');
assert.equal(floorAt(-5, 0), DECK, 'the wider waist must support walking');
assert.equal(floorAt(-5, 11), null, 'the bow must not leave an invisible square deck');
assert(floorAt(SX, 11) > DECK, 'the bow sheer must rise above the waist');
assert(blocked(SX, 6, floorAt(SX, 6)), 'the foremast must block walking through its base');
const mast = ship.find(s => s.cone && s.bb[1] === DECK && s.bb[4] > 18);
const lowerPole = hit(mast, SX + 2, 3, -3, -1, 0, 0);
const upperPole = hit(mast, SX + 2, 20, -3, -1, 0, 0);
assert(Math.abs(lowerPole - upperPole) < 1e-6 && 2 - lowerPole < 0.3, 'the main mast must remain a thin straight pole');
assert(blocked(SX, -12, DECK), 'the cabin walls must still block walking through their lower level');
me.x = SX + 1.7; me.z = -4.8; me.yaw = Math.PI;
keys.add('f');
for (let i = 0; i < 100; i++) step(0.02);
keys.clear();
assert(me.z < -11.5, 'the stairs must let a visitor reach the stern deck');
assert(Math.abs(floorAt(me.x, me.z) - 4.8) < 1e-6, 'the stern floor must match the castle roof');
assert(!blocked(me.x, me.z, floorAt(me.x, me.z)), 'the castle roof must provide a clear walking surface');
me.yaw = 0; keys.add('f');
for (let i = 0; i < 100; i++) step(0.02);
keys.clear();
assert(me.z > -5 && Math.abs(floorAt(me.x, me.z) - DECK) < 1e-6, 'the stairs must let a visitor descend to the main deck');
me.x = SX + 0.5; me.z = 10; me.yaw = Math.PI / 2;
keys.add('f');
for (let i = 0; i < 200; i++) step(0.02);
keys.clear();
assert(me.x > SX + 0.5, 'the bow deck must allow lateral walking');
assert(me.x < SX + shipProfile(10)[0] - 0.2, 'walking must stop before the tapered rail');
me.x = 0; me.z = -1.2; me.yaw = Math.PI / 2;
keys.add('f');
for (let i = 0; i < 70; i++) step(0.02);
keys.clear();
assert(me.x > 4, 'the open rail and gangway must join the ship to the dock');
const hull = ship.filter(s => s.hull);
const waistHit = Math.min(...hull.map(s => hit(s, 3, 1.02, 0.6, -1, 0, 0)));
const bowHit = Math.min(...hull.map(s => hit(s, 3, 2.5, 11, -1, 0, 0)));
assert(bowHit > waistHit, 'a side ray must see the narrowing bow');
const barrelHit = Math.min(...ship.filter(s => !s.hull).map(s => hit(s, 3, 1.02, 0.6, -1, 0, 0)));
assert(barrelHit < waistHit, 'the cannon must emerge from the side gun port');
for (const origin of [[25,5,0], [-25,5,0], [SX,5,-24], [SX,5,24], [SX,30,0], [0,3.6,-7.4]]) {
  for (const s of ship) {
    const b = s.bb, delta = [0,1,2].map(k => (b[k] + b[k+3]) / 2 - origin[k]);
    const length = Math.hypot(...delta), ray = delta.map(v => v / length);
    const t = hit(s, ...origin, ...ray);
    if (!Number.isFinite(t)) continue;
    const envelope = boxEntry(SHIP_BOUNDS, ...origin, ...ray.map(v => 1 / v));
    assert(envelope <= t + 1e-6 || Number.isNaN(envelope), 'the aggregate bounds must not hide a visible ship part');
  }
}
const rail = ship.find(s => s.rail && s.bb[2] < -4 && s.bb[5] > -4 && s.bb[0] > SX);
assert.equal(hit(rail, 3, 2.55, -4, -1, 0, 0), Infinity, 'the railing must leave open space between its bars');
assert(Number.isFinite(hit(rail, 3, 2.3, -4, -1, 0, 0)), 'the railing crossbar must remain visible');
cols = rows = 3; G = Array(9).fill(' '); C = Array(9).fill(''); SP = Array(9).fill(null);
ID = new Int32Array(9); D = new Float32Array(9).fill(Infinity);
cam.tanH = cam.tanV = 0.62; G[4] = '@'; D[4] = 5;
drawRope([-100, 1.5, 10], [100, 1.5, 10]);
assert.equal(G[3], '-', 'an off-screen stay must enter the visible grid');
assert.equal(G[4], '@', 'a stay must not draw through a nearer hull');
assert.equal(G[5], '-', 'an off-screen stay must reach the opposite grid edge');
cols = 240; rows = 120; mapMode = 2;
mapBox = {oi:1,oj:1,w:238,h:118,iw:236,ih:115};
mapTerrain();
for (const s of hull) footprint(s, 'o');
const cell = (x,z) => {
  const [i,j] = toMap(x,z);
  return MAPCELLS.get((mapBox.oj+j+1)*cols+mapBox.oi+i+1);
};
assert.equal(cell(-5,0)[1], 'o', 'the map must include the wider hull');
assert.notEqual(cell(-5,11)[1], 'o', 'the map must leave water beside the narrowing bow');
assert.equal(cell(SX,11)[1], 'o', 'the map must retain the raised bow');
"""
    )


def test_ship_canvas_stays_pale_and_flag_stays_black_at_night():
    _run_ship_scene(
        r"""
function paintPart(s, y) {
  cam.x = cam.lx = (s.bb[0] + s.bb[3]) / 2;
  cam.y = cam.ly = y; cam.z = s.bb[2] - 4;
  hitS = s; hitT = hit(s, cam.lx, cam.ly, cam.z, 0, 0, 1); hitK = entryK;
  shadeSolid(0, 0, true, 0, 0, 1, 0, 0);
  return COLORS[C[0]].slice(1).match(/../g).map(v => parseInt(v, 16));
}
const canvasPart = ship.find(s => s.tex === sailTexture);
const pale = paintPart(canvasPart, (canvasPart.bb[1] + canvasPart.bb[4]) / 2);
assert(pale.every(v => v > 150), 'the canvas must remain pale under night lighting');
const black = paintPart(ship.find(s => s.flag), 20.1);
assert(black.every(v => v < 80), 'the pirate flag must retain a dark silhouette');
const wood = paintPart(ship.find(s => s.hull), 0.15);
assert(wood[0] - wood[1] > 20 && wood[1] - wood[2] > 20, 'the hull must keep its warm wood tone instead of using the cloth paint');
"""
    )


def test_map_walks_use_supported_ship_and_dock_connections():
    _run_ship_scene(
        r"""
const dock = [me.x, me.z];
const starts = [dock, [-4,7], [-2.95,-3.5], [-4,2], [-5.1,1.2]];
function checkSegment(a, b) {
  const samples = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / 0.01));
  let previous = floorAt(...a);
  for (let i = 0; i <= samples; i++) {
    const x = a[0] + (b[0] - a[0]) * i / samples;
    const z = a[1] + (b[1] - a[1]) * i / samples;
    const height = floorAt(x, z);
    assert.notEqual(height, null, `map walk crosses water at ${x},${z}`);
    assert(!blocked(x, z, height), `map walk crosses a solid at ${x},${z}`);
    assert(Math.abs(height - previous) <= 0.6, `map walk skips a height transition at ${x},${z}`);
    previous = height;
  }
}
function walk(id, start, dt) {
  me.x = start[0]; me.z = start[1]; me.eye = floorAt(...start) + 1.6;
  const destination = standFor(anchors[id]);
  go(id);
  assert(walkPath.length, `no route from ${start} to ${id}`);
  let previous = start;
  for (const waypoint of walkPath) {
    checkSegment(previous, waypoint);
    previous = waypoint;
  }
  let frames = 0;
  while (walkPath.length && frames++ < 10000) {
    const before = [me.x, me.z];
    step(dt);
    checkSegment(before, [me.x, me.z]);
  }
  assert.equal(walkPath.length, 0, 'map walk did not finish');
  assert.equal(jumped, id, 'map walk did not face the destination');
  assert.deepEqual([me.x, me.z], destination, 'map walk missed the destination');
  return destination;
}
for (const dt of [0.02, 0.1]) {
  for (const start of starts) {
    assert(!blocked(...start, floorAt(...start)), 'the deck start must be reachable');
    anchors.return = {x: start[0], y: floorAt(...start), z: start[1] + 2.5, r: 0,
      ship: floorAt(...start) > 1.6};
    for (const id of ['how', 'spyglass']) {
      const end = walk(id, start, dt);
      if (id === 'spyglass') assert.equal(floorAt(...end), 4.8, 'the spyglass walk must reach the stern roof');
      const returned = walk('return', end, dt);
      assert(Math.hypot(returned[0] - start[0], returned[1] - start[1]) < 1e-9,
        'the return walk must reach the original start');
    }
  }
}
"""
    )
