import { describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import {
  formatFileSize,
  coverageEmptyMessage,
  coverageProgressValue,
  coverageStatusLabel,
  filterModelBom,
  filterCoverageItems,
  formatCoveragePercentage,
  modelStatusLabel,
  modelUploadError,
  validateModelUpload,
} from "./helpers";

describe("model upload validation", () => {
  it("accepts LDR and MPD case-insensitively", () => {
    expect(validateModelUpload({ name: "demo.LDR", size: 12 })).toBeNull();
    expect(validateModelUpload({ name: "demo.mpd", size: 12 })).toBeNull();
  });

  it("rejects unsupported, empty, and oversized files", () => {
    expect(validateModelUpload({ name: "demo.io", size: 12 })).toMatch("Only");
    expect(validateModelUpload({ name: "demo.ldr", size: 0 })).toMatch("empty");
    expect(validateModelUpload({ name: "demo.ldr", size: 26 * 1024 * 1024 })).toMatch("25 MiB");
  });

  it("filters BOM rows by part or color metadata", () => {
    const rows = [
      {
        partId: "3001",
        partName: "Brick 2 x 4",
        category: "Brick",
        colorCode: 4,
        colorName: "Red",
        colorHex: "#ff0000",
        quantity: 2,
        catalogAvailable: true,
        renderAssetUrl: "/api/ldraw/parts/3001.dat",
      },
    ];
    expect(filterModelBom(rows, "red")).toEqual(rows);
    expect(filterModelBom(rows, "plate")).toEqual([]);
  });
});

describe("model presentation helpers", () => {
  it("formats sizes and statuses", () => {
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(1536)).toBe("1.5 KiB");
    expect(formatFileSize(2 * 1024 * 1024)).toBe("2.0 MiB");
    expect(modelStatusLabel("ready_with_warnings")).toBe("Ready with warnings");
  });

  it("maps duplicate and oversized API errors", () => {
    expect(modelUploadError(new ApiError(409, "Duplicate", null))).toMatch("existing");
    expect(modelUploadError(new ApiError(413, "Large", null))).toMatch("upload-size");
  });
});

describe("model coverage presentation", () => {
  const rows = [
    {
      partId: "3001",
      partName: "Brick 2 x 4",
      category: "Brick",
      colorCode: 4,
      colorName: "Red",
      colorHex: "#C91A09",
      requiredQuantity: 4,
      ownedQuantity: 2,
      availableQuantity: 2,
      missingQuantity: 2,
      coveragePercentage: 50,
      status: "partial" as const,
      catalogAvailable: true,
      renderAssetUrl: "/api/ldraw/parts/3001.dat",
    },
    {
      partId: "3002",
      partName: "Brick 2 x 3",
      category: "Brick",
      colorCode: 1,
      colorName: "Blue",
      colorHex: "#0055BF",
      requiredQuantity: 1,
      ownedQuantity: 1,
      availableQuantity: 1,
      missingQuantity: 0,
      coveragePercentage: 100,
      status: "complete" as const,
      catalogAvailable: true,
      renderAssetUrl: "/api/ldraw/parts/3002.dat",
    },
  ];

  it("formats percentages and clamps progress values", () => {
    expect(formatCoveragePercentage(65.567)).toBe("65.57%");
    expect(coverageProgressValue(-2)).toBe(0);
    expect(coverageProgressValue(120)).toBe(100);
    expect(coverageProgressValue(Number.NaN)).toBe(0);
  });

  it("provides explicit accessible status labels", () => {
    expect(coverageStatusLabel("complete")).toBe("Complete");
    expect(coverageStatusLabel("partial")).toBe("Partially covered");
    expect(coverageStatusLabel("missing")).toBe("Missing");
  });

  it("derives wishlist and status/search filters", () => {
    expect(filterCoverageItems(rows, "", "all", true)).toEqual([rows[0]]);
    expect(filterCoverageItems(rows, "2 x 3", "complete", false)).toEqual([rows[1]]);
    expect(filterCoverageItems(rows, "plate", "all", false)).toEqual([]);
  });

  it("uses the explicit complete-wishlist success state", () => {
    expect(coverageEmptyMessage(true, false)).toBe(
      "You have all the pieces required for this model.",
    );
    expect(coverageEmptyMessage(true, true)).toBe("No model parts match these filters.");
  });
});
