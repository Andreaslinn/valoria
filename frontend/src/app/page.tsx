import {
  ArrowRight,
  Bell,
  FileText,
  Gauge,
  Link2,
  Radar,
  ShieldCheck,
  WalletCards,
} from "lucide-react";

import { PublicHeader } from "@/components/layout/public-header";
import { ButtonLink } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";

const productAreas = [
  {
    title: "Tasacion inteligente",
    description:
      "Valoracion real, comparables y senales de confianza en una pantalla clara.",
    icon: Gauge,
  },
  {
    title: "Analisis de publicacion",
    description:
      "Revisa URLs soportadas y lleva datos extraidos hacia Tasar sin inventar atributos faltantes.",
    icon: Link2,
  },
  {
    title: "Radar de oportunidades",
    description:
      "Busqueda manual de oportunidades recientes conectada al endpoint real de Radar.",
    icon: Radar,
  },
  {
    title: "Portafolio y alertas",
    description:
      "Watchlist y alertas reales para propiedades guardadas dentro de la beta.",
    icon: WalletCards,
  },
  {
    title: "Reportes de inversion",
    description:
      "Espacio en preparacion para reportes reales, sin previews ni descargas simuladas.",
    icon: FileText,
  },
];

export default function LandingPage() {
  return (
    <main className="min-h-screen bg-transparent">
      <PublicHeader />
      <section className="mx-auto grid max-w-7xl gap-10 px-5 pb-16 pt-10 lg:grid-cols-[1.05fr_0.95fr] lg:items-center lg:pb-20 lg:pt-14">
        <div>
          <p className="mb-4 inline-flex rounded-lg border border-brand-500/25 bg-brand-500/10 px-3 py-1 text-sm font-semibold text-violet-100">
            Fintech de inteligencia inmobiliaria para Chile
          </p>
          <h1 className="max-w-4xl text-4xl font-semibold leading-tight text-ink sm:text-6xl">
            Decide mejor al comprar, vender o invertir en propiedades.
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-8 text-muted">
            Valoria ordena tasaciones, publicaciones, radar, portfolio, alertas y reportes en una
            experiencia premium conectada al backend existente, sin mezclar datos reales con demos.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <ButtonLink href="/login">
              Entrar a la beta
              <ArrowRight size={18} />
            </ButtonLink>
            <ButtonLink href="/register" variant="secondary">
              Solicitar acceso
            </ButtonLink>
          </div>
        </div>

        <div className="rounded-lg border border-line bg-white/[0.055] p-5 shadow-soft backdrop-blur-xl">
          <div className="rounded-lg border border-line bg-black/30 p-5 text-white">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-ink">Cockpit Valoria</span>
              <span className="rounded-lg border border-accent-500/25 bg-accent-500/10 px-3 py-1 text-xs text-emerald-100">
                Beta por fases
              </span>
            </div>
            <div className="mt-8 grid gap-3">
              {[
                ["Tasar propiedad", "Conectado a POST /api/v1/valuations"],
                ["Analizar publicacion", "Conectado a POST /api/v1/listings/lookup-url"],
                ["Radar", "Conectado con ejecucion manual"],
                ["Portfolio / Watchlist", "Conectado a Watchlist real"],
              ].map(([label, detail]) => (
                <div className="rounded-lg border border-line bg-white/[0.055] p-4" key={label}>
                  <div className="text-sm font-semibold">{label}</div>
                  <div className="mt-1 text-xs text-slate-300">{detail}</div>
                </div>
              ))}
            </div>
            <div className="mt-5 rounded-lg border border-dashed border-line p-4 text-sm leading-6 text-muted">
              Las metricas de mercado apareceran cuando cada modulo tenga contrato estable. Esta
              vista evita mostrar cifras ficticias.
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto grid max-w-7xl gap-4 px-5 pb-16 md:grid-cols-2 lg:grid-cols-3">
        {productAreas.map((area) => {
          const Icon = area.icon;
          return (
            <Card key={area.title}>
              <div className="mb-4 grid h-10 w-10 place-items-center rounded-lg border border-brand-500/25 bg-brand-500/10 text-brand-500">
                <Icon size={20} />
              </div>
              <CardTitle>{area.title}</CardTitle>
              <CardDescription>{area.description}</CardDescription>
            </Card>
          );
        })}
      </section>

      <section className="border-t border-line bg-black/20">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-5 py-8 text-sm text-muted md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck size={18} />
            Beta cerrada conectada al backend FastAPI existente.
          </div>
          <div className="flex items-center gap-2">
            <Bell size={18} />
            Streamlit queda como backoffice y laboratorio.
          </div>
        </div>
      </section>
    </main>
  );
}
