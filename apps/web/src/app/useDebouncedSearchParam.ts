import { useEffect, useEffectEvent, useState } from "react";
import { useSearchParams } from "react-router-dom";

interface UseDebouncedSearchParamOptions {
  /** Additional param keys to delete when the search input changes. */
  deleteOnChange?: string[];
}

/**
 * Syncs a local search-input state with the `"query"` URL search param,
 * debouncing writes to the URL by 300 ms.  Resets `"page"` to `"1"` on every
 * change and optionally deletes extra params listed in `deleteOnChange`.
 */
export function useDebouncedSearchParam(options?: UseDebouncedSearchParamOptions) {
  const [params, setParams] = useSearchParams();
  const query = params.get("query") ?? "";
  const [searchInput, setSearchInput] = useState(query);

  // Effect Events see the latest committed props at call time, so the debounce
  // timer reads the current keys without making the caller's array reactive.
  const currentDeleteOnChange = useEffectEvent(() => options?.deleteOnChange ?? []);

  useEffect(() => setSearchInput(query), [query]);

  useEffect(() => {
    if (searchInput === query) return;
    const timer = window.setTimeout(() => {
      const deleteKeys = currentDeleteOnChange();
      setParams((current: URLSearchParams) => {
        const next = new URLSearchParams(current);
        const trimmed = searchInput.trim();
        if (trimmed) next.set("query", trimmed);
        else next.delete("query");
        next.set("page", "1");
        for (const key of deleteKeys) next.delete(key);
        return next;
      });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query, searchInput, setParams]);

  return { query, searchInput, setSearchInput, params, setParams };
}
