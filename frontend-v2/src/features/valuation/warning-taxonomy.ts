import definitions from "../../../../core/assessment/warning_definitions.json";
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

const WARNING_DEFINITIONS = definitions as Record<string, Omit<WarningDetail, "code" | "known">>;

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
        severity: "warning",
      });
      continue;
    }

    result.push({ ...definition, code, known: true });
  }

  return result;
}
