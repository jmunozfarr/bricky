import AxeBuilder from "@axe-core/playwright";
import { APIRequestContext, expect, Page, test } from "@playwright/test";

import { importSyntheticModel, SYNTHETIC_MPD } from "./synthetic";

const MODEL_NAME = "e2e-inventory-import";

// Keys the CSV writes: two synthetic-model parts plus a part that can never
// exist in the catalog. Quantities cover 3 of the model's 5 required pieces.
const CSV_KEYS = [
  { partId: "3001", colorCode: 4, quantity: 1 },
  { partId: "3020", colorCode: 2, quantity: 2 },
  { partId: "e2e-mystery-part", colorCode: 4, quantity: 2 },
] as const;

const IMPORT_CSV = [
  "part_id,color_code,quantity",
  ...CSV_KEYS.map((key) => `${key.partId},${key.colorCode},${key.quantity}`),
  "3001,16,1", // colour 16 is non-physical: reported as an invalid row
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

  const modelId = await importSyntheticModel(
    request,
    MODEL_NAME,
    SYNTHETIC_MPD.replace("0 Name: main.ldr", "0 Name: main.ldr\n0 // e2e-inventory variant"),
  );

  // The e2e stack shares the personal database: snapshot the rows this test
  // writes, start them from a clean slate, and restore them afterwards.
  const previous = [];
  for (const key of CSV_KEYS) {
    previous.push({ ...key, quantity: await quantityFor(request, key.partId, key.colorCode) });
    await request.delete(`/api/inventory/items/${key.partId}/${key.colorCode}`);
  }

  try {
    await page.goto("/inventory");
    const baseline = await totalPieces(page);

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

    // 4. Apply, toast, and the refreshed summary tiles. The toast waits for
    // the apply round trip plus the inventory/models refetches, which can be
    // slow on a cold dev server with both browser projects running.
    await dialog.getByRole("button", { name: "Import", exact: true }).click();
    await expect(page.getByText(/Imported 3 rows \(3 new, 0 updated\)/)).toBeVisible({
      timeout: 20_000,
    });
    await expect(dialog).toBeHidden();
    await expect.poll(() => totalPieces(page), { timeout: 15_000 }).toBe(baseline + 5);

    // 5. The catalog-unknown row is a first-class inventory item.
    await page.getByLabel("Search inventory").fill("e2e-mystery-part");
    const orphan = page.locator(".inventory-card", { hasText: "e2e-mystery-part" });
    await expect(orphan).toHaveCount(1);
    await expect(orphan).toContainText("× 2");
    await expect(orphan).toContainText("Catalog metadata unavailable");

    // 6. Model coverage reflects the import without any manual refresh:
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
