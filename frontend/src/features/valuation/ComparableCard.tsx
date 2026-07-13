import { ExternalLink } from "lucide-react";

import { Card } from "@/components/ui/card";
import type { Comparable } from "@/types/valuation";

import { formatClp, formatM2, formatNumber, formatUf } from "./formatters";

export function ComparableCard({ comparable }: { comparable: Comparable }) {
  const bedrooms = comparable.dormitorios ?? comparable.bedrooms;
  const bathrooms = comparable.banos ?? comparable.bathrooms;
  const program = [roomsLabel(bedrooms, "D"), roomsLabel(bathrooms, "B")].filter(Boolean).join(" / ");

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h4 className="text-sm font-semibold leading-5 text-ink">
            {comparable.title || "Comparable"}
          </h4>
          <p className="mt-1 text-xs text-muted">{comparable.comuna || "Comuna no disponible"}</p>
        </div>
        {comparable.url ? (
          <a
            className="rounded-lg border border-line p-2 text-muted transition hover:border-brand-500/40 hover:bg-brand-500/10 hover:text-brand-500"
            href={comparable.url}
            rel="noreferrer"
            target="_blank"
            title="Abrir publicacion"
          >
            <ExternalLink className="h-4 w-4" aria-hidden />
          </a>
        ) : null}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <ComparableFact label="Precio UF" value={formatUf(comparable.price_uf)} />
        <ComparableFact label="Precio CLP" value={formatClp(comparable.price_clp)} />
        <ComparableFact label="Superficie" value={formatM2(comparable.m2)} />
        <ComparableFact label="Programa" value={program || "No disponible"} />
        <ComparableFact label="Similitud" value={formatNumber(comparable.similarity, 2)} />
        <ComparableFact label="Referencia" value={comparable.listing_id ? `#${comparable.listing_id}` : "No disponible"} />
      </div>
    </Card>
  );
}

function ComparableFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 font-semibold text-ink">{value}</p>
    </div>
  );
}

function roomsLabel(value: number | null | undefined, suffix: string): string | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? `${value}${suffix}`
    : null;
}
