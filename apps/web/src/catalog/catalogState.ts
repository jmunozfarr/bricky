import { CatalogStatus } from "../api/catalog";

export type CatalogAvailability = "not-installed" | "not-indexed" | "stale" | "ready";

/** The documented setup steps, never run from the browser. */
export const LIBRARY_COMMAND =
  "docker compose run --rm api python -m app.cli.ldraw_library install";
export const REBUILD_COMMAND = "docker compose exec api python -m app.cli.ldraw_catalog rebuild";

export function getCatalogAvailability(status: CatalogStatus): CatalogAvailability {
  if (!status.libraryInstalled) {
    return "not-installed";
  }
  if (!status.indexed) {
    return "not-indexed";
  }
  return status.stale ? "stale" : "ready";
}

/** The command that moves the catalog out of the given state. */
export function catalogRemediationCommand(availability: CatalogAvailability): string {
  return availability === "not-installed" ? LIBRARY_COMMAND : REBUILD_COMMAND;
}
