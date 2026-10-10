"""Exercise fountain walking boundaries in the actual scene without a browser."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def test_fountain_stops_walking_and_leaves_room_to_pass():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to run the JavaScript scene")
    subprocess.run(
        [node, "-", str(ROOT / "harbor/public/harbor.js")],
        input=r"""
const fs = require('node:fs'), vm = require('node:vm');
const assert = require('node:assert/strict');
const element = {
  hidden: false, classList: { add() {} }, focus() {}, addEventListener() {},
  firstElementChild: {}, clientWidth: 600, clientHeight: 400,
  getContext: () => ({setTransform() {}, measureText: () => ({width: 6})})
};
const context = vm.createContext({
  document: {getElementById: () => element, querySelectorAll: () => [],
    documentElement: {}, addEventListener() {}},
  matchMedia: () => ({matches: false, addEventListener() {}}),
  getComputedStyle: () => ({getPropertyValue: () => 'monospace'}),
  devicePixelRatio: 1, innerWidth: 600, performance: {now: () => 0},
  IntersectionObserver: class {observe() {}},
  ResizeObserver: class {observe() {}}, requestAnimationFrame() {},
  console, window: {}, assert
});
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8') + `
for (const yaw of [0, Math.PI / 2, Math.PI, -Math.PI / 2]) {
  me.x = 5 - Math.sin(yaw) * 2.1;
  me.z = 24.6 - Math.cos(yaw) * 2.1;
  me.yaw = yaw;
  keys.add('f');
  for (let i = 0; i < 100; i++) step(0.02);
  keys.clear();
  assert(Math.hypot(me.x - 5, me.z - 24.6) > 1.5, 'walk entered the basin');
  assert(Math.hypot(me.x - 5, me.z - 24.6) < 2, 'walk stopped before the rim');
}
assert(blocked(5, 24.6, floorAt(5, 24.6)), 'basin centre is walkable');
for (const x of [2.9, 7.1]) {
  me.x = x; me.z = 21.5; me.yaw = 0;
  keys.add('f');
  for (let i = 0; i < 75; i++) step(0.02);
  keys.clear();
  assert(me.z > 26.5, 'cannot walk past the fountain');
}
const path = route(6, 7);
for (let k = 1; k < path.length; k++) {
  const [ax, az] = path[k - 1], [bx, bz] = path[k];
  for (let i = 0; i <= 20; i++) {
    const x = ax + (bx - ax) * i / 20, z = az + (bz - az) * i / 20;
    assert(!blocked(x, z, floorAt(x, z)), 'map route crosses the basin');
    assert.equal(ground(x, 1.2, z, 0, 1)[0], 't', 'map route leaves the paving');
  }
}
`, context);
""",
        text=True,
        check=True,
        capture_output=True,
    )
