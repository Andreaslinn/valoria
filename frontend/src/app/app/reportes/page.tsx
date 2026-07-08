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
        eyebrow="Reportes reales"
        title="Reportes"
        description="Centro de descargas HTML generadas por backend para tasaciones manuales y analisis de publicaciones."
      />
      <div className="grid gap-5">
        <StatusNote>
          Los informes se descargan desde los flujos reales despues de ejecutar una tasacion o analizar una publicacion. No hay previews ni archivos de ejemplo.
        </StatusNote>

        <section className="grid gap-4 xl:grid-cols-2">
          <ReportTypeCard
            ctaHref="/app/tasar"
            ctaLabel="Tasar propiedad"
            description="Informe de una tasacion manual con estimacion Valoria, rango, confianza, comparables y senales de mercado. No requiere URL, listing_id, precio publicado ni watchlist."
            icon={<Sparkles className="h-5 w-5" aria-hidden />}
            signals={[
              "Investment Intelligence Report HTML",
              "Disponible despues de una tasacion exitosa",
              "Generado por el backend",
              "PDF fuera de esta fase",
            ]}
            title="Investment Intelligence Report"
          />
          <ReportTypeCard
            ctaHref="/app/analizar-url"
            ctaLabel="Analizar publicacion"
            description="Informe de una publicacion concreta con precio publicado, diferencia frente a Valoria, URL, listing_id y riesgos del anuncio cuando existen datos reales."
            icon={<ShieldAlert className="h-5 w-5" aria-hidden />}
            signals={[
              "Listing Risk Report HTML",
              "Disponible despues de analizar una URL",
              "Usa el analisis real mostrado",
              "PDF fuera de esta fase",
            ]}
            title="Listing Risk Report"
          />
        </section>

        <Card>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <CardTitle>Formatos disponibles</CardTitle>
              <CardDescription>
                Esta version expone HTML autonomo descargable. PDF no se muestra porque no hay infraestructura backend estable para generarlo.
              </CardDescription>
            </div>
            <span className="rounded-lg border border-accent-500/25 bg-accent-500/10 px-3 py-1 text-xs font-semibold text-emerald-100">
              HTML conectado
            </span>
          </div>
          <div className="mt-5 grid gap-3 md:grid-cols-3">
            <Fact label="Tasar" value="Descargar informe tras una tasacion real" />
            <Fact label="Analizar URL" value="Descargar analisis tras una publicacion real" />
            <Fact label="Sin historial unificado" value="No se inventa una lista de reportes recientes" />
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
  title,
}: {
  ctaHref: string;
  ctaLabel: string;
  description: string;
  icon: React.ReactNode;
  signals: string[];
  title: string;
}) {
  return (
    <Card className="flex min-h-80 flex-col">
      <div className="mb-5 flex items-start justify-between gap-3">
        <div className="grid h-11 w-11 place-items-center rounded-lg border border-brand-500/25 bg-brand-500/10 text-brand-500">
          {icon}
        </div>
        <span className="rounded-lg border border-accent-500/25 bg-accent-500/10 px-3 py-1 text-xs font-semibold text-emerald-100">
          Disponible HTML
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
