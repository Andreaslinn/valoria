import { FileText, Link2, ShieldAlert, Sparkles } from "lucide-react";

import { PageHeading } from "@/components/layout/page-heading";
import { InternalBackLink } from "@/components/layout/placeholder-panel";
import { ButtonLink } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { StatusNote } from "@/components/ui/status-note";

export default function ReportesPage() {
  return (
    <>
      <InternalBackLink />
      <PageHeading
        eyebrow="Contrato en auditoria"
        title="Reportes"
        description="Preparacion honesta para reportes reales, separando tasaciones manuales de analisis de publicaciones."
      />
      <div className="grid gap-5">
        <StatusNote>
          No hay descargas ni previews en esta pantalla hasta que exista un endpoint autenticado y estable para reportes de tasacion o publicacion.
        </StatusNote>

        <section className="grid gap-4 xl:grid-cols-2">
          <ReportTypeCard
            ctaHref="/app/tasar"
            ctaLabel="Ir a Tasar"
            description="Reporte para una tasacion manual. Evalua la propiedad como activo y no requiere URL, listing_id, precio publicado, watchlist ni historial de publicacion."
            icon={<Sparkles className="h-5 w-5" aria-hidden />}
            signals={[
              "Confianza AVM",
              "Comparables",
              "Comuna y soporte de mercado",
              "Microzona cuando exista evidencia",
              "Liquidez o tendencia cuando haya endpoint estable",
            ]}
            status="Preparacion"
            title="Investment Intelligence Report"
          />
          <ReportTypeCard
            ctaHref="/app/analizar-url"
            ctaLabel="Analizar URL"
            description="Reporte para una publicacion concreta. Ahi si corresponde leer precio publicado, fuente, listing_id, historial, watchlist y alertas asociadas."
            icon={<ShieldAlert className="h-5 w-5" aria-hidden />}
            signals={[
              "Precio publicado",
              "Descuento o sobreprecio",
              "URL, fuente y listing_id",
              "Historial de precio",
              "Watchlist y alertas asociadas",
            ]}
            status="Preparacion"
            title="Listing Risk Report"
          />
        </section>

        <Card>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <CardTitle>Contrato necesario para conectar Next.js</CardTitle>
              <CardDescription>
                El generador HTML existe en la capa UI/Streamlit, pero falta exponer un contrato API seguro para estos dos reportes.
              </CardDescription>
            </div>
            <span className="rounded-lg border border-line bg-white/[0.05] px-3 py-1 text-xs font-semibold text-muted">
              Sin endpoint estable
            </span>
          </div>
          <div className="mt-5 grid gap-3 md:grid-cols-3">
            <Fact label="Output esperado" value="HTML real o metadata real desde backend" />
            <Fact label="No disponible aqui" value="PDF, HTML fake, paths locales o descarga simulada" />
            <Fact label="Endpoint parcial existente" value="Portfolio comparison report HTML, no aplica a estos reportes" />
          </div>
        </Card>
      </div>
    </>
  );
}

function ReportTypeCard({
  ctaHref,
  ctaLabel,
  description,
  icon,
  signals,
  status,
  title,
}: {
  ctaHref: string;
  ctaLabel: string;
  description: string;
  icon: React.ReactNode;
  signals: string[];
  status: string;
  title: string;
}) {
  return (
    <Card className="flex min-h-96 flex-col">
      <div className="mb-5 flex items-start justify-between gap-3">
        <div className="grid h-11 w-11 place-items-center rounded-lg border border-brand-500/25 bg-brand-500/10 text-brand-500">
          {icon}
        </div>
        <span className="rounded-lg border border-line bg-white/[0.05] px-3 py-1 text-xs font-semibold text-muted">
          {status}
        </span>
      </div>
      <CardTitle>{title}</CardTitle>
      <CardDescription>{description}</CardDescription>
      <div className="mt-5 grid gap-2">
        {signals.map((signal) => (
          <div
            className="flex items-center gap-2 rounded-lg border border-line bg-white/[0.04] px-3 py-2 text-sm text-ink"
            key={signal}
          >
            <FileText className="h-4 w-4 shrink-0 text-brand-500" aria-hidden />
            <span>{signal}</span>
          </div>
        ))}
      </div>
      <div className="mt-auto pt-5">
        <ButtonLink className="w-full" href={ctaHref} variant="secondary">
          <Link2 className="h-4 w-4" aria-hidden />
          {ctaLabel}
        </ButtonLink>
      </div>
    </Card>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-white/[0.04] p-3">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-2 text-sm font-semibold leading-6 text-ink">{value}</p>
    </div>
  );
}
