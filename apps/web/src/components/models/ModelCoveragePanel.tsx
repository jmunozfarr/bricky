import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { CompactInventoryEditor } from "../inventory/CompactInventoryEditor";
import { Alert, SegmentedControl } from "../ui/primitives";
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
                    <span
                      className="color-swatch"
                      style={{ backgroundColor: item.colorHex ?? "#808080" }}
                      aria-hidden="true"
                    />
                    <span className="builder-parts-overview-name">
                      {item.requiredQuantity}× {item.partName}
                    </span>
                    <small>
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
