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
  subject_address?: string | null;
};
export type SearchMode = "address" | "rol";
export function useAddressDetails(enabled: boolean, address: string, comuna: string, mode: SearchMode = "address") {
  const key = JSON.stringify([mode, comuna, address.trim()]);
  const [state, setState] = useState<{ key: string; loading: boolean; data: AddressData | null }>({ key: "", loading: false, data: null });
  useEffect(() => {
    if (!enabled || !address.trim() || !comuna) return;
    let active = true;
    const timer = setTimeout(() => {
      setState({ key, loading: true, data: null });
      const endpoint=mode==="rol"?"/api/v1/tasar/rol-details":"/api/v1/tasar/address-details";
      const query=mode==="rol"?{rol:address.trim(),comuna}:{address:address.trim(),comuna};
      void apiClient.post<AddressData>(endpoint, query).then(data => {
        if (active) setState({ key, loading: false, data });
      }).catch(() => {
        if (active) setState({ key, loading: false, data: { status: "unavailable", fields: {}, message: "No pudimos autocompletar. Inicia sesión o completa los datos manualmente." } });
      });
    }, 600);
    return () => { active = false; clearTimeout(timer); };
  }, [enabled, address, comuna, key, mode]);
  return enabled && address.trim() && comuna && state.key === key ? { ...state, needsCommune: false } : { loading: false, data: null, needsCommune: enabled && Boolean(address.trim()) && !comuna };
}

export function PropertySearch({mode,onModeChange,address,onAddressChange,rol,onRoleChange}:{mode:SearchMode;onModeChange:(mode:SearchMode)=>void;address:string;onAddressChange:(value:string)=>void;rol:string;onRoleChange:(value:string)=>void}) {
  return <div className="address-search">
    <div className="address-mode" role="group" aria-label="Buscar propiedad por">
      <button type="button" aria-pressed={mode==="address"} onClick={()=>onModeChange("address")}>Por dirección</button>
      <button type="button" aria-pressed={mode==="rol"} onClick={()=>onModeChange("rol")}>Por rol</button>
    </div>
    {mode==="address"?<label className="tasar-field address-search-field"><span>Dirección de la propiedad</span><input aria-label="Dirección (opcional)" maxLength={512} value={address} onChange={e=>onAddressChange(e.target.value)} placeholder="Calle, número y departamento"/></label>:<label className="tasar-field address-search-field"><span>Rol de la propiedad</span><input aria-label="Rol de la propiedad" maxLength={64} value={rol} onChange={e=>onRoleChange(e.target.value)} placeholder="Ej. 1234-56"/><small className="address-field-caption">Manzana-predio · En la comuna seleccionada</small></label>}
  </div>;
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
    {data.subject_address&&<p className="address-subject">{data.subject_address}</p>}
    <div className="address-facts">
      <div><span><Building2 size={16}/> Tipo de propiedad</span><strong>{data.fields.property_type==="house"?"Casa":data.fields.property_type==="apartment"?"Departamento":"Sin dato"}</strong></div>
      <div><span><CalendarDays size={16}/> Año de construcción</span><strong>{data.fields.construction_year??"Sin dato"}</strong></div>
    </div>
    <p className="address-match-footer">Puedes corregirlos.</p>
  </section>;
}
