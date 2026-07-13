export type WarningSeverity = "info" | "warning" | "risk";

export type WarningCategory =
  | "beta"
  | "comparables"
  | "datos"
  | "precio"
  | "superficie"
  | "ubicacion";

export type WarningDetail = {
  category: WarningCategory;
  code: string;
  description: string;
  known: boolean;
  label: string;
  severity: WarningSeverity;
};

const WARNING_DEFINITIONS: Record<string, Omit<WarningDetail, "code" | "known">> = {
  beta_scope_exploratory: {
    category: "beta",
    description: "El segmento existe en beta, pero la muestra todavia es limitada.",
    label: "Alcance beta exploratorio",
    severity: "warning",
  },
  beta_scope_no_data: {
    category: "beta",
    description: "No hay suficiente muestra para respaldar este segmento con fuerza.",
    label: "Sin datos suficientes de beta",
    severity: "risk",
  },
  beta_scope_weak_data: {
    category: "beta",
    description: "La cobertura beta para este caso es debil y debe leerse con cautela.",
    label: "Cobertura beta debil",
    severity: "warning",
  },
  high_dispersion: {
    category: "precio",
    description: "Los precios comparables muestran dispersion relevante.",
    label: "Alta dispersion de valor",
    severity: "warning",
  },
  high_price_m2_dispersion: {
    category: "precio",
    description: "Los precios por metro cuadrado varian mas de lo normal en la muestra.",
    label: "Precios comparables dispersos",
    severity: "warning",
  },
  house_land_area_weak: {
    category: "superficie",
    description: "Para casas, la evidencia de terreno no es suficientemente fuerte.",
    label: "Terreno con evidencia limitada",
    severity: "warning",
  },
  low_comparable_count: {
    category: "comparables",
    description: "La estimacion usa pocos comparables utiles para la propiedad consultada.",
    label: "Pocos comparables disponibles",
    severity: "warning",
  },
  low_data: {
    category: "datos",
    description: "La base disponible para esta consulta es acotada.",
    label: "Muestra de datos limitada",
    severity: "warning",
  },
  low_data_mode: {
    category: "datos",
    description: "La estimacion opera con una base de comparables limitada para este segmento.",
    label: "Muestra de datos limitada",
    severity: "warning",
  },
  near_duplicate_comparables: {
    category: "comparables",
    description: "Parte de la muestra parece repetida o demasiado similar.",
    label: "Comparables poco diversos",
    severity: "info",
  },
  poor_geocoding_comparables: {
    category: "ubicacion",
    description: "Algunos comparables usados no tienen ubicacion suficientemente precisa.",
    label: "Comparables con ubicacion debil",
    severity: "warning",
  },
  price_surface_high_dispersion: {
    category: "precio",
    description: "La superficie de precios presenta dispersion alta para este caso.",
    label: "Superficie de precio dispersa",
    severity: "warning",
  },
  price_surface_low_confidence: {
    category: "precio",
    description: "La referencia de precio por superficie tiene confianza limitada.",
    label: "Precio por superficie con baja confianza",
    severity: "warning",
  },
  single_source_comparables: {
    category: "comparables",
    description: "La estimacion usa principalmente datos provenientes de una fuente.",
    label: "Comparables de una sola fuente",
    severity: "warning",
  },
  surface_adjustment_high_dispersion: {
    category: "superficie",
    description: "El ajuste por superficie se mantiene cauteloso por dispersion alta.",
    label: "Ajuste por superficie cauteloso",
    severity: "warning",
  },
  surface_adjustment_risk_comuna: {
    category: "superficie",
    description: "La referencia de superficie usa soporte comunal y debe revisarse con cautela.",
    label: "Ajuste por superficie con soporte comunal",
    severity: "warning",
  },
  surface_adjustment_unavailable: {
    category: "superficie",
    description: "No hubo suficiente soporte para aplicar un ajuste adicional por superficie.",
    label: "Ajuste por superficie no disponible",
    severity: "info",
  },
  unknown_property_type: {
    category: "datos",
    description: "El tipo de propiedad no quedo completamente normalizado para el modelo.",
    label: "Tipo de propiedad no clasificado",
    severity: "warning",
  },
  weak_geolocation: {
    category: "ubicacion",
    description: "La ubicacion disponible no permite una lectura geografica completamente precisa.",
    label: "Ubicacion con precision limitada",
    severity: "warning",
  },
  weak_microzone: {
    category: "ubicacion",
    description: "No hay suficiente profundidad de datos a nivel microzona.",
    label: "Microzona limitada",
    severity: "warning",
  },
};

export function mapWarningCodes(codes: Array<string | null | undefined>): WarningDetail[] {
  const seen = new Set<string>();
  const result: WarningDetail[] = [];

  for (const rawCode of codes) {
    const code = String(rawCode ?? "").trim();
    if (!code || seen.has(code)) {
      continue;
    }
    seen.add(code);

    const definition = WARNING_DEFINITIONS[code];
    if (!definition) {
      result.push({
        category: "datos",
        code,
        description: "Valoria encontro una senal adicional que conviene revisar con cautela.",
        known: false,
        label: "Senal adicional no clasificada",
        severity: "info",
      });
      continue;
    }

    result.push({ ...definition, code, known: true });
  }

  return result;
}
