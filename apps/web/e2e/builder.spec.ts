import { APIRequestContext, expect, Page, test } from "@playwright/test";

// Each of these tests drives a full WebGL builder session; running them in
// parallel workers starves the software rasterizer and flakes first paints.
// "default" keeps them sequential in one worker without serial-mode's
// abort-following-tests behavior.
test.describe.configure({ mode: "default" });

const SYNTHETIC_MPD = [
  "0 FILE main.ldr",
  "0 Name: main.ldr",
  "1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat",
  "0 STEP",
  "1 14 0 -24 0 1 0 0 0 1 0 0 0 1 3001.dat",
  "0 STEP",
  "1 1 0 -48 0 1 0 0 0 1 0 0 0 1 3001.dat",
  "0 STEP",
  "1 16 60 0 0 1 0 0 0 1 0 0 0 1 wing.ldr",
  "0 FILE wing.ldr",
  "1 2 0 0 0 1 0 0 0 1 0 0 0 1 3020.dat",
  "0 STEP",
  "1 2 0 -8 0 1 0 0 0 1 0 0 0 1 3020.dat",
  "0 NOFILE",
  "",
].join("\n");

// An embedded custom part whose subpart exists nowhere: the scene source
// parses, but the derived scene cannot be assembled (B7's failure shape).
const BROKEN_SYNTHETIC_MPD = [
  "0 FILE main.ldr",
  "0 Name: main.ldr",
  "1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat",
  "0 STEP",
  "1 71 0 -24 0 1 0 0 0 1 0 0 0 1 custom-broken.dat",
  "0 FILE custom-broken.dat",
  "0 !LDRAW_ORG Unofficial_Part",
  "1 16 0 0 0 1 0 0 0 1 0 0 0 1 s\\e2e-missing-subpart.dat",
  "0 NOFILE",
  "",
].join("\n");

async function importSyntheticModel(
  request: APIRequestContext,
  name = "e2e-builder-smoke",
  content = SYNTHETIC_MPD,
): Promise<string> {
  const imported = await request.post("/api/models", {
    multipart: {
      name,
      file: {
        name: `${name}.mpd`,
        mimeType: "text/plain",
        buffer: Buffer.from(content),
      },
    },
  });
  if (imported.status() === 409) {
    const body = (await imported.json()) as { detail: { existingModelId: string } };
    return body.detail.existingModelId;
  }
  expect(imported.status()).toBe(201);
  const body = (await imported.json()) as { modelId: string };
  return body.modelId;
}

async function dragAcrossCanvas(page: Page, deltaX: number, deltaY: number): Promise<void> {
  const canvas = page.locator(".builder-viewport canvas");
  const bounds = await canvas.boundingBox();
  expect(bounds).not.toBeNull();
  if (!bounds) return;
  const centerX = bounds.x + bounds.width / 2;
  const centerY = bounds.y + bounds.height / 2;
  await page.mouse.move(centerX, centerY);
  await page.mouse.down();
  await page.mouse.move(centerX + deltaX, centerY + deltaY, { steps: 12 });
  await page.mouse.up();
}

test("guides a build task with step transport and camera interaction", async ({
  page,
  request,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium-desktop",
    "The builder flow runs once in Chromium.",
  );
  const library = await request.get("/api/ldraw/LDConfig.ldr");
  test.skip(!library.ok(), "The builder flow requires an installed LDraw library.");
  const models = await request.get("/api/models?page=1");
  test.skip(!models.ok(), "The builder flow requires a migrated database.");

  const modelId = await importSyntheticModel(request);
  try {
    await page.goto(`/models/${modelId}/build`);
    await expect(page.getByRole("heading", { name: "Step 1" })).toBeVisible();
    await expect(page.getByText("of 4")).toBeVisible();
    await expect(page.locator(".viewer-message")).toBeHidden({ timeout: 20_000 });

    // Every step advance must repaint the 3D view without further
    // interaction. Consecutive advances matter: the first one used to be
    // repainted by an incidental layout resize while later ones went stale.
    const buildCanvas = page.locator(".builder-viewport canvas");
    let previousFrame = await buildCanvas.screenshot();
    for (const step of [2, 3]) {
      await page.getByRole("button", { name: "Next" }).click();
      await expect(page.getByRole("heading", { name: `Step ${step}` })).toBeVisible();
      await page.waitForTimeout(300);
      const frame = await buildCanvas.screenshot();
      expect(frame.equals(previousFrame), `step ${step} must repaint`).toBe(false);
      previousFrame = frame;
    }
    await page.getByRole("button", { name: "Previous" }).click();
    await page.getByRole("button", { name: "Previous" }).click();

    // Direct step entry jumps to the requested step.
    const stepInput = page.getByRole("spinbutton");
    await stepInput.fill("3");
    await expect(page.getByRole("heading", { name: "Step 3" })).toBeVisible();

    // Rapid scrubbing always lands on the last requested step.
    const slider = page.getByRole("slider", { name: "Scrub through building steps" });
    for (const value of ["1", "2", "3", "4", "2", "1", "4"]) {
      await slider.fill(value);
    }
    await expect(page.getByRole("heading", { name: "Step 4" })).toBeVisible();

    // Two separate drag gestures must both rotate the model. The second one
    // starts after the performance-regression debounce has expired, which is
    // the case that previously disposed the controls mid-drag.
    const canvas = page.locator(".builder-viewport canvas");
    const initial = await canvas.screenshot();
    await dragAcrossCanvas(page, 140, 40);
    await page.waitForTimeout(500);
    const afterFirstDrag = await canvas.screenshot();
    expect(afterFirstDrag.equals(initial)).toBe(false);
    await dragAcrossCanvas(page, -180, -60);
    await page.waitForTimeout(500);
    const afterSecondDrag = await canvas.screenshot();
    expect(afterSecondDrag.equals(afterFirstDrag)).toBe(false);

    // Subassembly tasks open their own local step timeline.
    await page.getByRole("button", { name: "Open build task" }).click();
    await expect(page.getByText("of 2")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Step 1" })).toBeVisible();
  } finally {
    await request.delete(`/api/models/${modelId}`);
  }
});

test("step transitions issue no scene or library requests", async ({ page, request }, testInfo) => {
  test.skip(testInfo.project.name !== "chromium-desktop", "The perf smoke runs once in Chromium.");
  const library = await request.get("/api/ldraw/LDConfig.ldr");
  test.skip(!library.ok(), "The builder flow requires an installed LDraw library.");
  const models = await request.get("/api/models?page=1");
  test.skip(!models.ok(), "The builder flow requires a migrated database.");

  const modelId = await importSyntheticModel(
    request,
    "e2e-builder-perf",
    SYNTHETIC_MPD.replace("0 Name: main.ldr", "0 Name: main.ldr\n0 // e2e-builder-perf variant"),
  );
  try {
    await page.goto(`/models/${modelId}/build`);
    await expect(page.getByRole("heading", { name: "Step 1" })).toBeVisible();
    await expect(page.locator(".viewer-message")).toBeHidden({ timeout: 20_000 });

    // VISUAL_BUILDER_DESIGN.md acceptance target: step selection changes
    // visibility and presentation only — no scene URL change, no loader
    // invocation, no library traffic.
    const sceneOrLibraryRequests: string[] = [];
    page.on("request", (issued) => {
      const url = issued.url();
      if (url.includes("/api/ldraw/") || url.includes("/source")) {
        sceneOrLibraryRequests.push(url);
      }
    });

    for (const step of [2, 3, 4]) {
      await page.getByRole("button", { name: "Next" }).click();
      await expect(page.getByRole("heading", { name: `Step ${step}` })).toBeVisible();
    }
    const stepInput = page.getByRole("spinbutton");
    await stepInput.fill("1");
    await stepInput.press("Enter");
    await expect(page.getByRole("heading", { name: "Step 1" })).toBeVisible();
    await page.waitForTimeout(500);

    expect(sceneOrLibraryRequests).toEqual([]);
  } finally {
    await request.delete(`/api/models/${modelId}`);
  }
});

test("recovers builder scene and playback after WebGL context loss", async ({
  page,
  request,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium-desktop", "WebGL recovery runs once in Chromium.");
  const library = await request.get("/api/ldraw/LDConfig.ldr");
  test.skip(!library.ok(), "The builder flow requires an installed LDraw library.");
  const models = await request.get("/api/models?page=1");
  test.skip(!models.ok(), "The builder flow requires a migrated database.");

  // A distinct model per test: imports dedupe by content hash, so sharing
  // one would let a parallel test's cleanup delete it mid-run.
  const modelId = await importSyntheticModel(
    request,
    "e2e-builder-webgl",
    SYNTHETIC_MPD.replace("0 Name: main.ldr", "0 Name: main.ldr\n0 // e2e-builder-webgl variant"),
  );
  try {
    await page.goto(`/models/${modelId}/build`);
    await expect(page.getByRole("heading", { name: "Step 1" })).toBeVisible();
    await expect(page.locator(".viewer-message")).toBeHidden({ timeout: 20_000 });

    const supported = await page
      .locator(".builder-viewport canvas")
      .evaluate((canvas: HTMLCanvasElement) => {
        const gl = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
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

    // The persistent scene host must reattach to the remounted canvas and
    // step playback must keep working (audit suspect A4).
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByRole("heading", { name: "Step 2" })).toBeVisible();
    await page.waitForTimeout(300);
    const frame = await page.locator(".builder-viewport canvas").screenshot();
    expect(frame.byteLength).toBeGreaterThan(0);
  } finally {
    await request.delete(`/api/models/${modelId}`);
  }
});

test("surfaces a scene that cannot be assembled as an error with retry", async ({
  page,
  request,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium-desktop",
    "The builder flow runs once in Chromium.",
  );
  const library = await request.get("/api/ldraw/LDConfig.ldr");
  test.skip(!library.ok(), "The builder flow requires an installed LDraw library.");
  const models = await request.get("/api/models?page=1");
  test.skip(!models.ok(), "The builder flow requires a migrated database.");

  const modelId = await importSyntheticModel(request, "e2e-builder-broken", BROKEN_SYNTHETIC_MPD);
  try {
    await page.goto(`/models/${modelId}/build`);
    // A failed scene load must reject into the error state — never an
    // indefinite "Preparing 3D scene" (audit suspect A8, seen as B7's hang).
    const alert = page.getByRole("alert");
    await expect(alert).toContainText("Unable to prepare this assembly", { timeout: 30_000 });
    await expect(alert.getByRole("button", { name: "Try again" })).toBeVisible();
  } finally {
    await request.delete(`/api/models/${modelId}`);
  }
});
