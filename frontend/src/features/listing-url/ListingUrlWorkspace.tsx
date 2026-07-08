"use client";

import { AlertCircle, CheckCircle2, ExternalLink, FileText, Link2, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { StatusNote } from "@/components/ui/status-note";
import { ApiError } from "@/lib/api/client";
import { analyzeListingUrl, lookupListingUrl } from "@/lib/api/listings";
import { downloadListingAnalysisReport } from "@/lib/api/reports";
import { saveToWatchlist } from "@/lib/api/watchlist";
import {
  formatClp,
  formatConfidence,
  formatM2,
  formatNumber,
  formatPropertyType,
  formatText,
  formatUf,
} from "@/lib/formatters";
import type { ListingAnalysisResponse, ListingFreshnessMetadata, ListingLookupResponse } from "@/types/listing";

export function ListingUrlWorkspace() {
  const [url, setUrl] = useState("");
  const [result, setResult] = useState<ListingLookupResponse | null>(null);
  const [analysis, setAnalysis] = useState<ListingAnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [analysisLoading, setAnalysisLoading] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setResult(null);
    setAnalysis(null);
    setAnalysisError(null);

    const cleanUrl = url.trim();
    if (!cleanUrl) {
      setError("Ingresa una URL de publicacion.");
      return;
    }

    setLoading(true);
    try {
      setResult(await lookupListingUrl(cleanUrl));
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(340px,440px)_1fr]">
      <Card className="h-fit">
        <div className="flex items-start justify-between gap-4">
          <div>
            <CardTitle>Analizar publicacion</CardTitle>
            <CardDescription>
              Extrae datos disponibles desde una URL soportada para revisar la publicacion.
            </CardDescription>
          </div>
          <div className="rounded-lg border border-brand-500/25 bg-brand-500/10 p-2 text-brand-500">
            <Link2 className="h-5 w-5" aria-hidden />
          </div>
        </div>

        <form className="mt-6 grid gap-4" onSubmit={onSubmit}>
          <Input
            label="URL de publicacion"
            name="url"
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://www.yapo.cl/..."
            type="url"
            value={url}
            required
          />
          <StatusNote>
            Esta pantalla consulta endpoints reales. No crea reportes, previews ni descargas simuladas.
          </StatusNote>
          {error ? <StatusNote tone="warning">{error}</StatusNote> : null}
          <Button disabled={loading} type="submit">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
            {loading ? "Analizando..." : "Analizar URL"}
          </Button>
        </form>
      </Card>

      <LookupResult
        analysis={analysis}
        analysisError={analysisError}
        analysisLoading={analysisLoading}
        onAnalyze={async () => {
          if (!result) return;
          setAnalysisError(null);
          setAnalysisLoading(true);
          try {
            setAnalysis(await analyzeListingUrl(result.url));
          } catch (caught) {
            setAnalysis(null);
            setAnalysisError(errorText(caught));
          } finally {
            setAnalysisLoading(false);
          }
        }}
        result={result}
      />
    </div>
  );
}

function LookupResult({
  analysis,
  analysisError,
  analysisLoading,
  onAnalyze,
  result,
}: {
  analysis: ListingAnalysisResponse | null;
  analysisError: string | null;
  analysisLoading: boolean;
  onAnalyze: () => Promise<void>;
  result: ListingLookupResponse | null;
}) {
  const router = useRouter();
  const [saving, setSaving] = useState(false);
  const [watchlistMessage, setWatchlistMessage] = useState<string | null>(null);
  const [watchlistError, setWatchlistError] = useState<string | null>(null);

  if (!result) {
    return (
      <Card className="min-h-[360px]">
        <div className="flex h-full min-h-[320px] items-center justify-center rounded-lg border border-dashed border-line bg-black/20 p-8 text-center">
          <div>
            <Link2 className="mx-auto h-8 w-8 text-brand-500" aria-hidden />
            <h3 className="mt-4 text-lg font-semibold text-ink">Lista para analizar</h3>
            <p className="mt-2 max-w-md text-sm leading-6 text-muted">
              Pega una URL soportada. Si la API logra parsearla, veras los atributos que puede usar
              el flujo de tasacion.
            </p>
          </div>
        </div>
      </Card>
    );
  }

  const data = result.listing_data ?? {};
  const status = statusCopy(result.status);
  const listingId = typeof data.listing_id === "number" ? data.listing_id : null;

  async function saveCurrentListing() {
    if (listingId === null) return;
    setSaving(true);
    setWatchlistMessage(null);
    setWatchlistError(null);
    try {
      const saved = await saveToWatchlist(listingId);
      setWatchlistMessage(watchlistMessageForFreshness(saved) ?? "Publicacion guardada en tu watchlist.");
    } catch (caught) {
      setWatchlistError(errorText(caught));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="grid gap-5">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle>Resultado del lookup</CardTitle>
            <CardDescription>Respuesta real de POST /api/v1/listings/lookup-url.</CardDescription>
          </div>
          <span className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1 text-xs font-semibold uppercase tracking-wide ${status.className}`}>
            <CheckCircle2 className="h-4 w-4" aria-hidden />
            {status.label}
          </span>
        </div>

        <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <Fact label="Titulo" value={formatText(data.title)} />
          <Fact label="Comuna" value={formatText(data.comuna)} />
          <Fact label="Tipo" value={formatPropertyType(data.property_type)} />
          <Fact label="Superficie" value={formatM2(data.built_area_m2 ?? data.m2)} />
          <Fact label="Terreno" value={formatM2(data.land_area_m2)} />
          <Fact label="Dormitorios / banos" value={programLabel(data.dormitorios, data.banos)} />
          <Fact label="Estacionamientos" value={positiveNumberLabel(data.estacionamientos)} />
          <Fact label="Precio UF" value={formatUf(data.precio_publicado_uf)} />
          <Fact label="Precio CLP" value={formatClp(data.precio_publicado_clp)} />
          <Fact label="Fuente precio" value={priceSourceLabel(data)} />
        </div>

        <div className="mt-5">
          <StatusNote>
            El Listing Risk Report descargable sigue en preparacion. Esta accion genera un analisis JSON real, no un reporte falso.
          </StatusNote>
        </div>
        <FreshnessStatusNote freshness={analysis ?? result} />

        <div className="mt-5 flex flex-wrap gap-3">
          <Button disabled={analysisLoading} onClick={onAnalyze} type="button">
            {analysisLoading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <FileText className="h-4 w-4" aria-hidden />}
            {analysisLoading ? "Analizando..." : "Analizar publicacion"}
          </Button>
          {result.url ? (
            <a
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-line bg-white/[0.06] px-4 py-2 text-sm font-semibold text-ink transition hover:border-brand-500/45 hover:bg-brand-500/10"
              href={result.url}
              rel="noreferrer"
              target="_blank"
            >
              <ExternalLink className="h-4 w-4" aria-hidden />
              Abrir publicacion
            </a>
          ) : null}
          {listingId !== null ? (
            <Button disabled={saving} onClick={saveCurrentListing} type="button" variant="secondary">
              {saving ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
              {saving ? "Guardando..." : "Guardar en watchlist"}
            </Button>
          ) : (
            <Button disabled title="El lookup no devolvio listing_id para guardar." type="button" variant="secondary">
              Guardar no disponible
            </Button>
          )}
        </div>
        {analysisError ? (
          <div className="mt-4">
            <StatusNote tone="warning">{analysisError}</StatusNote>
          </div>
        ) : null}
        {watchlistMessage ? (
          <div className="mt-4">
            <StatusNote tone="success">
              {watchlistMessage}{" "}
              <button className="font-semibold text-emerald-100 underline" onClick={() => router.push("/app/portfolio")} type="button">
                Ver portfolio
              </button>
            </StatusNote>
          </div>
        ) : null}
        {watchlistError ? (
          <div className="mt-4">
            <StatusNote tone="warning">{watchlistError}</StatusNote>
          </div>
        ) : null}
      </Card>

      {analysis ? <ListingAnalysisCard analysis={analysis} /> : null}

      <Card>
        <CardTitle>Calidad de extraccion</CardTitle>
        <CardDescription>
          Campos faltantes o parciales vienen desde la API. No se completan con datos inventados.
        </CardDescription>
        {result.warnings?.length ? (
          <div className="mt-5 grid gap-2">
            {result.warnings.map((warning) => (
              <div
                className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100"
                key={warning}
              >
                <div className="flex items-center gap-2 font-semibold">
                  <AlertCircle className="h-4 w-4" aria-hidden />
                  {lookupWarningLabel(warning)}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-5 rounded-lg border border-line bg-white/[0.04] p-3 text-sm text-muted">
            La API no devolvio advertencias para esta publicacion.
          </div>
        )}
      </Card>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-white/[0.045] p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-2 break-words text-sm font-semibold text-ink">{value}</p>
    </div>
  );
}

function ListingAnalysisCard({ analysis }: { analysis: ListingAnalysisResponse }) {
  const tone = verdictTone(analysis.price_analysis.verdict);
  const [downloadState, setDownloadState] = useState<"idle" | "downloading" | "error">("idle");

  async function downloadReport() {
    setDownloadState("downloading");
    try {
      await downloadListingAnalysisReport(analysis);
      setDownloadState("idle");
    } catch {
      setDownloadState("error");
    }
  }

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <CardTitle>Analisis de publicacion</CardTitle>
          <CardDescription>Resultado real de POST /api/v1/listings/analyze-url.</CardDescription>
        </div>
        <span className={`inline-flex items-center rounded-lg border px-3 py-1 text-xs font-semibold uppercase tracking-wide ${tone}`}>
          {analysis.price_analysis.verdict_label}
        </span>
      </div>

      <p className="mt-4 text-sm leading-6 text-muted">{analysis.price_analysis.explanation}</p>

      <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <Fact label="Precio publicado" value={formatUf(analysis.price_analysis.published_price_uf ?? analysis.listing.price_uf)} />
        <Fact label="Estimacion Valoria" value={formatUf(analysis.valuation.estimated_value_uf)} />
        <Fact label="Diferencia" value={differenceLabel(analysis.price_analysis)} />
        <Fact label="Confianza" value={formatConfidence(analysis.valuation.confidence_score ?? analysis.valuation.confidence_label)} />
        <Fact label="Comparables usados" value={positiveNumberLabel(analysis.valuation.comparables_used)} />
        <Fact label="Rango estimado" value={rangeLabel(analysis.valuation.range_low_uf, analysis.valuation.range_high_uf)} />
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-3">
        <SignalList title="Senales positivas" items={analysis.signals.positives} empty="Sin senales positivas disponibles." />
        <SignalList title="Riesgos / advertencias" items={analysis.signals.risks} empty="Sin riesgos adicionales reportados." />
        <SignalList title="No disponible aun" items={analysis.signals.unavailable} empty="Sin pendientes reportados." />
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <Button disabled={downloadState === "downloading"} onClick={downloadReport} type="button" variant="secondary">
          {downloadState === "downloading" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <FileText className="h-4 w-4" aria-hidden />}
          {downloadState === "downloading" ? "Descargando..." : "Descargar analisis"}
        </Button>
        <span className="text-sm leading-6 text-muted">
          Listing Risk Report HTML generado por el backend con este analisis.
        </span>
      </div>
      {downloadState === "error" ? (
        <div className="mt-4">
          <StatusNote tone="warning">No fue posible generar el informe.</StatusNote>
        </div>
      ) : null}
      <FreshnessStatusNote freshness={analysis} />
    </Card>
  );
}

function FreshnessStatusNote({ freshness }: { freshness: ListingFreshnessMetadata }) {
  const message = freshnessMessage(freshness);
  if (!message) return null;
  return (
    <div className="mt-4">
      <StatusNote tone={freshnessTone(freshness.freshness_status)}>{message}</StatusNote>
    </div>
  );
}

function SignalList({ empty, items, title }: { empty: string; items: string[]; title: string }) {
  return (
    <div className="rounded-lg border border-line bg-white/[0.045] p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{title}</p>
      {items.length ? (
        <ul className="mt-3 grid gap-2 text-sm leading-5 text-ink">
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm leading-5 text-muted">{empty}</p>
      )}
    </div>
  );
}

function errorText(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "No pudimos analizar la URL. Intenta nuevamente.";
  }
  if (error.status === 401 || error.status === 403) {
    return "Tu sesion no esta vigente o no tiene permisos para analizar URLs.";
  }
  if (error.status === 400) {
    return error.message;
  }
  if (error.status === 502) {
    return "No se pudo parsear la publicacion. Prueba con otra URL soportada.";
  }
  if (error.status >= 500) {
    return "La API tuvo un problema al analizar la URL.";
  }
  return error.message;
}

function statusCopy(status: string) {
  if (status === "found_existing") {
    return {
      className: "border-accent-500/30 bg-accent-500/10 text-emerald-100",
      label: "Encontrada",
    };
  }
  if (status === "parsed_new") {
    return {
      className: "border-brand-500/30 bg-brand-500/10 text-violet-100",
      label: "Parseada",
    };
  }
  if (status === "partial") {
    return {
      className: "border-amber-500/30 bg-amber-500/10 text-amber-100",
      label: "Parcial",
    };
  }
  return {
    className: "border-line bg-white/[0.06] text-muted",
    label: status || "Disponible",
  };
}

function lookupWarningLabel(code: string): string {
  const labels: Record<string, string> = {
    invalid_url: "URL invalida",
    missing_comuna: "Comuna no detectada",
    missing_m2: "Superficie no detectada",
    missing_price: "Precio no detectado",
    missing_property_type: "Tipo de propiedad no detectado",
  };
  return labels[code] ?? code;
}

function freshnessMessage(freshness: ListingFreshnessMetadata): string | null {
  switch (freshness.freshness_status) {
    case "already_fresh":
      return "Publicacion confirmada recientemente.";
    case "fresh_confirmed":
      return "Publicacion vigente: Valoria la verifico en el portal.";
    case "removed":
    case "inactive":
    case "skipped_removed":
      return "El portal indica que esta publicacion ya no esta disponible.";
    case "blocked_or_captcha":
    case "skipped_recent_block":
      return "No pudimos confirmar vigencia porque el portal bloqueo la verificacion.";
    case "refresh_failed":
      return "No pudimos confirmar vigencia ahora. El analisis usa los datos disponibles.";
    case "skipped_recent_attempt":
      return "Valoria intento verificar esta publicacion recientemente.";
    case "url_missing_or_invalid":
      return "Esta URL no se puede refrescar automaticamente.";
    default:
      return null;
  }
}

function watchlistMessageForFreshness(freshness: ListingFreshnessMetadata): string | null {
  const message = freshnessMessage(freshness);
  if (!message) return null;
  return `Publicacion guardada en tu watchlist. ${message}`;
}

function freshnessTone(status: string | null | undefined): "info" | "warning" | "success" {
  if (status === "already_fresh" || status === "fresh_confirmed") {
    return "success";
  }
  if (
    status === "removed" ||
    status === "inactive" ||
    status === "skipped_removed" ||
    status === "blocked_or_captcha" ||
    status === "skipped_recent_block" ||
    status === "refresh_failed"
  ) {
    return "warning";
  }
  return "info";
}

function programLabel(dormitorios: number | null | undefined, banos: number | null | undefined): string {
  const parts = [positiveNumberLabel(dormitorios, "D"), positiveNumberLabel(banos, "B")].filter(
    (part) => part !== "No disponible",
  );
  return parts.length ? parts.join(" / ") : "No disponible";
}

function positiveNumberLabel(value: number | null | undefined, suffix = ""): string {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? `${formatNumber(value, 0)}${suffix}`
    : "No disponible";
}

function priceSourceLabel(data: ListingLookupResponse["listing_data"]): string {
  const currency = formatText(data.price_currency, "");
  const source = formatText(data.price_uf_source, "");
  const confidence = formatText(data.price_uf_confidence, "");
  const parts = [currency, source, confidence].filter(Boolean);
  return parts.length ? parts.join(" / ") : "No disponible";
}

function differenceLabel(priceAnalysis: ListingAnalysisResponse["price_analysis"]): string {
  if (typeof priceAnalysis.difference_pct !== "number" || typeof priceAnalysis.difference_uf !== "number") {
    return "No disponible";
  }
  const pct = `${formatNumber(priceAnalysis.difference_pct, 1)}%`;
  return `${formatUf(priceAnalysis.difference_uf)} / ${pct}`;
}

function rangeLabel(low: number | null | undefined, high: number | null | undefined): string {
  if (typeof low !== "number" || typeof high !== "number") {
    return "No disponible";
  }
  return `${formatUf(low)} - ${formatUf(high)}`;
}

function verdictTone(verdict: string): string {
  if (verdict === "under_market") {
    return "border-accent-500/30 bg-accent-500/10 text-emerald-100";
  }
  if (verdict === "over_market") {
    return "border-danger-500/30 bg-danger-500/10 text-red-100";
  }
  if (verdict === "in_range") {
    return "border-brand-500/30 bg-brand-500/10 text-violet-100";
  }
  return "border-amber-500/30 bg-amber-500/10 text-amber-100";
}
