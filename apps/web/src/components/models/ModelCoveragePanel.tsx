import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { downloadMissingParts, MissingPartsFormat } from "../../api/models";
import { CompactInventoryEditor } from "../inventory/CompactInventoryEditor";
import { PartThumbnail } from "../parts/PartThumbnail";
import { Alert, SegmentedControl } from "../ui/primitives";
import { useToast } from "../ui/ToastProvider";
import {
  coverageEmptyMessage,
  coverageProgressValue,
  coverageStatusLabel,
  filterCoverageItems,
  formatCoveragePercentage,
} from "../../models/helpers";
import { toAsyncState } from "../../queries/async";
import { useModelCoverage } from "../../queries/hooks";

/**
 * Build-readiness and per-part coverage for the workspace inspect panel:
 * the compact successor of the retired model-detail coverage page. Rows
 * render only once the list is expanded so large models stay cheap.
 */
export function ModelCoveragePanel({ modelId }: { modelId: string }) {
  const coverage = toAsyncState(useModelCoverage(modelId, {}), "Unable to load coverage.");
  const [missingOnly, setMissingOnly] = useState(false);
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [exporting, setExporting] = useState<MissingPartsFormat | null>(null);
  const showToast = useToast();

  async function exportMissingParts(format: MissingPartsFormat) {
    setExporting(format);
    try {
      const result = await downloadMissingParts(modelId, format);
      if (format === "bricklink-xml" && result.skippedCount !== null && result.skippedCount > 0) {
        showToast(
          `${result.skippedCount} of ${result.totalCount ?? result.skippedCount} missing ` +
            "parts have no BrickLink match — the CSV export has the complete list.",
        );
      } else {
        showToast("Missing-parts export downloaded.", "success");
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Export failed.", "error");
    } finally {
      setExporting(null);
    }
  }

  const visible = useMemo(
    () =>
      coverage.kind === "ready"
        ? filterCoverageItems(coverage.data.items, query, "all", missingOnly)
        : [],
    [coverage, missingOnly, query],
  );

  if (coverage.kind === "loading") {
    return (
      <div className="page-message" role="status">
        Calculating build readiness…
      </div>
    );
  }
  if (coverage.kind === "error") {
    return <Alert title="Coverage request failed.">{coverage.message}</Alert>;
  }

  const summary = coverage.data.summary;
  const progress = coverageProgressValue(summary.pieceCoveragePercentage);
  return (
    <section className="builder-coverage" aria-labelledby="builder-coverage-title">
      <div className="builder-coverage-heading">
        <h4 id="builder-coverage-title">
          {formatCoveragePercentage(summary.pieceCoveragePercentage)} covered
        </h4>
        <span
          className={`build-state build-state--${summary.fullyBuildable ? "complete" : "incomplete"}`}
        >
          {summary.fullyBuildable
            ? "Fully buildable"
            : `${summary.totalMissingQuantity.toLocaleString()} missing`}
        </span>
      </div>
      <div
        className="coverage-progress"
        role="progressbar"
        aria-label={`${formatCoveragePercentage(progress)} of required physical pieces available`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress}
      >
        <span style={{ width: `${progress}%` }} />
      </div>
      <div className="coverage-export-actions">
        <button
          type="button"
          disabled={summary.totalMissingQuantity === 0 || exporting !== null}
          onClick={() => void exportMissingParts("csv")}
        >
          {exporting === "csv" ? "Exporting…" : "Export missing parts (CSV)"}
        </button>
        <button
          type="button"
          disabled={summary.totalMissingQuantity === 0 || exporting !== null}
          onClick={() => void exportMissingParts("bricklink-xml")}
        >
          {exporting === "bricklink-xml" ? "Exporting…" : "Export missing parts (BrickLink XML)"}
        </button>
      </div>
      <details
        className="builder-parts-overview"
        onToggle={(event) => setExpanded(event.currentTarget.open)}
      >
        <summary>
          All parts · {summary.totalRequiredQuantity.toLocaleString()} pieces ·{" "}
          {summary.uniqueItemCount.toLocaleString()} kinds
        </summary>
        {expanded && (
          <>
            <div className="builder-coverage-filters">
              <SegmentedControl
                className="builder-coverage-view-switch"
                label="Coverage view"
                value={missingOnly ? "missing" : "all"}
                options={[
                  { value: "all", label: "All parts" },
                  { value: "missing", label: "Missing" },
                ]}
                onChange={(value) => setMissingOnly(value === "missing")}
              />
              <label>
                <span>Search part ID or name</span>
                <input
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.currentTarget.value)}
                />
              </label>
            </div>
            {visible.length === 0 ? (
              <div className="empty-state" role="status">
                {coverageEmptyMessage(missingOnly, Boolean(query.trim()))}
              </div>
            ) : (
              <ul className="builder-parts-overview-list">
                {visible.map((item) => (
                  <li className="builder-coverage-row" key={`${item.partId}-${item.colorCode}`}>
                    <PartThumbnail partId={item.partId} />
                    <span className="builder-parts-overview-name">
                      {item.requiredQuantity}× {item.partName}
                    </span>
                    <small>
                      <span
                        className="color-swatch"
                        style={{ backgroundColor: item.colorHex ?? "#808080" }}
                        aria-hidden="true"
                      />
                      {item.partId} · {item.colorName} ({item.colorCode})
                    </small>
                    <div className="builder-coverage-row-status">
                      <span
                        className={`coverage-status coverage-status--${item.status}`}
                        aria-label={`Coverage status: ${coverageStatusLabel(item.status)}`}
                      >
                        {coverageStatusLabel(item.status)}
                      </span>
                      <small>
                        {item.ownedQuantity} owned · {item.missingQuantity} missing
                      </small>
                    </div>
                    <div className="coverage-actions">
                      {item.catalogAvailable ? (
                        <Link to={`/catalog?part=${encodeURIComponent(item.partId)}`}>
                          Official part
                        </Link>
                      ) : (
                        <span>Official part unavailable</span>
                      )}
                      <CompactInventoryEditor
                        partId={item.partId}
                        colorCode={item.colorCode}
                        ownedQuantity={item.ownedQuantity}
                        catalogAvailable={item.catalogAvailable && item.colorHex !== null}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </details>
    </section>
  );
}
