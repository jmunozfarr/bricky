export async function fetchJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`Request returned HTTP ${response.status}`);
  }
  const data: unknown = await response.json();
  return data as T;
}
