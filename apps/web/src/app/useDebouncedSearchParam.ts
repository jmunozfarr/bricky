import { useEffect, useRef, useState } from "react";
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

  // Keep a ref so the effect closure always sees the latest list without
  // needing it in the dependency array (avoids re-runs from new array refs).
  const deleteOnChangeRef = useRef(options?.deleteOnChange);
  deleteOnChangeRef.current = options?.deleteOnChange;

  useEffect(() => setSearchInput(query), [query]);

  useEffect(() => {
    if (searchInput === query) return;
    const timer = window.setTimeout(() => {
      setParams((current: URLSearchParams) => {
        const next = new URLSearchParams(current);
        const trimmed = searchInput.trim();
        if (trimmed) next.set("query", trimmed);
        else next.delete("query");
        next.set("page", "1");
        if (deleteOnChangeRef.current) {
          for (const key of deleteOnChangeRef.current) next.delete(key);
        }
        return next;
      });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query, searchInput, setParams]);

  return { query, searchInput, setSearchInput, params, setParams };
}
