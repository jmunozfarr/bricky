import { useEffect, useState } from "react";

interface LibraryFileCounts {
  dat: number;
  ldr: number;
  png: number;
}

export interface LibraryStatus {
  installed: boolean;
  fileCounts: LibraryFileCounts | null;
  archiveSha256: string | null;
}

export type LibraryStatusState =
  | { kind: "loading" }
  | { kind: "ready"; status: LibraryStatus }
  | { kind: "error"; message: string };

function isFileCounts(value: unknown): value is LibraryFileCounts {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  return (
    "dat" in value &&
    typeof value.dat === "number" &&
    "ldr" in value &&
    typeof value.ldr === "number" &&
    "png" in value &&
    typeof value.png === "number"
  );
}

function isLibraryStatus(value: unknown): value is LibraryStatus {
  if (typeof value !== "object" || value === null || !("installed" in value)) {
    return false;
  }

  if (!("fileCounts" in value) || !("archiveSha256" in value)) {
    return false;
  }

  return (
    typeof value.installed === "boolean" &&
    (value.fileCounts === null || isFileCounts(value.fileCounts)) &&
    (value.archiveSha256 === null || typeof value.archiveSha256 === "string")
  );
}

export function useLibraryStatus(): LibraryStatusState {
  const [state, setState] = useState<LibraryStatusState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();

    async function loadStatus() {
      try {
        const response = await fetch("/api/library/status", {
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`Library status returned HTTP ${response.status}`);
        }

        const status: unknown = await response.json();
        if (!isLibraryStatus(status)) {
          throw new Error("Library status returned an unexpected response");
        }
        setState({ kind: "ready", status });
      } catch (error: unknown) {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        const message = error instanceof Error ? error.message : "Unknown status error";
        setState({ kind: "error", message });
      }
    }

    void loadStatus();
    return () => controller.abort();
  }, []);

  return state;
}
