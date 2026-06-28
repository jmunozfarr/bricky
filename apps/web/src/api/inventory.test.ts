import { describe, expect, it } from "vitest";

import { serializeInventoryQuery } from "./inventory";

describe("inventory query serialization", () => {
  it("encodes filters and pagination deterministically", () => {
    expect(
      serializeInventoryQuery({
        query: "brick & plate",
        category: "Brick",
        colorCode: 4,
        page: 2,
      }),
    ).toBe("query=brick+%26+plate&category=Brick&colorCode=4&page=2");
  });
});
