import {
  ArrowRight,
  Activity,
  BarChart3,
  Building2,
  CircleDot,
  Layers3,
  LockKeyhole,
  Radar,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
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

const cockpitStates: Array<{
  label: string;
  detail: string;
  icon: LucideIcon;
}> = [
  { label: "Publicacion", detail: "URL soportada", icon: BarChart3 },
  { label: "Radar", detail: "Busqueda manual", icon: Radar },
  { label: "Senales", detail: "Datos revisables", icon: Activity },
];

function TerritorialTexture() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-x-0 top-28 h-[32rem] overflow-hidden opacity-[0.45]"
    >
      <svg
        className="absolute left-1/2 top-10 h-[30rem] w-[78rem] -translate-x-1/2 text-violet-200/[0.45]"
        fill="none"
        viewBox="0 0 1240 480"
      >
        <defs>
          <radialGradient id="territory-fade" cx="50%" cy="50%" r="52%">
            <stop offset="0%" stopColor="rgba(124,92,255,0.22)" />
            <stop offset="58%" stopColor="rgba(124,92,255,0.08)" />
            <stop offset="100%" stopColor="rgba(124,92,255,0)" />
          </radialGradient>
          <linearGradient id="territory-line" x1="0%" x2="100%" y1="0%" y2="0%">
            <stop offset="0%" stopColor="rgba(196,181,253,0.02)" />
            <stop offset="45%" stopColor="rgba(196,181,253,0.28)" />
            <stop offset="100%" stopColor="rgba(196,181,253,0.03)" />
          </linearGradient>
        </defs>
        <ellipse cx="620" cy="252" fill="url(#territory-fade)" rx="520" ry="210" />
        <g stroke="url(#territory-line)" strokeWidth="1">
          <path d="M86 278 L188 218 L304 242 L418 172 L546 206 L676 138 L812 198 L946 158 L1128 222" />
          <path d="M124 344 L282 306 L430 348 L584 286 L742 322 L910 278 L1096 326" />
          <path d="M188 218 L282 306 L418 172 L430 348 L546 206 L584 286 L676 138 L742 322 L812 198 L910 278 L946 158" />
          <path d="M304 242 L546 206 L812 198 L1128 222" />
          <path d="M86 278 L304 242 L430 348 L676 138 L910 278" />
        </g>
        <g stroke="rgba(196,181,253,0.12)" strokeWidth="1">
          <path d="M156 166 L238 126 L330 150 L412 104 L506 132 L604 88 L720 130 L830 98 L970 146" />
          <path d="M212 396 L354 374 L512 410 L674 368 L840 396 L1014 360" />
        </g>
        <g fill="rgba(237,233,254,0.5)">
          {[
            [188, 218],
            [304, 242],
            [418, 172],
            [546, 206],
            [676, 138],
            [812, 198],
            [946, 158],
            [282, 306],
            [430, 348],
            [584, 286],
            [742, 322],
            [910, 278],
          ].map(([cx, cy]) => (
            <circle cx={cx} cy={cy} key={`${cx}-${cy}`} r="2.5" />
          ))}
        </g>
      </svg>
    </div>
  );
}

export default function LandingPage() {
  return (
    <main className="relative min-h-screen overflow-hidden bg-[#02040b] text-ink">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_18%_18%,rgba(124,92,255,0.23),transparent_27rem),radial-gradient(circle_at_82%_8%,rgba(61,220,151,0.09),transparent_24rem),radial-gradient(circle_at_50%_100%,rgba(124,92,255,0.25),transparent_35rem),linear-gradient(180deg,#02040b_0%,#07101d_48%,#02040b_100%)]" />
      <TerritorialTexture />
      <div className="pointer-events-none absolute inset-x-[-22%] top-[20rem] h-[36rem] rounded-[50%] border border-violet-400/15 bg-[radial-gradient(circle_at_50%_0%,rgba(124,92,255,0.14),transparent_62%)]" />

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

      <section className="relative z-10 mx-auto grid max-w-7xl gap-10 px-5 pb-12 pt-5 lg:grid-cols-[1.01fr_0.99fr] lg:items-center lg:pb-16 lg:pt-8">
        <div>
          <div className="inline-flex items-center gap-2 rounded-lg border border-brand-500/30 bg-brand-500/10 px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-violet-200 shadow-glow">
            <LockKeyhole size={16} />
            Acceso beta privado
          </div>
          <h1 className="mt-6 max-w-3xl text-[2.7rem] font-semibold leading-[1.03] text-white sm:text-5xl lg:text-[4.5rem]">
            Inteligencia inmobiliaria para decisiones con{" "}
            <span className="text-brand-500">ventaja.</span>
          </h1>
          <p className="mt-5 max-w-2xl text-base leading-7 text-slate-300 sm:text-lg">
            Valoria reune tasaciones, analisis de publicaciones y radar de oportunidades en una
            experiencia premium para compradores, vendedores e inversionistas en Chile.
          </p>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
            La beta es privada: el acceso se habilita por invitacion y las funcionalidades visibles
            trabajan sobre los modulos reales disponibles hoy.
          </p>
          <div className="mt-7 flex flex-col gap-3 sm:flex-row">
            <ButtonLink
              href="/login"
              className="min-h-[3.35rem] min-w-44 px-7 shadow-[0_0_34px_rgba(124,92,255,0.28)]"
            >
              Entrar a beta
              <ArrowRight size={18} />
            </ButtonLink>
            <ButtonLink href="/register" variant="secondary" className="min-h-[3.35rem] px-6">
              Solicitar acceso
            </ButtonLink>
          </div>
        </div>

        <div className="relative">
          <div className="absolute -inset-5 rounded-[2rem] bg-brand-500/10 blur-3xl" />
          <div className="relative overflow-hidden rounded-lg border border-violet-400/25 bg-[#060916]/[0.82] p-5 shadow-[0_28px_100px_rgba(0,0,0,0.52),0_0_70px_rgba(124,92,255,0.12)] backdrop-blur-2xl">
            <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(120deg,rgba(255,255,255,0.08),transparent_28%),radial-gradient(circle_at_80%_18%,rgba(124,92,255,0.18),transparent_18rem)]" />
            <div className="relative rounded-lg border border-line bg-black/30 p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-violet-200">
                    Cockpit Valoria
                  </p>
                  <h2 className="mt-3 max-w-sm text-2xl font-semibold leading-tight text-white">
                    Vista operativa para evaluar una propiedad.
                  </h2>
                </div>
                <span className="grid h-11 w-11 shrink-0 place-items-center rounded-lg border border-brand-500/30 bg-brand-500/10 text-brand-500">
                  <Sparkles size={21} />
                </span>
              </div>

              <div className="mt-6 grid gap-4 lg:grid-cols-[0.92fr_1.08fr]">
                <div className="rounded-lg border border-brand-500/25 bg-brand-500/[0.07] p-4">
                  <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-violet-200">
                    <CircleDot size={15} />
                    Tasacion
                  </div>
                  <div className="mt-5 space-y-3">
                    <div className="h-2 rounded-full bg-white/[0.12]">
                      <div className="h-2 w-4/5 rounded-full bg-brand-500/80 shadow-glow" />
                    </div>
                    <div className="h-2 rounded-full bg-white/[0.12]">
                      <div className="h-2 w-3/5 rounded-full bg-violet-300/55" />
                    </div>
                    <div className="h-2 rounded-full bg-white/[0.12]">
                      <div className="h-2 w-2/3 rounded-full bg-slate-300/35" />
                    </div>
                  </div>
                  <p className="mt-5 text-xs leading-5 text-slate-400">
                    Comparables, contexto y senales de confianza en revision.
                  </p>
                </div>

                <div className="grid gap-3">
                  {cockpitStates.map(({ label, detail, icon: Icon }) => (
                    <div
                      className="flex items-center justify-between gap-4 rounded-lg border border-line bg-white/[0.045] px-4 py-3"
                      key={label}
                    >
                      <div>
                        <div className="text-sm font-semibold text-white">{label}</div>
                        <div className="mt-1 text-xs text-slate-400">{detail}</div>
                      </div>
                      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-violet-300/20 bg-black/30 text-violet-200">
                        <Icon size={17} />
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="mt-5 rounded-lg border border-dashed border-violet-300/25 bg-brand-500/[0.035] p-4">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-violet-200">
                  <Layers3 size={15} />
                  Alcance beta
                </div>
                <p className="mt-2 text-sm leading-6 text-slate-300">
                  Sin metricas simuladas, clientes ficticios ni promesas fuera del alcance actual.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="relative z-10 mx-auto grid max-w-7xl gap-4 px-5 pb-14 md:grid-cols-[1.14fr_1fr_1fr]">
        {productAreas.map((area, index) => {
          const Icon = area.icon;
          return (
            <article
              className={`rounded-lg border p-6 shadow-soft backdrop-blur-xl ${
                index === 0
                  ? "border-brand-500/35 bg-brand-500/[0.075] md:-mt-3 md:p-7"
                  : "border-line bg-white/[0.052]"
              }`}
              key={area.title}
            >
              <div
                className={`mb-5 grid place-items-center rounded-lg border text-brand-500 ${
                  index === 0
                    ? "h-12 w-12 border-brand-500/40 bg-brand-500/15 shadow-glow"
                    : "h-11 w-11 border-brand-500/30 bg-brand-500/10"
                }`}
              >
                <Icon size={index === 0 ? 22 : 21} />
              </div>
              <h2 className={index === 0 ? "text-2xl font-semibold text-white" : "text-xl font-semibold text-white"}>
                {area.title}
              </h2>
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
