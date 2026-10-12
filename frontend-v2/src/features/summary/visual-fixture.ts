import type { MarketWidgetView } from "./market-view-model";
import type { AlertView, opportunityView, portfolioView, zonesView } from "./view-model";
const illustrativePhotos = ["/images/plaza-egana.jpg", "/images/los-leones.jpg"] as const;

const history = [40410,40530,40580,40720,40840,40830,40940,40840,40900,40800,40890,41050,41130,41200,41370,41280,41240,41470,41490,41450,41590,41610,41680,41790,42010,42110,42020,41930,41960,42120,42160,42390,42380,42260,42310,42200,42420,42570,42520,42750,42810,42790,42870,42690,42720,42870,42830,43040,43170,43110,43090,43200,43250,43200,43380,43450];
const summaryData = {
  periods: {
    "30D": { change: "+0,9%", label: "en 30 días", labels: ["26 AGO", "10 SEP", "25 SEP"], min: 42000, max: 44000, ticks: [44000,43000,42000], values: history.slice(-22), published: history.slice(-22).map((_, i) => 42230 + i * 24 + Math.sin(i * .8) * 50) },
    "90D": { change: "+2,4%", label: "en 90 días", labels: ["JUL", "AGO", "SEP"], min: 40000, max: 44200, ticks: [44000,42000,40000], values: history, published: history.map((_, i) => 40240 + i * 25 + Math.sin(i * .3) * 95 + Math.cos(i * 1.1) * 40) },
    "1A": { change: "+6,8%", label: "en 1 año", labels: ["OCT 25", "MAR 26", "SEP 26"], min: 37000, max: 45000, ticks: [45000,41000,37000], values: history.map((v, i) => v - (history.length - i) * 45), published: history.map((_, i) => 38200 + i * 60 + Math.sin(i * .4) * 150) },
  },
  zones: [
    { name: "Ñuñoa" },
    { name: "Providencia" },
    { name: "Las Condes" },
  ],
};



// Loaded only after an explicit ?fixture=visual request in development.
export const visualFixture = {
  marketWidget: Object.fromEntries((["Entradas", "Salidas", "Rebajas"] as const).map((metric, mode) => {
    const values = [3,5,2,4,6,3,5,4,7,3,5,4,6,3,2,5,8,4,6,5,7,9,6,5,4,8,6,7,5,6].map(value => Math.max(1, value - mode));
    const total = values.reduce((sum, value) => sum + value, 0);
    const previous = [128, 105, 68][mode];
    return [metric, { total, previous, change: (total / previous - 1) * 100, active: 1284,
      points: values.map((value, index) => ({ date: new Date(Date.UTC(2026, 7, 26 + index)).toISOString().slice(0, 10), value })),
      communes: ["Ñuñoa", "Providencia", "Las Condes", "Vitacura", "La Reina"].map((name, index) => ({ name, value: [38, 29, 24, 18, 12][index] - mode * 3 })) }];
  })) as Record<"Entradas" | "Salidas" | "Rebajas", MarketWidgetView>,
  user: "Heiko", now: Date.parse("2026-09-25T12:00:00Z"), count: "3", uf: 39820,
  periods: summaryData.periods, photos: illustrativePhotos,
  portfolio: { total: 42860, count: 8, covered: 7, published: 40920, publishedCount: 8, difference: 4.7, matchedCount: 7, confidence: "Media", note: "Fixture visual de desarrollo; datos ilustrativos." } satisfies ReturnType<typeof portfolioView>,
  zones: [
    { name: "Ñuñoa", value: 74.2, change: .8, width: 46 },
    { name: "Providencia", value: 88.6, change: .3, width: 71 },
    { name: "Las Condes", value: 96.1, change: -.2, width: 81 },
  ].map(zone => ({ ...zone, count: 0, trendPhase: "ready" as const, trendError: null, trendNote: "Fixture visual · datos ilustrativos" })) satisfies ReturnType<typeof zonesView>,
  alerts: [
    { id: 1, key: "visual-price", source: "watchlist", kind: "price", title: "Bajó el precio de una propiedad guardada", description: "Plaza Egaña, Ñuñoa", previous: "5.420", next: "5.180 UF", time: "Hace 2 h" },
    { id: 2, key: "visual-valuation", source: "patrimony", kind: "valuation", title: "Una valoración necesita actualizarse", description: "Providencia · Datos de comparables antiguos", previous: null, next: null, time: "Hace 1 día" },
    { id: 3, key: "visual-listing", source: "watchlist", kind: "listing", title: "Nueva publicación en tu búsqueda", description: "Las Condes · 2 dormitorios · 6.450 UF", previous: null, next: null, time: "Hace 4 h" },
  ].map(alert => ({ ...alert, timestamp: 0, detail: "Fixture visual de desarrollo. No representa una alerta real.", url: null })) as AlertView[],
  opportunities: [
    { id: 1, title: "Plaza Egaña, Ñuñoa", area: 74, bedrooms: 2, bathrooms: 2, price: "5.180 UF", estimate: "5.760 UF", discount: "10,1% bajo estimación", confidence: "Media", comparables: 12, url: null, note: "Fixture visual de desarrollo." },
    { id: 2, title: "Los Leones, Providencia", area: 68, bedrooms: 2, bathrooms: 2, price: "6.240 UF", estimate: "6.590 UF", discount: "5,3% bajo estimación", confidence: "Alta", comparables: 18, url: null, note: "Fixture visual de desarrollo." },
  ] satisfies ReturnType<typeof opportunityView>[],
};
export type VisualFixture = typeof visualFixture;
