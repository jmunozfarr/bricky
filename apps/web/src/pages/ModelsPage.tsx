import { useState } from "react";
import type { SubmitEvent } from "react";
import { Link } from "react-router-dom";

import type { CoverageSummary } from "../api/models";

import { useDebouncedSearchParam } from "../app/useDebouncedSearchParam";

import { getCatalogAvailability } from "../catalog/catalogState";
import {
  coverageVerdict,
  formatFileSize,
  modelUploadError,
  validateModelUpload,
} from "../models/helpers";
import { CatalogReadinessAlert } from "../components/catalog/CatalogReadinessAlert";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { useToast } from "../components/ui/ToastProvider";
import { Alert, EmptyState, ModelStatusPill, Pagination } from "../components/ui/primitives";
import { toAsyncState } from "../queries/async";
import { useCatalogStatus, useDeleteModel, useModelsList, useUploadModel } from "../queries/hooks";

export default function ModelsPage() {
  const { query, searchInput, setSearchInput, params, setParams } = useDebouncedSearchParam();
  const status = params.get("status") ?? "";
  const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);
  const results = toAsyncState(useModelsList({ query, status, page }), "Unable to load models.");
  const catalog = toAsyncState(useCatalogStatus());
  const upload = useUploadModel();
  const showToast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const deletion = useDeleteModel();
  const [confirmingDelete, setConfirmingDelete] = useState<{ id: string; name: string } | null>(
    null,
  );
  const uploading = upload.isPending;
  const uploadError =
    validationError ?? (upload.error !== null ? modelUploadError(upload.error) : null);

  function updateParams(key: "query" | "status" | "page", value: string, reset = false) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (value) next.set(key, value);
      else next.delete(key);
      if (reset) next.set("page", "1");
      return next;
    });
  }

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const validation = validateModelUpload(file);
    if (validation !== null || file === null) {
      setValidationError(validation);
      return;
    }
    setValidationError(null);
    setUploadProgress(0);
    upload.mutate(
      { file, name, onProgress: setUploadProgress },
      {
        onSuccess: (created) => showToast(`Imported ${created.name}.`),
        onSettled: () => setUploadProgress(null),
      },
    );
  }

  function removeModel(target: { id: string; name: string }) {
    deletion.mutate(target.id, {
      onSuccess: () => {
        setConfirmingDelete(null);
        showToast(`Deleted ${target.name}.`);
      },
      onError: () => setConfirmingDelete(null),
    });
  }

  const prefetchBuilder = () => void import("./VisualBuilderPage");
  return (
    <section className="page-panel" aria-labelledby="models-title">
      <div className="page-heading catalog-heading">
        <div>
          <p className="eyebrow">Local files</p>
          <h2 id="models-title">Imported models</h2>
        </div>
        <p>Original source bytes are preserved</p>
      </div>

      <form
        className={`model-upload${dragActive ? " model-upload--drag" : ""}`}
        onSubmit={submit}
        onDragOver={(event) => {
          event.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragActive(false);
          if (uploading) return;
          const dropped = event.dataTransfer.files[0] ?? null;
          if (dropped !== null) setFile(dropped);
        }}
      >
        <p className="model-upload-hint">Drop an .ldr or .mpd file anywhere in this panel</p>
        <label>
          <span>Model file</span>
          <input
            type="file"
            accept=".ldr,.mpd"
            disabled={uploading}
            onChange={(event) => setFile(event.currentTarget.files?.[0] ?? null)}
          />
        </label>
        <label>
          <span>Model name (optional)</span>
          <input
            value={name}
            maxLength={256}
            disabled={uploading}
            onChange={(event) => setName(event.currentTarget.value)}
            placeholder="Uses the filename by default"
          />
        </label>
        <button type="submit" disabled={uploading}>
          {uploading ? "Importing…" : "Import model"}
        </button>
        {file && (
          <p className="file-preview">
            {file.name} · {formatFileSize(file.size)}
          </p>
        )}
        {uploadProgress !== null && (
          <progress
            className="upload-progress"
            aria-label="Upload progress"
            max={1}
            value={uploadProgress}
          />
        )}
        {uploadError && (
          <p className="inline-error" role="alert">
            {uploadError}
          </p>
        )}
      </form>

      <div className="catalog-filters">
        <label>
          <span>Search models</span>
          <input
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.currentTarget.value)}
            placeholder="Name or original filename"
          />
        </label>
        <label>
          <span>Import status</span>
          <select
            value={status}
            onChange={(event) => updateParams("status", event.currentTarget.value, true)}
          >
            <option value="">All statuses</option>
            <option value="ready">Ready</option>
            <option value="ready_with_warnings">Ready with warnings</option>
            <option value="failed">Failed</option>
          </select>
        </label>
      </div>

      {catalog.kind === "ready" && (
        <CatalogReadinessAlert availability={getCatalogAvailability(catalog.data)} />
      )}

      {results.kind === "loading" && <div className="page-message">Loading models…</div>}
      {results.kind === "error" && <Alert title={results.message} />}
      {results.kind === "ready" && (
        <>
          <p className="results-count">{results.data.totalItems.toLocaleString()} models</p>
          {results.data.items.length === 0 ? (
            <EmptyState>
              {query || status ? "No models match these filters." : "No models have been imported."}
            </EmptyState>
          ) : (
            <div className="models-grid">
              {results.data.items.map((model) => (
                <article className="model-card" key={model.modelId}>
                  <div className="inventory-card-heading">
                    <ModelStatusPill status={model.importStatus} />
                    <span>{model.sourceFormat.toUpperCase()}</span>
                  </div>
                  <h3>{model.name}</h3>
                  <p>{model.originalFilename}</p>
                  <dl>
                    <div>
                      <dt>Steps</dt>
                      <dd>{model.declaredStepCount}</dd>
                    </div>
                    <div>
                      <dt>Parts</dt>
                      <dd>{model.totalPartQuantity}</dd>
                    </div>
                    <div>
                      <dt>Variants</dt>
                      <dd>{model.uniquePartColorCount}</dd>
                    </div>
                    <div>
                      <dt>Warnings</dt>
                      <dd>{model.unresolvedReferenceCount}</dd>
                    </div>
                  </dl>
                  {model.coverage && <ModelCardReadiness coverage={model.coverage} />}
                  <small>{new Date(model.createdAt).toLocaleString()}</small>
                  <div className="model-card-actions">
                    <Link
                      className="button-link"
                      to={`/models/${model.modelId}/build`}
                      onMouseEnter={prefetchBuilder}
                      onFocus={prefetchBuilder}
                    >
                      View
                    </Link>
                    <Link className="button-link" to={`/models/${model.modelId}/print`}>
                      Parts list
                    </Link>
                    <a
                      className="button-link"
                      href={`/api/models/${encodeURIComponent(model.modelId)}/source`}
                      download={model.originalFilename}
                    >
                      Download source
                    </a>
                    <button
                      type="button"
                      className="danger-button"
                      disabled={deletion.isPending}
                      onClick={() => setConfirmingDelete({ id: model.modelId, name: model.name })}
                    >
                      Delete
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
          {deletion.error !== null && (
            <Alert title="Delete failed.">
              {deletion.error instanceof Error ? deletion.error.message : "Delete failed."}
            </Alert>
          )}
          <ConfirmDialog
            open={confirmingDelete !== null}
            title={confirmingDelete ? `Delete ${confirmingDelete.name}?` : "Delete this model?"}
            description="The imported model and its preserved source file are removed permanently."
            confirmLabel="Delete model"
            destructive
            busy={deletion.isPending}
            onConfirm={() => confirmingDelete && removeModel(confirmingDelete)}
            onCancel={() => setConfirmingDelete(null)}
          />
          <Pagination
            page={page}
            totalPages={results.data.totalPages}
            label="Models pagination"
            onPageChange={(next) => updateParams("page", String(next))}
          />
        </>
      )}
    </section>
  );
}

/**
 * Three states, not two: a model whose references did not resolve has nothing
 * to be buildable against, so the card reports the absence of a verdict rather
 * than 100% of an empty requirement set.
 */
function ModelCardReadiness({ coverage }: { coverage: CoverageSummary }) {
  const verdict = coverageVerdict(coverage);
  return (
    <div className="model-card-readiness">
      <strong>{verdict.headline}</strong>
      <span>{verdict.label}</span>
      {verdict.explanation !== null && <span>{verdict.explanation}</span>}
    </div>
  );
}
