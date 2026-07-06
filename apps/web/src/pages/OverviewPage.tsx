import { Link } from "react-router-dom";

import { useLibraryStatus } from "../components/ldraw/useLibraryStatus";
import { toAsyncState } from "../queries/async";
import {
  useCatalogStatus,
  useHealth,
  useInventorySummary,
  useModelsReadiness,
} from "../queries/hooks";

export default function OverviewPage() {
  const health = toAsyncState(useHealth(), "Unknown health error");
  const catalog = toAsyncState(useCatalogStatus(), "Unknown catalog error");
  const inventory = toAsyncState(useInventorySummary(), "Unknown inventory error");
  const models = toAsyncState(useModelsReadiness(), "Unknown model readiness error");
  const library = useLibraryStatus();

  return (
    <section className="page-panel" aria-labelledby="overview-title">
      <div className="page-heading">
        <p className="eyebrow">Final local MVP</p>
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
      <Link className="overview-inventory-link" to="/models">
        <span>Imported model readiness</span>
        <strong>
          {models.kind === "ready"
            ? `${models.data.fullyBuildableModels.toLocaleString()} of ${models.data.totalModels.toLocaleString()} models fully buildable`
            : models.kind === "loading"
              ? "Loading…"
              : "Unavailable"}
        </strong>
        <span>
          {models.kind === "ready"
            ? `${models.data.totalMissingQuantity.toLocaleString()} missing pieces across per-model comparisons →`
            : "Open models →"}
        </span>
      </Link>
      <div className="overview-grid">
        <StatusCard label="Frontend" value="Online" tone="ok" />
        <StatusCard
          label="API"
          value={
            health.kind === "ready"
              ? "Online"
              : health.kind === "loading"
                ? "Checking…"
                : "Unavailable"
          }
          tone={health.kind === "ready" ? "ok" : health.kind === "error" ? "error" : "pending"}
        />
        <StatusCard
          label="PostgreSQL"
          value={
            health.kind === "ready" && health.data.database === "ok"
              ? "Online"
              : health.kind === "loading"
                ? "Checking…"
                : "Unavailable"
          }
          tone={health.kind === "ready" ? "ok" : health.kind === "error" ? "error" : "pending"}
        />
        <StatusCard
          label="Official library"
          value={
            library.kind === "ready"
              ? library.status.installed
                ? `${library.status.fileCounts?.dat.toLocaleString() ?? "0"} DAT files`
                : "Not installed"
              : library.kind === "loading"
                ? "Checking…"
                : "Unavailable"
          }
          tone={
            library.kind === "ready" && library.status.installed
              ? "ok"
              : library.kind === "loading"
                ? "pending"
                : "error"
          }
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
          tone={
            catalog.kind === "ready" && catalog.data.indexed && !catalog.data.stale
              ? "ok"
              : catalog.kind === "loading"
                ? "pending"
                : "error"
          }
        />
      </div>
      {(health.kind === "error" || catalog.kind === "error") && (
        <div className="error" role="alert">
          <strong>Some status checks failed.</strong>
          <span>
            {health.kind === "error"
              ? health.message
              : catalog.kind === "error"
                ? catalog.message
                : ""}
          </span>
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
