import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Category, getCategories, getColors, LDrawColor, nextPage, previousPage } from "../api/catalog";
import {
  deleteInventoryItem,
  getInventorySummary,
  InventoryItem,
  InventoryPage as InventoryPageData,
  InventorySummary,
  searchInventory,
  setInventoryQuantity,
} from "../api/inventory";
import { CatalogPartDetail } from "../components/catalog/CatalogPartDetail";
import { notifyInventoryChanged } from "../inventory/events";
import {
  colorSwatchValue,
  decrementQuantity,
  incrementQuantity,
  inventoryEmptyMessage,
  parseQuantityInput,
} from "../inventory/helpers";

type AsyncState<T> =
  | { kind: "loading" }
  | { kind: "ready"; data: T }
  | { kind: "error"; message: string };

export default function InventoryPage() {
  const [params, setParams] = useSearchParams();
  const query = params.get("query") ?? "";
  const category = params.get("category") ?? "";
  const rawColorCode = params.get("colorCode");
  const parsedColorCode = rawColorCode === null ? null : Number(rawColorCode);
  const colorCode = parsedColorCode !== null && Number.isInteger(parsedColorCode) && parsedColorCode >= 0
    ? parsedColorCode
    : null;
  const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);
  const selectedPartId = params.get("part");
  const [searchInput, setSearchInput] = useState(query);
  const [summary, setSummary] = useState<AsyncState<InventorySummary>>({ kind: "loading" });
  const [results, setResults] = useState<AsyncState<InventoryPageData>>({ kind: "loading" });
  const [categories, setCategories] = useState<Category[]>([]);
  const [colors, setColors] = useState<LDrawColor[]>([]);
  const [refreshVersion, setRefreshVersion] = useState(0);

  useEffect(() => setSearchInput(query), [query]);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([getCategories(controller.signal), getColors(controller.signal)])
      .then(([loadedCategories, loadedColors]) => {
        setCategories(loadedCategories);
        setColors(loadedColors);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void getInventorySummary(controller.signal)
      .then((data) => setSummary({ kind: "ready", data }))
      .catch((caught: unknown) => setAsyncError(caught, setSummary));
    return () => controller.abort();
  }, [refreshVersion]);

  useEffect(() => {
    const controller = new AbortController();
    setResults({ kind: "loading" });
    void searchInventory({ query, category, colorCode, page }, controller.signal)
      .then((data) => setResults({ kind: "ready", data }))
      .catch((caught: unknown) => setAsyncError(caught, setResults));
    return () => controller.abort();
  }, [category, colorCode, page, query, refreshVersion]);

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

  function updateFilter(key: "category" | "colorCode", value: string) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (value) next.set(key, value);
      else next.delete(key);
      next.set("page", "1");
      next.delete("part");
      return next;
    });
  }

  function setPage(nextPage: number) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.set("page", String(nextPage));
      return next;
    });
  }

  function inspectPart(partId: string | null) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (partId) next.set("part", partId);
      else next.delete("part");
      return next;
    });
  }

  function refreshInventory() {
    setRefreshVersion((version) => version + 1);
    notifyInventoryChanged();
  }

  if (selectedPartId) {
    return (
      <CatalogPartDetail
        partId={selectedPartId}
        onBack={() => inspectPart(null)}
        backLabel="Back to inventory"
      />
    );
  }

  const hasFilters = Boolean(query || category || colorCode !== null);
  return (
    <section className="page-panel" aria-labelledby="inventory-title">
      <div className="page-heading catalog-heading">
        <div>
          <p className="eyebrow">Local workspace</p>
          <h2 id="inventory-title">Personal inventory</h2>
        </div>
        <p>PostgreSQL is the source of truth</p>
      </div>

      {summary.kind === "ready" ? (
        <div className="inventory-summary">
          <SummaryCard label="Total pieces" value={summary.data.totalQuantity} />
          <SummaryCard label="Unique items" value={summary.data.uniqueItems} />
          <SummaryCard label="Unique parts" value={summary.data.uniqueParts} />
        </div>
      ) : summary.kind === "error" ? (
        <ErrorPanel message={summary.message} />
      ) : (
        <div className="page-message">Loading inventory summary…</div>
      )}

      <div className="catalog-filters inventory-filters">
        <label>
          <span>Search inventory</span>
          <input
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.currentTarget.value)}
            placeholder="Part ID or name"
          />
        </label>
        <label>
          <span>Category</span>
          <select value={category} onChange={(event) => updateFilter("category", event.currentTarget.value)}>
            <option value="">All categories</option>
            {categories.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
          </select>
        </label>
        <label>
          <span>Color</span>
          <select value={colorCode ?? ""} onChange={(event) => updateFilter("colorCode", event.currentTarget.value)}>
            <option value="">All colors</option>
            {colors.map((color) => <option key={color.code} value={color.code}>{color.name} ({color.code})</option>)}
          </select>
        </label>
      </div>

      {results.kind === "loading" && <div className="page-message">Loading inventory…</div>}
      {results.kind === "error" && <ErrorPanel message={results.message} />}
      {results.kind === "ready" && (
        <>
          <p className="results-count">{results.data.totalItems.toLocaleString()} items</p>
          {results.data.items.length === 0 ? (
            <div className="empty-state">{inventoryEmptyMessage(hasFilters)}</div>
          ) : (
            <div className="inventory-grid">
              {results.data.items.map((item) => (
                <InventoryCard
                  key={`${item.partId}-${item.colorCode}`}
                  item={item}
                  onChanged={refreshInventory}
                  onInspect={() => inspectPart(item.partId)}
                />
              ))}
            </div>
          )}
          <div className="pagination" aria-label="Inventory pagination">
            <button type="button" disabled={page <= 1} onClick={() => setPage(previousPage(page))}>Previous</button>
            <span>Page {page} of {Math.max(1, results.data.totalPages)}</span>
            <button type="button" disabled={page >= results.data.totalPages} onClick={() => setPage(nextPage(page, results.data.totalPages))}>Next</button>
          </div>
        </>
      )}
    </section>
  );
}

function InventoryCard({
  item,
  onChanged,
  onInspect,
}: {
  item: InventoryItem;
  onChanged: () => void;
  onInspect: () => void;
}) {
  const [input, setInput] = useState(String(item.quantity));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setInput(String(item.quantity)), [item.quantity]);

  async function save(quantity: number) {
    setBusy(true);
    setError(null);
    try {
      const saved = await setInventoryQuantity(item.partId, item.colorCode, quantity);
      setInput(String(saved.quantity));
      onChanged();
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "Update failed");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await deleteInventoryItem(item.partId, item.colorCode);
      onChanged();
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "Removal failed");
      setBusy(false);
    }
  }

  const parsedInput = parseQuantityInput(input);
  const decremented = decrementQuantity(item.quantity);
  return (
    <article className="inventory-card">
      <div className="inventory-card-heading">
        <span className="part-id">{item.partId}</span>
        <span className="quantity-badge">× {item.quantity}</span>
      </div>
      <h3>{item.partName}</h3>
      <p>{item.category}</p>
      <div className="inventory-color">
        <span className="color-swatch" style={{ backgroundColor: colorSwatchValue(item.colorHex, item.alpha) }} />
        <span>{item.colorName} ({item.colorCode})</span>
      </div>
      {!item.catalogAvailable && <p className="inline-error">Catalog metadata unavailable</p>}
      <div className="quantity-controls">
        <button type="button" aria-label={`Decrease ${item.partId} quantity`} disabled={busy} onClick={() => decremented === null ? void remove() : void save(decremented)}>−</button>
        <input
          aria-label={`Quantity for ${item.partId} in color ${item.colorCode}`}
          type="number"
          min="1"
          max="999999"
          value={input}
          onChange={(event) => setInput(event.currentTarget.value)}
          disabled={busy}
        />
        <button type="button" aria-label={`Increase ${item.partId} quantity`} disabled={busy || item.quantity >= 999999} onClick={() => void save(incrementQuantity(item.quantity))}>+</button>
      </div>
      <div className="inventory-card-actions">
        <button type="button" disabled={busy || parsedInput === null} onClick={() => parsedInput !== null && void save(parsedInput)}>Update</button>
        <button type="button" disabled={busy} onClick={() => void remove()}>Remove</button>
        <button type="button" disabled={busy || !item.catalogAvailable} onClick={onInspect}>Inspect</button>
      </div>
      {error && <p className="inline-error" role="alert">{error}</p>}
    </article>
  );
}

function SummaryCard({ label, value }: { label: string; value: number }) {
  return <article><span>{label}</span><strong>{value.toLocaleString()}</strong></article>;
}

function ErrorPanel({ message }: { message: string }) {
  return <div className="error" role="alert"><strong>Inventory request failed.</strong><span>{message}</span></div>;
}

function setAsyncError<T>(caught: unknown, setter: (state: AsyncState<T>) => void) {
  if (!(caught instanceof DOMException && caught.name === "AbortError")) {
    setter({ kind: "error", message: caught instanceof Error ? caught.message : "Unknown error" });
  }
}
