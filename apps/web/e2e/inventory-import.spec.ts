import AxeBuilder from "@axe-core/playwright";
import { APIRequestContext, expect, Page, test } from "@playwright/test";

import { importSyntheticModel } from "./synthetic";

const MODEL_NAME = "e2e-inventory-import";

// Specs run fully parallel against one shared personal database, so this
// test only touches part+colour keys no other spec writes or covers
// (core-loop.spec owns 3020/2 and the shared fixture's 3001 rows). The
// model requires 5 pieces; the CSV covers 3 of them.
const INVENTORY_MPD = [
  "0 FILE main.ldr",
  "0 Name: main.ldr",
  "1 71 0 0 0 1 0 0 0 1 0 0 0 1 3005.dat",
  "0 STEP",
  "1 19 0 -24 0 1 0 0 0 1 0 0 0 1 3004.dat",
  "1 19 0 -48 0 1 0 0 0 1 0 0 0 1 3004.dat",
  "0 STEP",
  "1 27 60 0 0 1 0 0 0 1 0 0 0 1 3622.dat",
  "1 27 60 -24 0 1 0 0 0 1 0 0 0 1 3622.dat",
  "0 NOFILE",
  "",
].join("\n");

const CSV_KEYS = [
  { partId: "3005", colorCode: 71, quantity: 1 },
  { partId: "3004", colorCode: 19, quantity: 2 },
  { partId: "e2e-mystery-part", colorCode: 4, quantity: 2 },
] as const;

const IMPORT_CSV = [
  "part_id,color_code,quantity",
  ...CSV_KEYS.map((key) => `${key.partId},${key.colorCode},${key.quantity}`),
  "3005,16,1", // colour 16 is non-physical: reported as an invalid row
  "",
].join("\n");

async function quantityFor(
  request: APIRequestContext,
  partId: string,
  colorCode: number,
): Promise<number | null> {
  const response = await request.get(`/api/inventory/items/${encodeURIComponent(partId)}`);
  if (!response.ok()) return null;
  const rows = (await response.json()) as { colorCode: number; quantity: number }[];
  return rows.find((row) => row.colorCode === colorCode)?.quantity ?? null;
}

async function totalPieces(page: Page): Promise<number> {
  const tile = page
    .locator(".inventory-summary article", { hasText: "Total pieces" })
    .locator("strong");
  await tile.waitFor();
  return Number((await tile.innerText()).replace(/[^0-9]/g, ""));
}

// Bulk CSV import end to end: dropzone -> server dry run -> strategy switch
// -> apply -> refreshed summary, orphan inventory row, and model coverage.
// Works with or without the LDraw library/catalog: without a catalog every
// row lands in the unknown bucket and still applies (include-unknown is on
// by default), and coverage stays pure BOM-vs-inventory arithmetic.
test("inventory import: preview, apply, coverage refresh", async ({ page, request }, testInfo) => {
  test.skip(testInfo.project.name !== "chromium-desktop", "The import flow runs once in Chromium.");

  const modelId = await importSyntheticModel(request, MODEL_NAME, INVENTORY_MPD);

  // Snapshot the rows this test writes, start them from a clean slate, and
  // restore them afterwards.
  const previous = [];
  for (const key of CSV_KEYS) {
    previous.push({ ...key, quantity: await quantityFor(request, key.partId, key.colorCode) });
    await request.delete(`/api/inventory/items/${key.partId}/${key.colorCode}`);
  }

  try {
    await page.goto("/inventory");

    await page.getByRole("button", { name: "Import CSV" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: "Import inventory from CSV" })).toBeVisible();

    // 1. Selecting a file runs the server-side dry run.
    const previewed = page.waitForResponse(
      (response) => response.url().includes("/api/inventory/import/preview") && response.ok(),
    );
    await dialog.getByLabel("CSV file").setInputFiles({
      name: "e2e-inventory.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(IMPORT_CSV),
    });
    await previewed;
    await expect(dialog.getByRole("group", { name: "Merge strategy" })).toBeVisible();
    await expect(dialog.getByText("1 invalid rows will be ignored")).toBeVisible();
    await expect(dialog.getByText("Not in catalog").first()).toBeVisible();
    await expect(dialog.getByText("0 → 2").first()).toBeVisible();
    await expect(dialog.getByRole("checkbox")).toBeChecked();

    // 2. Switching strategy recomputes the preview with the retained file.
    const replaced = page.waitForResponse(
      (response) => response.url().includes("/api/inventory/import/preview") && response.ok(),
    );
    await dialog.getByRole("button", { name: "Replace quantities" }).click();
    await replaced;
    await expect(dialog.getByRole("button", { name: "Replace quantities" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    // 3. The open dialog with a rendered preview passes the axe scan (the
    // route matrix in a11y.spec.ts only covers closed-dialog states).
    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(accessibility.violations, "axe violations with the import dialog open").toEqual([]);

    // 4. Apply and toast. The toast waits for the apply round trip plus the
    // inventory/models refetches, which can be slow on a cold dev server
    // with both browser projects running.
    await dialog.getByRole("button", { name: "Import", exact: true }).click();
    await expect(page.getByText(/Imported 3 rows \(3 new, 0 updated\)/)).toBeVisible({
      timeout: 20_000,
    });
    await expect(dialog).toBeHidden();

    // 5. Exact per-key persistence, then the summary tile catching up to the
    // server without a reload (the absolute total is shared with concurrent
    // specs, so assert convergence rather than a fixed number).
    for (const key of CSV_KEYS) {
      expect(await quantityFor(request, key.partId, key.colorCode)).toBe(key.quantity);
    }
    await expect
      .poll(
        async () => {
          const summary = await request.get("/api/inventory/summary");
          const { totalQuantity } = (await summary.json()) as { totalQuantity: number };
          return (await totalPieces(page)) === totalQuantity ? "in sync" : "stale";
        },
        { timeout: 15_000 },
      )
      .toBe("in sync");

    // 6. The catalog-unknown row is a first-class inventory item.
    await page.getByLabel("Search inventory").fill("e2e-mystery-part");
    const orphan = page.locator(".inventory-card", { hasText: "e2e-mystery-part" });
    await expect(orphan).toHaveCount(1);
    await expect(orphan).toContainText("× 2");
    await expect(orphan).toContainText("Catalog metadata unavailable");

    // 7. Model coverage reflects the import without any manual refresh:
    // 3 of the 5 required pieces are now owned.
    await page.goto(`/models?query=${MODEL_NAME}`);
    const modelCard = page.locator(".model-card", { hasText: MODEL_NAME });
    await expect(modelCard).toHaveCount(1);
    await expect(modelCard).toContainText("60% covered");
    await expect(modelCard).toContainText("2 pieces missing");
  } finally {
    for (const key of CSV_KEYS) {
      await request.delete(`/api/inventory/items/${key.partId}/${key.colorCode}`);
    }
    const restoreRows = previous.filter((key) => key.quantity !== null);
    if (restoreRows.length > 0) {
      // The import endpoint restores exact quantities even when the catalog
      // is absent (a PUT would 404 on catalog-unknown parts).
      await request.post("/api/inventory/import/apply", {
        multipart: {
          strategy: "replace",
          includeUnknown: "true",
          file: {
            name: "restore.csv",
            mimeType: "text/csv",
            buffer: Buffer.from(
              [
                "part_id,color_code,quantity",
                ...restoreRows.map((key) => `${key.partId},${key.colorCode},${key.quantity}`),
                "",
              ].join("\n"),
            ),
          },
        },
      });
    }
    await request.delete(`/api/models/${modelId}`);
  }
});
