const PROPERTY_TYPE_LABELS: Record<string, string> = {
  apartment: "Departamento",
  house: "Casa",
  office: "Oficina",
  unknown: "No disponible",
};

export function formatText(value: unknown, fallback = "No disponible"): string {
  const clean = String(value ?? "").trim();
  return clean || fallback;
}

export function formatNumber(
  value: number | null | undefined,
  maximumFractionDigits = 1,
): string {
  if (!isFiniteNumber(value)) {
    return "No disponible";
  }
  return new Intl.NumberFormat("es-CL", { maximumFractionDigits }).format(value);
}

export function formatUf(value: number | null | undefined): string {
  if (!isFiniteNumber(value)) {
    return "No disponible";
  }
  return `UF ${formatNumber(value, 0)}`;
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

export function formatM2(value: number | null | undefined): string {
  if (!isFiniteNumber(value)) {
    return "No disponible";
  }
  return `${formatNumber(value, 1)} m2`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "No disponible";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "No disponible" : date.toLocaleDateString("es-CL");
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "No disponible";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "No disponible";
  }
  return date.toLocaleString("es-CL", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function formatPropertyType(value: string | null | undefined): string {
  const key = String(value ?? "").trim().toLowerCase();
  return PROPERTY_TYPE_LABELS[key] ?? formatText(value);
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

export function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
