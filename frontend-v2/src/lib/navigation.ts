import { LEGACY_BASE_URL } from "./config";

// Legacy routes verified against frontend/src/app/app; Radar now has a v2 route.
const paths: Record<string, string> = {
  Radar: "/app/radar", "Explorar el Radar": "/app/radar",
  Tasar: "/app/tasar", "Tasar una propiedad": "/app/tasar", "Analizar propiedad": "/app/tasar",
  "Analizar URL": "/app/analizar-url", "Analizar una URL": "/app/analizar-url",
  "Mi cartera": "/app/portfolio", Alertas: "/app/alerts",
};
export function legacyRoute(label: string): string | null {
  if (label === "Alertas") return "/alerts";
  if (label === "Mi cartera") return "/portfolio";
  if (["Analizar URL", "Analizar una URL"].includes(label)) return "/analizar-url";
  if (["Tasar", "Tasar una propiedad", "Analizar propiedad"].includes(label)) return "/tasar";
  if (label === "Radar" || label === "Explorar el Radar") return "/radar";
  return paths[label] ? `${LEGACY_BASE_URL}${paths[label]}` : null;
}
export function safeExternalUrl(value: string | null | undefined): string | null {
  try { const url = new URL(value ?? ""); return ["https:", "http:"].includes(url.protocol) ? url.href : null; }
  catch { return null; }
}
