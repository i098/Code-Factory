// Loads the built page (dist/) in Playwright WebKit as an iPhone and fails on a crash, an uncaught
// error, a fallback to the plain page, or a multi-glyph fillText (WebKit keeps every distinct string
// it draws, which grew iOS Safari tabs until they were killed), a grid change after the first draw,
// a bright first intro frame, or a frozen scene during the intro. Run harbor/build.py first.
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
window.introClocks = [];
window.firstFrameBlack = false;
window.lateMeasures = 0;
const measureGrid = measure;
measure = function() { if (window.frames.length) window.lateMeasures++; measureGrid(); };
const renderScene = render;
render = function() {
  const start = performance.now();
  renderScene();
  if (!window.frames.length) {
    const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    window.firstFrameBlack = pixels.every((value, i) => i % 4 === 3 || value === 0);
  }
  if (introProgress < 1) window.introClocks.push(T);
  window.frames.push([cols, rows, cellW, cellH, cam.tanH, cam.tanV, canvas.width, canvas.height]);
  while (performance.now() - start < 25) {}
};
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
  const { scene, longest } = await page.evaluate(() => ({ scene: !document.getElementById("stage").hidden, longest: window.longest }));
  if (!scene) errors.push("the scene fell back to the plain page");
  if (longest !== 1) errors.push(`fillText drew ${longest} glyphs at once; touch devices must draw one at a time`);
  const { frames, lateMeasures } = await page.evaluate(() => ({ frames: window.frames, lateMeasures: window.lateMeasures }));
  if (frames.some((frame) => frame.some((value, i) => value !== frames[0][i]))) errors.push("the grid or field of view changed after the first draw");
  if (lateMeasures) errors.push(`the canvas layout changed ${lateMeasures} times after the first draw`);
  const { firstFrameBlack, introClocks } = await page.evaluate(() => ({ firstFrameBlack: window.firstFrameBlack, introClocks: window.introClocks }));
  if (!firstFrameBlack) errors.push("the first intro frame was not fully black");
  if (introClocks.length < 2 || introClocks.at(-1) <= introClocks[0]) errors.push("the scene froze during the intro");
}
await browser.close();
if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}
console.log("harbor: WebKit iPhone check passed");
