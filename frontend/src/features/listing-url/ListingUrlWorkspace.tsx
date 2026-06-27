"use client";

import { AlertCircle, CheckCircle2, ExternalLink, Link2, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { StatusNote } from "@/components/ui/status-note";
import { ApiError } from "@/lib/api/client";
import { lookupListingUrl } from "@/lib/api/listings";
import { saveToWatchlist } from "@/lib/api/watchlist";
import type { ListingLookupData, ListingLookupResponse } from "@/types/listing";
import { saveTasarPrefillFromListing } from "@/features/valuation/prefill";

export function ListingUrlWorkspace() {
  const [url, setUrl] = useState("");
  const [result, setResult] = useState<ListingLookupResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setResult(null);

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
              Extrae datos disponibles desde una URL soportada para revisarlos antes de tasar.
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
            Esta pantalla consulta el endpoint real de lookup. No tasa la propiedad ni crea reportes.
          </StatusNote>
          {error ? <StatusNote tone="warning">{error}</StatusNote> : null}
          <Button disabled={loading} type="submit">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
            {loading ? "Analizando..." : "Analizar URL"}
          </Button>
        </form>
      </Card>

      <LookupResult result={result} />
    </div>
  );
}

function LookupResult({ result }: { result: ListingLookupResponse | null }) {
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
      await saveToWatchlist(listingId);
      setWatchlistMessage("Publicacion guardada en tu watchlist.");
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
          <Fact label="Titulo" value={text(data.title)} />
          <Fact label="Comuna" value={text(data.comuna)} />
          <Fact label="Tipo" value={propertyTypeLabel(data.property_type)} />
          <Fact label="Superficie" value={m2Label(data.built_area_m2 ?? data.m2)} />
          <Fact label="Terreno" value={m2Label(data.land_area_m2)} />
          <Fact label="Dormitorios / banos" value={`${numberLabel(data.dormitorios)} / ${numberLabel(data.banos)}`} />
          <Fact label="Estacionamientos" value={numberLabel(data.estacionamientos)} />
          <Fact label="Precio UF" value={ufLabel(data.precio_publicado_uf)} />
          <Fact label="Precio CLP" value={clpLabel(data.precio_publicado_clp)} />
        </div>

        <div className="mt-5 flex flex-wrap gap-3">
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
          <Button
            onClick={() => {
              saveTasarPrefillFromListing(data, result.url);
              router.push("/app/tasar");
            }}
            type="button"
            variant="secondary"
          >
            Tasar esta publicacion
          </Button>
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

function propertyTypeLabel(value: ListingLookupData["property_type"]): string {
  const labels: Record<string, string> = {
    apartment: "Departamento",
    house: "Casa",
    office: "Oficina",
    unknown: "No disponible",
  };
  return labels[String(value ?? "")] ?? text(value);
}

function text(value: unknown): string {
  const clean = String(value ?? "").trim();
  return clean || "No disponible";
}

function numberLabel(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "No disponible";
}

function m2Label(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? `${value} m2` : "No disponible";
}

function ufLabel(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `UF ${new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 }).format(value)}`
    : "No disponible";
}

function clpLabel(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value)
    ? new Intl.NumberFormat("es-CL", {
        currency: "CLP",
        maximumFractionDigits: 0,
        style: "currency",
      }).format(value)
    : "No disponible";
}
