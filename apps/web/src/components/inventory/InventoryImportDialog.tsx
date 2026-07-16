import { useEffect, useRef, useState } from "react";
import type { SubmitEvent } from "react";

import { InventoryImportPreviewRow, InventoryImportStrategy } from "../../api/inventory";
import {
  colorSwatchValue,
  importErrorMessage,
  importFormatLabel,
  importToastMessage,
  validateInventoryImportFile,
  validateSetNumber,
} from "../../inventory/helpers";
import { formatFileSize } from "../../models/helpers";
import {
  useApplyInventoryImport,
  useApplySetImport,
  usePreviewInventoryImport,
  usePreviewSetImport,
} from "../../queries/hooks";
import { PartThumbnail } from "../parts/PartThumbnail";
import { SegmentedControl } from "../ui/primitives";
import { useToast } from "../ui/ToastProvider";

const STRATEGY_OPTIONS = [
  { value: "add", label: "Add to quantities" },
  { value: "replace", label: "Replace quantities" },
] as const;

const SOURCE_OPTIONS = [
  { value: "file", label: "Upload file" },
  { value: "set", label: "LEGO set number" },
] as const;

type ImportSource = "file" | "set";

/**
 * Bulk-import flow: pick a source (an uploaded file, or an official LEGO
 * set number expanded via the local Rebrickable set data), review the
 * server-computed dry run (nothing is written), then apply with an
 * explicit merge strategy. Built on the native <dialog>; rendered only
 * while open, so the modal is shown on mount and jsdom falls back to the
 * non-modal `open` attribute.
 */
export function InventoryImportDialog({ onClose }: { onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [source, setSource] = useState<ImportSource>("file");
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [setNum, setSetNum] = useState("");
  const [setNumError, setSetNumError] = useState<string | null>(null);
  const [strategy, setStrategy] = useState<InventoryImportStrategy>("add");
  const [includeUnknown, setIncludeUnknown] = useState(true);
  const [dragActive, setDragActive] = useState(false);
  const filePreview = usePreviewInventoryImport();
  const fileApply = useApplyInventoryImport();
  const setPreview = usePreviewSetImport();
  const setApply = useApplySetImport();
  const showToast = useToast();

  const preview = source === "file" ? filePreview : setPreview;
  const apply = source === "file" ? fileApply : setApply;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null || dialog.open) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }, []);

  const busy = apply.isPending;

  function switchSource(next: ImportSource) {
    setSource(next);
    filePreview.reset();
    fileApply.reset();
    setPreview.reset();
    setApply.reset();
    setFile(null);
    setFileError(null);
    setSetNum("");
    setSetNumError(null);
  }

  function choose(candidate: File | null) {
    fileApply.reset();
    if (candidate === null) {
      setFile(null);
      setFileError(null);
      filePreview.reset();
      return;
    }
    const problem = validateInventoryImportFile(candidate);
    if (problem !== null) {
      setFile(null);
      setFileError(problem);
      filePreview.reset();
      return;
    }
    setFile(candidate);
    setFileError(null);
    filePreview.mutate({ file: candidate, strategy });
  }

  function lookupSet(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    setApply.reset();
    const trimmed = setNum.trim();
    const problem = validateSetNumber(trimmed);
    if (problem !== null) {
      setSetNumError(problem);
      setPreview.reset();
      return;
    }
    setSetNumError(null);
    setPreview.mutate({ setNum: trimmed, strategy });
  }

  function switchStrategy(next: InventoryImportStrategy) {
    setStrategy(next);
    apply.reset();
    if (source === "file" && file !== null) {
      filePreview.mutate({ file, strategy: next });
    } else if (source === "set" && setPreview.isSuccess) {
      setPreview.mutate({ setNum: setNum.trim(), strategy: next });
    }
  }

  function runApply() {
    if (source === "file") {
      if (file === null) return;
      fileApply.mutate(
        { file, strategy, includeUnknown, format: filePreview.data?.format },
        {
          onSuccess: (result) => {
            showToast(importToastMessage(result));
            onClose();
          },
        },
      );
    } else {
      if (!setPreview.isSuccess) return;
      setApply.mutate(
        { setNum: setNum.trim(), strategy, includeUnknown },
        {
          onSuccess: (result) => {
            showToast(importToastMessage(result));
            onClose();
          },
        },
      );
    }
  }

  const error =
    (source === "file" ? fileError : setNumError) ??
    (preview.isError ? importErrorMessage(preview.error) : null) ??
    (apply.isError ? importErrorMessage(apply.error) : null);
  const data = preview.data;
  const applicableRows =
    data === undefined ? 0 : data.known.rowCount + (includeUnknown ? data.unknown.rowCount : 0);

  return (
    <dialog
      ref={dialogRef}
      className="confirm-dialog inventory-import-dialog"
      aria-labelledby="inventory-import-title"
      onCancel={(event) => {
        // Escape: keep React state as the single source of truth.
        event.preventDefault();
        if (!busy) onClose();
      }}
    >
      <h2 id="inventory-import-title">Import inventory</h2>
      <p>
        Native CSV (<code>part_id,color_code,quantity</code>), a Rebrickable MOC parts export, a
        BrickLink wanted-list XML, or an official LEGO set number. Nothing changes until you import.
      </p>

      <SegmentedControl
        className="segmented-control"
        label="Import source"
        value={source}
        options={SOURCE_OPTIONS}
        onChange={switchSource}
      />

      {source === "file" ? (
        <div
          className={`inventory-import-dropzone${dragActive ? " inventory-import-dropzone--drag" : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragActive(false);
            if (busy) return;
            const dropped = event.dataTransfer.files[0] ?? null;
            if (dropped !== null) choose(dropped);
          }}
        >
          <label>
            <span>Import file</span>
            <input
              type="file"
              accept=".csv,.xml"
              disabled={busy}
              onChange={(event) => choose(event.currentTarget.files?.[0] ?? null)}
            />
          </label>
          <p className="inventory-import-hint">Drop a .csv or .xml file anywhere in this box</p>
          {file !== null && (
            <p className="file-preview">
              {file.name} · {formatFileSize(file.size)}
            </p>
          )}
        </div>
      ) : (
        <form className="inventory-import-set-lookup" onSubmit={lookupSet}>
          <label>
            <span>LEGO set number</span>
            <input
              type="text"
              placeholder="e.g. 7922 or 7922-1"
              value={setNum}
              disabled={busy}
              onChange={(event) => setSetNum(event.currentTarget.value)}
            />
          </label>
          <button type="submit" disabled={busy || setPreview.isPending}>
            {setPreview.isPending ? "Looking up…" : "Look up"}
          </button>
        </form>
      )}

      {error !== null && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      {preview.isPending && (
        <p className="inventory-import-hint" role="status">
          Computing preview…
        </p>
      )}

      {data !== undefined && (
        <div className="inventory-import-preview">
          <p className="inventory-import-hint">Detected format: {importFormatLabel(data.format)}</p>
          {data.format === "set" && data.setName !== null && (
            <p className="inventory-import-hint">
              {data.officialPartCount !== null && data.expandedQuantity !== null
                ? `${data.setName} · Official count: ${data.officialPartCount.toLocaleString()} ` +
                  `· Expanded: ${data.expandedQuantity.toLocaleString()}`
                : data.setName}
            </p>
          )}
          {!data.mappingAvailable && (
            <p className="inline-error" role="alert">
              The Rebrickable/BrickLink ID mapping table isn&apos;t populated yet — run{" "}
              <code>python -m app.cli.rebrickable_mapping populate</code>, then retry.
            </p>
          )}
          <SegmentedControl
            className="segmented-control"
            label="Merge strategy"
            value={strategy}
            options={STRATEGY_OPTIONS}
            onChange={switchStrategy}
          />
          <ul className="inventory-import-facts">
            <li>
              <strong>{data.known.rowCount.toLocaleString()}</strong> catalog rows —{" "}
              {data.known.createCount} new, {data.known.updateCount} updated,{" "}
              {data.known.unchangedCount} unchanged
            </li>
            {data.unknown.rowCount > 0 && (
              <li>
                <strong>{data.unknown.rowCount.toLocaleString()}</strong> rows not in the catalog
              </li>
            )}
            {data.invalidRowCount > 0 && (
              <li>{data.invalidRowCount.toLocaleString()} invalid rows will be ignored</li>
            )}
            {data.duplicateRowCount > 0 && (
              <li>{data.duplicateRowCount.toLocaleString()} duplicate rows merged</li>
            )}
            {data.aliasCanonicalizedCount > 0 && (
              <li>{data.aliasCanonicalizedCount.toLocaleString()} moved part IDs renamed</li>
            )}
            {data.spareRowCount > 0 && (
              <li>{data.spareRowCount.toLocaleString()} spare rows included</li>
            )}
            {data.ignoredColumns.length > 0 && (
              <li>Ignored columns: {data.ignoredColumns.join(", ")}</li>
            )}
          </ul>
          {data.rows.length > 0 && (
            <ul className="inventory-import-rows">
              {data.rows.map((row) => (
                <ImportRow key={`${row.partId}-${row.colorCode}`} row={row} />
              ))}
            </ul>
          )}
          {data.rowsTruncated && (
            <p className="inventory-import-hint">
              Showing the first {data.rows.length.toLocaleString()} of{" "}
              {data.plannedRowCount.toLocaleString()} rows.
            </p>
          )}
          {data.issues.length > 0 && (
            <details className="inventory-import-issues">
              <summary>{data.invalidRowCount.toLocaleString()} invalid rows</summary>
              <ul>
                {data.issues.map((issue) => (
                  <li key={issue.lineNumber}>
                    Line {issue.lineNumber}: {issue.message}
                  </li>
                ))}
              </ul>
              {data.issuesTruncated && (
                <p className="inventory-import-hint">Only the first issues are listed.</p>
              )}
            </details>
          )}
          {data.unknown.rowCount > 0 && (
            <label className="inventory-import-include">
              <input
                type="checkbox"
                checked={includeUnknown}
                disabled={busy}
                onChange={(event) => setIncludeUnknown(event.currentTarget.checked)}
              />
              <span>
                Include the {data.unknown.rowCount.toLocaleString()} rows not in the catalog
              </span>
            </label>
          )}
        </div>
      )}

      <div className="confirm-dialog-actions">
        <button type="button" onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button
          type="button"
          disabled={busy || preview.isPending || applicableRows === 0}
          onClick={runApply}
        >
          {busy ? "Importing…" : "Import"}
        </button>
      </div>
    </dialog>
  );
}

function ImportRow({ row }: { row: InventoryImportPreviewRow }) {
  return (
    <li className="inventory-import-row">
      <PartThumbnail partId={row.partId} />
      <div className="inventory-import-row-body">
        <span>
          <span className="part-id">{row.partId}</span>
          {row.partName !== null && <span> {row.partName}</span>}
        </span>
        <span className="inventory-color">
          <span
            className="color-swatch"
            style={{
              backgroundColor: colorSwatchValue(row.colorHex ?? "#808080", row.alpha ?? 255),
            }}
          />
          <span>
            {row.colorName ?? `Color ${row.colorCode}`} ({row.colorCode})
          </span>
        </span>
        <span className="inventory-import-badges">
          {row.unknownReason === "part" && (
            <span className="inventory-import-badge">Not in catalog</span>
          )}
          {row.unknownReason === "color" && (
            <span className="inventory-import-badge">Unknown colour</span>
          )}
          {row.unknownReason === "unmapped" && (
            <span className="inventory-import-badge">No LDraw mapping</span>
          )}
          {row.canonicalizedFrom !== null && (
            <span className="inventory-import-badge">Renamed from {row.canonicalizedFrom}</span>
          )}
        </span>
      </div>
      <span className="inventory-import-quantities">
        {row.currentQuantity.toLocaleString()} → {row.resultingQuantity.toLocaleString()}
      </span>
    </li>
  );
}
