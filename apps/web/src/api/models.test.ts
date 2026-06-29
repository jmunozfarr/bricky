import { describe, expect, it } from "vitest";

import { serializeCoverageQuery, serializeModelsQuery } from "./models";

describe("models query serialization", () => {
  it("encodes filters and clamps the page", () => {
    expect(
      serializeModelsQuery({
        query: "truck & trailer",
        status: "ready_with_warnings",
        page: 0,
      }),
    ).toBe("query=truck+%26+trailer&status=ready_with_warnings&page=1");
  });
});

describe("coverage query serialization", () => {
  it("encodes validated status and trimmed part search", () => {
    expect(
      serializeCoverageQuery({ status: "partial", query: "  3001 & red  " }),
    ).toBe("status=partial&query=3001+%26+red");
  });

  it("omits empty filters", () => {
    expect(serializeCoverageQuery({ query: "  " })).toBe("");
  });
});
