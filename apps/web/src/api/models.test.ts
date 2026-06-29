import { describe, expect, it, vi } from "vitest";

import { getInstructionGraph, serializeCoverageQuery, serializeModelsQuery } from "./models";

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

describe("instruction graph API", () => {
  it("encodes the model identifier in the diagnostic endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ modelId: "model/id" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await getInstructionGraph("model/id");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/models/model%2Fid/instruction-graph",
      { signal: undefined },
    );
    fetchMock.mockRestore();
  });
});
