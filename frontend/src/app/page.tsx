import {
  ArrowRight,
  BarChart3,
  Building2,
  LockKeyhole,
  Radar,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import Link from "next/link";

import { ButtonLink } from "@/components/ui/button";

const productAreas = [
  {
    title: "Tasaciones inteligentes",
    description:
      "Estima valor con comparables, contexto y senales de confiabilidad para evaluar una propiedad con mas claridad.",
    icon: Building2,
  },
  {
    title: "Analisis de publicaciones",
    description:
      "Convierte URLs soportadas en informacion revisable y la conecta con el flujo de tasacion cuando hay datos suficientes.",
    icon: BarChart3,
  },
  {
    title: "Radar de oportunidades",
    description:
      "Explora oportunidades recientes dentro del alcance beta, con filtros y criterios conectados al backend real.",
    icon: Radar,
  },
];

export default function LandingPage() {
  return (
    <main className="relative min-h-screen overflow-hidden bg-[#02040b] text-ink">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_18%_18%,rgba(124,92,255,0.23),transparent_27rem),radial-gradient(circle_at_82%_8%,rgba(61,220,151,0.09),transparent_24rem),radial-gradient(circle_at_50%_100%,rgba(124,92,255,0.25),transparent_35rem),linear-gradient(180deg,#02040b_0%,#07101d_48%,#02040b_100%)]" />
      <div className="pointer-events-none absolute inset-x-[-22%] top-[22rem] h-[42rem] rounded-[50%] border border-violet-400/20 bg-[radial-gradient(circle_at_50%_0%,rgba(124,92,255,0.18),transparent_62%)]" />

      <header className="relative z-10 mx-auto flex w-full max-w-7xl items-center justify-between px-5 py-5">
        <Link className="flex items-center gap-3" href="/">
          <span className="grid h-11 w-11 place-items-center rounded-lg border border-violet-300/30 bg-white/[0.045] text-2xl font-black text-brand-500 shadow-glow backdrop-blur-xl">
            V
          </span>
          <span>
            <span className="block text-sm font-bold uppercase tracking-[0.26em] text-white">
              Valoria
            </span>
            <span className="block text-xs text-slate-400">Beta privada</span>
          </span>
        </Link>
        <nav className="flex items-center gap-2">
          <ButtonLink href="/login" variant="ghost">
            Iniciar sesion
          </ButtonLink>
          <ButtonLink href="/register" variant="secondary">
            Solicitar acceso
          </ButtonLink>
        </nav>
      </header>

      <section className="relative z-10 mx-auto grid max-w-7xl gap-12 px-5 pb-16 pt-8 lg:grid-cols-[1.02fr_0.98fr] lg:items-center lg:pb-24 lg:pt-12">
        <div>
          <div className="inline-flex items-center gap-2 rounded-lg border border-brand-500/30 bg-brand-500/10 px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-violet-200 shadow-glow">
            <LockKeyhole size={16} />
            Acceso beta privado
          </div>
          <h1 className="mt-7 max-w-4xl text-5xl font-semibold leading-[1.02] text-white sm:text-6xl lg:text-7xl">
            Inteligencia inmobiliaria para decisiones con{" "}
            <span className="text-brand-500">ventaja.</span>
          </h1>
          <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-300">
            Valoria reune tasaciones, analisis de publicaciones y radar de oportunidades en una
            experiencia premium para compradores, vendedores e inversionistas en Chile.
          </p>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
            La beta es privada: el acceso se habilita por invitacion y las funcionalidades visibles
            trabajan sobre los modulos reales disponibles hoy.
          </p>
          <div className="mt-9 flex flex-col gap-3 sm:flex-row">
            <ButtonLink href="/login" className="min-h-12 px-5">
              Entrar a beta
              <ArrowRight size={18} />
            </ButtonLink>
            <ButtonLink href="/register" variant="secondary" className="min-h-12 px-5">
              Solicitar acceso
            </ButtonLink>
          </div>
        </div>

        <div className="relative">
          <div className="absolute -inset-6 rounded-[2rem] bg-brand-500/10 blur-3xl" />
          <div className="relative rounded-lg border border-violet-400/25 bg-[#060916]/80 p-5 shadow-[0_28px_110px_rgba(0,0,0,0.55),0_0_70px_rgba(124,92,255,0.13)] backdrop-blur-2xl">
            <div className="rounded-lg border border-line bg-black/30 p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-violet-200">
                    Cockpit Valoria
                  </p>
                  <h2 className="mt-3 text-2xl font-semibold text-white">
                    Beta enfocada en evaluacion inmobiliaria.
                  </h2>
                </div>
                <span className="grid h-11 w-11 shrink-0 place-items-center rounded-lg border border-brand-500/30 bg-brand-500/10 text-brand-500">
                  <Sparkles size={21} />
                </span>
              </div>

              <div className="mt-7 grid gap-3">
                {[
                  ["Tasar propiedad", "Comparables y confiabilidad en una vista accionable."],
                  ["Analizar publicacion", "Lectura de URL soportada sin completar datos faltantes."],
                  ["Explorar Radar", "Busqueda manual dentro del alcance beta privado."],
                ].map(([label, detail]) => (
                  <div
                    className="rounded-lg border border-line bg-white/[0.055] p-4"
                    key={label}
                  >
                    <div className="text-sm font-semibold text-white">{label}</div>
                    <div className="mt-1 text-xs leading-5 text-slate-400">{detail}</div>
                  </div>
                ))}
              </div>

              <div className="mt-5 rounded-lg border border-dashed border-violet-300/25 bg-brand-500/[0.035] p-4 text-sm leading-6 text-slate-300">
                Sin metricas simuladas, clientes ficticios ni promesas fuera del alcance actual de
                la beta.
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="relative z-10 mx-auto grid max-w-7xl gap-4 px-5 pb-16 md:grid-cols-3">
        {productAreas.map((area) => {
          const Icon = area.icon;
          return (
            <article
              className="rounded-lg border border-line bg-white/[0.055] p-6 shadow-soft backdrop-blur-xl"
              key={area.title}
            >
              <div className="mb-5 grid h-11 w-11 place-items-center rounded-lg border border-brand-500/30 bg-brand-500/10 text-brand-500">
                <Icon size={21} />
              </div>
              <h2 className="text-xl font-semibold text-white">{area.title}</h2>
              <p className="mt-3 text-sm leading-6 text-slate-300">{area.description}</p>
            </article>
          );
        })}
      </section>

      <footer className="relative z-10 border-t border-line bg-black/25">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-5 py-8 text-sm text-slate-400 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-2 text-slate-300">
            <ShieldCheck size={18} />
            Acceso beta privado conectado al producto real.
          </div>
          <div>(c) 2026 Valoria. Inteligencia inmobiliaria para Chile.</div>
        </div>
      </footer>
    </main>
  );
}
