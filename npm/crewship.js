#!/usr/bin/env node
// Fetch install.sh from the Crewship release that matches this package version and
// run it; arguments go to `./ship.sh dock`. The package bundles nothing else.
const { spawnSync } = require("node:child_process");
const { version } = require("./package.json");

const ref = `v${version}`;
const url = `https://raw.githubusercontent.com/i098/Crewship/${ref}/install.sh`;

fetch(url)
  .then((response) => {
    if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
    return response.text();
  })
  .then((script) => {
    // The script goes in on stdin, never into the command line, the way `curl | bash` runs it.
    const result = spawnSync("bash", ["-s", "--", ...process.argv.slice(2)], {
      input: script,
      stdio: ["pipe", "inherit", "inherit"],
      env: { ...process.env, CREWSHIP_REF: ref },
    });
    process.exit(result.status ?? 1);
  })
  .catch((error) => {
    console.error(`crewship: ${error.message}`);
    process.exit(1);
  });
