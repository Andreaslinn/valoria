"use client";
import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api/client";
import type { PropertyType } from "@/types/valuation";
import { Check, MapPin, CalendarDays, Building2, LoaderCircle } from "lucide-react";
import "./address-autofill.css";

type AddressData = {
  status: "resolved" | "ambiguous" | "unavailable";
  fields: { closed_area_m2?: number | null; land_area_m2?: number | null; construction_year?: number | null; property_type?: PropertyType | null };
  message: string;
  source?: string | null;
  source_period?: string | null;
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
  if (lookup.needsCommune) return <div className="address-hint" role="status"><MapPin size={20}/><p>Elige la comuna para buscar los datos de tu propiedad.</p></div>;
  if (lookup.loading) return <div className="address-hint address-hint--loading" role="status"><LoaderCircle size={20}/><p>Buscando tu propiedad…</p></div>;
  if (!lookup.data) return null;
  const data = lookup.data;
  if(data.status!=="resolved") return <div className="address-hint address-hint--attention" role="status"><MapPin size={22}/><div><strong>{data.status==="ambiguous"?"Necesitamos identificar la unidad":"Completa los datos manualmente"}</strong><p>{data.message}</p></div></div>;
  const count=Object.values(data.fields).filter(value=>value!=null).length;
  return <section className="address-match" aria-label="Datos encontrados de la propiedad" role="status">
    <header><span className="address-match-icon"><Check size={22}/></span><div><h3>Propiedad encontrada</h3><p>{data.source??"Catastro SII"}{data.source_period?` · ${data.source_period}`:""}</p></div><span className="address-count">{count} datos</span></header>
    <div className="address-facts">
      <div><span><Building2 size={16}/> Tipo de propiedad</span><strong>{data.fields.property_type==="house"?"Casa":data.fields.property_type==="apartment"?"Departamento":"Sin dato"}</strong></div>
      <div><span><CalendarDays size={16}/> Año de construcción</span><strong>{data.fields.construction_year??"Sin dato"}</strong></div>
    </div>
    <p className="address-match-footer">Puedes corregirlos.</p>
  </section>;
}
