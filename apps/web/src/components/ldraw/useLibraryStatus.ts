import { useQuery } from "@tanstack/react-query";

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

async function fetchLibraryStatus(signal: AbortSignal): Promise<LibraryStatus> {
  const response = await fetch("/api/library/status", { signal });
  if (!response.ok) {
    throw new Error(`Library status returned HTTP ${response.status}`);
  }
  const status: unknown = await response.json();
  if (!isLibraryStatus(status)) {
    throw new Error("Library status returned an unexpected response");
  }
  return status;
}

export function useLibraryStatus(): LibraryStatusState {
  const query = useQuery({
    queryKey: ["library", "status"],
    queryFn: ({ signal }) => fetchLibraryStatus(signal),
  });
  if (query.isError) {
    return {
      kind: "error",
      message: query.error instanceof Error ? query.error.message : "Unknown status error",
    };
  }
  if (query.data !== undefined) {
    return { kind: "ready", status: query.data };
  }
  return { kind: "loading" };
}
