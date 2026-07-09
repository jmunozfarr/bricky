import { APIRequestContext, expect } from "@playwright/test";

/**
 * Shared synthetic fixture: a four-step model with one subassembly, built
 * from official part ids so the BOM and coverage flows work even when the
 * LDraw library and catalog are absent (only 3D scenes need the library).
 */
export const SYNTHETIC_MPD = [
  "0 FILE main.ldr",
  "0 Name: main.ldr",
  "1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat",
  "0 STEP",
  "1 14 0 -24 0 1 0 0 0 1 0 0 0 1 3001.dat",
  "0 STEP",
  "1 1 0 -48 0 1 0 0 0 1 0 0 0 1 3001.dat",
  "0 STEP",
  "1 16 60 0 0 1 0 0 0 1 0 0 0 1 wing.ldr",
  "0 FILE wing.ldr",
  "1 2 0 0 0 1 0 0 0 1 0 0 0 1 3020.dat",
  "0 STEP",
  "1 2 0 -8 0 1 0 0 0 1 0 0 0 1 3020.dat",
  "0 NOFILE",
  "",
].join("\n");

export async function importSyntheticModel(
  request: APIRequestContext,
  name = "e2e-builder-smoke",
  content = SYNTHETIC_MPD,
): Promise<string> {
  const imported = await request.post("/api/models", {
    multipart: {
      name,
      file: {
        name: `${name}.mpd`,
        mimeType: "text/plain",
        buffer: Buffer.from(content),
      },
    },
  });
  if (imported.status() === 409) {
    const body = (await imported.json()) as { detail: { existingModelId: string } };
    return body.detail.existingModelId;
  }
  expect(imported.status()).toBe(201);
  const body = (await imported.json()) as { modelId: string };
  return body.modelId;
}
