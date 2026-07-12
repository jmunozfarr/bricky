// @vitest-environment jsdom

import { MeshStandardMaterial } from "three";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createLDrawLoader, prepareOfficialLoader } from "./ldrawLoaderSetup";

// Minimal LDConfig: like the real one, it defines the code-16 main colour
// (pale yellow), so any accidental re-registration under code 16 is a no-op.
const LDCONFIG = [
  "0 !COLOUR Main_Colour CODE 16 VALUE #FFFF80 EDGE #333333",
  "0 !COLOUR Edge_Colour CODE 24 VALUE #7F7F7F EDGE #333333",
  "0 !COLOUR Red CODE 4 VALUE #C91A09 EDGE #333333",
].join("\n");

describe("prepareOfficialLoader", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps every palette material labelled with its own colour code", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(LDCONFIG)));
    const loader = createLDrawLoader();
    // Absolute URL: the node test environment has no document base to
    // resolve the app's usual relative /api/ldraw path against.
    await prepareOfficialLoader(loader, "http://api.test/ldraw/LDConfig.ldr", "/api/ldraw/");

    // The worker scene transfer serializes materials by userData.code and
    // re-resolves that code on the main thread: a red material mislabelled
    // "16" comes back as the pale-yellow main colour (red bodywork rendered
    // yellow in the builder).
    const red = loader.getMaterial("4") as MeshStandardMaterial;
    expect(red.userData.code).toBe("4");
    expect(red.color.getHex()).toBe(0xc91a09);

    const main = loader.getMaterial("16") as MeshStandardMaterial;
    expect(main.userData.code).toBe("16");
    expect(main.color.getHex()).toBe(0xffff80);
  });
});
