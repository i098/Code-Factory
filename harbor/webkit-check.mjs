// Loads the built page (dist/) in Playwright WebKit as an iPhone and fails on a crash, an uncaught
// error, a fallback to the plain page, or a multi-glyph fillText (WebKit keeps every distinct string
// it draws, which grew iOS Safari tabs until they were killed). Run harbor/build.py first.
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
  await route.fulfill({ body: await readFile(new URL(path, dist)), contentType: type });
});
await page.goto("http://harbor.test/");
await page.waitForTimeout(5000);
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
