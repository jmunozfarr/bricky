import { readdir, readFile } from "node:fs/promises";
import { gzipSync } from "node:zlib";

const assetsDirectory = new URL("../dist/assets/", import.meta.url);
const javascriptFiles = (await readdir(assetsDirectory)).filter((name) => name.endsWith(".js"));
const sizes = await Promise.all(
  javascriptFiles.map(async (name) => ({
    name,
    gzipBytes: gzipSync(await readFile(new URL(name, assetsDirectory))).byteLength,
  })),
);
sizes.sort((left, right) => right.gzipBytes - left.gzipBytes);

const [viewer, application] = sizes;
if (!viewer || !application) throw new Error("Production JavaScript bundles were not found.");

const budgets = [
  { label: "lazy viewer", bundle: viewer, maximum: 270 * 1024 },
  { label: "application entry", bundle: application, maximum: 85 * 1024 },
];
for (const budget of budgets) {
  const kib = (budget.bundle.gzipBytes / 1024).toFixed(2);
  console.log(`${budget.label}: ${budget.bundle.name} ${kib} KiB gzip`);
  if (budget.bundle.gzipBytes > budget.maximum) {
    throw new Error(`${budget.label} exceeds its gzip budget.`);
  }
}
