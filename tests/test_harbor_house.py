"""Window light stays inside the frames; house detail does not block the approach."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_house_panes_and_approach():
    source = (ROOT / "harbor/public/harbor.js").read_text()
    # Run the real world and collision code without the browser and rendering loop.
    world = source[source.index("const SX =") : source.index("const me =")]
    check = r"""
const assert = require('node:assert/strict');
const wall = world.find(s => s.spot === 'office' && s.mat === 's');
const front = (x, y) => wall.tex(x, y, 21, 0, 0, -1);
assert.equal(front(-7.9, 2.7), 'l');
assert.notEqual(front(-8.25, 2.7), 'l'); // outer frame
assert.notEqual(front(-7.4, 2.7), 'l'); // vertical crossbar
assert.notEqual(front(-7.9, 3), 'l');   // horizontal crossbar
assert.notEqual(front(-7.9, 3.9), 'l'); // wall above the window
assert.notEqual(front(-5, 2.7), 'l');  // door
assert.equal(blocked(-5, 20.7, 1.2), false); // the step adds no obstacle
assert.equal(blocked(-5, 20.8, 1.2), true);  // the old wall still blocks
assert.equal(blocked(-0.7, 23, 1.2), false); // side approach
assert.equal(blocked(-0.8, 23, 1.2), true);
"""
    subprocess.run(["node", "-e", world + check], check=True, timeout=10)


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_house_trim_targets_office_without_moving_anchor():
    source = (ROOT / "harbor/public/harbor.js").read_text()
    scene = source[source.index("const SX =") : source.index("const MONO =")]
    shading = source[source.index("const GRAIN =") : source.index("// ---- The sea:")]
    put = source[source.index("function put(") : source.index("// Is neighbour")]
    nearby = source[source.index("function nearby(") : source.index("// Cards are built")]
    check = r"""
const assert = require('node:assert/strict');
for (const [key, value] of Object.entries({x: -5, y: 4.85, z: 24.5, r: 4.4})) {
  assert.ok(Math.abs(anchors.office[key] - value) < 1e-12);
}
assert.equal(anchors.office.n, 2);
assert.equal(anchors.office.ship, 0);
const cam = {};
let G = [], C = [], ID = [], D = [], SP = [];
moveLights();
Object.assign(me, {x: -5, z: 19.6, eye: 2.8});
assert.equal(nearby(), null);
function aim(list, origin, point) {
  Object.assign(cam, {x: origin[0], y: origin[1], z: origin[2]});
  const delta = point.map((v, i) => v - origin[i]);
  const length = Math.hypot(...delta);
  const [dx, dy, dz] = delta.map(v => v / length);
  hitT = Infinity; hitS = null;
  trace(list, 0, ...origin, dx, dy, dz);
  assert.ok(hitS);
  shadeSolid(0, 0, false, dx, dy, dz, dx, dy);
  assert.equal(SP[0], 'office');
  assert.ok(D[0] < RANGE.office);
}
aim(world, [-5, 2.8, 19.6], [-5, 3.95, 20.91]);
assert.equal(hitS.solid, false);
aim(world, [-5, 2.8, 19.6], [-7.9, 2.7, 21]);
assert.equal(hitS.solid, true);
aim(world, [0, 2.8, 24.5], [-0.91, 3.95, 24.5]);
assert.equal(hitS.solid, false);
for (const s of world.filter(s => s.anchor === false)) {
  const b = s.bb;
  const point = [(b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2];
  for (const axis of [0, 1, 2]) for (const direction of [-1, 1]) {
    const origin = [...point];
    origin[axis] = b[axis + (direction > 0 ? 3 : 0)] + direction;
    aim([s], origin, point);
  }
}
"""
    subprocess.run(
        [
            "node",
            "-e",
            "const spots = {office: {}}; const touchFirst = {matches: false};\n"
            + scene + shading + put + nearby + check,
        ],
        check=True,
        timeout=10,
    )


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_house_entry_exit_and_room_collisions():
    source = (ROOT / "harbor/public/harbor.js").read_text()
    setup = r"""
const assert = require('node:assert/strict');
const element = {
  hidden: false, classList: {add() {}, toggle() {}}, focus() {}, addEventListener() {},
  firstElementChild: {style: {}}, clientWidth: 600, clientHeight: 400,
  replaceChildren() {}, getContext: () => ({setTransform() {}, measureText: () => ({width: 6})})
};
const document = {getElementById: () => element, querySelectorAll: () => [],
  documentElement: {}, addEventListener() {}};
const matchMedia = () => ({matches: false, addEventListener() {}});
const getComputedStyle = () => ({getPropertyValue: () => 'monospace'});
const devicePixelRatio = 1, innerWidth = 600, performance = {now: () => 0};
const IntersectionObserver = class {observe() {}}, ResizeObserver = class {observe() {}};
function requestAnimationFrame() {}
function addEventListener() {}
const window = {};
"""
    check = r"""
Object.assign(me, {x: -5, z: 20.6, yaw: 0});
keys.add('f');
for (let i = 0; i < 4; i++) step(0.02);
keys.clear();
assert(insideHouse, 'walking into the door must enter the room');
assert.equal(floorAt(me.x, me.z), 0);
assert(!blocked(me.x, me.z, 0), 'entry must leave the player in a clear aisle');
assert.equal(walkPath.length, 0);
mapKey({code: 'KeyM'});
minimap();
assert.equal(mapMode, 0, 'the island map must not open inside');
assert.equal(mapBox, null);
for (const [x, z] of [[-2, 3], [0, 4]]) {
  assert(blocked(x, z, 0), 'interior furniture must block walking');
}
Object.assign(me, {x: 0, z: 0.8, yaw: 0});
keys.add('f');
for (let i = 0; i < 60; i++) step(0.02);
keys.clear();
assert(me.z > 2.5 && me.z < 3, 'walking must stop at the bed foot');
keys.add('r');
for (let i = 0; i < 24; i++) step(0.02);
keys.clear();
keys.add('f');
for (let i = 0; i < 60; i++) step(0.02);
keys.clear();
assert(me.z > 5 && !blocked(me.x, me.z, 0), 'the right aisle must reach the window');
for (const [x, z, yaw] of [[-2.7, 1, -Math.PI/2], [2.7, 1, Math.PI/2], [1.8, 5.4, 0]]) {
  Object.assign(me, {x, z, yaw});
  keys.add('f');
  for (let i = 0; i < 30; i++) step(0.02);
  keys.clear();
  assert(insideHouse, 'walking into a wall must not leave the room');
  assert.notEqual(floorAt(me.x, me.z), null, 'walking must stay within room bounds');
  assert(!blocked(me.x, me.z, 0));
}
Object.assign(me, {x: 0, z: 0.8, yaw: Math.PI});
stick.y = 1;
for (let i = 0; i < 8; i++) step(0.02);
stick.y = 0;
assert(!insideHouse, 'the touch stick must exit through the door');
assert.equal(me.yaw, Math.PI);
assert(me.z < 20.75 && me.z > 19.8, 'exit must land just outside the door');
assert(!blocked(me.x, me.z, floorAt(me.x, me.z)));
Object.assign(me, {x: -5, z: 20.6, yaw: 0});
stick.y = 1;
for (let i = 0; i < 4; i++) step(0.02);
stick.y = 0;
assert(insideHouse, 'the touch stick must enter through the door');
Object.assign(me, {x: 0, z: 0.8, yaw: Math.PI});
keys.add('f');
for (let i = 0; i < 8; i++) step(0.02);
keys.clear();
assert(!insideHouse, 'keyboard walking must exit through the door');
for (const x of [-5.5, -4.5]) {
  Object.assign(me, {x, z: 20.6, yaw: 0});
  keys.add('f');
  for (let i = 0; i < 20; i++) step(0.02);
  keys.clear();
  assert(!insideHouse, 'walking into the door frame must not enter');
  assert(me.z <= 20.75, 'the exterior wall must still block walking');
}
"""
    subprocess.run(
        ["node", "-e", setup + source + check],
        check=True,
        timeout=10,
    )
