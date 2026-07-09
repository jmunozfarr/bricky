import { mkdir, stat, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { chromium } from "@playwright/test";

// Operator CLI: pre-renders official part thumbnails through the app's own
// viewer (the /thumbnail-harness route) into the derived thumbnails
// directory. Resumable: existing files are skipped unless --force.
//
//   --scope referenced   parts in the inventory and imported-model BOMs (default)
//   --scope all          the whole catalog (~20k parts, expect over an hour)
//   --limit N            stop after rendering N thumbnails
//   --force              re-render thumbnails that already exist

const baseUrl = process.env.PLAYWRIGHT_BASE_URL ?? "http://web:5173";
const outDir = process.env.THUMBNAILS_OUT ?? "/thumbnails";
const args = process.argv.slice(2);
const scope = args.includes("--scope") ? args[args.indexOf("--scope") + 1] : "referenced";
const limit = args.includes("--limit") ? Number(args[args.indexOf("--limit") + 1]) : Infinity;
const force = args.includes("--force");
if (scope !== "referenced" && scope !== "all") {
  throw new Error(`Unknown --scope ${scope}; use "referenced" or "all".`);
}

const safeName = /^[a-z0-9][a-z0-9._-]*$/;

async function fetchJson(path) {
  const response = await fetch(new URL(path, baseUrl));
  if (!response.ok) throw new Error(`${path} returned HTTP ${response.status}`);
  return response.json();
}

/** part id -> render asset url */
async function collectTargets() {
  const targets = new Map();
  if (scope === "all") {
    let page = 1;
    for (;;) {
      const result = await fetchJson(`/api/parts?page=${page}&pageSize=100`);
      for (const part of result.items) targets.set(part.partId, part.renderAssetUrl);
      if (page >= result.totalPages) break;
      page += 1;
    }
    return targets;
  }

  const referenced = new Set();
  let inventoryPage = 1;
  for (;;) {
    const result = await fetchJson(`/api/inventory/items?page=${inventoryPage}&pageSize=100`);
    for (const item of result.items) referenced.add(item.partId);
    if (inventoryPage >= result.totalPages) break;
    inventoryPage += 1;
  }
  let modelsPage = 1;
  for (;;) {
    const result = await fetchJson(`/api/models?page=${modelsPage}&pageSize=50`);
    for (const model of result.items) {
      const detail = await fetchJson(`/api/models/${model.modelId}`);
      for (const row of detail.bom) {
        referenced.add(row.partId);
        if (row.renderAssetUrl) targets.set(row.partId, row.renderAssetUrl);
      }
    }
    if (modelsPage >= result.totalPages) break;
    modelsPage += 1;
  }
  for (const partId of referenced) {
    if (targets.has(partId)) continue;
    const response = await fetch(new URL(`/api/parts/${encodeURIComponent(partId)}`, baseUrl));
    if (!response.ok) continue; // not in the catalog: nothing to render
    const detail = await response.json();
    if (detail.renderAssetUrl) targets.set(partId, detail.renderAssetUrl);
  }
  return targets;
}

const targets = await collectTargets();
console.log(`${targets.size} candidate parts (scope: ${scope}).`);
await mkdir(outDir, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 400, height: 400 } });
let rendered = 0;
let skipped = 0;
let failed = 0;

for (const [partId, assetUrl] of targets) {
  if (rendered >= limit) break;
  const fileName = `${partId.trim().toLowerCase()}.png`;
  if (!safeName.test(fileName)) {
    console.warn(`skipping unsafe part id: ${partId}`);
    failed += 1;
    continue;
  }
  const filePath = join(outDir, fileName);
  if (!force && (await stat(filePath).catch(() => null)) !== null) {
    skipped += 1;
    continue;
  }
  try {
    const query = `part=${encodeURIComponent(partId)}&asset=${encodeURIComponent(assetUrl)}`;
    await page.goto(`${baseUrl}/thumbnail-harness?${query}`);
    await page.waitForSelector('[data-render-state="ready"]', { timeout: 30_000 });
    await page.waitForTimeout(250);
    const shot = await page.locator(".thumbnail-harness canvas").screenshot({ type: "png" });
    await writeFile(filePath, shot);
    rendered += 1;
    if (rendered % 25 === 0) console.log(`${rendered} rendered…`);
  } catch (error) {
    failed += 1;
    console.warn(`failed ${partId}: ${error instanceof Error ? error.message : String(error)}`);
  }
}

await browser.close();
console.log(`Done: ${rendered} rendered, ${skipped} already existed, ${failed} failed.`);
