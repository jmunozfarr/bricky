import { useDebouncedSearchParam } from "../app/useDebouncedSearchParam";
import { getCatalogAvailability, LIBRARY_COMMAND, REBUILD_COMMAND } from "../catalog/catalogState";
import { CatalogPartDetail } from "../components/catalog/CatalogPartDetail";
import { PartThumbnail } from "../components/parts/PartThumbnail";
import { Alert, EmptyState, Pagination } from "../components/ui/primitives";
import { toAsyncState } from "../queries/async";
import { useCatalogStatus, useCategories, usePartsSearch } from "../queries/hooks";

export default function CatalogPage() {
  const { query, searchInput, setSearchInput, params, setParams } = useDebouncedSearchParam({
    deleteOnChange: ["part"],
  });
  const category = params.get("category") ?? "";
  const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);
  const selectedPartId = params.get("part");
  const status = toAsyncState(useCatalogStatus());
  const ready = status.kind === "ready" && getCatalogAvailability(status.data) === "ready";
  const categoriesQuery = useCategories(ready);
  const resultsQuery = usePartsSearch({ query, category, page }, ready);
  const categories = toAsyncState(categoriesQuery);
  const results = toAsyncState(resultsQuery);

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
            <EmptyState>No parts match this search.</EmptyState>
          ) : (
            <div className="parts-grid">
              {results.data.items.map((part) => (
                <article className="part-card" key={part.partId}>
                  <PartThumbnail className="part-thumbnail--card" partId={part.partId} />
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
          <Pagination
            page={page}
            totalPages={results.data.totalPages}
            label="Catalog pagination"
            onPageChange={(next) => updateParam("page", String(next))}
          />
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
  return <Alert title="Catalog request failed.">{message}</Alert>;
}
