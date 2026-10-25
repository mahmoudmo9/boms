/** Fetch wrapper: CSRF header, UI source marker, JSON errors, auth (401) and lock (423) signals. */

export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/** Fired with detail "unauthenticated" (401) or "locked" (423). */
export const authEvents = new EventTarget();

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)boms_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  form?: FormData;
  /** Polling requests do not count as user activity for the idle lock. */
  background?: boolean;
  signal?: AbortSignal;
  query?: Record<string, string | number | boolean | null | undefined | string[]>;
}

export function buildUrl(path: string, query?: RequestOptions["query"]): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => params.append(key, v));
    else params.append(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

export async function api<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = { "X-BOMS-Client": "ui", Accept: "application/json" };
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken();
  if (opts.background) headers["X-BOMS-Background"] = "1";
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }

  const response = await fetch(buildUrl(path, opts.query), {
    method,
    headers,
    body,
    credentials: "same-origin",
    signal: opts.signal,
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const err = data?.error ?? {};
    if (response.status === 401 && err.code === "not_authenticated") {
      authEvents.dispatchEvent(new CustomEvent("auth", { detail: "unauthenticated" }));
    }
    if (response.status === 423) authEvents.dispatchEvent(new CustomEvent("auth", { detail: "locked" }));
    throw new ApiError(response.status, err.code ?? `http_${response.status}`, err.message ?? response.statusText,
      err.details ?? {});
  }
  return data as T;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
