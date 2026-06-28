import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { CatalogStatus, getCatalogStatus } from "../api/catalog";
import { fetchJson } from "../api/client";
import { getInventorySummary, InventorySummary } from "../api/inventory";
import { useLibraryStatus } from "../components/ldraw/useLibraryStatus";
import { subscribeInventoryChanged } from "../inventory/events";

interface HealthResponse {
  status: "ok";
  database: "ok";
}

type AsyncState<T> =
  | { kind: "loading" }
  | { kind: "ready"; data: T }
  | { kind: "error"; message: string };

export default function OverviewPage() {
  const [health, setHealth] = useState<AsyncState<HealthResponse>>({ kind: "loading" });
  const [catalog, setCatalog] = useState<AsyncState<CatalogStatus>>({ kind: "loading" });
  const [inventory, setInventory] = useState<AsyncState<InventorySummary>>({ kind: "loading" });
  const library = useLibraryStatus();

  useEffect(() => {
    const controller = new AbortController();
    void fetchJson<HealthResponse>("/api/health", controller.signal)
      .then((data) => setHealth({ kind: "ready", data }))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setHealth({
            kind: "error",
            message: error instanceof Error ? error.message : "Unknown health error",
          });
        }
      });
    void getCatalogStatus(controller.signal)
      .then((data) => setCatalog({ kind: "ready", data }))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setCatalog({
            kind: "error",
            message: error instanceof Error ? error.message : "Unknown catalog error",
          });
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    let controller = new AbortController();
    const load = () => {
      controller.abort();
      controller = new AbortController();
      void getInventorySummary(controller.signal)
        .then((data) => setInventory({ kind: "ready", data }))
        .catch((error: unknown) => {
          if (!(error instanceof DOMException && error.name === "AbortError")) {
            setInventory({ kind: "error", message: error instanceof Error ? error.message : "Unknown inventory error" });
          }
        });
    };
    load();
    const unsubscribe = subscribeInventoryChanged(load);
    return () => {
      controller.abort();
      unsubscribe();
    };
  }, []);

  return (
    <section className="page-panel" aria-labelledby="overview-title">
      <div className="page-heading">
        <p className="eyebrow">Checkpoint 5</p>
        <h2 id="overview-title">Local workspace status</h2>
        <p>Runtime services, official library, and catalog indexing remain local.</p>
      </div>
      <Link className="overview-inventory-link" to="/inventory">
        <span>Personal inventory</span>
        <strong>
          {inventory.kind === "ready"
            ? `${inventory.data.totalQuantity.toLocaleString()} pieces · ${inventory.data.uniqueItems.toLocaleString()} items`
            : inventory.kind === "loading"
              ? "Loading…"
              : "Unavailable"}
        </strong>
        <span>Open inventory →</span>
      </Link>
      <div className="overview-grid">
        <StatusCard label="Frontend" value="Online" tone="ok" />
        <StatusCard
          label="API"
          value={health.kind === "ready" ? "Online" : health.kind === "loading" ? "Checking…" : "Unavailable"}
          tone={health.kind === "ready" ? "ok" : health.kind === "error" ? "error" : "pending"}
        />
        <StatusCard
          label="PostgreSQL"
          value={health.kind === "ready" && health.data.database === "ok" ? "Online" : health.kind === "loading" ? "Checking…" : "Unavailable"}
          tone={health.kind === "ready" ? "ok" : health.kind === "error" ? "error" : "pending"}
        />
        <StatusCard
          label="Official library"
          value={
            library.kind === "ready"
              ? library.status.installed
                ? `${library.status.fileCounts?.dat.toLocaleString() ?? 0} DAT files`
                : "Not installed"
              : library.kind === "loading"
                ? "Checking…"
                : "Unavailable"
          }
          tone={library.kind === "ready" && library.status.installed ? "ok" : library.kind === "loading" ? "pending" : "error"}
        />
        <StatusCard
          label="Parts catalog"
          value={
            catalog.kind === "ready"
              ? catalog.data.indexed
                ? catalog.data.stale
                  ? "Stale"
                  : `${catalog.data.partCount.toLocaleString()} parts indexed`
                : "Not indexed"
              : catalog.kind === "loading"
                ? "Checking…"
                : "Unavailable"
          }
          tone={catalog.kind === "ready" && catalog.data.indexed && !catalog.data.stale ? "ok" : catalog.kind === "loading" ? "pending" : "error"}
        />
      </div>
      {(health.kind === "error" || catalog.kind === "error") && (
        <div className="error" role="alert">
          <strong>Some status checks failed.</strong>
          <span>{health.kind === "error" ? health.message : catalog.kind === "error" ? catalog.message : ""}</span>
        </div>
      )}
    </section>
  );
}

interface StatusCardProps {
  label: string;
  value: string;
  tone: "ok" | "pending" | "error";
}

function StatusCard({ label, value, tone }: StatusCardProps) {
  return (
    <article className="status-card">
      <span className={`status-dot status-dot--${tone}`} aria-hidden="true" />
      <div>
        <h3>{label}</h3>
        <p>{value}</p>
      </div>
    </article>
  );
}
