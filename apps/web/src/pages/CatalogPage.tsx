import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  Category,
  CatalogStatus,
  getCatalogStatus,
  getCategories,
  nextPage,
  PartsPage,
  previousPage,
  searchParts,
} from "../api/catalog";
import { getCatalogAvailability } from "../catalog/catalogState";
import { CatalogPartDetail } from "../components/catalog/CatalogPartDetail";

const LIBRARY_COMMAND = "docker compose run --rm api python -m app.cli.ldraw_library install";
const REBUILD_COMMAND = "docker compose exec api python -m app.cli.ldraw_catalog rebuild";

type AsyncState<T> =
  { kind: "loading" } | { kind: "ready"; data: T } | { kind: "error"; message: string };

export default function CatalogPage() {
  const [params, setParams] = useSearchParams();
  const query = params.get("query") ?? "";
  const category = params.get("category") ?? "";
  const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);
  const selectedPartId = params.get("part");
  const [searchInput, setSearchInput] = useState(query);
  const [status, setStatus] = useState<AsyncState<CatalogStatus>>({ kind: "loading" });
  const [categories, setCategories] = useState<AsyncState<Category[]>>({ kind: "loading" });
  const [results, setResults] = useState<AsyncState<PartsPage>>({ kind: "loading" });

  useEffect(() => setSearchInput(query), [query]);

  useEffect(() => {
    const controller = new AbortController();
    void getCatalogStatus(controller.signal)
      .then((data) => setStatus({ kind: "ready", data }))
      .catch((error: unknown) => setRequestError(error, setStatus));
    return () => controller.abort();
  }, []);

  const ready = status.kind === "ready" && getCatalogAvailability(status.data) === "ready";

  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    void getCategories(controller.signal)
      .then((data) => setCategories({ kind: "ready", data }))
      .catch((error: unknown) => setRequestError(error, setCategories));
    return () => controller.abort();
  }, [ready]);

  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    setResults({ kind: "loading" });
    void searchParts({ query, category, page }, controller.signal)
      .then((data) => setResults({ kind: "ready", data }))
      .catch((error: unknown) => setRequestError(error, setResults));
    return () => controller.abort();
  }, [category, page, query, ready]);

  useEffect(() => {
    if (searchInput === query) return;
    const timer = window.setTimeout(() => {
      setParams((current) => {
        const next = new URLSearchParams(current);
        if (searchInput.trim()) next.set("query", searchInput.trim());
        else next.delete("query");
        next.set("page", "1");
        next.delete("part");
        return next;
      });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query, searchInput, setParams]);

  function updateParam(key: string, value: string) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (value) next.set(key, value);
      else next.delete(key);
      if (key === "category") {
        next.set("page", "1");
        next.delete("part");
      }
      return next;
    });
  }

  if (status.kind === "loading") return <div className="page-message">Checking catalog…</div>;
  if (status.kind === "error") return <ErrorPanel message={status.message} />;
  const availability = getCatalogAvailability(status.data);
  if (availability !== "ready") {
    return <CatalogSetupState availability={availability} />;
  }
  if (selectedPartId) {
    return <CatalogPartDetail partId={selectedPartId} onBack={() => updateParam("part", "")} />;
  }

  return (
    <section className="page-panel" aria-labelledby="catalog-title">
      <div className="page-heading catalog-heading">
        <div>
          <p className="eyebrow">Official library</p>
          <h2 id="catalog-title">Parts catalog</h2>
        </div>
        <p>{status.data.partCount.toLocaleString()} indexed parts</p>
      </div>
      <div className="catalog-filters">
        <label>
          <span>Search parts</span>
          <input
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.currentTarget.value)}
            placeholder="Part ID or name"
          />
        </label>
        <label>
          <span>Category</span>
          <select
            value={category}
            onChange={(event) => updateParam("category", event.currentTarget.value)}
            disabled={categories.kind !== "ready"}
          >
            <option value="">All categories</option>
            {categories.kind === "ready" &&
              categories.data.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name} ({item.count})
                </option>
              ))}
          </select>
        </label>
      </div>
      {results.kind === "loading" && <div className="page-message">Loading parts…</div>}
      {results.kind === "error" && <ErrorPanel message={results.message} />}
      {results.kind === "ready" && (
        <>
          <p className="results-count">{results.data.totalItems.toLocaleString()} results</p>
          {results.data.items.length === 0 ? (
            <div className="empty-state">No parts match this search.</div>
          ) : (
            <div className="parts-grid">
              {results.data.items.map((part) => (
                <article className="part-card" key={part.partId}>
                  <span className="part-id">{part.partId}</span>
                  <h3>{part.name}</h3>
                  <p>{part.category}</p>
                  {part.author && <small>By {part.author}</small>}
                  <button type="button" onClick={() => updateParam("part", part.partId)}>
                    Inspect part
                  </button>
                </article>
              ))}
            </div>
          )}
          <div className="pagination" aria-label="Catalog pagination">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => updateParam("page", String(previousPage(page)))}
            >
              Previous
            </button>
            <span>
              Page {page} of {Math.max(1, results.data.totalPages)}
            </span>
            <button
              type="button"
              disabled={page >= results.data.totalPages}
              onClick={() => updateParam("page", String(nextPage(page, results.data.totalPages)))}
            >
              Next
            </button>
          </div>
        </>
      )}
    </section>
  );
}

function CatalogSetupState({
  availability,
}: {
  availability: ReturnType<typeof getCatalogAvailability>;
}) {
  const missing = availability === "not-installed";
  return (
    <section className="page-panel setup-state">
      <p className="eyebrow">Catalog unavailable</p>
      <h2>
        {missing
          ? "Official library not installed"
          : availability === "stale"
            ? "Catalog index is stale"
            : "Catalog not indexed"}
      </h2>
      <p>
        {missing
          ? "Install the official library explicitly before indexing."
          : "Rebuild the database catalog explicitly; the browser never starts indexing."}
      </p>
      <pre>
        <code>{missing ? LIBRARY_COMMAND : REBUILD_COMMAND}</code>
      </pre>
    </section>
  );
}

function ErrorPanel({ message }: { message: string }) {
  return (
    <div className="error" role="alert">
      <strong>Catalog request failed.</strong>
      <span>{message}</span>
    </div>
  );
}

function setRequestError<T>(error: unknown, setter: (state: AsyncState<T>) => void) {
  if (!(error instanceof DOMException && error.name === "AbortError")) {
    setter({ kind: "error", message: error instanceof Error ? error.message : "Unknown error" });
  }
}
