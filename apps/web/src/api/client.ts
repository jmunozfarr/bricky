export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly detail: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function fetchJson<T>(
  url: string,
  signal?: AbortSignal,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(url, { ...init, signal });
  if (!response.ok) {
    throw await responseError(response);
  }
  const data: unknown = await response.json();
  return data as T;
}

export async function fetchNoContent(url: string, init: RequestInit): Promise<void> {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw await responseError(response);
  }
}

async function responseError(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
    if (
      typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      typeof body.detail === "string"
    ) {
      return new ApiError(response.status, body.detail, body.detail);
    }
    if (
      typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      typeof body.detail === "object" &&
      body.detail !== null &&
      "message" in body.detail &&
      typeof body.detail.message === "string"
    ) {
      return new ApiError(response.status, body.detail.message, body.detail);
    }
  } catch {
    // Fall back to the HTTP status when the response is not JSON.
  }
  return new ApiError(response.status, `Request returned HTTP ${response.status}`, body);
}
