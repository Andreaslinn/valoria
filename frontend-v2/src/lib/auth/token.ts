export const TOKEN_KEY = "valoria_access_token";
export const SESSION_EVENT = "valoria:session";

export function getAccessToken(): string | null {
  return typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
}
export function setAccessToken(token: string): void {
  if (getAccessToken() === token) return;
  window.localStorage.setItem(TOKEN_KEY, token);
  window.dispatchEvent(new Event(SESSION_EVENT));
}
export function clearAccessToken(): void {
  if (!getAccessToken()) return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.dispatchEvent(new Event(SESSION_EVENT));
}
// A complete document reset discards all account-specific React state and requests.
export function observeSessionChange(reset: () => void): () => void {
  const storage = (event: StorageEvent) => {
    if (event.key === TOKEN_KEY || event.key === null) reset();
  };
  window.addEventListener("storage", storage);
  window.addEventListener(SESSION_EVENT, reset);
  return () => {
    window.removeEventListener("storage", storage);
    window.removeEventListener(SESSION_EVENT, reset);
  };
}
