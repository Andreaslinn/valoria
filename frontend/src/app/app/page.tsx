import {
  ArrowRight,
  Bell,
  FileText,
  Gauge,
  Link2,
  Radar,
  WalletCards,
} from "lucide-react";

import { PageHeading } from "@/components/layout/page-heading";
import { ButtonLink } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { StatusNote } from "@/components/ui/status-note";

const actions = [
  {
    title: "Tasar propiedad",
    description: "Flujo conectado al backend real para estimar valor, rango, confianza y comparables.",
    href: "/app/tasar",
    icon: Gauge,
    status: "Conectado",
  },
  {
    title: "Analizar publicacion",
    description: "Base para pegar una URL, revisar datos y generar reportes mas adelante.",
    href: "/app/analizar-url",
    icon: Link2,
    status: "Pendiente",
  },
  {
    title: "Buscar oportunidades en Radar",
    description: "Entrada futura al Radar profesional, todavia sin mapa ni consulta real.",
    href: "/app/radar",
    icon: Radar,
    status: "Pendiente",
  },
  {
    title: "Ver portfolio / watchlist",
    description: "Preparado para Watchlist, comparaciones y snapshots de portfolio.",
    href: "/app/portfolio",
    icon: WalletCards,
    status: "Pendiente",
  },
  {
    title: "Gestionar alertas",
    description: "Bandeja futura para eventos relevantes de propiedades guardadas.",
    href: "/app/alerts",
    icon: Bell,
    status: "Pendiente",
  },
  {
    title: "Reportes",
    description: "Area preparada para HTML/PDF autenticados cuando el backend los exponga.",
    href: "/app/reportes",
    icon: FileText,
    status: "Pendiente",
  },
];

export default function DashboardPage() {
  return (
    <>
      <PageHeading
        eyebrow="Cockpit"
        title="Centro de inteligencia Valoria"
        description="Accesos operativos a los modulos reales y a las areas preparadas para las siguientes migraciones."
      />
      <section className="mb-6 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <Card className="overflow-hidden">
          <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-brand-500">
                Proximo mejor paso
              </p>
              <h2 className="mt-2 text-2xl font-semibold text-ink">Tasar una propiedad</h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
                Es el primer modulo conectado al backend real. Desde aqui puedes validar la API,
                el token Bearer y la visualizacion de comparables sin tocar Streamlit.
              </p>
            </div>
            <ButtonLink href="/app/tasar">
              Abrir Tasar
              <ArrowRight size={17} />
            </ButtonLink>
          </div>
        </Card>
        <Card>
          <CardTitle>Estado de datos</CardTitle>
          <CardDescription>
            Este dashboard no muestra metricas de negocio hasta que cada modulo tenga endpoint
            conectado en Next.js.
          </CardDescription>
          <div className="mt-4">
            <StatusNote>Sin datos simulados en el cockpit.</StatusNote>
          </div>
        </Card>
      </section>
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {actions.map((action) => {
          const Icon = action.icon;
          return (
            <Card className="flex min-h-60 flex-col" key={action.href}>
              <div className="mb-5 flex items-start justify-between gap-3">
                <div className="grid h-11 w-11 place-items-center rounded-lg border border-brand-500/25 bg-brand-500/10 text-brand-500">
                  <Icon size={20} />
                </div>
                <span className="rounded-lg border border-line bg-white/[0.05] px-3 py-1 text-xs font-semibold text-muted">
                  {action.status}
                </span>
              </div>
              <CardTitle>{action.title}</CardTitle>
              <CardDescription>{action.description}</CardDescription>
              <div className="mt-auto pt-5">
                <ButtonLink className="w-full" href={action.href} variant="secondary">
                  Abrir
                </ButtonLink>
              </div>
            </Card>
          );
        })}
      </section>
    </>
  );
}
