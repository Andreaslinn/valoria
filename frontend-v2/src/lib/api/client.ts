import { API_BASE_URL } from "@/lib/config";
import { clearAccessToken, getAccessToken } from "@/lib/auth/token";

type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export class ApiError extends Error {
  status: number;
  payload: unknown;

  constructor(message: string, status: number, payload: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

export type RequestOptions = {
  token?: string | null;
  body?: unknown;
  headers?: HeadersInit;
  signal?: AbortSignal;
  timeoutMs?: number;
  form?: URLSearchParams;
};

async function request<T>(
  method: HttpMethod,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  const token = options.token === undefined ? getAccessToken() : options.token;

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let body: BodyInit | undefined;
  if (options.form) body = options.form;
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.body);
  }

  let response: Response;
  const timeout = AbortSignal.timeout(options.timeoutMs ?? 25000);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body,
      cache: "no-store",
      signal,
    });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    throw new ApiError(
      "No pudimos conectar con Valoria. Intenta nuevamente en unos minutos.",
      0,
      error,
    );
  }

  const payload = await parseResponse(response);
  if (!response.ok) {
    if (response.status === 401 && token && getAccessToken() === token) clearAccessToken();

    throw new ApiError(errorMessage(payload, response.status), response.status, payload);
  }

  return payload as T;
}

async function parseResponse(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function errorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail?: unknown }).detail;
    if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") return detail.message;
    if (typeof detail === "string") {
      return detail;
    }
  }
  if (status === 401) {
    return "Credenciales invalidas o sesion expirada.";
  }
  if (status === 403) {
    return "No tienes permisos para realizar esta accion.";
  }
  if (status === 409) {
    return "El recurso ya existe.";
  }
  return "No pudimos completar la solicitud. Intenta nuevamente.";
}

export const apiClient = {
  get: <T>(path: string, options?: RequestOptions) => request<T>("GET", path, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("POST", path, { ...options, body }),
  form: <T>(path: string, form: URLSearchParams, options?: RequestOptions) =>
    request<T>("POST", path, { ...options, form }),
  patch: <T>(path: string, options?: RequestOptions) => request<T>("PATCH", path, options),
  delete: <T>(path: string, options?: RequestOptions) => request<T>("DELETE", path, options),
  health: () => request<{ status: string }>("GET", "/health"),
};

