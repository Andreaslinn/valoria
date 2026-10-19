"use client";
import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api/client";
import type { SiiClosingOpinion as Opinion } from "@/types/valuation";
import "./sii-closing.css";

export function useSiiClosingCapability() {
  const [enabled,setEnabled]=useState(false);
  useEffect(()=>{let active=true;void apiClient.get<{sii_closing_layer:boolean}>("/api/v1/tasar/capabilities").then(value=>{if(active)setEnabled(value.sii_closing_layer===true);}).catch(()=>{});return()=>{active=false;};},[]);
  return enabled;
}
const uf=(value:number|null|undefined)=>typeof value==="number"?`${new Intl.NumberFormat("es-CL",{maximumFractionDigits:0}).format(value)} UF`:"—";
const day=(value:string|null|undefined)=>value?value.split("-").reverse().join("/"):"—";
export function SiiClosingOpinion({opinion}:{opinion:Opinion|null|undefined}) {
  if(!opinion)return null;
  if(opinion.status!=="available")return <aside className="sii-notice" aria-label="Consulta de cierres SII"><strong>No mostramos una segunda opinión SII</strong><p>{opinion.message}</p>{opinion.candidates.length>0&&<><p>{opinion.candidate_count} opciones posibles:</p><ul>{opinion.candidates.map(item=><li key={item.id}>{item.label}</li>)}</ul></>}</aside>;
  const high=opinion.confidence_label==="Confianza alta";
  return <section aria-label="Segunda opinión con cierres SII" className={`sii-opinion ${high?"sii-opinion--high":"sii-opinion--reference"}`}>
    <header><div><span className="sii-eyebrow">CIERRES DECLARADOS · SII</span><h2>Segunda opinión con cierres SII</h2></div><span className="sii-badge">{opinion.confidence_label}</span></header>
    <p className="sii-value">{uf(opinion.value_uf)}</p>
    <div className="sii-range"><span>Rango P25–P75 de los comparables</span><strong>{uf(opinion.p25_uf)} — {uf(opinion.p75_uf)}</strong></div>
    <p className="sii-evidence"><strong>{opinion.comparable_count} cierres comparables</strong> · del {day(opinion.date_min)} al {day(opinion.date_max)}</p>
    <p>{opinion.message} {high?"No garantiza un error individual menor al 10%.":""}</p>
    <p className="sii-scope">{opinion.scope_message} {typeof opinion.area_m2==="number"?`${opinion.area_basis==="catastro_closed"?"Superficie cerrada SII":"Superficie ingresada"}: ${opinion.area_m2} m².`:""}</p>
    <details><summary>Ver fechas de los cierres</summary><ul className="sii-dates">{opinion.closing_dates.map((date,index)=><li key={`${date}-${index}`}>{day(date)}</li>)}</ul></details>
    <p className="sii-footer">Esta segunda opinión acompaña la estimación Valoria. El valor actual no se modifica.</p>
  </section>;
}
