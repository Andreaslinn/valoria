import { ArrowRight, type LucideIcon } from "lucide-react";
import Link from "next/link";

import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { StatusNote } from "@/components/ui/status-note";

export function PlaceholderPanel({
  title,
  description,
  icon: Icon,
  nextSteps,
}: {
  title: string;
  description: string;
  icon: LucideIcon;
  nextSteps: string[];
}) {
  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_0.7fr]">
      <Card>
        <div className="mb-5 grid h-12 w-12 place-items-center rounded-lg border border-brand-500/25 bg-brand-500/10 text-brand-500">
          <Icon size={22} />
        </div>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
        <div className="mt-5">
          <StatusNote>Modulo en preparacion. No muestra datos simulados como reales.</StatusNote>
        </div>
        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          {["Contrato API", "Estados UI", "QA beta"].map((item) => (
            <div className="rounded-lg border border-line bg-white/[0.04] p-3" key={item}>
              <p className="text-xs uppercase tracking-wide text-muted">{item}</p>
              <p className="mt-2 text-sm font-semibold text-ink">Pendiente</p>
            </div>
          ))}
        </div>
      </Card>
      <Card>
        <CardTitle>Preparado para el siguiente prompt</CardTitle>
        <ul className="mt-4 grid gap-3">
          {nextSteps.map((step) => (
            <li className="flex gap-3 text-sm leading-6 text-muted" key={step}>
              <ArrowRight className="mt-1 shrink-0 text-brand-500" size={16} />
              {step}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

export function InternalBackLink() {
  return (
    <Link className="mb-5 hidden text-sm font-semibold text-brand-500 lg:inline-flex" href="/app">
      Volver al dashboard
    </Link>
  );
}
