"use client";

import { CheckCircle2, ExternalLink, FileText, Link2, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

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
  formatM2,
  formatNumber,
  formatPropertyType,
  formatText,
  formatUf,
} from "@/lib/formatters";
import type { ListingFreshnessMetadata, ListingLookupResponse } from "@/types/listing";

export function ListingUrlWorkspace() {
  const [url, setUrl] = useState("");
  const [result, setResult] = useState<ListingLookupResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisMessage, setAnalysisMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const analysisInFlightRef = useRef(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setResult(null);
    setAnalysisError(null);
    setAnalysisMessage(null);

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
            Analiza publicaciones soportadas y muestra solo datos disponibles para revision.
          </StatusNote>
          {error ? <StatusNote tone="warning">{error}</StatusNote> : null}
          <Button disabled={loading} type="submit">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
            {loading ? "Analizando..." : "Analizar URL"}
          </Button>
        </form>
      </Card>

      <LookupResult
        analysisError={analysisError}
        analysisMessage={analysisMessage}
        analysisLoading={analysisLoading}
        onAnalyze={async () => {
          if (!result || analysisInFlightRef.current) return;
          analysisInFlightRef.current = true;
          setAnalysisError(null);
          setAnalysisMessage(null);
          setAnalysisLoading(true);
          try {
            const analysis = await analyzeListingUrl(result.url);
            await downloadListingAnalysisReport(analysis);
            setAnalysisMessage("Reporte preparado. La descarga deberia comenzar automaticamente.");
          } catch (caught) {
            setAnalysisError(errorText(caught));
          } finally {
            analysisInFlightRef.current = false;
            setAnalysisLoading(false);
          }
        }}
        result={result}
      />
    </div>
  );
}

function LookupResult({
  analysisError,
  analysisMessage,
  analysisLoading,
  onAnalyze,
  result,
}: {
  analysisError: string | null;
  analysisMessage: string | null;
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
              Pega una URL soportada para ver los atributos disponibles y usarlos como punto de
              partida para una tasacion.
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
            <CardTitle>Datos de la publicacion</CardTitle>
            <CardDescription>Informacion extraida desde la publicacion soportada.</CardDescription>
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
            El informe descargable estara disponible despues de completar el analisis de la publicacion.
          </StatusNote>
        </div>
        <FreshnessStatusNote freshness={result} />

        <div className="mt-5 flex flex-wrap gap-3">
          <Button disabled={analysisLoading} onClick={onAnalyze} type="button">
            {analysisLoading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <FileText className="h-4 w-4" aria-hidden />}
            {analysisLoading ? "Preparando reporte..." : "Analizar publicacion"}
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
            <Button disabled title="Esta publicacion no esta disponible para guardar." type="button" variant="secondary">
              Guardar no disponible
            </Button>
          )}
        </div>
        {analysisError ? (
          <div className="mt-4">
            <StatusNote tone="warning">{analysisError}</StatusNote>
          </div>
        ) : null}
        {analysisMessage ? (
          <div className="mt-4">
            <StatusNote tone="success">{analysisMessage}</StatusNote>
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

function FreshnessStatusNote({ freshness }: { freshness: ListingFreshnessMetadata }) {
  const message = freshnessMessage(freshness);
  if (!message) return null;
  return (
    <div className="mt-4">
      <StatusNote tone={freshnessTone(freshness.freshness_status)}>{message}</StatusNote>
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
    return "No pudimos analizar la URL en este momento. Intenta nuevamente en unos minutos.";
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

