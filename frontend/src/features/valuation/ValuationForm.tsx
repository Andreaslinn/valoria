"use client";

import { Calculator, ChevronDown, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { StatusNote } from "@/components/ui/status-note";
import type { PropertyType, ValuationRequest } from "@/types/valuation";

import type { ValuationFormPrefill } from "./prefill";

import { useSiiClosingCapability } from "./SiiClosingOpinion";
import { AddressAutofillNote, useAddressDetails } from "./address-autofill";

type FormValues = { address: string; propertyType: PropertyType; comuna: string; builtAreaM2: string; landAreaM2: string; dormitorios: string; banos: string; estacionamientos: string; publishedPriceUf: string; publishedPriceClp: string };
type Props = { importedPrefill?: ValuationFormPrefill | null; isSubmitting: boolean; onSubmit: (payload: ValuationRequest) => Promise<void> };

const initialValues: FormValues = { address: "", propertyType: "apartment", comuna: "", builtAreaM2: "", landAreaM2: "", dormitorios: "", banos: "", estacionamientos: "", publishedPriceUf: "", publishedPriceClp: "" };
const propertyTypes: Array<{ label: string; value: PropertyType }> = [{ label: "Departamento", value: "apartment" }, { label: "Casa", value: "house" }, { label: "Oficina", value: "office" }];
const betaComunas = [
  { label: "Santiago", value: "santiago" },
  { label: "Providencia", value: "providencia" },
  { label: "Ñuñoa", value: "nunoa" },
  { label: "Las Condes", value: "las_condes" },
  { label: "Vitacura", value: "vitacura" },
  { label: "Lo Barnechea", value: "lo_barnechea" },
  { label: "La Reina", value: "la_reina" },
  { label: "Macul", value: "macul" },
  { label: "San Miguel", value: "san_miguel" },
  { label: "Estación Central", value: "estacion_central" },
  { label: "Independencia", value: "independencia" },
  { label: "Recoleta", value: "recoleta" },
  { label: "San Joaquín", value: "san_joaquin" },
  { label: "La Florida", value: "la_florida" },
];
const selectClassName = "min-h-11 w-full rounded-lg border border-line bg-slate-950/70 px-3 text-sm text-ink outline-none transition focus:border-brand-500/70 focus:ring-4 focus:ring-brand-100";

export function ValuationForm({ importedPrefill, isSubmitting, onSubmit }: Props) {
  const siiEnabled = useSiiClosingCapability();
  const [values, setValues] = useState<FormValues>(initialValues);
  const [formError, setFormError] = useState<string | null>(null);
  const [priceOpen, setPriceOpen] = useState(false);
  const isHouse = values.propertyType === "house";
  const autoArea = useRef<string|null>(null), autoLand = useRef<string|null>(null), typeEdited = useRef(false), autoType = useRef(false);
  const lookup = useAddressDetails(siiEnabled&&!isSubmitting, values.address, values.comuna);
  useEffect(() => {
    const data=lookup.data;if(data?.status!=="resolved")return;
    const area=data.fields.closed_area_m2;
    const fillArea=typeof area==="number"&&area>0&&values.builtAreaM2==="";
    const land=data.fields.land_area_m2;
    const fillLand=typeof land==="number"&&land>0&&values.landAreaM2==="";
    if(fillLand)autoLand.current=String(land);
    const fillType=data.fields.property_type&&!typeEdited.current?data.fields.property_type:null;
    if(fillArea)autoArea.current=String(area);
    if(fillType)autoType.current=true;
    setValues(v=>({...v,...(fillArea&&v.builtAreaM2===""?{builtAreaM2:String(area)}:{}),...(fillLand&&v.landAreaM2===""?{landAreaM2:String(land)}:{}),...(fillType?{propertyType:fillType}:{})}));
  },[lookup.data]);
  function update(key:keyof FormValues,value:string) {
    const clearArea=(key==="address"||key==="comuna")&&autoArea.current!==null;
    const clearLand=(key==="address"||key==="comuna")&&autoLand.current!==null;
    if(clearLand||key==="landAreaM2")autoLand.current=null;
    if(clearArea||key==="builtAreaM2")autoArea.current=null;
    const clearType=(key==="address"||key==="comuna")&&autoType.current;
    if(clearType)autoType.current=false;
    setValues(v=>({...v,...(clearArea?{builtAreaM2:""}:{}),...(clearLand?{landAreaM2:""}:{}),...(clearType?{propertyType:"apartment" as PropertyType}:{}),[key]:value}));
  }

  useEffect(() => {
    if (!importedPrefill) return;
    autoArea.current=null;autoLand.current=null;autoType.current=false;typeEdited.current=true;
    setValues((current) => ({
      ...current,
      address: "",
      propertyType: importedPrefill.propertyType ?? current.propertyType,
      comuna: comunaValue(importedPrefill.comuna) ?? current.comuna,
      builtAreaM2: textNumber(importedPrefill.builtAreaM2 ?? importedPrefill.usableAreaM2) ?? current.builtAreaM2,
      landAreaM2: textNumber(importedPrefill.landAreaM2) ?? current.landAreaM2,
      dormitorios: textNumber(importedPrefill.dormitorios) ?? current.dormitorios,
      banos: textNumber(importedPrefill.banos) ?? current.banos,
      estacionamientos: textNumber(importedPrefill.estacionamientos) ?? current.estacionamientos,
      publishedPriceUf: textNumber(importedPrefill.publishedPriceUf) ?? current.publishedPriceUf,
      publishedPriceClp: textNumber(importedPrefill.publishedPriceClp) ?? current.publishedPriceClp,
    }));
  }, [importedPrefill]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    const builtArea = numberFrom(values.builtAreaM2);
    const landArea = numberFrom(values.landAreaM2);
    if (!values.comuna.trim()) return setFormError("Ingresa la comuna de la propiedad.");
    if (!builtArea || builtArea <= 0) return setFormError("Ingresa una superficie útil o construida mayor a 0.");
    if (isHouse && (!landArea || landArea <= 0)) return setFormError("Para casas, ingresa la superficie de terreno.");
    await onSubmit({ comuna: values.comuna, property_type: values.propertyType, m2: builtArea, built_area_m2: builtArea, land_area_m2: isHouse ? landArea : null, usable_area_m2: values.propertyType === "apartment" && autoArea.current===null ? builtArea : null, dormitorios: integerOrNull(values.dormitorios), banos: integerOrNull(values.banos), estacionamientos: integerOrNull(values.estacionamientos), precio_publicado_uf: numberOrNull(values.publishedPriceUf), precio_publicado_clp: integerOrNull(values.publishedPriceClp), ...(siiEnabled && values.address.trim() ? { address: values.address.trim() } : {}) });
  }

  return <Card className="h-fit p-5 sm:p-6">
    <CardTitle>Datos de la propiedad</CardTitle>
    <CardDescription>Ingresa las principales características del inmueble.</CardDescription>
    <form className="mt-6 grid gap-4" onSubmit={handleSubmit}>
      {importedPrefill ? <StatusNote>Datos importados desde una publicación. Revísalos antes de tasar.</StatusNote> : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField label="Tipo de propiedad" value={values.propertyType} onChange={(value) => {typeEdited.current=true;autoType.current=false;setValues((current) => ({ ...current, propertyType: value as PropertyType }));}}>{propertyTypes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</SelectField>
        <SelectField label="Comuna" value={values.comuna} onChange={(value) => update("comuna",value)} required><option value="">Selecciona una comuna</option>{comunaOptionsFor(values.comuna).map((comuna) => <option key={comuna.value} value={comuna.value}>{comuna.label}</option>)}</SelectField>
      </div>
      {siiEnabled ? <div><Input label="Dirección de la propiedad" name="address" value={values.address} onChange={(event) => update("address",event.target.value)} placeholder="Calle, número y departamento" /></div> : null}
      <AddressAutofillNote lookup={lookup}/>
      <div className="grid gap-4 sm:grid-cols-2">
        <Input label={autoArea.current!==null?"Construcción · SII":"Superficie útil"} min="1" name="builtAreaM2" onChange={(event) => update("builtAreaM2",event.target.value)} required type="number" value={values.builtAreaM2} />
        <Input disabled={!isHouse} label={isHouse ? autoLand.current!==null?"Terreno · SII":"Superficie total / terreno" : "Superficie total"} min="1" name="landAreaM2" onChange={(event) => update("landAreaM2",event.target.value)} placeholder={isHouse ? "300" : "No aplica"} type="number" value={values.landAreaM2} />
      </div>
      {siiEnabled&&lookup.data?.status==="resolved"&&<div className="address-section-title">Completa tu ficha <span>Opcional</span></div>}
      <div className="grid gap-3 sm:grid-cols-3">
        <Input label="Dormitorios" min="0" name="dormitorios" onChange={(event) => setValues((current) => ({ ...current, dormitorios: event.target.value }))} type="number" value={values.dormitorios} />
        <Input label="Baños" min="0" name="banos" onChange={(event) => setValues((current) => ({ ...current, banos: event.target.value }))} type="number" value={values.banos} />
        <Input label="Estacionamientos" min="0" name="estacionamientos" onChange={(event) => setValues((current) => ({ ...current, estacionamientos: event.target.value }))} type="number" value={values.estacionamientos} />
      </div>
      <div className="overflow-hidden rounded-lg border border-line bg-black/15">
        <button aria-expanded={priceOpen} className="flex min-h-12 w-full items-center justify-between px-3 text-left text-sm font-semibold text-ink" onClick={() => setPriceOpen((current) => !current)} type="button">Comparar con un precio publicado<ChevronDown className={`h-4 w-4 text-muted transition ${priceOpen ? "rotate-180" : ""}`} /></button>
        {priceOpen ? <div className="grid gap-3 border-t border-line p-3 sm:grid-cols-2"><Input label="Precio publicado UF" min="0" name="publishedPriceUf" onChange={(event) => setValues((current) => ({ ...current, publishedPriceUf: event.target.value }))} placeholder="Ej. 14.500" type="number" value={values.publishedPriceUf} /><Input label="Precio publicado CLP" min="0" name="publishedPriceClp" onChange={(event) => setValues((current) => ({ ...current, publishedPriceClp: event.target.value }))} placeholder="Ej. 560.000.000" type="number" value={values.publishedPriceClp} /></div> : null}
      </div>
      {formError ? <StatusNote tone="warning">{formError}</StatusNote> : null}
      <Button className="mt-1 w-full" disabled={isSubmitting} type="submit">{isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Calculator className="h-4 w-4" />}{isSubmitting ? "Tasando..." : "Tasar propiedad"}</Button>
    </form>
  </Card>;
}

function SelectField({ children, label, onChange, required, value }: { children: React.ReactNode; label: string; onChange: (value: string) => void; required?: boolean; value: string }) { return <label className="grid gap-2 text-sm font-medium text-ink">{label}<select className={selectClassName} onChange={(event) => onChange(event.target.value)} required={required} value={value}>{children}</select></label>; }
function numberFrom(value: string): number | null { const parsed = Number(value); return value.trim() && Number.isFinite(parsed) ? parsed : null; }
function numberOrNull(value: string): number | null { const parsed = numberFrom(value); return parsed && parsed > 0 ? parsed : null; }
function integerOrNull(value: string): number | null { const parsed = numberFrom(value); return parsed === null ? null : Math.max(0, Math.trunc(parsed)); }
function textNumber(value: number | undefined): string | undefined { return typeof value === "number" && Number.isFinite(value) ? String(value) : undefined; }
function comunaValue(value: string | undefined): string | undefined {
  const cleanValue = value?.trim();
  if (!cleanValue) return undefined;
  const normalized = cleanValue.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  return betaComunas.some((comuna) => comuna.value === normalized) ? normalized : cleanValue;
}
function comunaOptionsFor(selectedValue: string) {
  if (!selectedValue || betaComunas.some((comuna) => comuna.value === selectedValue)) return betaComunas;
  return [...betaComunas, { label: selectedValue, value: selectedValue }];
}
