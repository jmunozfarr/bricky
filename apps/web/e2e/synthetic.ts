import { APIRequestContext, expect } from "@playwright/test";

/**
 * Shared synthetic fixture: a four-step model with one subassembly, built from
 * official part ids (`3001` ×3 in the main file, `3020` ×2 in `wing.ldr`).
 *
 * Official ids do not make the BOM and coverage flows catalog-independent, as
 * this comment used to claim. `load_catalog_context` builds `official_part_ids`
 * from the `parts` table, so until the catalog is indexed every reference below
 * takes the unresolved branch in `ldraw_model_parser`, the BOM comes out empty,
 * and there is no requirement set to measure coverage against — the card reads
 * `Coverage unavailable` / `Requirements unknown` rather than the `40% covered`
 * these specs assert. `scripts/e2e.sh` therefore indexes a synthetic catalog
 * covering exactly these ids and colours before Playwright starts, without a
 * network fetch (`apps/api/tests/seed_e2e_catalog.py`).
 *
 * What is genuinely separable is the 3D scene: it reads part geometry from the
 * installed LDraw library, which stays a manual setup step, so the specs that
 * drive a scene skip until one is present.
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
