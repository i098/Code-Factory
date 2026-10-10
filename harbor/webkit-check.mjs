// Loads the built page (dist/) in Playwright WebKit as an iPhone and fails on a crash, an uncaught
// error, a fallback to the plain page, or a multi-glyph fillText (WebKit keeps every distinct string
// it draws, which grew iOS Safari tabs until they were killed), or a grid change after the first draw.
// Run harbor/build.py first.
import { readFile } from "node:fs/promises";
import assert from "node:assert/strict";
import { webkit, devices } from "playwright";

const dist = new URL("dist/", import.meta.url);
const browser = await webkit.launch();
const page = await browser.newPage({ ...devices["iPhone 13"], viewport: { width: 390, height: 844 } });
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
await page.context().route("**/*", async (route) => {
  const url = new URL(route.request().url());
  if (url.origin !== "http://harbor.test") {
    await route.fulfill({ body: "<title>Link destination</title>", contentType: "text/html" });
    return;
  }
  const path = url.pathname.slice(1) || "index.html";
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
  ids: ORDER,
  go(id) { go(id); render(); },
  bounds() {
    return {
      box: signBox,
      x: padX + signBox.i * cellW, y: padY + signBox.j * cellH,
      width: signBox.w * cellW, height: signBox.h * cellH,
      padTop: pad.getBoundingClientRect().top,
      links: signLinks.map(({start, height, a}) => ({
        x: padX + (signBox.i + 2) * cellW,
        y: padY + (signBox.j + 1 + start + height / 2) * cellH,
        href: a.href
      }))
    };
  }
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
}
if (!page.isClosed() && !errors.length) {
await page.emulateMedia({ reducedMotion: "reduce" });
for (const id of [null, ...await page.evaluate(() => window.harborCheck.ids)]) {
  if (id) await page.evaluate((id) => window.harborCheck.go(id), id);
  const bounds = await page.evaluate(() => window.harborCheck.bounds());
  assert(bounds.x >= 0 && bounds.y >= 0, `${id}: sign starts off screen`);
  assert(bounds.x + bounds.width <= 390, `${id}: sign extends past the screen`);
  assert(bounds.y + bounds.height < bounds.padTop, `${id}: sign covers the move pad`);
  assert(bounds.links.length >= 1 && bounds.links.length <= 3, `${id}: invalid link count`);
  for (const link of bounds.links) {
    const popup = page.waitForEvent("popup");
    await page.touchscreen.tap(link.x, link.y);
    const opened = await popup;
    await opened.waitForLoadState();
    assert.equal(opened.url(), link.href, `${id}: grid tap opened the wrong link`);
    await opened.close();
  }
}
await page.locator('#manifest [data-spot="docsboard"] a').focus();
const keyboardPopup = page.waitForEvent("popup");
await page.keyboard.press("Enter");
const opened = await keyboardPopup;
await opened.waitForLoadState();
assert.equal(opened.url(), "https://github.com/i098/Crewship#more-docs");
await opened.close();
await page.locator("#stage").focus();
const stagePopup = page.waitForEvent("popup");
await page.keyboard.press("Enter");
const stageOpened = await stagePopup;
await stageOpened.waitForLoadState();
assert.equal(stageOpened.url(), "https://github.com/i098/Crewship#more-docs");
await stageOpened.close();
}
await browser.close();
if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}
console.log("harbor: WebKit iPhone check passed");
