export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
    public rawBody?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const NETWORK_MESSAGE =
  "Could not reach the API. Check that the backend is running.";
const SERVER_ERROR_MESSAGE =
  "Something went wrong on the server. Try again.";
const NOT_FOUND_MESSAGE = "Not found.";
const REQUEST_FAILED_MESSAGE = "Request failed.";

function statusFallback(status: number): string {
  if (status === 404) return NOT_FOUND_MESSAGE;
  if (status === 500 || status === 502 || status === 504) {
    return SERVER_ERROR_MESSAGE;
  }
  return REQUEST_FAILED_MESSAGE;
}

function formatValidationItem(item: unknown): string | null {
  if (typeof item === "string") return item;
  if (!item || typeof item !== "object") return null;
  const record = item as { loc?: unknown; msg?: unknown };
  const msg = typeof record.msg === "string" ? record.msg : null;
  if (!msg) return null;
  const loc = Array.isArray(record.loc)
    ? record.loc
        .filter((part): part is string | number =>
          typeof part === "string" || typeof part === "number",
        )
        .filter((part) => part !== "body" && part !== "query" && part !== "path")
        .join(".")
    : "";
  return loc ? `${loc}: ${msg}` : msg;
}

/** Parse a FastAPI (or plain) error body into a human-readable message. */
export function parseApiErrorBody(status: number, body: string): string {
  const trimmed = body.trim();
  if (!trimmed) return statusFallback(status);

  // 5xx: never surface opaque server JSON / generic Internal Server Error
  if (status === 500 || status === 502 || status === 504) {
    return SERVER_ERROR_MESSAGE;
  }

  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (parsed && typeof parsed === "object" && "detail" in parsed) {
      const detail = (parsed as { detail: unknown }).detail;
      if (typeof detail === "string" && detail.trim()) {
        return detail.trim();
      }
      if (Array.isArray(detail)) {
        const parts = detail
          .map(formatValidationItem)
          .filter((part): part is string => Boolean(part));
        if (parts.length > 0) return parts.join("; ");
      }
    }
  } catch {
    // non-JSON body
  }

  if (trimmed.startsWith("<") || trimmed.startsWith("<!")) {
    return statusFallback(status);
  }

  // Avoid dumping huge HTML/proxy blobs
  if (trimmed.length > 300) {
    return statusFallback(status);
  }

  return trimmed;
}

export async function throwApiError(res: Response): Promise<never> {
  const rawBody = await res.text();
  const message = parseApiErrorBody(res.status, rawBody);
  throw new ApiError(res.status, message, undefined, rawBody);
}

export function formatErrorForUi(err: unknown): string {
  if (err instanceof ApiError) {
    return err.message;
  }
  if (err instanceof Error) {
    const msg = err.message;
    if (
      msg === "Failed to fetch" ||
      msg === "NetworkError when attempting to fetch resource." ||
      /networkerror|failed to fetch|load failed/i.test(msg)
    ) {
      return NETWORK_MESSAGE;
    }
    return msg || "Unknown error";
  }
  return "Unknown error";
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) await throwApiError(res);
  return res.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) await throwApiError(res);
  return res.json() as Promise<T>;
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "PUT",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) await throwApiError(res);
  return res.json() as Promise<T>;
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "PATCH",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) await throwApiError(res);
  return res.json() as Promise<T>;
}

export async function apiDelete(path: string): Promise<void> {
  const res = await fetch(path, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  if (!res.ok) await throwApiError(res);
}
