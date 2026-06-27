import { API_BASE_URL } from "@/lib/config";
import { apiClient, ApiError } from "@/lib/api/client";

export type TokenResponse = {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
};

export type User = {
  id: number;
  email: string;
  role: string;
  is_active: boolean;
};

export async function login(email: string, password: string): Promise<TokenResponse> {
  const form = new URLSearchParams();
  form.set("username", email);
  form.set("password", password);

  const response = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: form,
  });

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError("Credenciales invalidas o sesion no disponible.", response.status, payload);
  }
  return payload as TokenResponse;
}

export async function register(email: string, password: string): Promise<User> {
  return apiClient.post<User>("/api/v1/auth/register", { email, password }, { token: null });
}

export async function me(token?: string | null): Promise<User> {
  return apiClient.get<User>("/api/v1/auth/me", { token });
}
