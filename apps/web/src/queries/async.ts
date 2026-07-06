import type { UseQueryResult } from "@tanstack/react-query";

/** The render-facing shape the pages already speak. */
export type AsyncState<T> =
  { kind: "loading" } | { kind: "ready"; data: T } | { kind: "error"; message: string };

export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function toAsyncState<T>(
  query: UseQueryResult<T>,
  fallback = "Unknown error",
): AsyncState<T> {
  if (query.isError) {
    return { kind: "error", message: errorMessage(query.error, fallback) };
  }
  if (query.data !== undefined) {
    return { kind: "ready", data: query.data };
  }
  return { kind: "loading" };
}
