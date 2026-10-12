"use client";

import { ArrowDown, ArrowRight, Bell, Bookmark, Building2, FileText, House, Link2, RefreshCw, Target, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { AppShell, type ShowDetail } from "@/components/layout/app-shell";
import { Badge, Button, Card, TextAction } from "@/components/ui/primitives";
import { legacyRoute } from "@/lib/navigation";
import { formatNumber } from "@/lib/formatters";
import { Portfolio } from "./portfolio";
import { MarketToday } from "./market-today";
import { StateNotice, type SummaryActions as Actions } from "./state-notice";
import { ArrowLeftRight } from "lucide-react";

import { useSummary, errorText, type SummaryModel } from "./use-summary";
import { alertsView, opportunityView, pctText, searchableProperties, zonesView, type AlertView } from "./view-model";


function Attention({ model, alerts, count, openAlert, allAlerts, actions }: { model: SummaryModel; alerts: AlertView[]; count: string; openAlert: (alert: AlertView) => void; allAlerts: () => void; actions: Actions }) {
  const icons = { price: ArrowDown, valuation: RefreshCw, listing: FileText, notice: Bell };
  const { alerts: watchlist, patrimonyAlerts: patrimony } = model.sources;
  const primary = watchlist.phase === "ready" ? patrimony.phase === "ready" ? watchlist : patrimony : watchlist;
  const partial = [watchlist, patrimony].some(source => source.phase === "error");
  return <Card label="Lo que requiere tu atención" className="attention-card">
    <div className="card-heading"><h2 className="eyebrow">Lo que requiere tu atención</h2><Badge>{count} novedades</Badge></div>
    {partial && alerts.length > 0 && <button className="source-note" onClick={actions.retry}>Datos parciales · reintentar fuente no disponible</button>}
    <div className="alert-list">{alerts.length ? alerts.slice(0, 3).map(alert => { const Icon = icons[alert.kind]; return <article className="alert-row" key={alert.key}><div className="alert-icon"><Icon size={25} strokeWidth={1.5}/></div><i className={`status-dot ${alert.kind}`}/><div className="alert-content"><div className="alert-title"><h3 title={alert.title}>{alert.title}</h3><span>{alert.time}</span></div><p title={alert.description}>{alert.description}</p><div className="alert-bottom">{alert.previous && alert.next && <strong>{alert.previous} <ArrowRight size={18}/> {alert.next}</strong>}<TextAction onClick={() => openAlert(alert)}>{alert.kind === "price" ? "Revisar cambio" : alert.kind === "valuation" ? "Revisar evidencia" : alert.kind === "listing" ? "Ver publicación" : "Revisar detalle"}</TextAction></div></div></article>; }) : <StateNotice resource={primary} empty="No tienes novedades pendientes." {...actions}/>}</div>
    <button className="text-action all-alerts" onClick={allAlerts}><span>Ver todas las alertas</span><ArrowRight size={17}/></button>
  </Card>;
}

function Opportunities({ model, onNavigate, showDetail, actions }: { model: SummaryModel; onNavigate: (label: string) => void; showDetail: ShowDetail; actions: Actions }) {
  const { opportunities, radar, watchlist } = model.sources;
  const items = model.fixture?.opportunities ?? opportunities.data?.map(opportunityView) ?? [];
  return <Card label="Oportunidades para revisar" className="opportunities-card"><div className="section-heading"><h2>Oportunidades para revisar</h2><TextAction onClick={() => onNavigate("Radar")}>Abrir Radar</TextAction></div>
    {!model.fixture && watchlist.phase === "error" && <button className="source-note" onClick={actions.retry}>Watchlist no disponible: {watchlist.error} · reintentar</button>}
    {model.mutationError && <p className="source-note" role="alert">{model.mutationError}</p>}
    {!model.fixture && opportunities.phase === "idle" ? radar.phase !== "ready" ? <StateNotice resource={radar} empty="Radar no disponible." {...actions}/> : <div className="data-state radar-state"><p>{radar.data?.summary ?? "Oportunidades bajo demanda"}</p><span className="muted">{radar.data?.ready_for_radar_count ?? 0} candidatas listas para evaluar</span><Button onClick={model.loadOpportunities}>Buscar oportunidades <ArrowRight size={16}/></Button></div> : (!model.fixture && opportunities.phase !== "ready") || !items.length ? <StateNotice resource={opportunities} empty="No se encontraron oportunidades con los criterios actuales de Radar." retry={model.loadOpportunities} login={actions.login}/> : <div className="opportunity-list">{items.map((item, index) => { const saved = watchlist.data?.some(entry => entry.listing_id === item.id && entry.status === "active"); return <article className="opportunity-row" key={item.id ?? `untracked-${index}`}>
      {model.fixture ? <img src={model.fixture.photos[index]} alt="Interior ilustrativo de la propiedad"/> : <div className="property-image-placeholder" role="img" aria-label="Fotografía no disponible"><Building2 size={25}/><small>Sin fotografía</small></div>}
      <div className="opportunity-info"><h3 title={item.title}>{item.url ? <a href={item.url} target="_blank" rel="noopener noreferrer">{item.title}</a> : item.title}</h3><p>{item.area ?? "—"} m² · {item.bedrooms ?? "—"} dorm. · {item.bathrooms ?? "—"} baños</p></div><strong className="asking-price">{item.price}</strong><div className="estimate"><span>Estimación</span><strong>{item.estimate}</strong></div><div className="opportunity-discount"><button onClick={() => showDetail(item.title, item.note || "Sin advertencias adicionales en el resultado de Radar.")} title={item.note}><strong>{item.discount}</strong></button><p title={item.confidence}>{item.confidence} · {item.comparables} comparables</p></div><button className={`bookmark${saved ? " saved" : ""}`} aria-label={`${saved ? "Quitar" : "Guardar"} ${item.title} en tu cartera`} aria-pressed={Boolean(saved)} disabled={item.id == null || model.busyId !== null || (!model.fixture && watchlist.phase !== "ready")} title={watchlist.phase !== "ready" ? "La cartera no está disponible para guardar" : undefined} onClick={() => model.fixture ? showDetail("Fixture visual", "Las acciones sobre la cartera están desactivadas en este modo de desarrollo.") : item.id != null && void model.toggleSaved(item.id)}><Bookmark size={21} strokeWidth={1.5}/></button>
    </article>; })}</div>}
  </Card>;
}

function ZonePulse({ model, showDetail, actions }: { model: SummaryModel; showDetail: ShowDetail; actions: Actions }) {
  const rows = model.fixture?.zones ?? zonesView(model.sources.market.data, model.selection.names, model.trends);
  const market = model.sources.market;
  return <Card label="Pulso de tus zonas" className="zones-card"><div className="section-heading"><h2>Pulso de tus zonas</h2><span className="period-caption">{model.fixture ? "Últimos 30 días" : "Publicaciones activas"}</span></div><p className="zone-subtitle">{model.fixture ? "Precio publicado mediano · departamentos" : `UF/m² · departamentos · ${model.selection.marketSelection ? "comunas con mayor oferta" : "comunas de tu cartera"}`}</p>
    {!model.fixture && market.phase !== "ready" ? <StateNotice resource={market} empty="Mercado no disponible." {...actions}/> : !model.fixture && (!rows.length || !market.data?.communes.length) ? <StateNotice resource={market} empty="No hay publicaciones disponibles en el mercado." {...actions}/> : <><div className="zones">{rows.map(zone => <div className="zone-row" key={zone.name}><strong>{zone.name}</strong><div className="zone-track"><span style={{ width: `${zone.width}%` }}/></div><span>{zone.value == null ? "Sin datos" : `${formatNumber(zone.value, 1)} UF/m²`}</span></div>)}</div><TextAction onClick={() => showDetail("Contexto de mercado", model.fixture ? "Fixture visual de desarrollo: precios y variaciones ilustrativos, no datos reales." : `${model.selection.marketSelection ? "Comunas con mayor oferta activa; no son preferencias de zonas seguidas. " : "Comunas derivadas de las propiedades que sigues. "}Precios medianos reales de las publicaciones activas, no de cierre.\n\n${rows.map(row => `${row.name}: ${row.count} publicaciones. ${row.trendNote}`).join("\n\n")}\n\n${market.data?.methodology ?? ""}`)}>Ver contexto de mercado</TextAction></>}
  </Card>;
}

type Detail = { title: string; description: string; mode?: "login" | "account" | "alerts"; alert?: AlertView };
export function Summary() {
  const model = useSummary();
  const [widget, setWidget] = useState<"market" | "portfolio">("market");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const { sources } = model;
  const alerts = model.fixture?.alerts ?? alertsView(sources.alerts.data ?? [], sources.patrimonyAlerts.data?.items ?? [], sources.watchlist.data ?? [], model.now);
  const personalCount = sources.portfolio.data?.unread_alert_count ?? sources.alerts.data?.length;
  const patrimonyCount = sources.patrimonyAlerts.data?.items.filter(alert => !alert.read_at && !alert.dismissed_at).length;
  const count = model.fixture?.count ?? (personalCount == null && patrimonyCount == null ? "—" : `${(personalCount ?? 0) + (patrimonyCount ?? 0)}${sources.alerts.data?.length === 100 && !sources.portfolio.data ? "+" : ""}${sources.alerts.phase !== "ready" || sources.patrimonyAlerts.phase !== "ready" ? "*" : ""}`);
  const user = model.fixture?.user ?? (sources.user.data?.email.split("@")[0] || "tu espacio");
  const showDetail: ShowDetail = (title, description) => { setDialogError(null); setDetail({ title, description }); };
  const openAlert = (alert: AlertView) => { setDialogError(null); setDetail({ title: alert.title, description: alert.detail, alert }); };
  const openLogin = () => { if (model.fixture) { showDetail("Fixture visual", "Datos ilustrativos de desarrollo. Abre Resumen sin ?fixture=visual para conectar tu cuenta real."); return; } setDialogError(null); setDetail({ title: "Iniciar sesión en Valoria", description: "Usa tu cuenta para consultar tu cartera y alertas.", mode: "login" }); };
  const allAlerts = () => { setDialogError(null); setDetail({ title: "Tus novedades", description: "Alertas pendientes de tus propiedades y patrimonio.", mode: "alerts" }); };
  const actions = { retry: model.refresh, login: openLogin };
  const alertsResource = [sources.alerts, sources.patrimonyAlerts].find(source => source.phase !== "ready") ?? sources.alerts;
  useEffect(() => { if (detail) dialogRef.current?.showModal(); else dialogRef.current?.close(); }, [detail]);
  const onNavigate = (label: string) => {
    if (label === "Workspace personal") {
      if (!model.token) openLogin(); else { setDialogError(null); setDetail({ title: "Tu cuenta", description: sources.user.data?.email ?? "Sesión de Valoria", mode: "account" }); }
      return;
    }
    if (label === "Alertas") { allAlerts(); return; }
    const destination = legacyRoute(label);
    if (destination) window.location.assign(destination);
  };
  const login = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (submitting) return;
    const form = new FormData(event.currentTarget); setSubmitting(true); setDialogError(null);
    try { await model.signIn(String(form.get("email")), String(form.get("password"))); setDetail(null); }
    catch (error) { setDialogError(errorText(error)); }
    finally { setSubmitting(false); }
  };
  const markRead = async (alert: AlertView) => {
    setSubmitting(true); setDialogError(null);
    try { await model.readAlert(alert); setDetail(null); }
    catch (error) { setDialogError(errorText(error)); }
    finally { setSubmitting(false); }
  };
  const zones = model.fixture?.zones ?? zonesView(sources.market.data, model.selection.names, model.trends);
  const now = model.now ? new Date(model.now) : null;
  const uf = sources.uf.data;
  const publicUf = uf && !uf.is_fallback && Number.isFinite(uf.rate_clp) && uf.rate_clp > 0 ? uf : null;
  return <AppShell onNavigate={onNavigate} showDetail={showDetail} data={{ user, alertCount: count, searchItems: searchableProperties(sources.portfolio.data, sources.watchlist.data), searchStatus: sources.watchlist.phase === "auth" ? "Inicia sesión para buscar en tu cartera." : sources.watchlist.phase === "loading" ? "Cargando cartera…" : sources.watchlist.phase === "error" && !sources.portfolio.data ? "Cartera no disponible." : "", locationNote: model.fixture ? "Fixture visual · selección ilustrativa de comunas." : model.selection.marketSelection ? "Comunas seleccionadas por su oferta activa en Valoria. No hay un contrato de zonas seguidas; si guardas propiedades, se usan sus comunas." : `Comunas derivadas de tu cartera: ${model.selection.names.join(", ")}.` }}>
    <div className="page-heading"><div><h1>{sources.user.data || model.fixture ? `Buenos días, ${user}.` : "Bienvenido a Valoria."}</h1><p>Esto cambió en tu mercado.</p></div><div className="page-context"><time dateTime={now?.toISOString()}>{now?.toLocaleDateString("es-CL", { day: "2-digit", month: "short", year: "numeric" }).replaceAll(".", "").toUpperCase() ?? "—"}</time><button onClick={model.fixture ? () => window.location.assign(window.location.pathname) : model.token ? model.refresh : openLogin}><Badge subtle>{model.fixture ? "Fixture visual · Solo desarrollo" : model.token ? "Datos Valoria · actualizar" : "Conecta tu cuenta de Valoria"}</Badge></button></div></div>
    <section className="market-ticker" aria-label="Indicadores del mercado"><div className="uf-ticker" title={model.fixture ? "Fixture visual · UF ilustrativa" : publicUf ? `Fuente: ${publicUf.source} · ${publicUf.rate_date ?? "Fecha no disponible"}${publicUf.is_stale ? " · dato desactualizado" : ""}` : sources.uf.error ?? "UF real no disponible"}><span>UF</span><button onClick={sources.uf.phase === "error" ? model.refresh : undefined}><strong>{model.fixture ? `$${formatNumber(model.fixture.uf, 0)}` : sources.uf.phase === "loading" ? "…" : publicUf ? `$${formatNumber(publicUf.rate_clp, 0)}${publicUf.is_stale ? "*" : ""}` : sources.uf.phase === "error" ? "Error · reintentar" : "Sin datos"}</strong></button></div>{zones.map(zone => <div key={zone.name} title={zone.trendNote}><span>{zone.name}</span><p>{!model.fixture && sources.market.phase === "loading" ? "…" : sources.market.phase === "error" ? "Error" : zone.value == null ? "—" : `${formatNumber(zone.value, 1)} UF/m²`}</p><strong className={zone.change != null && zone.change < 0 ? "negative" : "accent"}>{zone.trendPhase === "error" ? "Error" : zone.trendPhase === "loading" ? "…" : pctText(zone.change)}</strong></div>)}</section>
    <div className="dashboard-grid"><div className="summary-widget-slot"><button className="widget-switch" onClick={() => setWidget(widget === "market" ? "portfolio" : "market")} aria-label={widget === "market" ? "Cambiar a Tu cartera en perspectiva" : "Cambiar a Tu mercado hoy"}>{widget === "market" ? "Ver cartera" : "Ver mercado"}<ArrowLeftRight size={14}/></button>{widget === "market" ? <MarketToday model={model} actions={actions}/> : <Portfolio model={model} actions={actions}/>}</div><Attention model={model} alerts={alerts} count={count} openAlert={openAlert} allAlerts={allAlerts} actions={actions}/><Opportunities model={model} onNavigate={onNavigate} showDetail={showDetail} actions={actions}/><ZonePulse model={model} showDetail={showDetail} actions={actions}/></div>
    <Card label="Qué quieres analizar hoy" className="quick-actions"><h2>¿Qué quieres analizar hoy?</h2><div>{[{ label: "Tasar una propiedad", icon: House }, { label: "Analizar una URL", icon: Link2 }, { label: "Explorar el Radar", icon: Target }].map(({ label, icon: Icon }) => <Button key={label} onClick={() => onNavigate(label)}><Icon size={26} strokeWidth={1.5}/><span>{label}</span><ArrowRight size={17}/></Button>)}</div></Card>
    <dialog ref={dialogRef} className="detail-dialog" aria-labelledby="detail-title" onCancel={() => setDetail(null)} onClose={() => setDetail(null)} onClick={event => { if (event.target === event.currentTarget) { const rect = event.currentTarget.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) setDetail(null); } }}><div className="dialog-heading"><Bell size={22}/><button className="dialog-close" onClick={() => setDetail(null)} aria-label="Cerrar"><X size={22}/></button></div><h2 id="detail-title">{detail?.title}</h2><p>{detail?.description}</p>
      {dialogError && <p className="form-error" role="alert">{dialogError}</p>}
      {detail?.mode === "login" ? <form className="login-form" onSubmit={login}><label>Correo electrónico<input name="email" type="email" autoComplete="username" required/></label><label>Contraseña<input name="password" type="password" autoComplete="current-password" required/></label><Button type="submit" disabled={submitting}>{submitting ? "Conectando…" : "Iniciar sesión"}</Button></form> : detail?.mode === "account" ? <Button onClick={() => { model.signOut(); setDetail(null); }}>Cerrar sesión</Button> : detail?.mode === "alerts" ? <div className="dialog-alert-list">{alerts.length ? alerts.map(alert => <button key={alert.key} onClick={() => openAlert(alert)}><strong>{alert.title}</strong><span>{alert.description}</span></button>) : <StateNotice resource={alertsResource} empty="No hay alertas pendientes." {...actions}/>}</div> : detail?.alert ? <div className="dialog-actions">{detail.alert.url && <a className="button" href={detail.alert.url} target="_blank" rel="noopener noreferrer">Ver publicación</a>}<Button disabled={submitting || Boolean(model.fixture)} onClick={() => void markRead(detail.alert!)}>{submitting ? "Guardando…" : "Marcar como leída"}</Button></div> : <Button onClick={() => setDetail(null)}>Volver a Resumen <ArrowRight size={17}/></Button>}
    </dialog>
  </AppShell>;
}
