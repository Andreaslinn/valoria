// next.config.ts forwards this prefix to NEXT_PUBLIC_API_BASE_URL.
export const API_BASE_URL = "/backend";
export const LEGACY_BASE_URL = (process.env.NEXT_PUBLIC_LEGACY_BASE_URL || "http://localhost:3000").replace(/\/$/, "");
