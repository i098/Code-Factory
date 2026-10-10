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
