import { expect, test } from "@playwright/test";

import { importSyntheticModel, SYNTHETIC_MPD } from "./synthetic";

test.describe.configure({ mode: "default" });

const MODEL_NAME = "e2e-core-loop";

// The full user journey on the synthetic fixture: import -> models list ->
// build readiness -> workspace coverage -> guided steps -> delete. The
// import/coverage/delete flow is pure BOM arithmetic and must work without
// the LDraw library or catalog (CI); scene and inventory assertions switch
// on progressively with the installed capabilities.
test("core loop: import, readiness, workspace coverage, delete", async ({
  page,
  request,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium-desktop", "The core loop runs once in Chromium.");

  // Imports dedupe by content SHA-256: a byte-identical fixture would make
  // this test share (and race deletion of) builder.spec's model, so the
  // content carries a spec-unique marker.
  const modelId = await importSyntheticModel(
    request,
    MODEL_NAME,
    SYNTHETIC_MPD.replace("0 Name: main.ldr", "0 Name: main.ldr\n0 // e2e-core-loop variant"),
  );
  const libraryAvailable = (await request.get("/api/ldraw/LDConfig.ldr")).ok();
  const catalogAvailable = (await request.get("/api/parts/3020")).ok();

  // The e2e stack shares the personal database: snapshot the real inventory
  // row before mutating it and restore it afterwards.
  let previousQuantity: number | null = null;
  if (catalogAvailable) {
    const variants = await request.get("/api/inventory/items/3020");
    if (variants.ok()) {
      const rows = (await variants.json()) as { colorCode: number; quantity: number }[];
      previousQuantity = rows.find((row) => row.colorCode === 2)?.quantity ?? null;
    }
    const put = await request.put("/api/inventory/items/3020/2", { data: { quantity: 2 } });
    expect(put.ok()).toBe(true);
  }

  try {
    // 1. The imported model appears on /models with coverage facts.
    await page.goto(`/models?query=${MODEL_NAME}`);
    const card = page.locator(".model-card", { hasText: MODEL_NAME });
    await expect(card).toHaveCount(1);
    await expect(card).toContainText("MPD");
    if (catalogAvailable) {
      // 2 of 5 required pieces owned after the inventory write above.
      await expect(card).toContainText("40% covered");
      await expect(card).toContainText("3 pieces missing");
    } else {
      await expect(card).toContainText("0% covered");
      await expect(card).toContainText("5 pieces missing");
    }

    // 2. Instrument scene traffic before entering the workspace.
    const sceneRequests: string[] = [];
    const libraryPartRequests: string[] = [];
    page.on("request", (candidate) => {
      const url = candidate.url();
      if (url.includes("/instruction-occurrences/") && url.includes("/source")) {
        sceneRequests.push(url);
      }
      if (url.includes("/api/ldraw/parts/")) libraryPartRequests.push(url);
    });

    const playbackResponse = await request.get(`/api/models/${modelId}/instruction-playback`);
    const playback = (await playbackResponse.json()) as { rootOccurrenceId: string | null };
    const manifestOk =
      playback.rootOccurrenceId !== null &&
      (
        await request.get(
          `/api/models/${modelId}/instruction-occurrences/${playback.rootOccurrenceId}/build-manifest`,
        )
      ).ok();

    await card.getByRole("link", { name: "View", exact: true }).click();
    await page.waitForURL(`**/models/${modelId}/build`);

    if (manifestOk) {
      // 3. The workspace inspect panel owns build readiness now.
      await expect(page.getByText(/assembled model is shown in full colour/i)).toBeVisible();
      const readiness = page.locator(".builder-coverage-heading h4");
      await expect(readiness).toHaveText(catalogAvailable ? "40% covered" : "0% covered");
      await page.locator(".builder-parts-overview summary").click();
      const wingRow = page.locator(".builder-coverage-row", { hasText: "3020" });
      if (catalogAvailable) {
        await expect(wingRow.getByLabel("Coverage status: Complete")).toBeVisible();
        await expect(wingRow).toContainText("2 owned · 0 missing");
      } else {
        await expect(wingRow.getByLabel("Coverage status: Missing")).toBeVisible();
        await expect(wingRow).toContainText("0 owned · 2 missing");
      }

      // 4. Guided steps come from the manifest alone.
      await page.getByRole("button", { name: "Build", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Step 1" })).toBeVisible();
      await expect(page.getByText("of 4")).toBeVisible();

      if (libraryAvailable) {
        // 5. Builder-ready budget: the packed scene loads in at most two
        // requests (StrictMode double-mounts effects on the dev server, so
        // the first fetch is superseded once; production issues one) and no
        // per-part library traffic (packing inlines every dependency).
        await expect(page.locator(".viewer-message")).toBeHidden({ timeout: 30_000 });
        expect(sceneRequests.length, "packed scene request budget").toBeLessThanOrEqual(2);
        expect(libraryPartRequests, "no per-part library requests").toHaveLength(0);
      }
    }

    if (manifestOk) {
      // 6. The printable parts list walks every distinct build task.
      await page.goto(`/models/${modelId}/print`);
      await expect(page.getByRole("heading", { name: MODEL_NAME })).toBeVisible();
      await expect(page.getByText("2 build tasks")).toBeVisible();
      await expect(page.getByText(/Attach completed subassembly/)).toBeVisible();
      await expect(page.getByRole("heading", { name: "Step 4" })).toBeVisible();
    }

    // 7. Delete through the UI, dialog and toast included.
    await page.goto(`/models?query=${MODEL_NAME}`);
    await expect(card).toHaveCount(1);
    await card.getByRole("button", { name: "Delete", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText(`Delete ${MODEL_NAME}?`);
    await dialog.getByRole("button", { name: "Delete model" }).click();
    await expect(page.getByText(`Deleted ${MODEL_NAME}.`)).toBeVisible();
    await expect(card).toHaveCount(0);
  } finally {
    if (catalogAvailable) {
      if (previousQuantity === null) {
        await request.delete("/api/inventory/items/3020/2");
      } else {
        await request.put("/api/inventory/items/3020/2", {
          data: { quantity: previousQuantity },
        });
      }
    }
    // The UI flow already deleted the model; this only covers early failures.
    await request.delete(`/api/models/${modelId}`);
  }
});
