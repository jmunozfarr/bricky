import { chromium } from "@playwright/test";

// Read-only smoke against the production nginx stack: loads each route and
// fails on Content-Security-Policy violations, page errors, or console
// errors. Never run the full e2e suite against production data; this script
// only issues GET navigations.
const baseUrl = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:8080";
const routes = ["/", "/catalog", "/inventory", "/models", "/viewer-demo"];

const browser = await chromium.launch();
const page = await browser.newPage();

const failures = [];
page.on("pageerror", (error) => failures.push(`page error: ${error.message}`));
page.on("console", (message) => {
  if (message.type() === "error") failures.push(`console error: ${message.text()}`);
});
await page.addInitScript(() => {
  window.__cspViolations = [];
  document.addEventListener("securitypolicyviolation", (event) => {
    window.__cspViolations.push(`${event.violatedDirective} blocked ${event.blockedURI}`);
  });
});

for (const route of routes) {
  await page.goto(new URL(route, baseUrl).href, { waitUntil: "networkidle" });
  if (route === "/viewer-demo") {
    // The viewer route exercises the WebGL canvas and the LDraw parse
    // worker, the two surfaces most likely to trip worker-src/img-src.
    await page.waitForSelector("canvas", { timeout: 30_000 });
    await page.waitForTimeout(2_000);
  }
  const violations = await page.evaluate(() => window.__cspViolations);
  failures.push(...violations.map((violation) => `${route} CSP ${violation}`));
  console.log(`${route}: loaded, ${violations.length} CSP violations`);
}

await browser.close();
if (failures.length > 0) {
  for (const failure of failures) console.error(failure);
  throw new Error("CSP smoke found problems.");
}
console.log("CSP smoke passed.");
