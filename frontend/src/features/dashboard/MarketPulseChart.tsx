"use client";

import { useState } from "react";
import { Area, CartesianGrid, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis, ComposedChart } from "recharts";

import type { MarketDashboardPulsePoint } from "@/types/market";
import { formatNumber } from "@/lib/formatters";

const series = [
  { key: "new_listings", label: "Nuevas publicaciones", color: "#6685ff" },
  { key: "removed_or_inactive", label: "Retiradas", color: "#f6a73c" },
  { key: "listings_with_price_drop", label: "Rebajas", color: "#72d572" },
] as const;

export function MarketPulseChart({ data }: { data: MarketDashboardPulsePoint[] }) {
  const [visible, setVisible] = useState<Record<string, boolean>>({ new_listings: true, removed_or_inactive: true, listings_with_price_drop: true });
  return (
    <div className="min-w-0">
      <div className="mb-3 flex flex-wrap gap-2">
        {series.map((item) => (
          <button className={`inline-flex items-center gap-2 rounded-md border px-2.5 py-1 text-xs font-medium transition ${visible[item.key] ? "border-line bg-white/[0.06] text-ink" : "border-transparent text-muted"}`} key={item.key} onClick={() => setVisible((current) => ({ ...current, [item.key]: !current[item.key] }))} type="button">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />{item.label}
          </button>
        ))}
      </div>
      <div className="h-[220px] min-w-0 sm:h-[250px]">
        <ResponsiveContainer height="100%" width="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 10, left: -18, bottom: 0 }}>
            <defs><linearGradient id="newPulse" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#6685ff" stopOpacity={0.22} /><stop offset="100%" stopColor="#6685ff" stopOpacity={0} /></linearGradient></defs>
            <CartesianGrid stroke="rgba(148,163,184,0.18)" strokeDasharray="3 4" vertical={false} />
            <XAxis axisLine={false} dataKey="date" minTickGap={28} tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={(value) => new Date(`${value}T00:00:00`).toLocaleDateString("es-CL", { day: "numeric", month: "short" })} tickLine={false} />
            <YAxis axisLine={false} allowDecimals={false} tick={{ fill: "#94a3b8", fontSize: 11 }} tickLine={false} />
            <Tooltip content={<PulseTooltip />} cursor={{ stroke: "rgba(255,255,255,0.25)", strokeDasharray: "3 3" }} />
            <Legend content={() => null} />
            {visible.new_listings ? <Area dataKey="new_listings" fill="url(#newPulse)" fillOpacity={1} stroke="#6685ff" strokeWidth={2} type="monotone" /> : null}
            {visible.removed_or_inactive ? <Line dataKey="removed_or_inactive" dot={false} name="Retiradas" stroke="#f6a73c" strokeWidth={2} type="monotone" /> : null}
            {visible.listings_with_price_drop ? <Line dataKey="listings_with_price_drop" dot={false} name="Rebajas" stroke="#72d572" strokeWidth={2} type="monotone" /> : null}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function PulseTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ color: string; name: string; value: number }>; label?: string }) {
  if (!active || !payload?.length) return null;
  return <div className="rounded-lg border border-line bg-[#0a101a] px-3 py-2 shadow-xl"><p className="text-xs font-semibold text-ink">{label ? new Date(`${label}T00:00:00`).toLocaleDateString("es-CL", { day: "numeric", month: "long" }) : ""}</p>{payload.map((item) => <p className="mt-1 text-xs text-muted" key={item.name}><span style={{ color: item.color }}>●</span> {item.name}: {formatNumber(item.value, 0)}</p>)}</div>;
}
