export function formatUf(value: number | null | undefined): string {
  if (!isFiniteNumber(value)) {
    return "No disponible";
  }
  return `UF ${new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 }).format(value)}`;
}

export function formatClp(value: number | null | undefined): string {
  if (!isFiniteNumber(value)) {
    return "No disponible";
  }
  return new Intl.NumberFormat("es-CL", {
    currency: "CLP",
    maximumFractionDigits: 0,
    style: "currency",
  }).format(value);
}

export function formatNumber(value: number | null | undefined, maximumFractionDigits = 1): string {
  if (!isFiniteNumber(value)) {
    return "No disponible";
  }
  return new Intl.NumberFormat("es-CL", { maximumFractionDigits }).format(value);
}

export function formatM2(value: number | null | undefined): string {
  if (!isFiniteNumber(value)) {
    return "m2 no disponible";
  }
  return `${formatNumber(value, 1)} m2`;
}

export function formatConfidence(value: string | number | null | undefined): string {
  if (typeof value === "number") {
    return `${Math.round(value * 100)}%`;
  }

  const normalized = String(value ?? "").trim().toLowerCase();
  const labels: Record<string, string> = {
    high: "Alta confianza",
    medium: "Confianza media",
    low: "Datos limitados",
    insufficient_data: "Datos insuficientes",
  };
  return labels[normalized] ?? "No disponible";
}

export function formatPercent(value: number | null | undefined): string {
  if (!isFiniteNumber(value)) {
    return "No disponible";
  }
  return `${Math.round(value * 100)}%`;
}

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
