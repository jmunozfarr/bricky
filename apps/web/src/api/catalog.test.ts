import { describe, expect, it } from "vitest";

import { nextPage, previousPage, serializePartsQuery } from "./catalog";

describe("catalog query serialization", () => {
  it("encodes search values safely and omits empty filters", () => {
    expect(serializePartsQuery({ query: "brick & plate", category: "", page: 2 })).toBe(
      "query=brick+%26+plate&page=2",
    );
  });
});

describe("catalog pagination", () => {
  it("does not move outside available page limits", () => {
    expect(previousPage(1)).toBe(1);
    expect(previousPage(3)).toBe(2);
    expect(nextPage(2, 3)).toBe(3);
    expect(nextPage(3, 3)).toBe(3);
  });
});
