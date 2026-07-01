import { describe, expect, it } from "vitest";

import { CatalogStatus } from "../api/catalog";
import { getCatalogAvailability } from "./catalogState";

function status(overrides: Partial<CatalogStatus>): CatalogStatus {
  return {
    libraryInstalled: true,
    indexed: true,
    stale: false,
    partCount: 1,
    colorCount: 1,
    indexedAt: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("catalog availability", () => {
  it("distinguishes unavailable, unindexed, stale, and ready states", () => {
    expect(getCatalogAvailability(status({ libraryInstalled: false }))).toBe("not-installed");
    expect(getCatalogAvailability(status({ indexed: false }))).toBe("not-indexed");
    expect(getCatalogAvailability(status({ stale: true }))).toBe("stale");
    expect(getCatalogAvailability(status({}))).toBe("ready");
  });
});
