import { describe, expect, it } from "vitest";

import { formatPageTitle } from "./pageTitle";

describe("page titles", () => {
  it("combines useful route context with the application name", () => {
    expect(formatPageTitle("Inventory")).toBe("Inventory · Bricky");
    expect(formatPageTitle("  ")).toBe("Bricky");
  });
});
