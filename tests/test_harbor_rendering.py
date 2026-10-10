"""Check paving and shore glyphs without starting the browser scene."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_paving_and_shore_glyphs_and_colours():
    subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            r"""
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
const source = fs.readFileSync(process.argv[1], "utf8");
const names = ["plazaCurb", "plazaStone", "plazaPaving", "wetSand",
  "waterFoam", "waterReflection", "waterGlyph"];
const functions = names.map(name =>
  source.match(new RegExp(`^function ${name}\\(.*?^}`, "ms"))[0]);
const constants = ["hash", "RAMP", "tier", "glyph", "SEA"].map(name =>
  source.match(new RegExp(`^const ${name} = .*;$`, "m"))[0]);
const put = source.match(/^function put\(.*$/m)[0];
vm.runInNewContext([...constants, ...functions, put, `
let T = 0;
const G = [], C = [], ID = [], D = [];
// Joint line, curb stone, curb joint and open stone include material and glyph.
assert.equal(plazaPaving(4.81, 24.5, 0.3), "s|");
assert.equal(plazaPaving(5.2, 24.31, 0.3), "s-");
assert.equal(plazaPaving(8, 24.6, 3), "s=");
const jointAngle = 3.004166666666667 - Math.PI;
assert.equal(plazaPaving(5 + 3 * Math.cos(jointAngle),
  24.6 + 3 * Math.sin(jointAngle), 3), "t:");
assert.match(plazaPaving(5.2, 24.5, 0.3), /^t[,.]$/);
// A moving foam edge and wet sand retain distinct colours and glyphs.
assert.equal(wetSand(0, 0.12, 0), "k~");
assert.equal(wetSand(0, 0.3, 0), "n:");
assert.equal(wetSand(0, 0.5, 0), null);
waterGlyph(0, 10, waterFoam(0, 0, 0, 1), 0.05, 1, "w");
assert.equal(G[0], "~");
assert.equal(C[0], "k4");
assert.equal(waterFoam(0, 0, 0, 0), 0);
waterGlyph(0, 10, waterFoam(0, 0, 0, 0), 0.12, 1, "d");
assert.equal(G[0], String.fromCharCode(96));
assert.equal(C[0], "d1");
assert.equal(waterReflection(0.2, 0.15), "l");
assert.equal(waterReflection(0.15, 0.2), "m");
assert.equal(waterReflection(0.1, 0.1), null);
`].join("\n"), { assert });
""",
            str(ROOT / "harbor/public/harbor.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
