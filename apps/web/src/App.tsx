import { useEffect, useState } from "react";

type ServiceState =
  | { kind: "loading" }
  | { kind: "online" }
  | { kind: "error"; message: string };

interface HealthResponse {
  status: "ok";
  database: "ok";
}

function isHealthResponse(value: unknown): value is HealthResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  return (
    "status" in value &&
    value.status === "ok" &&
    "database" in value &&
    value.database === "ok"
  );
}

export function App() {
  const [serviceState, setServiceState] = useState<ServiceState>({
    kind: "loading",
  });

  useEffect(() => {
    const controller = new AbortController();

    async function checkHealth() {
      try {
        const response = await fetch("/api/health", {
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`API returned HTTP ${response.status}`);
        }

        const health: unknown = await response.json();
        if (!isHealthResponse(health)) {
          throw new Error("API returned an unexpected health response");
        }

        setServiceState({ kind: "online" });
      } catch (error: unknown) {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }

        const message = error instanceof Error ? error.message : "Unknown error";
        setServiceState({ kind: "error", message });
      }
    }

    void checkHealth();

    return () => controller.abort();
  }, []);

  return (
    <main className="shell">
      <section className="card" aria-labelledby="page-title">
        <p className="eyebrow">Checkpoint 1</p>
        <h1 id="page-title">Bricky</h1>
        <p className="subtitle">Local LEGO workspace</p>

        <div className="status-list" aria-live="polite">
          <StatusRow label="Frontend" state="online" />
          {serviceState.kind === "loading" && (
            <StatusRow label="API and PostgreSQL" state="checking" />
          )}
          {serviceState.kind === "online" && (
            <>
              <StatusRow label="API" state="online" />
              <StatusRow label="PostgreSQL" state="online" />
            </>
          )}
          {serviceState.kind === "error" && (
            <div className="error" role="alert">
              <strong>API unavailable</strong>
              <span>{serviceState.message}</span>
              <span>Check the API container logs and try again.</span>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}

interface StatusRowProps {
  label: string;
  state: "checking" | "online";
}

function StatusRow({ label, state }: StatusRowProps) {
  const text = state === "online" ? `${label} online` : `Checking ${label}`;

  return (
    <div className="status-row">
      <span className={`indicator indicator--${state}`} aria-hidden="true" />
      <span>{text}</span>
    </div>
  );
}
