import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

/**
 * The accessibility gate: axe over every route, both themes, desktop and phone.
 *
 * Scanning a settled page is the whole point. Routes are lazy-loaded behind a
 * Suspense fallback that renders inside `main`, so waiting for `main` returns as
 * soon as the app shell paints — before the route chunk resolves and before its
 * queries land. Axe then audits "Loading page…", which is trivially clean, and
 * the matrix reports green over markup it never looked at. A real violation on
 * the catalog setup panel survived this suite that way.
 *
 * So each scan waits for content the route only renders once its data arrived,
 * and the run collects every finding across the matrix rather than stopping at
 * the first, because one broken shared style tends to show up in many cells.
 */

const ROUTES = ["/", "/catalog", "/inventory", "/models", "/viewer-demo"];
const THEMES = ["light", "dark"] as const;
const VIEWPORTS = [
  { name: "desktop", width: 1280, height: 800 },
  { name: "phone", width: 375, height: 812 },
] as const;

/** Content each route only renders once its data has actually arrived. */
const SETTLED: Record<string, string> = {
  "/": ".overview-grid",
  "/catalog": ".setup-state, .catalog-filters",
  "/inventory": ".inventory-summary",
  "/models": ".results-count, .empty-state",
  "/viewer-demo": ".viewer-section",
};

/** Every loading placeholder in the app; none may remain when axe runs. */
const LOADING = ".page-message, .viewer-loading";

test("axe matrix: every settled route stays clean across themes and viewports", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium-desktop", "The axe matrix runs once in Chromium.");
  test.setTimeout(180_000);

  const findings: string[] = [];

  for (const viewport of VIEWPORTS) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    for (const theme of THEMES) {
      for (const route of ROUTES) {
        await page.goto(route);
        await page.getByLabel("Theme").selectOption(theme);
        await page.locator("main").waitFor();

        // Settle: the lazy route chunk plus every fetch it kicks off. Network
        // idle on its own would just be a longer guess -- the positive content
        // marker below is what makes it trustworthy, since a scan of a
        // placeholder passes without auditing anything.
        await page.waitForLoadState("networkidle");
        await expect(page.locator(LOADING)).toHaveCount(0);
        await expect(page.locator(SETTLED[route]).first()).toBeVisible();

        const where = `${route} (${theme}, ${viewport.name})`;
        const accessibility = await new AxeBuilder({ page }).analyze();
        for (const violation of accessibility.violations) {
          for (const node of violation.nodes) {
            findings.push(
              `${where} | ${violation.id} | ${violation.impact} | ` +
                `${violation.tags.filter((tag) => tag.startsWith("wcag")).join(",")} | ` +
                `${JSON.stringify(node.target)} | ${node.html.slice(0, 160).replace(/\s+/g, " ")}`,
            );
          }
        }

        if (viewport.name === "phone") {
          const overflow = await page.evaluate(
            () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
          );
          if (overflow > 1) findings.push(`${where} | horizontal-overflow | ${overflow}px`);
        }
      }
    }
  }

  // Every finding travels in the failure message, so the Playwright output is
  // enough to diagnose without re-running.
  expect(
    findings,
    `Accessibility findings on settled pages (${findings.length}):\n${findings.join("\n")}`,
  ).toEqual([]);
});
