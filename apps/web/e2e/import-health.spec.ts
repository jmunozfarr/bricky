import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { importSyntheticModel } from "./synthetic";

test.describe.configure({ mode: "default" });

const MODEL_NAME = "e2e-import-health";

// An LDCad-style generated section that yields no physical parts: the parser
// flags it with a resolvable generated_section_without_parts warning without
// needing the LDraw library or catalog, so the ignore/remove flow runs
// everywhere; the map flow additionally needs the indexed catalog.
const GENERATED_MPD = [
  "0 FILE main.ldr",
  "0 Name: main.ldr",
  "0 // e2e-import-health fixture",
  "1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat",
  "0 STEP",
  "1 16 0 -24 0 1 0 0 0 1 0 0 0 1 flexpath.ldr",
  "0 FILE flexpath.ldr",
  "0 !LDCAD GENERATED [meta=e2e]",
  "0 // path section without physical parts",
  "0 NOFILE",
  "",
].join("\n");

test("import health: resolve, undo, and map reference warnings", async ({
  page,
  request,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium-desktop",
    "The import-health loop runs once in Chromium.",
  );

  const modelId = await importSyntheticModel(request, MODEL_NAME, GENERATED_MPD);
  const catalogAvailable = (await request.get("/api/parts/3001")).ok();
  const playbackResponse = await request.get(`/api/models/${modelId}/instruction-playback`);
  const playback = (await playbackResponse.json()) as { rootOccurrenceId: string | null };
  const manifestOk =
    playback.rootOccurrenceId !== null &&
    (
      await request.get(
        `/api/models/${modelId}/instruction-occurrences/${playback.rootOccurrenceId}/build-manifest`,
      )
    ).ok();
  test.skip(!manifestOk, "The workspace inspect panel needs the build manifest.");

  try {
    await page.goto(`/models/${modelId}/build`);
    await expect(page.getByRole("heading", { name: "Import health" })).toBeVisible();

    // 1. The generated-section warning arrives with remediation actions.
    const warningRow = page.locator(".import-health-issue", { hasText: "flexpath.ldr" });
    await expect(warningRow).toContainText("Generated section without parts");

    // The panel (and its actions) stays axe-clean.
    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(accessibility.violations, "Violations with the import health panel open").toEqual([]);

    // 2. Ignoring creates a manual resolution and reprocesses server-side.
    await warningRow.getByRole("button", { name: "Ignore" }).click();
    await expect(page.getByText("Ignored flexpath.ldr and reprocessed the model.")).toBeVisible();
    const ignoredRow = page.locator(".import-health-issue", { hasText: "flexpath.ldr" });
    await expect(ignoredRow).toContainText("Ignored reference");
    await expect(page.getByText("Manual resolutions")).toBeVisible();
    await expect(page.getByText("Excluded from the BOM")).toBeVisible();

    // 3. Removing the resolution restores the original warning.
    await page.getByRole("button", { name: "Remove" }).click();
    await expect(
      page.getByText("Removed the resolution for flexpath.ldr and reprocessed the model."),
    ).toBeVisible();
    await expect(page.locator(".import-health-issue", { hasText: "flexpath.ldr" })).toContainText(
      "Generated section without parts",
    );

    if (catalogAvailable) {
      // 4. Mapping through the part-picker dialog counts the reference as an
      // official part at the chosen colour.
      await page
        .locator(".import-health-issue", { hasText: "flexpath.ldr" })
        .getByRole("button", { name: "Map to part…" })
        .click();
      const dialog = page.locator(".import-health-dialog");
      await expect(dialog.getByRole("heading", { name: "Map flexpath.ldr" })).toBeVisible();
      await dialog.getByLabel("Search official parts").fill("3001");
      await dialog.getByRole("button", { name: "3001 Brick 2 x 4" }).click();
      await dialog.getByRole("button", { name: "Map reference" }).click();
      await expect(
        page.getByText("Mapped flexpath.ldr to 3001 and reprocessed the model."),
      ).toBeVisible();
      await expect(page.getByText("Mapped to 3001")).toBeVisible();
    }
  } finally {
    await request.delete(`/api/models/${modelId}`);
  }
});
