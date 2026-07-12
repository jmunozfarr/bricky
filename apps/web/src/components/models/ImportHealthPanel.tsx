import { useEffect, useRef, useState } from "react";

import { ModelDetail, ModelResolutionInput } from "../../api/models";
import {
  importIssueLabel,
  isResolvableIssue,
  resolutionLabel,
  sortImportIssues,
  suggestedMapQuery,
} from "../../models/helpers";
import { errorMessage } from "../../queries/async";
import {
  useColors,
  useDeleteModelResolution,
  usePartsSearch,
  useReprocessModel,
  useUpsertModelResolution,
} from "../../queries/hooks";
import { PartThumbnail } from "../parts/PartThumbnail";
import { useToast } from "../ui/ToastProvider";

/**
 * Import issues with their remediation actions for the workspace inspect
 * panel: map a problematic reference to an official catalog part, exclude it
 * from the BOM, or undo either. Every action reprocesses the model from its
 * immutable original on the server and returns the re-derived detail.
 */
export function ImportHealthPanel({ model }: { model: ModelDetail }) {
  const showToast = useToast();
  const reprocess = useReprocessModel();
  const upsertResolution = useUpsertModelResolution();
  const deleteResolution = useDeleteModelResolution();
  const [mapSource, setMapSource] = useState<string | null>(null);

  if (model.issues.length === 0 && model.resolutions.length === 0) return null;

  const issues = sortImportIssues(model.issues);
  const warningCount = issues.filter((issue) => issue.severity === "warning").length;
  // Resolutions store normalized (lowercased) references; issue filenames
  // keep the source file's original casing.
  const resolvedSources = new Set(
    model.resolutions.map((resolution) => resolution.sourceReference.toLowerCase()),
  );
  const busy = reprocess.isPending || upsertResolution.isPending || deleteResolution.isPending;

  function applyResolution(input: ModelResolutionInput, success: string) {
    upsertResolution.mutate(
      { modelId: model.modelId, input },
      {
        onSuccess: () => {
          setMapSource(null);
          showToast(success);
        },
        onError: (error) => showToast(errorMessage(error, "The resolution failed."), "error"),
      },
    );
  }

  function removeResolution(sourceReference: string) {
    deleteResolution.mutate(
      { modelId: model.modelId, sourceReference },
      {
        onSuccess: () =>
          showToast(`Removed the resolution for ${sourceReference} and reprocessed the model.`),
        onError: (error) =>
          showToast(errorMessage(error, "Removing the resolution failed."), "error"),
      },
    );
  }

  function reprocessNow() {
    reprocess.mutate(model.modelId, {
      onSuccess: () => showToast(`Reprocessed ${model.name}.`),
      onError: (error) => showToast(errorMessage(error, "Reprocessing failed."), "error"),
    });
  }

  return (
    <section className="import-health" aria-labelledby="import-health-title">
      <div className="import-health-heading">
        <div>
          <h4 id="import-health-title">Import health</h4>
          <p>
            {warningCount > 0
              ? `${warningCount} ${warningCount === 1 ? "warning needs" : "warnings need"} attention.`
              : "All import notices are informational."}
          </p>
        </div>
        <button type="button" onClick={reprocessNow} disabled={busy}>
          {reprocess.isPending ? "Reprocessing…" : "Reprocess"}
        </button>
      </div>
      <ul className="import-health-issues">
        {issues.map((issue) => {
          const filename = issue.referencedFilename;
          const actionable =
            filename !== null &&
            issue.severity === "warning" &&
            isResolvableIssue(issue) &&
            !resolvedSources.has(filename.toLowerCase());
          return (
            <li
              key={`${issue.code}-${issue.message}-${filename ?? ""}`}
              className={`import-health-issue import-health-issue--${
                issue.severity === "warning" ? "warning" : "info"
              }`}
            >
              <div className="import-health-issue-heading">
                <strong>{importIssueLabel(issue.code)}</strong>
                {issue.occurrenceCount > 1 && (
                  <span className="import-health-count">×{issue.occurrenceCount}</span>
                )}
              </div>
              <span>
                {issue.message}
                {filename ? ` — ${filename}` : ""}
              </span>
              {actionable && (
                <div className="import-health-actions">
                  <button type="button" disabled={busy} onClick={() => setMapSource(filename)}>
                    Map to part…
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      applyResolution(
                        { sourceReference: filename, action: "ignore" },
                        `Ignored ${filename} and reprocessed the model.`,
                      )
                    }
                  >
                    Ignore
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {model.resolutions.length > 0 && (
        <div className="import-health-resolutions">
          <h5>Manual resolutions</h5>
          <ul>
            {model.resolutions.map((resolution) => (
              <li key={resolution.sourceReference}>
                <div>
                  <strong>{resolution.sourceReference}</strong>
                  <span>{resolutionLabel(resolution)}</span>
                </div>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => removeResolution(resolution.sourceReference)}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {mapSource !== null && (
        <MapReferenceDialog
          sourceReference={mapSource}
          busy={upsertResolution.isPending}
          onCancel={() => setMapSource(null)}
          onSubmit={(partId, colorCode) =>
            applyResolution(
              {
                sourceReference: mapSource,
                action: "map",
                partId,
                ...(colorCode === null ? {} : { colorCode }),
              },
              `Mapped ${mapSource} to ${partId} and reprocessed the model.`,
            )
          }
        />
      )}
    </section>
  );
}

/**
 * Native <dialog> for picking the official part (and optional colour
 * override) a reference should count as. Rendered only while open, so the
 * modal is shown on mount; jsdom lacks showModal and falls back to the
 * non-modal `open` attribute.
 */
function MapReferenceDialog({
  sourceReference,
  busy,
  onCancel,
  onSubmit,
}: {
  sourceReference: string;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (partId: string, colorCode: number | null) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [query, setQuery] = useState(() => suggestedMapQuery(sourceReference));
  const [selectedPartId, setSelectedPartId] = useState<string | null>(null);
  const [colorValue, setColorValue] = useState("");

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null || dialog.open) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }, []);

  const trimmedQuery = query.trim();
  const parts = usePartsSearch(
    { query: trimmedQuery, category: "", page: 1, pageSize: 6 },
    trimmedQuery.length > 0,
  );
  const colors = useColors();
  const physicalColors = (colors.data ?? []).filter(
    (color) => color.code !== 16 && color.code !== 24,
  );

  return (
    <dialog
      ref={dialogRef}
      className="confirm-dialog import-health-dialog"
      aria-labelledby="map-reference-title"
      onCancel={(event) => {
        // Escape: keep React state as the single source of truth.
        event.preventDefault();
        onCancel();
      }}
    >
      <h2 id="map-reference-title">Map {sourceReference}</h2>
      <p>
        Count this reference as an official catalog part whenever the model is imported or
        reprocessed.
      </p>
      <label>
        <span>Search official parts</span>
        <input
          type="search"
          value={query}
          onChange={(event) => {
            setQuery(event.currentTarget.value);
            setSelectedPartId(null);
          }}
        />
      </label>
      {trimmedQuery.length === 0 ? (
        <p className="import-health-dialog-hint">Type a part ID or name to search the catalog.</p>
      ) : parts.isError ? (
        <p className="import-health-dialog-hint" role="alert">
          Part search failed; is the catalog indexed?
        </p>
      ) : parts.data === undefined ? (
        <p className="import-health-dialog-hint" role="status">
          Searching…
        </p>
      ) : parts.data.items.length === 0 ? (
        <p className="import-health-dialog-hint" role="status">
          No official parts match this search.
        </p>
      ) : (
        <ul className="import-health-part-options">
          {parts.data.items.map((part) => (
            <li key={part.partId}>
              <button
                type="button"
                aria-pressed={part.partId === selectedPartId}
                onClick={() => setSelectedPartId(part.partId)}
              >
                <PartThumbnail partId={part.partId} />
                <span>
                  <strong>{part.partId}</strong> {part.name}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <label>
        <span>Colour</span>
        <select value={colorValue} onChange={(event) => setColorValue(event.currentTarget.value)}>
          <option value="">Keep the colour used by the reference</option>
          {physicalColors.map((color) => (
            <option key={color.code} value={String(color.code)}>
              {color.name} ({color.code})
            </option>
          ))}
        </select>
      </label>
      <div className="confirm-dialog-actions">
        <button type="button" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button
          type="button"
          disabled={busy || selectedPartId === null}
          onClick={() => {
            if (selectedPartId !== null) {
              onSubmit(selectedPartId, colorValue === "" ? null : Number(colorValue));
            }
          }}
        >
          {busy ? "Mapping…" : "Map reference"}
        </button>
      </div>
    </dialog>
  );
}
