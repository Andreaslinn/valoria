"use client";
import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api/client";
import type { PropertyType } from "@/types/valuation";

type AddressData = {
  status: "resolved" | "ambiguous" | "unavailable";
  fields: { closed_area_m2?: number | null; construction_year?: number | null; property_type?: PropertyType | null };
  message: string;
  source?: string | null;
};
export function useAddressDetails(enabled: boolean, address: string, comuna: string) {
  const key = JSON.stringify([comuna, address.trim()]);
  const [state, setState] = useState<{ key: string; loading: boolean; data: AddressData | null }>({ key: "", loading: false, data: null });
  useEffect(() => {
    if (!enabled || !address.trim() || !comuna) return;
    let active = true;
    const timer = setTimeout(() => {
      setState({ key, loading: true, data: null });
      void apiClient.post<AddressData>("/api/v1/tasar/address-details", { address: address.trim(), comuna }).then(data => {
        if (active) setState({ key, loading: false, data });
      }).catch(() => {
        if (active) setState({ key, loading: false, data: { status: "unavailable", fields: {}, message: "No pudimos autocompletar. Inicia sesión o completa los datos manualmente." } });
      });
    }, 600);
    return () => { active = false; clearTimeout(timer); };
  }, [enabled, address, comuna, key]);
  return enabled && address.trim() && comuna && state.key === key ? { ...state, needsCommune: false } : { loading: false, data: null, needsCommune: enabled && Boolean(address.trim()) && !comuna };
}

export function AddressAutofillNote({ lookup }: { lookup: ReturnType<typeof useAddressDetails> }) {
  if (lookup.needsCommune) return <p className="sii-address-note" role="status">Selecciona la comuna para autocompletar desde la dirección.</p>;
  if (lookup.loading) return <p className="sii-address-note" role="status">Buscando datos de la dirección…</p>;
  if (!lookup.data) return null;
  const data = lookup.data;
  return <div className="sii-address-note" role="status"><p>{data.message}</p>
    {data.status === "resolved" && <>
      {typeof data.fields.closed_area_m2 === "number" && <p>Superficie cerrada SII: {data.fields.closed_area_m2} m². Se rellena si el campo está vacío; tus datos se conservan.</p>}
      {data.fields.construction_year != null && <p>Año de construcción: {data.fields.construction_year} · {data.source}.</p>}
      <p>Revisa los datos antes de tasar. La superficie cerrada puede diferir de la útil.</p>
    </>}
  </div>;
}
