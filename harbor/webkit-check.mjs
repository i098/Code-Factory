// Loads the built page (dist/) in Playwright WebKit as an iPhone and fails on a crash, an uncaught
// error, a fallback to the plain page, or a multi-glyph fillText (WebKit keeps every distinct string
// it draws, which grew iOS Safari tabs until they were killed), an exterior grid change after the first draw,
// a bright first intro frame, or a frozen scene during the intro. Run harbor/build.py first.
import { readFile } from "node:fs/promises";
import assert from "node:assert/strict";
import { webkit, devices } from "playwright";

const dist = new URL("dist/", import.meta.url);
const browser = await webkit.launch();
const errors = [];
for (const [name, width, height, touch, scale = 1] of [
  ["desktop", 1440, 900, false],
  ["portrait", 390, 844, true],
  ["landscape", 844, 390, true],
  ["narrow-portrait", 320, 568, true, 1.15 ** 6],
  ["narrow-landscape", 568, 320, true, 1.15 ** 6],
  ["short-landscape", 568, 256, true, 1.15 ** 6],
  ["shortest-landscape", 568, 192, true, 1.15 ** 6]
]) {
const page = await browser.newPage({
  ...(touch ? devices["iPhone 13"] : {}),
  viewport: { width, height }
});
const expectedInsets = touch ? (width > height ? [0, 47, 21, 47] : [47, 0, 34, 0]) : [0, 0, 0, 0];
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
    // Force slow frames to check that the exterior grid and projection stay fixed.
    const source = await readFile(new URL(path, dist), "utf8");
    return route.fulfill({ contentType: type, body: source + `
["top", "right", "bottom", "left"].forEach((side, n) => stage.style.setProperty("--safe-" + side, ${JSON.stringify(expectedInsets)}[n] + "px"));
const drawPopup = drawSign;
drawSign = function() {
  window.signGlyphs = 0;
  window.highlightedHref = null;
  const fill = ctx.fillText;
  ctx.fillText = function(text, ...args) {
    window.signGlyphs += text.trim().length;
    if (text.startsWith("[") && ctx.fillStyle === COLORS.l) window.highlightedHref = document.activeElement.href;
    return fill.call(this, text, ...args);
  };
  try { drawPopup(); } finally { ctx.fillText = fill; }
};
window.frames = [];
window.introClocks = [];
window.firstFrameBlack = false;
window.lateMeasures = 0;
const measureGrid = measure;
measure = function() {
  if (window.frames.length) window.lateMeasures++;
  measureGrid();
  if (${scale} !== 1) {
    cellH *= ${scale};
    ctx.font = cellH + "px " + MONO;
    cellW = ctx.measureText("M").width;
    cols = Math.floor(stage.clientWidth / cellW);
    rows = Math.floor(stage.clientHeight / cellH);
    padX = (stage.clientWidth - cols * cellW) / 2;
    padY = (stage.clientHeight - rows * cellH) / 2;
    G = new Array(cols * rows); C = new Array(cols * rows);
    ID = new Int32Array(cols * rows); D = new Float32Array(cols * rows); SP = new Array(cols * rows);
  }
};
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
window.harborCheck = {
  place(x, z, yaw) { Object.assign(me, {x, z, yaw, pitch: 0}); moved = dirty = true; },
  state() { return {inside: insideHouse, x: me.x, z: me.z, yaw: me.yaw, clear: !blocked(me.x, me.z, floorAt(me.x, me.z))}; },
  ids: ORDER,
  go(id) {
    if (id) go(id);
    else { moved = false; jumped = null; show(null); }
    render(); dirty = false;
  },
  focusState() {
    step(1 / 60);
    render();
    return {
      map: mapMode, pending: walkPath.length, destination: walkTo, target,
      drawn: !!signBox && window.signGlyphs > 0, highlighted: window.highlightedHref,
      href: document.activeElement.href,
      x: stage.scrollLeft, y: stage.scrollTop
    };
  },
  focusLink(selector, pendingId) {
    walkPath = [[me.x, me.z]];
    walkTo = pendingId;
    document.querySelector(selector).focus();
    return this.focusState();
  },
  bounds() {
    return {
      box: signBox,
      glyphs: window.signGlyphs,
      x: padX + signBox.i * cellW, y: padY + signBox.j * cellH,
      width: signBox.w * cellW, height: signBox.h * cellH,
      safe: [safe.top, safe.right, safe.bottom, safe.left], screenWidth: stage.clientWidth, screenHeight: stage.clientHeight,
      pad: pad.offsetParent ? pad.getBoundingClientRect().toJSON() : null,
      map: { x: padX + mapBox.oi * cellW, y: padY + mapBox.oj * cellH,
        width: mapBox.w * cellW, height: mapBox.h * cellH },
      links: signLinks.map(({start, height, a}) => ({
        x: padX + (signBox.i + 2) * cellW,
        y: padY + (signBox.j + 1 + start + height / 2) * cellH,
        href: a.href, height: height * cellH,
        hit: signHit(padX + (signBox.i + 2) * cellW,
          padY + (signBox.j + 1 + start + height / 2) * cellH)?.href,
        top: padY + (signBox.j + 1 + start) * cellH,
        bottom: padY + (signBox.j + 1 + start + height) * cellH,
        left: padX + (signBox.i + 1) * cellW,
        right: padX + (signBox.i + signBox.w - 1) * cellW
      }))
    };
  }
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
  const { scene, longest } = await page.evaluate(() => ({ scene: !document.getElementById("stage").hidden, longest: window.longest }));
  if (!scene) errors.push("the scene fell back to the plain page");
  if (touch && longest !== 1) errors.push(`fillText drew ${longest} glyphs at once; touch devices must draw one at a time`);
  const { frames, lateMeasures } = await page.evaluate(() => ({ frames: window.frames, lateMeasures: window.lateMeasures }));
  if (frames.some((frame) => frame.some((value, i) => value !== frames[0][i]))) errors.push("the grid or field of view changed after the first draw");
  if (lateMeasures) errors.push(`the canvas layout changed ${lateMeasures} times after the first draw`);
  const { firstFrameBlack, introClocks } = await page.evaluate(() => ({ firstFrameBlack: window.firstFrameBlack, introClocks: window.introClocks }));
  if (!firstFrameBlack) errors.push("the first intro frame was not fully black");
  if (introClocks.length < 2 || introClocks.at(-1) <= introClocks[0]) errors.push("the scene froze during the intro");
}
if (touch && !page.isClosed() && !errors.length) {
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
}
if (!page.isClosed() && !errors.length) {
await page.emulateMedia({ reducedMotion: "reduce" });
const overlaps = (a, b) => b && a.x < b.x + b.width && a.x + a.width > b.x
  && a.y < b.y + b.height && a.y + a.height > b.y;
for (const id of [null, ...await page.evaluate(() => window.harborCheck.ids)]) {
  const timeout = setTimeout(() => {
    console.error(`${name}/${id}: sign rendering stalled`);
    process.exit(1);
  }, 10000);
  const bounds = await page.evaluate((id) => {
    window.harborCheck.go(id);
    return window.harborCheck.bounds();
  }, id);
  clearTimeout(timeout);
  assert.deepEqual(bounds.safe, expectedInsets, `${name}/${id}: safe insets were not measured`);
  assert(bounds.glyphs > 0, `${name}/${id}: sign did not draw`);
  const [top, right, bottom, left] = bounds.safe;
  assert(bounds.x >= left && bounds.y >= top, `${name}/${id}: sign starts outside the safe area`);
  assert(bounds.x + bounds.width <= bounds.screenWidth - right, `${name}/${id}: sign extends past the safe area: ${JSON.stringify(bounds)}`);
  assert(bounds.y + bounds.height <= bounds.screenHeight - bottom, `${name}/${id}: sign extends below the safe area`);
  if (!bounds.box.overlay) {
    assert(!overlaps(bounds, bounds.map), `${name}/${id}: sign covers the map`);
    assert(!overlaps(bounds, bounds.pad), `${name}/${id}: sign covers the move pad`);
  }
  assert.equal(bounds.links.length, id ? 1 : 3, `${id}: a sign link is missing`);
  for (const link of bounds.links) {
    assert.equal(link.hit, link.href, `${name}/${id}: link is not hit-testable`);
    if (touch && !bounds.box.overlay) assert(link.height >= 44, `${id}: touch link is too short`);
    assert(link.top >= bounds.y && link.bottom <= bounds.y + bounds.height, `${id}: link region extends outside the frame`);
    assert(link.left >= bounds.x && link.right <= bounds.x + bounds.width, `${id}: link region extends outside the frame`);
    const popup = page.waitForEvent("popup");
    if (touch) await page.touchscreen.tap(link.x, link.y);
    else await page.mouse.click(link.x, link.y);
    const opened = await popup;
    await opened.waitForLoadState();
    assert.equal(opened.url(), link.href, `${id}: grid tap opened the wrong link`);
    await opened.close();
  }
  for (let n = 0; n < bounds.links.length; n++) {
    const focus = await page.evaluate(({ n, id }) =>
      window.harborCheck.focusLink("#card a:nth-of-type(" + (n + 1) + ")", window.harborCheck.ids.find((other) => other !== id)),
      { n, id });
    assert.equal(focus.x, 0, `${name}/${id}: keyboard focus scrolled the stage horizontally`);
    assert.equal(focus.y, 0, `${name}/${id}: keyboard focus scrolled the stage vertically`);
    assert.equal(focus.pending, 0, `${name}/${id}: card focus retained an auto-walk`);
    assert.equal(focus.destination, null, `${name}/${id}: card focus retained an arrival selection`);
    assert(focus.drawn, `${name}/${id}: focused sign did not draw`);
    assert.equal(focus.highlighted, focus.href, `${name}/${id}: focused sign link was not highlighted`);
  }
}
for (const id of await page.evaluate(() => window.harborCheck.ids)) {
  await page.locator("#stage").focus();
  await page.keyboard.press("m");
  await page.keyboard.press("m");
  const focus = await page.evaluate((id) =>
    window.harborCheck.focusLink('#manifest [data-spot="' + id + '"] a',
      window.harborCheck.ids.find((other) => other !== id)), id);
  assert.equal(focus.map, 0, `${name}/${id}: manifest focus did not close the full map`);
  assert.equal(focus.pending, 0, `${name}/${id}: manifest focus retained an auto-walk`);
  assert.equal(focus.destination, null, `${name}/${id}: manifest focus retained an arrival selection`);
  assert.equal(focus.target, id, `${name}/${id}: arrival replaced the focused sign`);
  assert(focus.drawn, `${name}/${id}: focused sign did not draw`);
  assert.equal(focus.highlighted, focus.href, `${name}/${id}: manifest link did not highlight its sign`);
  assert.equal(focus.x, 0, `${name}/${id}: manifest focus scrolled the stage horizontally`);
  assert.equal(focus.y, 0, `${name}/${id}: manifest focus scrolled the stage vertically`);
}
await page.locator('#manifest [data-spot="docsboard"] a').focus();
const keyboardPopup = page.waitForEvent("popup");
await page.keyboard.press("Enter");
const opened = await keyboardPopup;
await opened.waitForLoadState();
assert.equal(opened.url(), "https://github.com/i098/Crewship#features");
await opened.close();
await page.locator("#stage").focus();
const stagePopup = page.waitForEvent("popup");
await page.keyboard.press("Enter");
const stageOpened = await stagePopup;
await stageOpened.waitForLoadState();
assert.equal(stageOpened.url(), "https://github.com/i098/Crewship#features");
await stageOpened.close();
if (!page.isClosed()) {
  const { scene, longest } = await page.evaluate(() => ({ scene: !document.getElementById("stage").hidden, longest: window.longest }));
  if (!scene) errors.push("the scene fell back to the plain page");
  if (touch && longest !== 1) errors.push(`fillText drew ${longest} glyphs at once; touch devices must draw one at a time`);
}
}
await page.close();
}
await browser.close();
if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}
console.log("harbor: desktop and WebKit iPhone portrait/landscape checks passed");
