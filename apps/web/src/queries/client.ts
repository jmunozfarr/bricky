import { QueryClient } from "@tanstack/react-query";

/**
 * Matches the previous hand-rolled fetch behavior: no automatic retries
 * (errors surface immediately) and no focus-driven refetching. Queries are
 * refetched on mount and via invalidation, exactly like the old effects and
 * the inventory event bus did.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}
