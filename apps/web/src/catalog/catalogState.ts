import { CatalogStatus } from "../api/catalog";

export type CatalogAvailability = "not-installed" | "not-indexed" | "stale" | "ready";

export function getCatalogAvailability(status: CatalogStatus): CatalogAvailability {
  if (!status.libraryInstalled) {
    return "not-installed";
  }
  if (!status.indexed) {
    return "not-indexed";
  }
  return status.stale ? "stale" : "ready";
}
