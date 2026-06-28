export async function fetchJson<T>(
  url: string,
  signal?: AbortSignal,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(url, { ...init, signal });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
  const data: unknown = await response.json();
  return data as T;
}

export async function fetchNoContent(url: string, init: RequestInit): Promise<void> {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
}

async function responseErrorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (
      typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      typeof body.detail === "string"
    ) {
      return body.detail;
    }
  } catch {
    // Fall back to the HTTP status when the response is not JSON.
  }
  return `Request returned HTTP ${response.status}`;
}
