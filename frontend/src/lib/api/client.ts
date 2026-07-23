import { API_BASE_URL } from "@/lib/config";
import { getAccessToken } from "@/lib/auth/token";

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

type RequestOptions = {
  token?: string | null;
  body?: unknown;
  headers?: HeadersInit;
};

async function request<T>(
  method: HttpMethod,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  const token = options.token ?? getAccessToken();

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let body: BodyInit | undefined;
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.body);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body,
      cache: "no-store",
    });
  } catch (error) {
    throw new ApiError(
      "No pudimos conectar con la API de Valoria. Revisa que FastAPI este corriendo.",
      0,
      error,
    );
  }

  const payload = await parseResponse(response);
  if (!response.ok) {
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
  return "La API respondio con un error inesperado.";
}

export const apiClient = {
  get: <T>(path: string, options?: RequestOptions) => request<T>("GET", path, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("POST", path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("PATCH", path, { ...options, body }),
  delete: <T>(path: string, options?: RequestOptions) => request<T>("DELETE", path, options),
  health: () => request<{ status: string }>("GET", "/health"),
};
