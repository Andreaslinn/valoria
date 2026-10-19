"use client";

import { Check, CheckCircle2, Download, Edit3, Home, MapPin, ShieldCheck, Sparkles, Users } from "lucide-react";
import { useEffect, useState } from "react";

import { Button, ButtonLink } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { StatusNote } from "@/components/ui/status-note";
import { ApiError } from "@/lib/api/client";
import { createPatrimonyProperty } from "@/lib/api/patrimony";
import { downloadValuationReport } from "@/lib/api/reports";
import type { Comparable, ValuationRequest, ValuationResponse } from "@/types/valuation";

import { SiiClosingOpinion } from "./SiiClosingOpinion";
import { ComparableCard } from "./ComparableCard";
import { getComparablePresentation } from "./comparables";
import { valuationEngineDisplayName } from "./engine-names";
import { formatClp, formatConfidence, formatPercent, formatUf } from "./formatters";
import { mapWarningCodes } from "./warningTaxonomy";

export function ValuationResult({ onEdit, payload, result }: { onEdit: () => void; payload: ValuationRequest | null; result: ValuationResponse | null }) {
  const [showAllComparables, setShowAllComparables] = useState(false);
  const [downloadState, setDownloadState] = useState<"idle" | "downloading" | "error">("idle");
  const [homeName, setHomeName] = useState("");
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    setHomeName(defaultHomeName(payload));
    setSaveState("idle");
    setSaveError(null);
    setShowAllComparables(false);
  }, [payload, result]);

  if (!result) return <EmptyResult />;

  const valuation = result;
  const engineName = valuationEngineDisplayName(result);
  const comparablePresentation = getComparablePresentation(result);
  const reportAvailable = Boolean(payload && (result.estimated_price_uf || result.estimated_price_clp) && comparablePresentation.availableCount);
  const visibleComparables = showAllComparables ? comparablePresentation.available : comparablePresentation.initiallyVisible;
  const warnings = mapWarningCodes([...(result.warnings ?? []), ...(result.confidence_risk_flags ?? []), ...(result.comparable_quality_flags ?? []), ...(result.beta_scope_flags ?? [])]);
  const range = rangePosition(result);

  async function saveToPatrimony() {
    if (!payload || !valuation.estimated_price_uf || saveState === "saving" || saveState === "saved") return;
    setSaveState("saving");
    setSaveError(null);
    try {
      await createPatrimonyProperty(buildPatrimonyPayload(homeName, payload, valuation));
      setSaveState("saved");
    } catch (caught) {
      setSaveState("error");
      setSaveError(caught instanceof ApiError && (caught.status === 401 || caught.status === 403) ? "Tu sesión no está vigente. Vuelve a iniciar sesión para guardar en Mi hogar." : "No pudimos guardar esta tasación en Mi hogar.");
    }
  }

  async function downloadReport() {
    if (!payload || !reportAvailable) return;
    setDownloadState("downloading");
    try {
      await downloadValuationReport({ payload, result: valuation });
      setDownloadState("idle");
    } catch {
      setDownloadState("error");
    }
  }

  return <div className="grid gap-5">
    <Card className="min-h-[420px] p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4"><div><CardTitle>Estimación Valoria</CardTitle></div><span className="inline-flex items-center gap-2 rounded-full border border-accent-500/25 bg-accent-500/10 px-3 py-1 text-xs font-semibold text-emerald-200"><Check className="h-3.5 w-3.5" />Tasación completada</span></div>
      <div className="py-10 text-center"><p className="text-4xl font-semibold tracking-tight text-ink sm:text-5xl">{formatUfDisplay(result.estimated_price_uf)}</p>{result.estimated_price_clp ? <p className="mt-3 whitespace-nowrap text-xl text-slate-300">{formatClp(result.estimated_price_clp)}</p> : null}</div>
      {(result.price_range_low_uf || result.price_range_high_uf) ? <div className="border-t border-line pt-5"><p className="text-center text-sm text-muted">Rango razonable</p><p className="mt-1 text-center text-lg font-semibold text-ink">{formatUfDisplay(result.price_range_low_uf)} — {formatUfDisplay(result.price_range_high_uf)}</p><div className="mt-5 h-1.5 rounded-full bg-slate-700/80"><div className="relative h-full rounded-full bg-slate-500/80" style={{ width: `${range.width}%` }}><span className="absolute top-1/2 h-4 w-4 -translate-y-1/2 rounded-full bg-brand-500 shadow-glow" style={{ left: `${range.marker}%` }} /></div></div><div className="mt-3 flex justify-between text-xs text-muted"><span>{formatUfDisplay(result.price_range_low_uf)}</span><span className="font-semibold text-ink">{formatUfDisplay(result.estimated_price_uf)}</span><span>{formatUfDisplay(result.price_range_high_uf)}</span></div></div> : null}
      <div className="mt-6 grid divide-y divide-line border-y border-line sm:grid-cols-3 sm:divide-x sm:divide-y-0"><SummaryMetric label="Confianza" value={result.confidence_score != null ? formatPercent(result.confidence_score) : formatConfidence(result.confidence_label || result.confidence)} tone="text-accent-500" /><SummaryMetric label="Comparables" value={result.comparable_count != null ? String(result.comparable_count) : null} /><SummaryMetric label="UF/m²" value={result.price_m2_uf ? formatUfDisplay(result.price_m2_uf) : null} /></div>
      {engineName ? <div className="mt-5 flex items-center justify-center gap-2 text-sm text-muted"><Sparkles className="h-4 w-4 text-brand-500" /><span>Motor de tasación</span><span className="font-semibold text-ink">{engineName}</span></div> : null}
      {payload && result.estimated_price_uf ? <div className="mt-5"><Input disabled={saveState === "saving" || saveState === "saved"} label="Nombre en Mi hogar (opcional)" name="patrimony-name" onChange={(event) => setHomeName(event.target.value)} value={homeName} /></div> : null}
      <div className="mt-6 grid gap-2 sm:grid-cols-2"><Button disabled={!payload || saveState === "saving" || saveState === "saved"} onClick={saveToPatrimony} type="button">{saveState === "saving" ? "Guardando..." : <><Home className="h-4 w-4" />Guardar en Mi hogar</>}</Button><Button disabled={!reportAvailable || downloadState === "downloading"} onClick={downloadReport} type="button" variant="secondary">{downloadState === "downloading" ? "Descargando..." : <><Download className="h-4 w-4" />Descargar informe</>}</Button><Button className="sm:col-span-2" onClick={onEdit} type="button" variant="secondary"><Edit3 className="h-4 w-4" />Editar datos</Button></div>
      {saveState === "saved" ? <div className="mt-4 flex flex-wrap items-center gap-3 rounded-lg border border-accent-500/30 bg-accent-500/10 p-3 text-sm text-emerald-100"><CheckCircle2 className="h-4 w-4" />Propiedad guardada en Mi hogar.<ButtonLink href="/app/patrimonio" variant="secondary">Ir a Mi patrimonio</ButtonLink></div> : null}
      {saveError ? <div className="mt-4"><StatusNote tone="warning">{saveError}</StatusNote></div> : null}
      {downloadState === "error" ? <div className="mt-4"><StatusNote tone="warning">No fue posible generar el informe.</StatusNote></div> : null}
    </Card>
    <SiiClosingOpinion opinion={result.sii_closing_opinion} />
    <EvidenceSection payload={payload} result={result} warnings={warnings} />
    <SignalsSection result={result} warnings={warnings} />
    <ComparablesSection availableCount={comparablePresentation.availableCount} comparables={visibleComparables} expanded={showAllComparables} onToggle={() => setShowAllComparables((current) => !current)} totalUsed={comparablePresentation.totalUsed} />
  </div>;
}

function EmptyResult() { return <Card className="grid min-h-[420px] place-items-center p-8 text-center"><div><Sparkles className="mx-auto h-8 w-8 text-brand-500" /><h2 className="mt-4 text-xl font-semibold text-ink">Tu estimación aparecerá aquí</h2><p className="mt-2 max-w-sm text-sm leading-6 text-muted">Completa los datos de la propiedad para revisar valor, rango y evidencia disponible.</p></div></Card>; }
function SummaryMetric({ label, tone = "text-ink", value }: { label: string; tone?: string; value: string | null }) { return value ? <div className="p-4 text-center"><p className="text-xs text-muted">{label}</p><p className={`mt-1 text-lg font-semibold ${tone}`}>{value}</p></div> : null; }
function EvidenceSection({ payload, result, warnings }: { payload: ValuationRequest | null; result: ValuationResponse; warnings: ReturnType<typeof mapWarningCodes> }) { const confidence = formatConfidence(result.confidence_label || result.confidence); return <Card><CardTitle>Qué respalda esta tasación</CardTitle><div className="mt-5 grid gap-5 sm:grid-cols-2 lg:grid-cols-4"><EvidenceFact icon={<Users />} value={result.comparable_count != null ? String(result.comparable_count) : null} text="comparables utilizados." /><EvidenceFact icon={<Sparkles />} value={result.price_m2_uf ? formatUfDisplay(result.price_m2_uf) : null} text="en el segmento analizado." /><EvidenceFact icon={<MapPin />} value={payload?.comuna ?? null} text="es la comuna analizada." /><EvidenceFact icon={<ShieldCheck />} value={confidence !== "No disponible" ? confidence : null} text={warnings.length ? "con señales que revisar." : "sin señales adicionales."} /></div>{result.confidence_reasons?.length ? <p className="mt-6 border-t border-line pt-4 text-sm leading-6 text-muted">{humanReason(result.confidence_reasons[0])}</p> : null}</Card>; }
function EvidenceFact({ icon, text, value }: { icon: React.ReactNode; text: string; value: string | null }) { return value ? <div><span className="grid h-10 w-10 place-items-center rounded-full bg-brand-500/10 text-brand-500">{icon}</span><p className="mt-3 text-lg font-semibold text-ink">{value}</p><p className="mt-1 text-sm leading-5 text-muted">{text}</p></div> : null; }
function SignalsSection({ result, warnings }: { result: ValuationResponse; warnings: ReturnType<typeof mapWarningCodes> }) { const cards = warnings.slice(0, 3); if (!cards.length) cards.push({ category: "datos", code: "confidence", description: "La estimación no reporta advertencias adicionales para esta propiedad.", known: true, label: "Evidencia disponible", severity: "info" }); return <Card><CardTitle>Señales de la tasación</CardTitle><div className="mt-5 grid gap-3 lg:grid-cols-3">{cards.map((warning) => <div className="rounded-lg border border-line bg-black/15 p-4" key={warning.code}><p className="font-semibold text-ink">{warning.label}</p><p className="mt-2 text-sm leading-6 text-muted">{warning.description}</p></div>)}</div>{result.surface_adjustment_reason ? <p className="mt-4 text-sm text-muted">{humanReason(result.surface_adjustment_reason)}</p> : null}</Card>; }
function ComparablesSection({ availableCount, comparables, expanded, onToggle, totalUsed }: { availableCount: number; comparables: Comparable[]; expanded: boolean; onToggle: () => void; totalUsed: number }) {
  const hasAvailableComparables = availableCount > 0;
  const hasUsedComparables = totalUsed > 0;

  return <Card><CardTitle>Comparables utilizados</CardTitle><CardDescription>Propiedades que respaldan la estimación.</CardDescription>{hasAvailableComparables ? <><div className="mt-5 grid gap-3 md:grid-cols-2">{comparables.map((comparable, index) => <ComparableCard comparable={comparable} key={`${comparable.listing_id ?? "comparable"}-${index}`} />)}</div>{totalUsed !== availableCount ? <p className="mt-4 text-sm text-muted">El motor utilizó {totalUsed} comparables; esta respuesta incluye {availableCount} fichas para revisar.</p> : null}{availableCount > 4 ? <div className="mt-5 text-center"><Button onClick={onToggle} type="button" variant="secondary">{expanded ? "Ver menos comparables" : `Ver los ${availableCount} comparables`}</Button></div> : null}</> : hasUsedComparables ? <p className="mt-5 text-sm text-muted">El motor utilizó {totalUsed} comparables, pero esta respuesta no incluye fichas para revisar.</p> : <p className="mt-5 text-sm text-muted">Esta respuesta no incluye comparables revisables.</p>}</Card>;
}
function selectedEngineResult(result: ValuationResponse) { return result.engine_results.find((engine) => engine.selected_for_final) ?? result.engine_results.find((engine) => engine.status === "ok") ?? result.engine_results[0] ?? null; }
function formatUfDisplay(value: number | null | undefined) { const formatted = formatUf(value); return formatted === "No disponible" ? formatted : formatted.replace("UF ", "") + " UF"; }
function rangePosition(result: ValuationResponse) { const low = result.price_range_low_uf; const high = result.price_range_high_uf; const estimate = result.estimated_price_uf; if (!low || !high || !estimate || high <= low) return { marker: 50, width: 100 }; const marker = Math.min(96, Math.max(4, ((estimate - low) / (high - low)) * 100)); return { marker, width: 100 }; }
function defaultHomeName(payload: ValuationRequest | null) { if (!payload?.comuna) return ""; const type = payload.property_type === "house" ? "Casa" : payload.property_type === "office" ? "Oficina" : "Departamento"; return `${type} ${titleCase(payload.comuna)}`; }
function titleCase(value: string) { return value.split(/[\s_-]+/).filter(Boolean).map((word) => `${word.charAt(0).toUpperCase()}${word.slice(1).toLowerCase()}`).join(" "); }
function humanReason(value: string) { return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase()); }
function buildPatrimonyPayload(name: string, payload: ValuationRequest, result: ValuationResponse) { const engine = selectedEngineResult(result); return { name: name.trim() || defaultHomeName(payload), comuna: payload.comuna, property_type: payload.property_type ?? null, m2: payload.m2, built_area_m2: payload.built_area_m2 ?? null, land_area_m2: payload.land_area_m2 ?? null, usable_area_m2: payload.usable_area_m2 ?? null, bedrooms: payload.dormitorios ?? null, bathrooms: payload.banos ?? null, parking: payload.estacionamientos ?? null, characteristics: { source: "tasar", ...payload }, valuation: { estimated_value_uf: result.estimated_price_uf, estimated_value_clp: result.estimated_price_clp, lower_bound_uf: result.price_range_low_uf ?? null, upper_bound_uf: result.price_range_high_uf ?? null, lower_bound_clp: result.price_range_low_clp ?? null, upper_bound_clp: result.price_range_high_clp ?? null, confidence: result.confidence, confidence_score: result.confidence_score ?? null, engine_name: engine?.engine_name ?? null, engine_version: engine?.engine_version ?? result.consensus_method ?? null, engine_payload: { consensus_used: result.consensus_used ?? false, selected_engine_names: result.selected_engine_names } } }; }
