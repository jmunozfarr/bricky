import { describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import {
  formatFileSize,
  filterModelBom,
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
