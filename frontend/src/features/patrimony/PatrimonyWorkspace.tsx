"use client";

import { Bell, CheckCircle2, Compass, Home, Loader2, RefreshCw, Save, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

import { Button, ButtonLink } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { StatusNote } from "@/components/ui/status-note";
import { ApiError } from "@/lib/api/client";
import {
  createPatrimonyStrategy,
  deletePatrimonyProperty,
  deletePatrimonyStrategy,
  dismissPatrimonyAlert,
  evaluatePatrimonyAlerts,
  getPatrimonyProperty,
  getPatrimonyPropertyIntelligence,
  listPatrimonyProperties,
  listPatrimonyAlerts,
  listPatrimonyStrategies,
  markPatrimonyAlertRead,
  updatePatrimonyStrategy,
} from "@/lib/api/patrimony";
import {
  formatCommuneName,
  formatConfidence,
  formatDate,
  formatDateTime,
  formatM2,
  formatNumber,
  formatPercent,
  formatPropertyType,
  formatUf,
} from "@/lib/formatters";
import type {
  PatrimonyIntelligence,
  PatrimonyAlert,
  PatrimonyRecommendation,
  PatrimonyStrategy,
  PatrimonyStrategyInput,
  StrategyObjective,
  PropertyAsset,
  PropertyValuationSnapshot,
  TerritorialDevelopment,
} from "@/types/patrimony";

type PatrimonyTab = "home" | "strategy";

export function PatrimonyWorkspace() {
  const [items, setItems] = useState<PropertyAsset[]>([]);
  const [alerts, setAlerts] = useState<PatrimonyAlert[]>([]);
  const [strategies, setStrategies] = useState<PatrimonyStrategy[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selected, setSelected] = useState<PropertyAsset | null>(null);
  const [intelligence, setIntelligence] = useState<PatrimonyIntelligence | null>(null);
  const [activeTab, setActiveTab] = useState<PatrimonyTab>("home");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [strategySaving, setStrategySaving] = useState(false);
  const [alertUpdatingId, setAlertUpdatingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    void loadProperties();
  }, []);

  useEffect(() => {
    if (selectedId === null) {
      setSelected(null);
      setIntelligence(null);
      return;
    }
    void loadDetail(selectedId);
  }, [selectedId]);

  async function loadProperties() {
    setLoading(true);
    setError(null);
    try {
      await evaluatePatrimonyAlerts();
      const [response, strategyResponse, alertResponse] = await Promise.all([
        listPatrimonyProperties(),
        listPatrimonyStrategies(),
        listPatrimonyAlerts(),
      ]);
      setItems(response.items);
      setStrategies(strategyResponse.items);
      setAlerts(alertResponse.items);
      setSelectedId((current) => current ?? response.items[0]?.id ?? null);
    } catch (caught) {
      setError(errorText(caught, "No pudimos cargar tus propiedades."));
    } finally {
      setLoading(false);
    }
  }

  async function loadDetail(propertyId: number) {
    setDetailLoading(true);
    setError(null);
    setIntelligence(null);
    try {
      const [property, marketIntelligence] = await Promise.all([
        getPatrimonyProperty(propertyId),
        getPatrimonyPropertyIntelligence(propertyId),
      ]);
      setSelected(property);
      setIntelligence(marketIntelligence);
    } catch (caught) {
      setError(errorText(caught, "No pudimos cargar el detalle de esta propiedad."));
      setIntelligence(null);
    } finally {
      setDetailLoading(false);
    }
  }

  async function deleteProperty(property: PropertyAsset) {
    const confirmed = window.confirm(`Eliminar ${property.name} de Mi hogar?`);
    if (!confirmed) return;

    setDeletingId(property.id);
    setError(null);
    setMessage(null);
    try {
      await deletePatrimonyProperty(property.id);
      setItems((current) => {
        const next = current.filter((item) => item.id !== property.id);
        if (selectedId === property.id) {
          setSelectedId(next[0]?.id ?? null);
          setSelected(next[0] ?? null);
        }
        return next;
      });
      setStrategies((current) => current.filter((strategy) => strategy.property_asset_id !== property.id));
      setMessage("Propiedad eliminada de Mi hogar.");
    } catch (caught) {
      setError(errorText(caught, "No pudimos eliminar esta propiedad."));
    } finally {
      setDeletingId(null);
    }
  }

  async function saveStrategy(payload: PatrimonyStrategyInput, strategyId: number | null) {
    setStrategySaving(true);
    setError(null);
    setMessage(null);
    try {
      const saved = strategyId
        ? await updatePatrimonyStrategy(strategyId, payload)
        : await createPatrimonyStrategy(payload);
      setStrategies((current) => {
        const withoutSaved = current.filter((strategy) => strategy.id !== saved.id);
        return [saved, ...withoutSaved];
      });
      setMessage("Estrategia guardada.");
    } catch (caught) {
      setError(errorText(caught, "No pudimos guardar la estrategia."));
    } finally {
      setStrategySaving(false);
    }
  }

  async function removeStrategy(strategy: PatrimonyStrategy) {
    const confirmed = window.confirm("Eliminar esta estrategia?");
    if (!confirmed) return;

    setStrategySaving(true);
    setError(null);
    setMessage(null);
    try {
      await deletePatrimonyStrategy(strategy.id);
      setStrategies((current) => current.filter((item) => item.id !== strategy.id));
      setMessage("Estrategia eliminada.");
    } catch (caught) {
      setError(errorText(caught, "No pudimos eliminar la estrategia."));
    } finally {
      setStrategySaving(false);
    }
  }

  async function markAlertRead(alertId: number) {
    setAlertUpdatingId(alertId);
    setError(null);
    try {
      await markPatrimonyAlertRead(alertId);
      setAlerts((current) => current.filter((alert) => alert.id !== alertId));
    } catch (caught) {
      setError(errorText(caught, "No pudimos actualizar la alerta."));
    } finally {
      setAlertUpdatingId(null);
    }
  }

  async function dismissAlert(alertId: number) {
    setAlertUpdatingId(alertId);
    setError(null);
    try {
      await dismissPatrimonyAlert(alertId);
      setAlerts((current) => current.filter((alert) => alert.id !== alertId));
    } catch (caught) {
      setError(errorText(caught, "No pudimos descartar la alerta."));
    } finally {
      setAlertUpdatingId(null);
    }
  }

  const currentDetail = selected ?? items.find((item) => item.id === selectedId) ?? null;

  if (loading) {
    return (
      <Card>
        <div className="flex min-h-64 items-center justify-center gap-3 text-sm text-muted">
          <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
          Cargando Mi patrimonio...
        </div>
      </Card>
    );
  }

  return (
    <div className="grid gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-3">
        <p className="text-sm text-muted">{propertyCountLabel(items.length)}</p>
        <div aria-label="Secciones de patrimonio" className="flex flex-wrap gap-2" role="tablist">
          <button
            className={tabClass(activeTab === "home")}
            onClick={() => setActiveTab("home")}
            aria-selected={activeTab === "home"}
            role="tab"
            type="button"
          >
            Mi hogar
          </button>
          <button
            className={tabClass(activeTab === "strategy")}
            onClick={() => setActiveTab("strategy")}
            aria-selected={activeTab === "strategy"}
            role="tab"
            type="button"
          >
            Mi estrategia
          </button>
        </div>
      </div>

      {message ? <StatusNote tone="success">{message}</StatusNote> : null}
      {error ? <StatusNote tone="warning">{error}</StatusNote> : null}

      {items.length === 0 ? (
        <EmptyState />
      ) : activeTab === "home" ? (
        <div className="grid gap-5">
          <PatrimonyAlertsPanel
            alerts={alerts}
            loadingId={alertUpdatingId}
            onDismiss={dismissAlert}
            onRead={markAlertRead}
          />
          <section className="min-w-0">
            <div>
              <div>
                <h2 className="text-lg font-semibold text-ink">Propiedades</h2>
                <p className="mt-1 text-sm text-muted">Selecciona una propiedad para revisar su ultima valoracion.</p>
              </div>
            </div>
            <div className="mt-4 grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {items.map((property) => (
                <PropertyListCard
                  key={property.id}
                  onSelect={() => setSelectedId(property.id)}
                  property={property}
                  selected={property.id === currentDetail?.id}
                />
              ))}
            </div>
          </section>

          <PropertyDetail
            deleting={deletingId === currentDetail?.id}
            intelligence={intelligence}
            loading={detailLoading}
            onDelete={deleteProperty}
            property={currentDetail}
          />
        </div>
      ) : (
        <div className="grid gap-5">
          <PatrimonyAlertsPanel
            alerts={alerts}
            loadingId={alertUpdatingId}
            onDismiss={dismissAlert}
            onRead={markAlertRead}
          />
          <StrategyWorkspace
            currentProperty={currentDetail}
            loading={detailLoading || strategySaving}
            onDelete={removeStrategy}
            onSave={saveStrategy}
            onSelectProperty={setSelectedId}
            properties={items}
            selectedPropertyId={selectedId}
            strategies={strategies}
          />
        </div>
      )}
    </div>
  );
}

function PatrimonyAlertsPanel({
  alerts,
  loadingId,
  onDismiss,
  onRead,
}: {
  alerts: PatrimonyAlert[];
  loadingId: number | null;
  onDismiss: (alertId: number) => void;
  onRead: (alertId: number) => void;
}) {
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <CardTitle>Requiere atencion</CardTitle>
          <CardDescription>Eventos pendientes de tus propiedades y estrategias.</CardDescription>
        </div>
        <span className="inline-flex items-center gap-2 text-sm text-violet-100">
          <Bell className="h-4 w-4" aria-hidden />
          {alerts.length} sin revisar
        </span>
      </div>

      {alerts.length ? (
        <div className="mt-4 divide-y divide-line border-t border-line">
          {alerts.map((alert) => (
            <div className="py-4" key={alert.id}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-ink">{alert.title}</p>
                  <p className="mt-2 text-sm leading-6 text-muted">{alert.message}</p>
                  <p className="mt-2 text-xs text-muted">
                    {alertRelationLabel(alert)} - {formatDateTime(alert.created_at)}
                  </p>
                </div>
                <span className={`rounded-lg border px-3 py-1 text-xs font-semibold uppercase tracking-wide ${severityClass(alert.severity)}`}>
                  {severityLabel(alert.severity)}
                </span>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button disabled={loadingId === alert.id} onClick={() => onRead(alert.id)} type="button" variant="secondary">
                  {loadingId === alert.id ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <CheckCircle2 className="h-4 w-4" aria-hidden />}
                  Marcar leida
                </Button>
                <Button disabled={loadingId === alert.id} onClick={() => onDismiss(alert.id)} type="button" variant="ghost">
                  <Trash2 className="h-4 w-4" aria-hidden />
                  Descartar
                </Button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-4 border-t border-line pt-4 text-sm leading-6 text-muted">No hay alertas pendientes.</p>
      )}
    </Card>
  );
}

function StrategyWorkspace({
  currentProperty,
  loading,
  onDelete,
  onSave,
  onSelectProperty,
  properties,
  selectedPropertyId,
  strategies,
}: {
  currentProperty: PropertyAsset | null;
  loading: boolean;
  onDelete: (strategy: PatrimonyStrategy) => void;
  onSave: (payload: PatrimonyStrategyInput, strategyId: number | null) => void;
  onSelectProperty: (propertyId: number) => void;
  properties: PropertyAsset[];
  selectedPropertyId: number | null;
  strategies: PatrimonyStrategy[];
}) {
  const currentStrategy = strategies.find((strategy) => strategy.property_asset_id === selectedPropertyId) ?? null;
  const [form, setForm] = useState<StrategyFormState>(() => strategyFormState(currentProperty, currentStrategy));

  useEffect(() => {
    setForm(strategyFormState(currentProperty, currentStrategy));
  }, [currentProperty, currentStrategy]);

  function submitStrategy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedPropertyId) return;
    onSave(strategyPayload(form, selectedPropertyId), currentStrategy?.id ?? null);
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(320px,0.9fr)_minmax(0,1.4fr)]">
      <Card>
        <CardTitle>Mi estrategia</CardTitle>
        <CardDescription>Define el plan asociado a una propiedad guardada.</CardDescription>
        <form className="mt-5 grid gap-4" onSubmit={submitStrategy}>
          <label className="grid gap-2 text-sm text-muted">
            Propiedad
            <select
              className={fieldClass}
              onChange={(event) => onSelectProperty(Number(event.target.value))}
              value={selectedPropertyId ?? ""}
            >
              {properties.map((property) => (
                <option key={property.id} value={property.id}>
                  {property.name} - {formatCommuneName(property.comuna)}
                </option>
              ))}
            </select>
          </label>

          <label className="grid gap-2 text-sm text-muted">
            Objetivo
            <select
              className={fieldClass}
              onChange={(event) => setForm((current) => ({ ...current, objective: event.target.value as StrategyObjective }))}
              value={form.objective}
            >
              {objectiveOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-2 text-sm text-muted">
              Horizonte
              <select
                className={fieldClass}
                onChange={(event) => setForm((current) => ({ ...current, horizon: event.target.value }))}
                value={form.horizon}
              >
                {horizonOptions.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-2 text-sm text-muted">
              Precio objetivo UF
              <input
                className={fieldClass}
                inputMode="decimal"
                onChange={(event) => setForm((current) => ({ ...current, targetValueUf: event.target.value }))}
                placeholder="Opcional"
                type="number"
                value={form.targetValueUf}
              />
            </label>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-2 text-sm text-muted">
              Urgencia
              <select
                className={fieldClass}
                onChange={(event) => setForm((current) => ({ ...current, urgency: event.target.value }))}
                value={form.urgency}
              >
                {urgencyOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-2 text-sm text-muted">
              Perfil de riesgo
              <select
                className={fieldClass}
                onChange={(event) => setForm((current) => ({ ...current, riskProfile: event.target.value }))}
                value={form.riskProfile}
              >
                {riskOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="grid gap-2 text-sm text-muted">
            Proximo movimiento
            <textarea
              className={`${fieldClass} min-h-24 resize-y`}
              onChange={(event) => setForm((current) => ({ ...current, nextMove: event.target.value }))}
              placeholder="Opcional"
              value={form.nextMove}
            />
          </label>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-2 text-sm text-muted">
              Tipo deseado
              <input
                className={fieldClass}
                onChange={(event) => setForm((current) => ({ ...current, desiredPropertyType: event.target.value }))}
                placeholder="departamento, casa..."
                value={form.desiredPropertyType}
              />
            </label>
            <label className="grid gap-2 text-sm text-muted">
              Presupuesto deseado UF
              <input
                className={fieldClass}
                inputMode="decimal"
                onChange={(event) => setForm((current) => ({ ...current, desiredBudgetUf: event.target.value }))}
                placeholder="Opcional"
                type="number"
                value={form.desiredBudgetUf}
              />
            </label>
          </div>

          <label className="grid gap-2 text-sm text-muted">
            Comunas deseadas
            <input
              className={fieldClass}
              onChange={(event) => setForm((current) => ({ ...current, desiredCommunes: event.target.value }))}
              placeholder="Vitacura, Las Condes"
              value={form.desiredCommunes}
            />
          </label>

          <div className="flex flex-wrap gap-3">
            <Button disabled={loading || !selectedPropertyId} type="submit">
              {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Save className="h-4 w-4" aria-hidden />}
              Guardar estrategia
            </Button>
            {currentStrategy ? (
              <Button disabled={loading} onClick={() => onDelete(currentStrategy)} type="button" variant="secondary">
                <Trash2 className="h-4 w-4" aria-hidden />
                Eliminar estrategia
              </Button>
            ) : null}
          </div>
        </form>
      </Card>

      <StrategySummary property={currentProperty} strategy={currentStrategy} />
    </div>
  );
}

function StrategySummary({ property, strategy }: { property: PropertyAsset | null; strategy: PatrimonyStrategy | null }) {
  if (!property) {
    return (
      <Card>
        <div className="flex min-h-80 items-center justify-center text-sm text-muted">
          Selecciona una propiedad para definir su estrategia.
        </div>
      </Card>
    );
  }

  if (!strategy) {
    return (
      <Card>
        <Compass className="h-8 w-8 text-brand-500" aria-hidden />
        <div className="mt-4">
          <CardTitle>Sin estrategia guardada</CardTitle>
        </div>
        <CardDescription>Configura un objetivo para generar una recomendacion explicable.</CardDescription>
      </Card>
    );
  }

  const recommendation = strategy.recommendation;
  const shouldShowRadar = strategyNeedsRadar(strategy);
  return (
    <section className="grid gap-5">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle>{objectiveLabel(strategy.objective)}</CardTitle>
            <CardDescription>
              {property.name} - {formatCommuneName(property.comuna)}
            </CardDescription>
          </div>
          <span className="rounded-lg border border-line bg-white/[0.06] px-3 py-1 text-sm text-muted">
            {recommendation.suggested_next_review ?? "Revision pendiente"}
          </span>
        </div>

        <div className="mt-5 rounded-lg border border-brand-500/30 bg-brand-500/10 p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-muted">Recomendacion actual</p>
          <p className="mt-2 text-xl font-bold text-ink">
            {recommendation.current_recommendation ?? "Aun no hay suficiente informacion para una recomendacion"}
          </p>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <Fact compact label="Valor actual" value={formatUf(recommendation.latest_valuation_uf)} />
          <Fact compact label="Precio objetivo" value={formatUf(recommendation.target_value_uf)} />
          <Fact compact label="Progreso" value={progressLabel(recommendation.progress_to_target_pct)} />
        </div>
      </Card>

      <Card>
        <CardTitle>Plan de acciones</CardTitle>
        <SignalList title="Proximos pasos" items={recommendation.next_steps} />
        <SignalList title="Condiciones para actuar" items={recommendation.action_conditions} />
        <SignalList title="Razones" items={recommendation.reasons} />
        {shouldShowRadar ? (
          <ButtonLink className="mt-5" href={radarStrategyHref(strategy)} variant="secondary">
            <Compass className="h-4 w-4" aria-hidden />
            Buscar oportunidades compatibles en Radar
          </ButtonLink>
        ) : null}
      </Card>
    </section>
  );
}

function EmptyState() {
  return (
    <Card>
      <div className="flex min-h-72 items-center justify-center p-8 text-center">
        <div>
          <Home className="mx-auto h-10 w-10 text-brand-500" aria-hidden />
          <h3 className="mt-4 text-lg font-semibold text-ink">Mi hogar aun esta vacio</h3>
          <p className="mt-2 max-w-lg text-sm leading-6 text-muted">
            Ejecuta una tasacion y guardala en Mi hogar para empezar a construir tu patrimonio.
          </p>
          <ButtonLink className="mt-5" href="/app/tasar">
            Tasar una propiedad
          </ButtonLink>
        </div>
      </div>
    </Card>
  );
}

function PropertyListCard({
  onSelect,
  property,
  selected,
}: {
  onSelect: () => void;
  property: PropertyAsset;
  selected: boolean;
}) {
  const latest = property.latest_valuation;
  return (
    <button
      className={`rounded-lg border p-4 text-left shadow-soft transition ${
        selected
          ? "border-brand-500/45 bg-brand-500/[0.14]"
          : "border-line bg-white/[0.055] hover:border-brand-500/35 hover:bg-white/[0.075]"
      }`}
      onClick={onSelect}
      type="button"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-base font-semibold text-ink">{property.name}</h3>
          <p className="mt-1 text-sm text-muted">
            {formatPropertyType(property.property_type)} en {formatCommuneName(property.comuna)}
          </p>
        </div>
        {selected ? <CheckCircle2 className="h-5 w-5 shrink-0 text-brand-500" aria-hidden /> : null}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2">
        <Fact compact label="Valor" value={formatUf(latest?.estimated_value_uf)} />
        <Fact compact label="Confianza" value={formatConfidence(latest?.confidence_score ?? latest?.confidence)} />
      </div>
    </button>
  );
}

function PropertyDetail({
  deleting,
  intelligence,
  loading,
  onDelete,
  property,
}: {
  deleting: boolean;
  intelligence: PatrimonyIntelligence | null;
  loading: boolean;
  onDelete: (property: PropertyAsset) => void;
  property: PropertyAsset | null;
}) {
  const snapshots = useMemo(
    () => sortSnapshots(property?.valuation_snapshots ?? []),
    [property?.valuation_snapshots],
  );
  const latest = property?.latest_valuation ?? snapshots.at(-1) ?? null;
  const trend = snapshots.length >= 2 ? snapshotTrend(snapshots) : null;

  if (!property) {
    return (
      <Card>
        <div className="flex min-h-80 items-center justify-center text-sm text-muted">
          Selecciona una propiedad para ver su detalle.
        </div>
      </Card>
    );
  }

  return (
    <section className="grid gap-5">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle>{property.name}</CardTitle>
            <CardDescription>
              {formatPropertyType(property.property_type)} en {formatCommuneName(property.comuna)}
            </CardDescription>
          </div>
          {loading ? (
            <span className="inline-flex items-center gap-2 rounded-lg border border-line bg-white/[0.06] px-3 py-1 text-sm text-muted">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              Actualizando
            </span>
          ) : null}
        </div>

        <div className="mt-6 grid gap-5 border-y border-line py-5 lg:grid-cols-[minmax(0,1.3fr)_repeat(3,minmax(0,0.8fr))]">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-muted">Valor estimado</p>
            <p className="mt-2 text-3xl font-semibold text-ink">{formatUf(latest?.estimated_value_uf)}</p>
          </div>
          <Fact compact label="Rango estimado" value={rangeLabel(latest)} />
          <Fact compact label="Confianza" value={formatConfidence(latest?.confidence_score ?? latest?.confidence)} />
          <Fact compact label="Actualizada" value={formatDateTime(latest?.snapshot_at ?? property.updated_at)} />
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Fact label="Tipo" value={formatPropertyType(property.property_type)} />
          <Fact label="Comuna" value={formatCommuneName(property.comuna)} />
          <Fact label="Superficie" value={formatM2(property.m2)} />
          <Fact label="Programa" value={programLabel(property)} />
        </div>

        {trend ? (
          <div className="mt-5 border-t border-line pt-5">
            <p className="text-sm font-semibold text-ink">Variacion desde la valoracion anterior</p>
            <p className="mt-2 text-lg font-bold text-ink">
              {trend.absolute >= 0 ? "+" : ""}
              {formatUf(trend.absolute)} ({trend.percent >= 0 ? "+" : ""}
              {formatPercent(trend.percent / 100)})
            </p>
          </div>
        ) : (
          <p className="mt-5 border-t border-line pt-5 text-sm leading-6 text-muted">
            Hay una sola valoracion real para esta propiedad. La variacion aparecera cuando guardes una nueva tasacion.
          </p>
        )}

        <div className="mt-5 flex flex-wrap gap-3">
          <ButtonLink href="/app/tasar" variant="secondary">
            <RefreshCw className="h-4 w-4" aria-hidden />
            Actualizar tasacion
          </ButtonLink>
          <Button disabled={deleting} onClick={() => onDelete(property)} type="button" variant="secondary">
            {deleting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Trash2 className="h-4 w-4" aria-hidden />}
            Eliminar propiedad
          </Button>
        </div>
      </Card>

      <IntelligencePanel intelligence={intelligence} loading={loading} />
      <TerritorialPerspectivePanel intelligence={intelligence} loading={loading} />

      <Card>
        <CardTitle>Historial de valoraciones</CardTitle>
        <CardDescription>Estimaciones guardadas para esta propiedad, ordenadas por fecha.</CardDescription>
        <div className="mt-5 divide-y divide-line border-t border-line">
          {snapshots.length ? (
            snapshots
              .slice()
              .reverse()
              .map((snapshot) => (
                <div
                  className="grid gap-3 py-4 sm:grid-cols-4"
                  key={snapshot.id}
                >
                  <Fact compact label="Fecha" value={formatDateTime(snapshot.snapshot_at)} />
                  <Fact compact label="Valor" value={formatUf(snapshot.estimated_value_uf)} />
                  <Fact compact label="Rango" value={rangeLabel(snapshot)} />
                  <Fact compact label="Confianza" value={formatConfidence(snapshot.confidence_score ?? snapshot.confidence)} />
                </div>
              ))
          ) : (
            <p className="py-4 text-sm text-muted">Esta propiedad aun no tiene valoraciones guardadas.</p>
          )}
        </div>
      </Card>
    </section>
  );
}

function TerritorialPerspectivePanel({
  intelligence,
  loading,
}: {
  intelligence: PatrimonyIntelligence | null;
  loading: boolean;
}) {
  const developments = intelligence?.territorial_developments ?? [];
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <CardTitle>Perspectiva territorial</CardTitle>
          <CardDescription>Proyeccion por escenarios, no promesa de plusvalia.</CardDescription>
        </div>
        {loading ? <Loader2 className="h-5 w-5 animate-spin text-muted" aria-hidden /> : <Compass className="h-5 w-5 text-brand-500" aria-hidden />}
      </div>

      {!developments.length ? (
        <p className="mt-5 border-t border-line pt-4 text-sm leading-6 text-muted">
          {intelligence?.territorial_projection_message ?? "No hay proyecciones territoriales verificadas disponibles para esta propiedad."}
        </p>
      ) : (
        <div className="mt-5 grid gap-4">
          {developments.map((development) => (
            <TerritorialDevelopmentCard development={development} key={development.id} />
          ))}
        </div>
      )}
    </Card>
  );
}

function TerritorialDevelopmentCard({ development }: { development: TerritorialDevelopment }) {
  return (
    <div className="border-t border-line pt-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-base font-semibold text-ink">{development.name}</p>
          <p className="mt-2 text-sm leading-6 text-muted">{development.description}</p>
        </div>
        <span className="rounded-lg border border-brand-500/25 bg-brand-500/10 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-violet-100">
          {statusLabel(development.status)}
        </span>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <Fact compact label="Horizonte" value={development.horizon} />
        <Fact compact label="Confianza" value={formatConfidence(development.confidence)} />
        <Fact compact label="Tipo" value={formatText(development.development_type)} />
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <Fact compact label="Conservador" value={scenarioRange(development.scenarios.conservative_min_pct, development.scenarios.conservative_max_pct)} />
        <Fact compact label="Central" value={scenarioRange(development.scenarios.central_min_pct, development.scenarios.central_max_pct)} />
        <Fact compact label="Favorable" value={scenarioMax(development.scenarios.favorable_max_pct)} />
      </div>

      <p className="mt-4 border-l-2 border-brand-500/50 pl-3 text-sm leading-6 text-muted">
        {development.scenarios.narrative}
      </p>
      <SignalList title="Riesgos" items={development.risks} />
      <p className="mt-4 text-sm leading-6 text-muted">{development.methodology}</p>
      <p className="mt-3 text-xs text-muted">
        Fuente: {development.source.url ? (
          <a className="text-violet-100 underline-offset-4 hover:underline" href={development.source.url} rel="noreferrer" target="_blank">
            {development.source.name}
          </a>
        ) : (
          development.source.name
        )}
        {development.source.date ? ` - ${formatDate(development.source.date)}` : ""}
      </p>
    </div>
  );
}

function IntelligencePanel({
  intelligence,
  loading,
}: {
  intelligence: PatrimonyIntelligence | null;
  loading: boolean;
}) {
  const recommendation = intelligence?.recommendation ? recommendationCopy[intelligence.recommendation] : null;
  const hasRecommendation = intelligence?.status === "available" && recommendation !== null;
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <CardTitle>Inteligencia patrimonial</CardTitle>
          <CardDescription>Senales de mercado para la comuna de esta propiedad.</CardDescription>
        </div>
        {loading ? <Loader2 className="h-5 w-5 animate-spin text-muted" aria-hidden /> : <Sparkles className="h-5 w-5 text-brand-500" aria-hidden />}
      </div>

      {!hasRecommendation ? (
        <div className="mt-5 rounded-lg border border-line bg-black/20 p-4 text-sm leading-6 text-muted">
          Aún no hay suficiente información para una recomendación
        </div>
      ) : (
        <>
          <div className="mt-5 border-l-2 border-brand-500/60 pl-4">
            <p className="text-xs font-medium uppercase tracking-wide text-muted">Recomendacion</p>
            <p className="mt-2 text-xl font-bold text-ink">{recommendation}</p>
            <p className="mt-2 text-sm leading-6 text-muted">
              Confianza {formatConfidence(intelligence.confidence)} - {intelligence.recent_movement ?? "Movimiento reciente no disponible"}
            </p>
          </div>

          <div className="mt-5 grid gap-3 sm:grid-cols-3">
            <Fact compact label="Balance" value={intelligence.buyer_seller_balance ?? "No disponible"} />
            <Fact compact label="Dinamismo" value={intelligence.dynamism ?? "No disponible"} />
            <Fact compact label="Tiempo publicado" value={daysLabel(intelligence.observed_publication_time_days)} />
          </div>

          <SignalList title="Razones" items={intelligence.reasons} />
          <SignalList title="Senales pendientes" items={intelligence.change_conditions} />
        </>
      )}
    </Card>
  );
}

function SignalList({ items, title }: { items: string[]; title: string }) {
  if (!items.length) return null;
  return (
    <div className="mt-5">
      <p className="text-sm font-semibold text-ink">{title}</p>
      <ul className="mt-3 grid gap-2 text-sm leading-6 text-muted">
        {items.map((item) => (
          <li className="border-l border-line pl-3" key={item}>
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Fact({
  compact = false,
  label,
  value,
}: {
  compact?: boolean;
  label: string;
  value: string;
}) {
  return (
    <div className={compact ? "" : "rounded-lg border border-line bg-white/[0.04] p-3"}>
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-2 break-words text-sm font-semibold text-ink">{value}</p>
    </div>
  );
}

function sortSnapshots(snapshots: PropertyValuationSnapshot[]) {
  return snapshots
    .slice()
    .sort((left, right) => new Date(left.snapshot_at).getTime() - new Date(right.snapshot_at).getTime());
}

function snapshotTrend(snapshots: PropertyValuationSnapshot[]) {
  const latest = snapshots.at(-1)?.estimated_value_uf;
  const previous = snapshots.at(-2)?.estimated_value_uf;
  if (!isFiniteValue(latest) || !isFiniteValue(previous) || previous === 0) {
    return null;
  }
  return {
    absolute: latest - previous,
    percent: ((latest - previous) / previous) * 100,
  };
}

function rangeLabel(snapshot: PropertyValuationSnapshot | null | undefined) {
  const low = snapshot?.lower_bound_uf;
  const high = snapshot?.upper_bound_uf;
  if (!isFiniteValue(low) || !isFiniteValue(high)) {
    return "No disponible";
  }
  return `${formatUf(low)} - ${formatUf(high)}`;
}

type StrategyFormState = {
  objective: StrategyObjective;
  horizon: string;
  targetValueUf: string;
  urgency: string;
  riskProfile: string;
  nextMove: string;
  desiredPropertyType: string;
  desiredCommunes: string;
  desiredBudgetUf: string;
};

const fieldClass =
  "min-h-11 rounded-lg border border-line bg-black/30 px-3 py-2 text-sm text-ink outline-none transition focus:border-brand-500";

const objectiveOptions: Array<{ value: StrategyObjective; label: string }> = [
  { value: "maintain", label: "Mantener" },
  { value: "sell", label: "Vender" },
  { value: "sell_and_buy", label: "Vender y comprar" },
  { value: "buy_to_invest", label: "Comprar para invertir" },
  { value: "grow_patrimony", label: "Crecer patrimonio" },
];

const horizonOptions = ["3 meses", "6 meses", "6 a 12 meses", "12 meses o mas"];

const urgencyOptions = [
  { value: "low", label: "Baja" },
  { value: "medium", label: "Media" },
  { value: "high", label: "Alta" },
];

const riskOptions = [
  { value: "conservative", label: "Conservador" },
  { value: "balanced", label: "Balanceado" },
  { value: "aggressive", label: "Agresivo" },
];

function tabClass(active: boolean) {
  return active
    ? "min-h-10 border-b-2 border-brand-500 px-3 text-sm font-semibold text-ink"
    : "min-h-10 border-b-2 border-transparent px-3 text-sm font-semibold text-muted hover:text-ink";
}

function propertyCountLabel(count: number) {
  return count === 1 ? "1 propiedad guardada" : `${count} propiedades guardadas`;
}

const recommendationCopy: Record<PatrimonyRecommendation, string> = {
  maintain: "Mantener",
  monitor: "Monitorear",
  prepare_sale: "Preparar venta",
  evaluate_exit: "Evaluar salida",
  favorable_market: "Mercado favorable",
};

function strategyFormState(property: PropertyAsset | null, strategy: PatrimonyStrategy | null): StrategyFormState {
  return {
    objective: strategy?.objective ?? "maintain",
    horizon: strategy?.horizon ?? "6 a 12 meses",
    targetValueUf: optionalNumberInput(strategy?.target_value_uf ?? property?.latest_valuation?.estimated_value_uf),
    urgency: strategy?.urgency ?? "medium",
    riskProfile: strategy?.risk_profile ?? "balanced",
    nextMove: strategy?.next_move ?? "",
    desiredPropertyType: strategy?.desired_property_type ?? "",
    desiredCommunes: strategy?.desired_communes.join(", ") ?? "",
    desiredBudgetUf: optionalNumberInput(strategy?.desired_budget_uf),
  };
}

function strategyPayload(form: StrategyFormState, propertyId: number): PatrimonyStrategyInput {
  return {
    property_asset_id: propertyId,
    objective: form.objective,
    horizon: form.horizon || null,
    target_value_uf: optionalNumber(form.targetValueUf),
    urgency: form.urgency || null,
    risk_profile: form.riskProfile || null,
    next_move: form.nextMove || null,
    desired_property_type: form.desiredPropertyType || null,
    desired_communes: form.desiredCommunes
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean),
    desired_budget_uf: optionalNumber(form.desiredBudgetUf),
  };
}

function objectiveLabel(objective: StrategyObjective) {
  return objectiveOptions.find((option) => option.value === objective)?.label ?? objective;
}

function strategyNeedsRadar(strategy: PatrimonyStrategy): boolean {
  if (strategy.objective === "sell_and_buy" || strategy.objective === "buy_to_invest") {
    return true;
  }

  const nextMove = strategy.next_move
    ?.normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
  return Boolean(nextMove && (nextMove.includes("compr") || nextMove.includes("invert")));
}

function radarStrategyHref(strategy: PatrimonyStrategy): string {
  const params = new URLSearchParams({ source: "mi-estrategia" });
  if (strategy.desired_property_type) {
    params.set("property_type", strategy.desired_property_type);
  }
  for (const commune of strategy.desired_communes) {
    params.append("communes", commune);
  }
  if (strategy.desired_budget_uf != null) {
    params.set("max_price_uf", String(strategy.desired_budget_uf));
  }
  return `/app/radar?${params.toString()}`;
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    announced: "Anunciado",
    planned: "Planificado",
    confirmed: "Confirmado",
    under_construction: "En construccion",
    completed: "Completado",
    cancelled: "Cancelado",
  };
  return labels[status] ?? formatText(status);
}

function alertRelationLabel(alert: PatrimonyAlert) {
  if (alert.property_name) return alert.property_name;
  if (alert.strategy_objective) return `Estrategia: ${objectiveLabel(alert.strategy_objective as StrategyObjective)}`;
  if (alert.territorial_development_name) return alert.territorial_development_name;
  return "Mi patrimonio";
}

function severityLabel(severity: string) {
  const labels: Record<string, string> = {
    low: "Baja",
    medium: "Media",
    high: "Alta",
  };
  return labels[severity] ?? formatText(severity);
}

function severityClass(severity: string) {
  if (severity === "high") return "border-rose-400/35 bg-rose-500/10 text-rose-100";
  if (severity === "medium") return "border-amber-400/35 bg-amber-500/10 text-amber-100";
  return "border-line bg-white/[0.06] text-muted";
}

function scenarioRange(min: number | null | undefined, max: number | null | undefined) {
  if (!isFiniteValue(min) || !isFiniteValue(max)) return "No disponible";
  return `${formatPercent(min / 100)} - ${formatPercent(max / 100)}`;
}

function scenarioMax(value: number | null | undefined) {
  if (!isFiniteValue(value)) return "No disponible";
  return `Hasta ${formatPercent(value / 100)}`;
}

function formatText(value: string | null | undefined) {
  if (!value) return "No disponible";
  return value.replaceAll("_", " ");
}

function optionalNumberInput(value: number | null | undefined) {
  return isFiniteValue(value) ? String(value) : "";
}

function optionalNumber(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function progressLabel(value: number | null | undefined) {
  if (!isFiniteValue(value)) return "No disponible";
  return formatPercent(value / 100);
}

function daysLabel(value: number | null | undefined) {
  if (!isFiniteValue(value)) return "No disponible";
  return `${formatNumber(value, 0)} dias`;
}

function programLabel(property: PropertyAsset) {
  const parts = [
    positiveNumberLabel(property.bedrooms, "D"),
    positiveNumberLabel(property.bathrooms, "B"),
    positiveNumberLabel(property.parking, "E"),
  ].filter((part) => part !== null);
  return parts.length ? parts.join(" / ") : "No disponible";
}

function positiveNumberLabel(value: number | null | undefined, suffix: string): string | null {
  return isFiniteValue(value) && value > 0 ? `${formatNumber(value, 0)}${suffix}` : null;
}

function isFiniteValue(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function errorText(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError)) return fallback;
  if (error.status === 401 || error.status === 403) return "Tu sesion no esta vigente o no tiene permisos.";
  if (error.status === 404) return "La propiedad no existe o ya fue eliminada.";
  if (error.status >= 500) return "No pudimos actualizar Mi hogar.";
  return error.message;
}
