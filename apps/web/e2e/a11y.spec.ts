import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const ROUTES = ["/", "/catalog", "/inventory", "/models", "/viewer-demo"];
const THEMES = ["light", "dark"] as const;
const VIEWPORTS = [
  { name: "desktop", width: 1280, height: 800 },
  { name: "phone", width: 375, height: 812 },
] as const;

test("axe matrix: every route stays clean across themes and viewports", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium-desktop", "The axe matrix runs once in Chromium.");
  test.setTimeout(240_000);

  for (const viewport of VIEWPORTS) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    for (const theme of THEMES) {
      for (const route of ROUTES) {
        await page.goto(route);
        await page.getByLabel("Theme").selectOption(theme);
        await page.locator("main").waitFor();

        const accessibility = await new AxeBuilder({ page }).analyze();
        expect(
          accessibility.violations,
          `Violations on ${route} (${theme}, ${viewport.name})`,
        ).toEqual([]);

        if (viewport.name === "phone") {
          const overflow = await page.evaluate(
            () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
          );
          expect(overflow, `Horizontal overflow on ${route} (phone)`).toBeLessThanOrEqual(1);
        }
      }
    }
  }
});
