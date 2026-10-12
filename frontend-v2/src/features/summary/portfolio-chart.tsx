import { useId } from "react";
import { number, type Period } from "./data";
import type { ChartSeries } from "./view-model";
import type { VisualFixture } from "./visual-fixture";

export function PortfolioChart({ period, real, visual }: { period: Period; real?: ChartSeries | null; visual?: VisualFixture["periods"][Period] }) {
  const id = useId().replace(/:/g, "");
  const illustrative = process.env.NODE_ENV === "development" ? visual : undefined;
  const series = illustrative ?? real;
  if (!series) return null;
  const width = 700, height = 154;
  const x = (i: number) => real && real.timestamps.at(-1)! > real.timestamps[0]
    ? (real.timestamps[i] - real.timestamps[0]) / (real.timestamps.at(-1)! - real.timestamps[0]) * width
    : i / (series.values.length - 1) * width;
  const y = (value: number) => height - (value - series.min) / (series.max - series.min) * height;
  const path = (values: number[]) => values.map((value, i) => {
    if (!i) return `M${x(i)},${y(value)}`;
    if (!illustrative) return `L${x(i)},${y(value)}`;
    const previous = values[i - 1];
    const dx = (x(i) - x(i - 1)) / 3;
    return `C${x(i - 1) + dx},${y(previous)} ${x(i) - dx},${y(value)} ${x(i)},${y(value)}`;
  }).join(" ");
  const high = series.values.map((v, i) => `${x(i)},${y(v + 330 + i * 4)}`);
  const low = series.values.map((v, i) => `${x(i)},${y(v - 220 - i * 3)}`).reverse();
  return <div className="portfolio-chart">
    <svg viewBox="0 0 780 206" role="img" aria-label={real ? "Total valorado de las propiedades cubiertas por cada snapshot. No representa rentabilidad." : "EJEMPLO: gráfica ilustrativa, no corresponde a tu cartera."} preserveAspectRatio="none">
      <defs><linearGradient id={`area-${id}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#c7f574" stopOpacity=".20"/><stop offset="1" stopColor="#c7f574" stopOpacity=".08"/></linearGradient><pattern id={`grid-${id}`} width="16.28" height="154" patternUnits="userSpaceOnUse"><path d="M 0 0 V 154" fill="none" stroke="#62747a" strokeOpacity=".14" strokeWidth="1"/></pattern></defs>
      <g transform="translate(60,13)"><rect width={width} height={height} fill={`url(#grid-${id})`}/>
        {series.ticks.map((tick, i) => <g key={tick}><line x1="0" x2={width} y1={y(tick)} y2={y(tick)} stroke="#62747a" strokeOpacity={i === 2 ? .5 : .25}/><text x="-12" y={y(tick) + 4} textAnchor="end" fill="#c8d0d8" fontSize="13">{number(tick)}{i === 0 ? " UF" : ""}</text></g>)}
        {illustrative && <path d={`M${high.join(" L")} L${low.join(" L")} Z`} fill={`url(#area-${id})`}/>}
        {illustrative && <path d={path(illustrative.published)} fill="none" stroke="#929da5" strokeWidth="1.6" strokeDasharray="4 3"/>}
        <path d={path(series.values)} fill="none" stroke="#f3f7ed" strokeWidth="2.1" strokeLinejoin="round" strokeLinecap="round"/>
        <circle cx={width} cy={y(series.values.at(-1)!)} r="4" fill="#192227" stroke="#f3f7ed" strokeWidth="2.3"/>
        {series.labels.map((label, i) => <text key={i} x={real ? i * width / 2 : i * width / 3 + 4} textAnchor={real && i === 2 ? "end" : "start"} y="176" fill="#a7b4c0" fontSize="12">{label}</text>)}
      </g>
    </svg>
    <div className="chart-legend" title={real?.note}><span><i/>{real ? "Total cubierto · snapshots reales" : "Estimación de cartera"}</span>{illustrative && <span><i className="dashed"/>Precio publicado agregado</span>}</div>
  </div>;
}
