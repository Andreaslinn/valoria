import { ExternalLink } from "lucide-react";

import { Card } from "@/components/ui/card";
import type { Comparable } from "@/types/valuation";

import { formatClp, formatM2, formatUf } from "./formatters";

export function ComparableCard({ comparable }: { comparable: Comparable }) {
  const bedrooms = comparable.dormitorios ?? comparable.bedrooms;
  const bathrooms = comparable.banos ?? comparable.bathrooms;
  const facts = [comparable.m2 ? formatM2(comparable.m2) : null, roomFact(bedrooms, "D"), roomFact(bathrooms, "B")].filter(Boolean);
  return <Card className="p-4">
    <div className="flex items-start justify-between gap-3"><div className="min-w-0"><h4 className="truncate text-sm font-semibold text-ink">{comparable.title || "Propiedad comparable"}</h4>{comparable.comuna ? <p className="mt-1 text-xs text-muted">{comparable.comuna}</p> : null}</div>{comparable.url ? <a className="shrink-0 text-muted hover:text-brand-500" href={comparable.url} rel="noreferrer" target="_blank" title="Ver publicación"><ExternalLink className="h-4 w-4" /></a> : null}</div>
    <p className="mt-4 text-xl font-semibold text-ink">{formatUf(comparable.price_uf)}</p>
    {comparable.price_clp ? <p className="mt-1 whitespace-nowrap text-sm text-muted">{formatClp(comparable.price_clp)}</p> : null}
    <div className="mt-3 flex flex-wrap gap-x-2 gap-y-1 text-xs text-muted">{comparable.price_uf && comparable.m2 ? <span>{formatUf(comparable.price_uf / comparable.m2)}/m²</span> : null}{facts.map((fact) => <span key={fact}>• {fact}</span>)}{comparable.similarity > 0 ? <span>• Similitud {Math.round(comparable.similarity * 100)}%</span> : null}</div>
  </Card>;
}

function roomFact(value: number | null | undefined, suffix: string) { return typeof value === "number" && value > 0 ? `${value}${suffix}` : null; }
