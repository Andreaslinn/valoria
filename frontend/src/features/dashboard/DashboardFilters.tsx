"use client";

import { Building2, CalendarDays, MapPin } from "lucide-react";

type DashboardFiltersProps = {
  communes: string[];
  commune: string;
  loading: boolean;
  periodDays: 7 | 30 | 90;
  onCommuneChange: (value: string) => void;
  onPeriodChange: (value: 7 | 30 | 90) => void;
};

const fieldClass = "min-h-10 min-w-0 rounded-lg border border-line bg-black/20 px-3 text-sm font-medium text-ink outline-none transition focus:border-brand-500/70";

export function DashboardFilters({ communes, commune, loading, periodDays, onCommuneChange, onPeriodChange }: DashboardFiltersProps) {
  return (
    <div className="grid w-full gap-2 sm:grid-cols-3 lg:w-auto lg:min-w-[520px]">
      <label className="relative">
        <MapPin className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-brand-500" aria-hidden />
        <select className={`${fieldClass} w-full pl-9`} disabled={loading} onChange={(event) => onCommuneChange(event.target.value)} value={commune}>
          <option value="">Toda la RM</option>
          {communes.map((item) => <option key={item} value={item}>{item.replace(/_/g, " ")}</option>)}
        </select>
      </label>
      <label className="relative">
        <Building2 className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted" aria-hidden />
        <select aria-label="Tipo de propiedad" className={`${fieldClass} w-full pl-9`} disabled value="apartment">
          <option value="apartment">Departamentos</option>
        </select>
      </label>
      <label className="relative">
        <CalendarDays className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted" aria-hidden />
        <select className={`${fieldClass} w-full pl-9`} disabled={loading} onChange={(event) => onPeriodChange(Number(event.target.value) as 7 | 30 | 90)} value={periodDays}>
          <option value={7}>Ultimos 7 dias</option>
          <option value={30}>Ultimos 30 dias</option>
          <option value={90}>Ultimos 90 dias</option>
        </select>
      </label>
    </div>
  );
}
