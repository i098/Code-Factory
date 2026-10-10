// Loads the built page (dist/) in Playwright WebKit as an iPhone and fails on a crash, an uncaught
// error, a fallback to the plain page, or a multi-glyph fillText (WebKit keeps every distinct string
// it draws, which grew iOS Safari tabs until they were killed), or a grid change after the first draw.
// Run harbor/build.py first.
import { readFile } from "node:fs/promises";
import { webkit, devices } from "playwright";

const dist = new URL("dist/", import.meta.url);
const browser = await webkit.launch();
const page = await browser.newPage({ ...devices["iPhone 15 Pro"] });
const errors = [];
page.on("pageerror", (e) => errors.push(`uncaught: ${e.message}`));
page.on("crash", () => errors.push("the page crashed"));
page.on("console", (m) => m.type() === "error" && errors.push(`console: ${m.text()}`));
await page.addInitScript(() => {
  const fillText = CanvasRenderingContext2D.prototype.fillText;
  window.longest = 0;
  CanvasRenderingContext2D.prototype.fillText = function (text, ...rest) {
    window.longest = Math.max(window.longest, text.length);
    return fillText.call(this, text, ...rest);
  };
});
await page.route("http://harbor.test/**", async (route) => {
  const path = new URL(route.request().url()).pathname.slice(1) || "index.html";
  const type = { html: "text/html", js: "text/javascript", css: "text/css" }[path.split(".").pop()];
  if (path === "harbor.js") {
    // Record the real grid and projection. Force slow frames to exercise the old adaptive zoom path.
    const source = await readFile(new URL(path, dist), "utf8");
    return route.fulfill({ contentType: type, body: source + `
window.frames = [];
window.lateMeasures = 0;
const measureGrid = measure;
measure = function() { if (window.frames.length) window.lateMeasures++; measureGrid(); };
const renderScene = render;
render = function() {
  const start = performance.now();
  renderScene();
  window.frames.push([cols, rows, cellW, cellH, cam.tanH, cam.tanV, canvas.width, canvas.height]);
  while (performance.now() - start < 25) {}
};
    window.harborCheck = {
      place(x, z, yaw) { Object.assign(me, {x, z, yaw, pitch: 0}); moved = dirty = true; },
      state() { return {inside: insideHouse, x: me.x, z: me.z, yaw: me.yaw, clear: !blocked(me.x, me.z, floorAt(me.x, me.z))}; }
    };
    stage.addEventListener("pointerdown", () => { if (padId !== null) for (let i = 0; i < 8; i++) step(0.02); });
` });
  }
  await route.fulfill({ body: await readFile(new URL(path, dist)), contentType: type });
});
await page.goto("http://harbor.test/");
try {
  await page.waitForFunction(() => window.frames?.length >= 30, null, { timeout: 30000 });
} catch (e) {
  errors.push(`the scene did not draw 30 frames: ${e.message}`);
}
if (!page.isClosed() && !errors.length) {
  const { frames, lateMeasures } = await page.evaluate(() => ({ frames: window.frames, lateMeasures: window.lateMeasures }));
  if (frames.some((frame) => frame.some((value, i) => value !== frames[0][i]))) errors.push("the grid or field of view changed after the first draw");
  if (lateMeasures) errors.push(`the canvas layout changed ${lateMeasures} times after the first draw`);
}
await page.evaluate(() => window.harborCheck.place(-5, 20.6, 0));
await page.locator("#pad").waitFor({ state: "visible" });
const pad = await page.locator("#pad").boundingBox();
const padX = pad.x + pad.width / 2, padY = pad.y + 2;
await page.touchscreen.tap(padX, padY);
await page.waitForTimeout(2000);
const room = await page.evaluate(() => window.harborCheck.state());
await page.keyboard.down("ArrowRight");
await page.waitForTimeout(2000);
await page.keyboard.up("ArrowRight");
await page.waitForTimeout(100);
const painted = await page.evaluate(() => {
  const canvas = document.getElementById("scene");
  return canvas.getContext("2d").getImageData(canvas.width / 2, canvas.height / 2, 1, 1).data[3] === 255;
});
if (!painted) errors.push("the idle room cleared after looking around");
if (!room.inside || !room.clear) errors.push("touch walking did not enter a clear room");
await page.evaluate(() => {
  const {x, z} = window.harborCheck.state();
  window.harborCheck.place(x, z, Math.PI);
});
await page.touchscreen.tap(padX, padY);
await page.touchscreen.tap(padX, padY);
await page.waitForTimeout(1000);
const outside = await page.evaluate(() => window.harborCheck.state());
if (outside.inside || !outside.clear || outside.z >= 20.75 || outside.yaw !== Math.PI) errors.push("touch walking did not return outside facing away");
if (!page.isClosed()) {
  const { scene, longest } = await page.evaluate(() => ({ scene: !document.getElementById("stage").hidden, longest: window.longest }));
  if (!scene) errors.push("the scene fell back to the plain page");
  if (longest !== 1) errors.push(`fillText drew ${longest} glyphs at once; touch devices must draw one at a time`);
}
await browser.close();
if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}
console.log("harbor: WebKit iPhone check passed");
