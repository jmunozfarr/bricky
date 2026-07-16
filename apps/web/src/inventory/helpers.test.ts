import { describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import type { InventoryImportResult } from "../api/inventory";
import {
  colorSwatchValue,
  decrementQuantity,
  importErrorMessage,
  importFormatLabel,
  importToastMessage,
  incrementQuantity,
  inventoryEmptyMessage,
  parseQuantityInput,
  validateInventoryImportFile,
} from "./helpers";

describe("inventory quantity helpers", () => {
  it("validates input boundaries", () => {
    expect(parseQuantityInput("1")).toBe(1);
    expect(parseQuantityInput("999999")).toBe(999999);
    expect(parseQuantityInput("0")).toBeNull();
    expect(parseQuantityInput("-1")).toBeNull();
    expect(parseQuantityInput("1.5")).toBeNull();
  });

  it("handles increment and decrement boundaries", () => {
    expect(incrementQuantity(999999)).toBe(999999);
    expect(decrementQuantity(2)).toBe(1);
    expect(decrementQuantity(1)).toBeNull();
  });
});

describe("inventory presentation helpers", () => {
  it("distinguishes empty inventory from an empty search", () => {
    expect(inventoryEmptyMessage(false)).toContain("inventory is empty");
    expect(inventoryEmptyMessage(true)).toContain("match these filters");
  });

  it("formats transparent colors and falls back for invalid hex", () => {
    expect(colorSwatchValue("#C91A09", 128)).toBe("rgba(201, 26, 9, 0.502)");
    expect(colorSwatchValue("invalid", 255)).toBe("rgba(128, 128, 128, 1.000)");
  });
});

describe("inventory import helpers", () => {
  const importResult = (overrides: Partial<InventoryImportResult>): InventoryImportResult => ({
    format: "native",
    strategy: "add",
    includeUnknown: true,
    appliedRowCount: 0,
    createdCount: 0,
    updatedCount: 0,
    unchangedCount: 0,
    skippedUnknownRowCount: 0,
    invalidRowCount: 0,
    quantityDelta: 0,
    ...overrides,
  });

  it("validates the selected import file before any request", () => {
    expect(validateInventoryImportFile(null)).toBe("Choose a CSV or XML file.");
    expect(validateInventoryImportFile({ name: "inventory.txt", size: 10 })).toContain(".csv");
    expect(validateInventoryImportFile({ name: "inventory.csv", size: 0 })).toContain("empty");
    expect(validateInventoryImportFile({ name: "inventory.csv", size: 1024 * 1024 + 1 })).toContain(
      "1 MiB",
    );
    expect(validateInventoryImportFile({ name: "Inventory.CSV", size: 42 })).toBeNull();
    expect(validateInventoryImportFile({ name: "wanted.xml", size: 42 })).toBeNull();
  });

  it("labels each detected import format", () => {
    expect(importFormatLabel("native")).toBe("Native CSV");
    expect(importFormatLabel("rebrickable")).toBe("Rebrickable CSV");
    expect(importFormatLabel("bricklink")).toBe("BrickLink XML");
  });

  it("maps import errors to actionable messages", () => {
    expect(importErrorMessage(new ApiError(413, "too big", "too big"))).toContain("upload-size");
    expect(importErrorMessage(new ApiError(422, "The CSV has no header row", "detail"))).toBe(
      "The CSV has no header row",
    );
    expect(importErrorMessage(new Error("network down"))).toBe("network down");
    expect(importErrorMessage("boom")).toBe("Inventory import failed.");
  });

  it("summarizes an applied import including skips and invalid rows", () => {
    expect(importToastMessage(importResult({ appliedRowCount: 1, createdCount: 1 }))).toBe(
      "Imported 1 row (1 new, 0 updated).",
    );
    expect(
      importToastMessage(
        importResult({
          appliedRowCount: 5,
          createdCount: 2,
          updatedCount: 2,
          unchangedCount: 1,
          skippedUnknownRowCount: 1,
          invalidRowCount: 2,
        }),
      ),
    ).toBe(
      "Imported 5 rows (2 new, 2 updated, 1 unchanged). " +
        "Skipped 1 row not in the catalog. Ignored 2 rows with errors.",
    );
  });
});
