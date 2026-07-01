import { useEffect, useState } from "react";
import type { SubmitEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { listModels, ModelsPage as ModelsPageData, uploadModel } from "../api/models";
import {
  formatFileSize,
  formatCoveragePercentage,
  modelStatusLabel,
  modelUploadError,
  validateModelUpload,
} from "../models/helpers";

type ResultsState =
  | { kind: "loading" }
  | { kind: "ready"; data: ModelsPageData }
  | { kind: "error"; message: string };

export default function ModelsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const query = params.get("query") ?? "";
  const status = params.get("status") ?? "";
  const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);
  const [searchInput, setSearchInput] = useState(query);
  const [results, setResults] = useState<ResultsState>({ kind: "loading" });
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  useEffect(() => setSearchInput(query), [query]);

  useEffect(() => {
    const controller = new AbortController();
    setResults({ kind: "loading" });
    void listModels({ query, status, page }, controller.signal)
      .then((data) => setResults({ kind: "ready", data }))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setResults({
            kind: "error",
            message: error instanceof Error ? error.message : "Unable to load models.",
          });
        }
      });
    return () => controller.abort();
  }, [page, query, status]);

  useEffect(() => {
    if (searchInput === query) return;
    const timer = window.setTimeout(() => {
      updateParams("query", searchInput.trim(), true);
    }, 300);
    return () => window.clearTimeout(timer);
  });

  function updateParams(key: "query" | "status" | "page", value: string, reset = false) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (value) next.set(key, value);
      else next.delete(key);
      if (reset) next.set("page", "1");
      return next;
    });
  }

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const validation = validateModelUpload(file);
    if (validation !== null || file === null) {
      setUploadError(validation);
      return;
    }
    setUploading(true);
    setUploadError(null);
    try {
      const created = await uploadModel(file, name);
      const returnSearch = params.toString();
      await navigate(`/models/${created.modelId}?return=${encodeURIComponent(returnSearch)}`);
    } catch (error: unknown) {
      setUploadError(modelUploadError(error));
    } finally {
      setUploading(false);
    }
  }

  const returnSearch = params.toString();
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

      <form className="model-upload" onSubmit={(event) => void submit(event)}>
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

      {results.kind === "loading" && <div className="page-message">Loading models…</div>}
      {results.kind === "error" && (
        <div className="error" role="alert">
          {results.message}
        </div>
      )}
      {results.kind === "ready" && (
        <>
          <p className="results-count">{results.data.totalItems.toLocaleString()} models</p>
          {results.data.items.length === 0 ? (
            <div className="empty-state">
              {query || status ? "No models match these filters." : "No models have been imported."}
            </div>
          ) : (
            <div className="models-grid">
              {results.data.items.map((model) => (
                <article className="model-card" key={model.modelId}>
                  <div className="inventory-card-heading">
                    <span className={`model-status model-status--${model.importStatus}`}>
                      {modelStatusLabel(model.importStatus)}
                    </span>
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
                  {model.coverage && (
                    <div className="model-card-readiness">
                      <strong>
                        {formatCoveragePercentage(model.coverage.pieceCoveragePercentage)} covered
                      </strong>
                      <span>
                        {model.coverage.fullyBuildable
                          ? "Fully buildable"
                          : `${model.coverage.totalMissingQuantity.toLocaleString()} pieces missing`}
                      </span>
                    </div>
                  )}
                  <small>{new Date(model.createdAt).toLocaleString()}</small>
                  <div className="model-card-actions">
                    <Link
                      className="button-link"
                      to={`/models/${model.modelId}?return=${encodeURIComponent(returnSearch)}`}
                    >
                      Model details
                    </Link>
                    <Link
                      className="button-link"
                      to={`/models/${model.modelId}/build`}
                      onMouseEnter={prefetchBuilder}
                      onFocus={prefetchBuilder}
                    >
                      Open builder
                    </Link>
                  </div>
                </article>
              ))}
            </div>
          )}
          <div className="pagination">
            <button disabled={page <= 1} onClick={() => updateParams("page", String(page - 1))}>
              Previous
            </button>
            <span>
              Page {page} of {Math.max(1, results.data.totalPages)}
            </span>
            <button
              disabled={page >= results.data.totalPages}
              onClick={() => updateParams("page", String(page + 1))}
            >
              Next
            </button>
          </div>
        </>
      )}
    </section>
  );
}
