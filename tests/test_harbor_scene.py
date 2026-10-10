"""Exercise fountain walking boundaries in the actual scene without a browser."""

import json
import runpy
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def test_fountain_stops_walking_and_leaves_room_to_pass():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to run the JavaScript scene")
    builder = runpy.run_path(str(ROOT / "harbor/build.py"))
    points = builder["points"](
        (ROOT / "README.md").read_text(), (ROOT / "CHANGELOG.md").read_text()
    )
    point_data = json.dumps([[spot, title] for spot, title, *_ in points])
    subprocess.run(
        [node, "-", str(ROOT / "harbor/public/harbor.js"), point_data],
        input=r"""
const fs = require('node:fs'), vm = require('node:vm');
const assert = require('node:assert/strict');
const element = {
  hidden: false, classList: { add() {}, toggle() {} }, focus() {}, addEventListener() {},
  firstElementChild: {}, clientWidth: 600, clientHeight: 400,
  getContext: () => ({setTransform() {}, measureText: () => ({width: 6})})
};
const manifest = JSON.parse(process.argv[3]).map(([id, title]) => ({
  dataset: {spot: id}, querySelector: tag => tag === 'a' ? {textContent: title, href: '#'} : {}
}));
const context = vm.createContext({
  document: {getElementById: () => element, querySelectorAll: () => manifest,
    documentElement: {}, addEventListener() {}},
  matchMedia: () => ({matches: false, addEventListener() {}}),
  getComputedStyle: () => ({getPropertyValue: () => 'monospace'}),
  devicePixelRatio: 1, innerWidth: 600, performance: {now: () => 0},
  IntersectionObserver: class {observe() {}},
  ResizeObserver: class {observe() {}}, requestAnimationFrame() {},
  console, window: {}, assert, addEventListener() {}
});
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8') + `
cols = 100; rows = 120; pick = ORDER.indexOf('antenna');
me.x = 0; me.z = -7.4; me.yaw = 0;
mapKey({code: 'KeyM', key: 'm'});
mapKey({code: 'KeyM', key: 'm'});
assert.equal(mapMode, 2, 'M twice must open the full map');
minimap();
const labelRow = toMap(anchors.antenna.x, anchors.antenna.z)[1];
const mapRowText = Array.from({length: mapBox.iw}, (_, i) =>
  MAPCELLS.get((mapBox.oj + labelRow + 1) * cols + mapBox.oi + i + 1)[0]).join('');
assert(mapRowText.includes('Chat clients'), 'full map corrupts the Chat clients label');
assert(!mapRowText.includes('Chat Olients'), 'fountain overwrites the Chat clients label');
function fountainMapCell() {
  const [i, j] = toMap(5, 24.6);
  return MAPCELLS.get((mapBox.oj + j + 1) * cols + mapBox.oi + i + 1);
}
assert.deepEqual(fountainMapCell(), ['O', 'w'], 'full map label overwrites the fountain');
cols = 17; rows = 20; setMap(1);
minimap();
assert.deepEqual(toMap(anchors.antenna.x, anchors.antenna.z), toMap(5, 24.6),
  'coarse map must exercise a point and scenery overlap');
assert.deepEqual(fountainMapCell(), ['@', 'h'], 'fountain overwrites the selected point');
me.x = 2.9; me.z = 24.6;
minimap();
assert.deepEqual(fountainMapCell(), ['^', 'k'], 'scenery or selected point overwrites the player');
setMap(0); cols = rows = 0;
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
function walkToSpot(id, start, dt) {
  me.x = start[0]; me.z = start[1]; me.eye = floorAt(...start) + 1.6;
  const stand = standFor(anchors[id]);
  go(id);
  let frames = 0;
  while (walkPath.length && frames++ < 10000) {
    const x0 = me.x, z0 = me.z;
    autoStep(dt);
    for (let i = 0; i <= 10; i++) {
      const x = x0 + (me.x - x0) * i / 10, z = z0 + (me.z - z0) * i / 10;
      if (x >= 0 && x <= 10 && z >= 21 && z <= 30) {
        assert(!blocked(x, z, floorAt(x, z)), 'auto-walk crosses the basin or plaza hedges');
      }
    }
  }
  assert.equal(walkPath.length, 0, 'auto-walk did not finish');
  assert.equal(jumped, id, 'auto-walk did not face its destination');
  assert.deepEqual([me.x, me.z], stand, 'auto-walk missed its destination');
}
function stoppedMapWalk(start, id, useMap = false) {
  me.x = 7.1; me.z = 24.6; me.eye = floorAt(me.x, me.z) + 1.6;
  go('how');
  me.x = start[0]; me.z = start[1]; me.eye = floorAt(...start) + 1.6;
  assert(!blocked(me.x, me.z, floorAt(me.x, me.z)), 'disconnected start must be walkable');
  if (useMap) {
    pick = ORDER.indexOf(id); setMap(1);
    mapKey({key: 'Enter', code: 'Enter'});
  } else go(id);
  for (let i = 0; i < 100; i++) {
    step(0.016);
    assert.deepEqual([me.x, me.z], start, 'failed map walk moved the player');
    assert(!blocked(me.x, me.z, floorAt(me.x, me.z)), 'failed map walk entered a blocked cell');
  }
  assert.equal(jumped, null, 'failed map walk reported arrival');
}
stoppedMapWalk([-0.6, 25], 'how', true);
anchors.disconnected = {x: -0.6, y: 1.2, z: 27.5, r: 0, ship: 0};
stoppedMapWalk([7.1, 24.6], 'disconnected');
const savedRoadLinks = LINKS.slice();
try {
  LINKS.length = 0;
  stoppedMapWalk([7.1, 24.6], 'how');
} finally {
  LINKS.push(...savedRoadLinks);
}
const corner = [6.876, 26.5], cornerTarget = [7.1, 24.6];
assert(!blocked(...corner, floorAt(...corner)), 'corner start must be walkable');
assert.notDeepEqual(approach(corner, cornerTarget), [cornerTarget], 'corner-crossing link was accepted');
assert.notDeepEqual(approach(cornerTarget, corner), [corner], 'reverse corner-crossing link was accepted');
assert.deepEqual(approach([7.1, 26.5], cornerTarget), [cornerTarget], 'clear link was rejected');
assert.deepEqual(approach(cornerTarget, [7.1, 26.5]), [[7.1, 26.5]], 'reverse clear link was rejected');
const basinBoundary = fountainBasin.bb[3] + 0.25;
assert(!blocked(basinBoundary, 24.6, floorAt(basinBoundary, 24.6)), 'walking boundary must remain open');
assert(blocked(basinBoundary - 0.001, 24.6, floorAt(basinBoundary, 24.6)), 'basin interior must remain blocked');
assert.deepEqual(approach([basinBoundary, 24], [basinBoundary, 25]), [[basinBoundary, 25]], 'boundary-parallel link was rejected');
assert.deepEqual(approach(cornerTarget, cornerTarget), [cornerTarget], 'stationary clear link was rejected');
anchors.corner = {x: cornerTarget[0], y: 1.2, z: cornerTarget[1] + 2.5, r: 0, ship: 0};
walkToSpot('corner', corner, 0.016);
const plazaPoints = [[2.9, 24.6], [7.1, 24.6], [5, 22.5], [5, 26.7],
  [5, 29.5], [3.8, 29.5], [6.2, 29.5], [5, 27.5], [2.9, 29.5], [7.1, 29.5],
  [0.5, 28], [9.5, 28], [0.5, 21.5], [9.5, 21.5], corner,
  [3.124, 26.5], [6.876, 22.7], [3.124, 22.7]];
for (const start of plazaPoints) {
  for (const id of ORDER) walkToSpot(id, start, 0.1);
  for (const end of plazaPoints) {
    const approachPath = [start, ...approach(start, end)];
    assert.deepEqual(approachPath[approachPath.length - 1], end, 'approach missed its endpoint');
    for (let k = 1; k < approachPath.length; k++) {
      const [ax, az] = approachPath[k - 1], [bx, bz] = approachPath[k];
      const cells = Math.max(1, Math.ceil(Math.hypot(bx - ax, bz - az) / 0.05));
      for (let i = 0; i <= cells; i++) {
        const x = ax + (bx - ax) * i / cells, z = az + (bz - az) * i / cells;
        const fy = floorAt(x, z);
        assert.notEqual(fy, null, 'approach leaves walkable ground');
        assert(!blocked(x, z, fy), 'approach enters a hedge or solid cell');
        const surface = ground(x, fy, z, 0, 1);
        assert(surface[0] === 't' || surface === 's_' || surface.endsWith("'") ||
          ['r*', 'b*', 's*'].includes(surface), 'approach leaves paving or grass');
      }
    }
    anchors.approach = {x: end[0], y: 1.2, z: end[1] + 2.5, r: 0, ship: 0};
    walkToSpot('approach', start, 0.02);
  }
}
`, context);
""",
        text=True,
        check=True,
        capture_output=True,
    )
