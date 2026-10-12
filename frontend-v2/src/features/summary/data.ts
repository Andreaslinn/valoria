export type Period = "30D" | "90D" | "1A";
export const periods = ["30D", "90D", "1A"] as const;
export const number = (value: number) => new Intl.NumberFormat('es-CL', { maximumFractionDigits: 0 }).format(value);
