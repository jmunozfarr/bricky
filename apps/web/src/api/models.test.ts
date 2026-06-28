import { describe, expect, it } from "vitest";

import { serializeModelsQuery } from "./models";

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
