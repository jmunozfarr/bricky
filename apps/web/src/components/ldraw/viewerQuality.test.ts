import { describe, expect, it } from "vitest";

import { maximumViewerDpr } from "./viewerQuality";

describe("viewer quality policy", () => {
  it("caps tablet and desktop device pixel ratios", () => {
    expect(maximumViewerDpr(800, 3)).toBe(1.5);
    expect(maximumViewerDpr(1280, 3)).toBe(2);
    expect(maximumViewerDpr(1280, 1.25)).toBe(1.25);
    expect(maximumViewerDpr(1280, 0.75)).toBe(1);
  });
});
