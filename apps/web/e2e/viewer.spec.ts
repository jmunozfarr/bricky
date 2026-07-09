import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("persists the selected theme without accessibility violations", async ({ page }) => {
  await page.goto("/viewer-demo");
  await expect(page.getByRole("heading", { name: "Building-step demo" })).toBeVisible();
  await page.getByLabel("Theme").selectOption("dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.getByLabel("Theme")).toHaveValue("dark");

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test("supports viewer controls and keyboard step navigation", async ({ page }, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium-desktop",
    "WebGL interaction runs once in Chromium.",
  );
  await page.goto("/viewer-demo");

  const viewer = page.locator(".viewer-section");
  await expect(viewer.getByRole("toolbar", { name: "3D view controls" })).toBeVisible();
  await expect(viewer.getByText("Step 1 of 3", { exact: true })).toBeVisible();
  await viewer.locator(".viewer-frame").focus();
  await page.keyboard.press("ArrowRight");
  await expect(viewer.getByText("Step 2 of 3", { exact: true })).toBeVisible();
  await viewer.getByRole("button", { name: "Top" }).click();
  await viewer.getByRole("button", { name: "Zoom in" }).click();
});

test("responds to the first drag as soon as the canvas is available", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium-desktop",
    "WebGL interaction runs once in Chromium.",
  );
  await page.goto("/viewer-demo");

  const canvas = page.locator(".viewer-section canvas");
  await expect(canvas).toBeVisible();
  const bounds = await canvas.boundingBox();
  expect(bounds).not.toBeNull();
  if (!bounds) return;

  const before = await canvas.screenshot();
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width / 2 + 120, bounds.y + bounds.height / 2 + 30, {
    steps: 3,
  });
  await page.mouse.up();
  await page.waitForTimeout(100);
  const after = await canvas.screenshot();

  expect(after.equals(before)).toBe(false);
});

test("keeps the application within the tablet viewport", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "webkit-tablet", "Tablet layout is validated in WebKit.");
  await page.goto("/viewer-demo");
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
  await expect(page.getByRole("toolbar", { name: "3D view controls" })).toBeVisible();
});

test("reports and recovers from WebGL context loss", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "chromium-desktop", "WebGL recovery runs once in Chromium.");
  await page.goto("/viewer-demo");
  await expect(page.getByText("Step 1 of 3", { exact: true })).toBeVisible();
  const supported = await page.locator("canvas").evaluate((element) => {
    if (!(element instanceof HTMLCanvasElement)) return false;
    const gl = element.getContext("webgl2") ?? element.getContext("webgl");
    const extension = gl?.getExtension("WEBGL_lose_context");
    if (!extension) return false;
    extension.loseContext();
    window.setTimeout(() => extension.restoreContext(), 300);
    return true;
  });
  test.skip(!supported, "The browser does not expose WEBGL_lose_context.");
  await expect(page.getByText("The 3D graphics context was interrupted.")).toBeVisible();
  await expect(page.getByText("The 3D graphics context was interrupted.")).toBeHidden({
    timeout: 5_000,
  });
  await expect(page.getByText("Step 1 of 3", { exact: true })).toBeVisible();
});
