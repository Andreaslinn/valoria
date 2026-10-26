import { API_BASE_URL } from "@/lib/config";
import { getAccessToken } from "@/lib/auth/token";
import { ApiError } from "@/lib/api/client";

type DownloadOptions = {
  endpoint: string;
  body?: unknown;
  fallbackFilename: string;
  method?: "GET" | "POST";
};

export async function downloadAuthenticatedReport({
  body,
  endpoint,
  fallbackFilename,
  method = "POST",
}: DownloadOptions): Promise<string> {
  const token = getAccessToken();
  const headers = new Headers();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${endpoint}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch (error) {
    throw new ApiError("No pudimos conectar con la API de Valoria.", 0, error);
  }

  if (!response.ok) {
    throw new ApiError(await downloadErrorMessage(response), response.status);
  }

  const blob = await response.blob();
  const filename = filenameFromDisposition(response.headers.get("Content-Disposition")) ?? fallbackFilename;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  return filename;
}

async function downloadErrorMessage(response: Response): Promise<string> {
  try {
    const payload = await response.json();
    if (payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string") {
      return payload.detail;
    }
  } catch {
    // Fall through to generic message.
  }
  if (response.status === 401) return "Credenciales invalidas o sesion expirada.";
  if (response.status === 403) return "No tienes permisos para descargar este informe.";
  if (response.status === 422) return "No fue posible generar el informe con estos datos.";
  return "No fue posible descargar el informe.";
}

function filenameFromDisposition(value: string | null): string | null {
  if (!value) return null;
  const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) return decodeURIComponent(utf8Match[1]);
  const asciiMatch = value.match(/filename="?([^";]+)"?/i);
  return asciiMatch?.[1] ?? null;
}
