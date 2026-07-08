import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { CoverageStatus, InstructionGraph, ModelCoverage, ModelCoverageItem } from "../api/models";
import { CompactInventoryEditor } from "../components/inventory/CompactInventoryEditor";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { useToast } from "../components/ui/ToastProvider";
import { Alert, ModelStatusPill } from "../components/ui/primitives";
import { toAsyncState } from "../queries/async";
import {
  useDeleteModel,
  useInstructionGraph,
  useModelCoverage,
  useModelDetail,
} from "../queries/hooks";
import {
  coverageEmptyMessage,
  coverageProgressValue,
  coverageStatusLabel,
  filterCoverageItems,
  formatCoveragePercentage,
} from "../models/helpers";

type CoverageView = "all" | "wishlist";

export default function ModelDetailPage() {
  const { modelId = "" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [coverageView, setCoverageView] = useState<CoverageView>("all");
  const [coverageStatus, setCoverageStatus] = useState<CoverageStatus | "all">("all");
  const [coverageQuery, setCoverageQuery] = useState("");
  const returnSearch = params.get("return");
  const returnTarget = `/models${returnSearch ? `?${returnSearch}` : ""}`;
  // Coverage refetches automatically when inventory mutations invalidate the
  // "models" queries — this replaces the old inventory-changed event bus.
  const detailState = toAsyncState(useModelDetail(modelId), "Unable to load model.");
  const coverage = toAsyncState(useModelCoverage(modelId, {}), "Unable to load coverage.");
  const deletion = useDeleteModel();
  const deleting = deletion.isPending;
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const showToast = useToast();
  const state =
    deletion.error !== null
      ? ({
          kind: "error",
          message: deletion.error instanceof Error ? deletion.error.message : "Delete failed.",
        } as const)
      : detailState;

  function remove() {
    deletion.mutate(modelId, {
      onSuccess: () => {
        setConfirmingDelete(false);
        showToast("Model deleted.");
        void navigate(returnTarget);
      },
      onError: () => setConfirmingDelete(false),
    });
  }

  const visibleCoverage = useMemo(
    () =>
      coverage.kind === "ready"
        ? filterCoverageItems(
            coverage.data.items,
            coverageQuery,
            coverageStatus,
            coverageView === "wishlist",
          )
        : [],
    [coverage, coverageQuery, coverageStatus, coverageView],
  );

  if (state.kind === "loading") return <div className="page-message">Loading model…</div>;
  if (state.kind === "error") {
    return <Alert title="Model request failed.">{state.message}</Alert>;
  }
  const model = state.data;

  return (
    <div className="model-detail">
      <div className="detail-actions">
        <Link className="button-link" to={returnTarget}>
          Back to models
        </Link>
        <button
          className="danger-button"
          disabled={deleting}
          onClick={() => setConfirmingDelete(true)}
        >
          {deleting ? "Deleting…" : "Delete model"}
        </button>
        <ConfirmDialog
          open={confirmingDelete}
          title="Delete this model?"
          description="The imported model and its preserved source file are removed permanently."
          confirmLabel="Delete model"
          destructive
          busy={deleting}
          onConfirm={remove}
          onCancel={() => setConfirmingDelete(false)}
        />
      </div>
      <section className="page-panel">
        <div className="page-heading catalog-heading">
          <div>
            <p className="eyebrow">Imported {model.sourceFormat.toUpperCase()}</p>
            <h2>{model.name}</h2>
          </div>
          <ModelStatusPill status={model.importStatus} />
        </div>
        <dl className="part-metadata">
          <Meta label="Original filename" value={model.originalFilename} />
          <Meta label="Top-level source steps" value={model.declaredStepCount} />
          <Meta label="Physical pieces" value={model.totalPartQuantity} />
          <Meta label="Unique part/color rows" value={model.uniquePartColorCount} />
          <Meta label="Unresolved references" value={model.unresolvedReferenceCount} />
          <Meta label="Source SHA-256" value={model.sourceSha256} />
        </dl>
      </section>

      <section className="page-panel builder-launch-panel" aria-labelledby="builder-launch-title">
        <div>
          <p className="eyebrow">Interactive instructions</p>
          <h2 id="builder-launch-title">Visual builder</h2>
          <p>
            Follow authored steps with current parts highlighted, inventory context, and guided
            subassembly tasks.
          </p>
        </div>
        <Link
          className="button-link"
          to={`/models/${model.modelId}/build`}
          onMouseEnter={() => void import("./VisualBuilderPage")}
          onFocus={() => void import("./VisualBuilderPage")}
        >
          Open visual builder
        </Link>
      </section>

      {params.get("debug") === "viewer" && <InstructionGraphPanel modelId={model.modelId} />}

      {coverage.kind === "loading" && (
        <div className="page-message">Calculating build readiness…</div>
      )}
      {coverage.kind === "error" && (
        <Alert title="Coverage request failed.">{coverage.message}</Alert>
      )}
      {coverage.kind === "ready" && (
        <>
          <BuildReadiness coverage={coverage.data} />
          <section className="page-panel coverage-panel" aria-labelledby="coverage-title">
            <div className="page-heading catalog-heading">
              <div>
                <p className="eyebrow">Exact part and color matching</p>
                <h2 id="coverage-title">
                  {coverageView === "all" ? "Model coverage" : "Missing parts"}
                </h2>
              </div>
              <p>{visibleCoverage.length.toLocaleString()} unique rows shown</p>
            </div>

            <div className="segmented-control" aria-label="Coverage view">
              <button
                type="button"
                aria-pressed={coverageView === "all"}
                onClick={() => {
                  setCoverageView("all");
                  setCoverageStatus("all");
                }}
              >
                All parts
              </button>
              <button
                type="button"
                aria-pressed={coverageView === "wishlist"}
                onClick={() => {
                  setCoverageView("wishlist");
                  setCoverageStatus("all");
                }}
              >
                Missing parts
              </button>
            </div>

            <div className="coverage-filters">
              <label>
                <span>Search part ID or name</span>
                <input
                  type="search"
                  value={coverageQuery}
                  onChange={(event) => setCoverageQuery(event.currentTarget.value)}
                />
              </label>
              <label>
                <span>Coverage status</span>
                <select
                  value={coverageStatus}
                  onChange={(event) =>
                    setCoverageStatus(event.currentTarget.value as CoverageStatus | "all")
                  }
                >
                  <option value="all">All</option>
                  <option value="missing">Missing</option>
                  <option value="partial">Partial</option>
                  <option value="complete">Complete</option>
                </select>
              </label>
            </div>

            {visibleCoverage.length === 0 ? (
              <div className="empty-state" role="status">
                {coverageEmptyMessage(
                  coverageView === "wishlist",
                  Boolean(coverageQuery.trim() || coverageStatus !== "all"),
                )}
              </div>
            ) : (
              <CoverageTable items={visibleCoverage} />
            )}
          </section>
        </>
      )}

      {model.issues.length > 0 && (
        <section className="page-panel">
          <div className="page-heading">
            <p className="eyebrow">Import diagnostics</p>
            <h2>Warnings</h2>
          </div>
          <ul className="issue-list">
            {model.issues.map((issue, index) => (
              <li key={`${issue.code}-${index}`}>
                <strong>{issue.code.replaceAll("_", " ")}</strong>
                <span>
                  {issue.message}
                  {issue.referencedFilename ? ` — ${issue.referencedFilename}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

type InstructionGraphState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; data: InstructionGraph }
  | { kind: "error"; message: string };

function InstructionGraphPanel({ modelId }: { modelId: string }) {
  const [opened, setOpened] = useState(false);
  const query = useInstructionGraph(modelId, opened);
  const state: InstructionGraphState = !opened
    ? { kind: "idle" }
    : query.isError
      ? {
          kind: "error",
          message:
            query.error instanceof Error
              ? query.error.message
              : "Unable to load instruction graph.",
        }
      : query.data !== undefined
        ? { kind: "ready", data: query.data }
        : { kind: "loading" };

  const visibleOccurrenceLimit = 500;
  return (
    <details
      className="page-panel instruction-graph-panel"
      onToggle={(event) => {
        if (event.currentTarget.open) setOpened(true);
      }}
    >
      <summary>
        <span>
          <span className="eyebrow">Developer diagnostic</span>Instruction hierarchy
        </span>
      </summary>
      {state.kind === "loading" && <div className="page-message">Parsing instruction graph…</div>}
      {state.kind === "error" && <Alert title={state.message} />}
      {state.kind === "ready" && (
        <div className="instruction-graph-content">
          <dl className="part-metadata">
            <Meta label="Model definitions" value={state.data.modelDefinitionCount} />
            <Meta label="Expanded occurrences" value={state.data.expandedOccurrenceCount} />
            <Meta label="Instruction nodes" value={state.data.instructionNodeCount} />
            <Meta label="Maximum depth" value={state.data.maximumNestingDepth} />
            <Meta label="Truncated" value={state.data.truncated ? "Yes" : "No"} />
          </dl>
          {state.data.issues.length > 0 && (
            <ul className="issue-list">
              {state.data.issues.map((issue, index) => (
                <li key={`${issue.code}-${index}`}>
                  <strong>{issue.code.replaceAll("_", " ")}</strong>
                  <span>{issue.message}</span>
                </li>
              ))}
            </ul>
          )}
          <ol className="instruction-tree">
            {state.data.occurrences.slice(0, visibleOccurrenceLimit).map((occurrence) => (
              <li
                key={occurrence.occurrenceId}
                style={{ marginLeft: `${Math.min(occurrence.depth, 12) * 1.25}rem` }}
              >
                <code>{occurrence.occurrenceId}</code>
                <strong>{occurrence.sourceSubmodelName}</strong>
                <span>
                  depth {occurrence.depth}
                  {occurrence.attachmentStep !== null
                    ? ` · parent step ${occurrence.attachmentStep}`
                    : " · root"}
                  {occurrence.effectiveColor !== null
                    ? ` · color ${occurrence.effectiveColor}`
                    : ""}
                  {` · position ${occurrence.localTransform.translation.join(", ")}`}
                </span>
              </li>
            ))}
          </ol>
          {state.data.expandedOccurrenceCount > visibleOccurrenceLimit && (
            <p className="metadata-warning">
              Showing the first {visibleOccurrenceLimit.toLocaleString()} occurrences in
              deterministic traversal order.
            </p>
          )}
        </div>
      )}
    </details>
  );
}

function BuildReadiness({ coverage }: { coverage: ModelCoverage }) {
  const summary = coverage.summary;
  const progress = coverageProgressValue(summary.pieceCoveragePercentage);
  return (
    <section className="page-panel readiness-panel" aria-labelledby="readiness-title">
      <div className="readiness-heading">
        <div>
          <p className="eyebrow">Build readiness</p>
          <h2 id="readiness-title">
            {formatCoveragePercentage(summary.pieceCoveragePercentage)} covered
          </h2>
        </div>
        <span
          className={`build-state build-state--${summary.fullyBuildable ? "complete" : "incomplete"}`}
        >
          {summary.fullyBuildable ? "Fully buildable" : "Incomplete"}
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
      <p className="coverage-progress-text">
        {summary.totalAvailableQuantity.toLocaleString()} available of{" "}
        {summary.totalRequiredQuantity.toLocaleString()} required physical pieces;{" "}
        {summary.totalMissingQuantity.toLocaleString()} missing.
      </p>
      <dl className="readiness-counts">
        <Meta label="Unique BOM rows" value={summary.uniqueItemCount} />
        <Meta label="Complete rows" value={summary.completeItemCount} />
        <Meta label="Partial rows" value={summary.partialItemCount} />
        <Meta label="Missing rows" value={summary.missingItemCount} />
      </dl>
    </section>
  );
}

function CoverageTable({ items }: { items: ModelCoverageItem[] }) {
  return (
    <div className="table-scroll">
      <table className="bom-table coverage-table">
        <thead>
          <tr>
            <th>Part</th>
            <th>Name</th>
            <th>Exact color</th>
            <th>Required</th>
            <th>Owned</th>
            <th>Missing</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr
              className={`coverage-row coverage-row--${item.status}`}
              key={`${item.partId}-${item.colorCode}`}
            >
              <td data-label="Part">
                <span className="part-id">{item.partId}</span>
              </td>
              <td data-label="Name">
                {item.partName}
                {!item.catalogAvailable && (
                  <small className="metadata-warning">Catalog metadata unavailable</small>
                )}
              </td>
              <td data-label="Exact color">
                <span className="inventory-color">
                  {item.colorHex && (
                    <span
                      className="color-swatch"
                      style={{ backgroundColor: item.colorHex }}
                      aria-hidden="true"
                    />
                  )}
                  {item.colorName} ({item.colorCode})
                </span>
              </td>
              <td data-label="Required">{item.requiredQuantity}</td>
              <td data-label="Owned">{item.ownedQuantity}</td>
              <td data-label="Missing">
                <strong>{item.missingQuantity}</strong>
              </td>
              <td data-label="Status">
                <span
                  className={`coverage-status coverage-status--${item.status}`}
                  aria-label={`Coverage status: ${coverageStatusLabel(item.status)}`}
                >
                  {coverageStatusLabel(item.status)}
                </span>
              </td>
              <td data-label="Actions">
                <div className="coverage-actions">
                  {item.catalogAvailable ? (
                    <Link to={`/catalog?part=${encodeURIComponent(item.partId)}`}>
                      Inspect official part
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
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
