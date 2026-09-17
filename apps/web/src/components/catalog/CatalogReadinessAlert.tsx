import { CatalogAvailability, catalogRemediationCommand } from "../../catalog/catalogState";
import { Alert } from "../ui/primitives";

/**
 * Why model readiness cannot be trusted before the catalog is indexed: with no
 * `parts` rows nothing resolves official part references, so every coverage
 * verdict is computed over a requirement set that was never established. The
 * numbers the pages show are then correct and useless at the same time, which
 * is worth saying out loud next to them.
 *
 * Renders nothing once the catalog is usable, so callers can mount it
 * unconditionally.
 */
export function CatalogReadinessAlert({ availability }: { availability: CatalogAvailability }) {
  if (availability !== "not-installed" && availability !== "not-indexed") return null;
  const missing = availability === "not-installed";
  return (
    <Alert
      title={
        missing
          ? "The official LDraw library is not installed."
          : "The parts catalog is not indexed."
      }
    >
      Model part references cannot be resolved without it, so required pieces and build readiness
      stay unknown. Run <code>{catalogRemediationCommand(availability)}</code>, then reprocess the
      imported models.
    </Alert>
  );
}
