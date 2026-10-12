"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { summaryApi } from "@/lib/api/summary";
import { ApiError } from "@/lib/api/client";
import { getAccessToken, setAccessToken, clearAccessToken } from "@/lib/auth/token";
import { removeFromWatchlist, saveToWatchlist } from "@/lib/api/watchlist";
import type { PriceTrend } from "@/types/summary";
import { normalizeCommune, zoneSelection, type AlertView } from "./view-model";

export type Phase = "loading" | "ready" | "error" | "auth" | "idle";
export type Resource<T> = { phase: Phase; data: T | null; error: string | null };
type Keys = "user" | "portfolio" | "watchlist" | "alerts" | "patrimonyAlerts" | "uf" | "marketFlow" | "market" | "radar" | "opportunities";
type Payload<K extends Keys> = Awaited<ReturnType<(typeof summaryApi)[K]>>;
type Sources = { [K in Keys]: Resource<Payload<K>> };
const initial = (phase: Phase): Sources => Object.fromEntries(["user", "portfolio", "watchlist", "alerts", "patrimonyAlerts", "uf", "marketFlow", "market", "radar", "opportunities"].map(key => [key, { phase: key === "opportunities" ? "idle" : phase, data: null, error: null }])) as Sources;
export const errorText = (error: unknown) => error instanceof ApiError ? error.status === 401 ? "Tu sesión expiró. Inicia sesión de nuevo." : error.status === 403 ? "Tu cuenta no tiene acceso a estos datos." : error.status === 404 ? "Esta función no está disponible en la API configurada." : error.status === 0 ? "No se pudo conectar con Valoria. Revisa la API y vuelve a intentar." : error.message : "No se pudo completar la solicitud. Vuelve a intentar.";

import type { VisualFixture } from "./visual-fixture";

export function useSummary() {
  const [mode, setMode] = useState<"pending" | "live" | "fixture">("pending");
  const [fixture, setFixture] = useState<VisualFixture | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [sources, setSources] = useState<Sources>(() => initial("loading"));
  const [trends, setTrends] = useState<Record<string, Resource<PriceTrend>>>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [now, setNow] = useState(0);
  const controller = useRef<AbortController | null>(null);
  const mutationLock = useRef(false);
  const sourceRef = useRef(sources);
  sourceRef.current = sources;

  useEffect(() => {
    if (process.env.NODE_ENV === "development" && new URLSearchParams(window.location.search).get("fixture") === "visual") {
      void import("./visual-fixture").then(({ visualFixture }) => {
        setFixture(visualFixture); setNow(visualFixture.now); setMode("fixture");
      });
      return;
    }
    setMode("live");
    setToken(getAccessToken());
    const updateSession = () => setToken(getAccessToken());
    window.addEventListener("storage", updateSession);
    return () => window.removeEventListener("storage", updateSession);
  }, []);

  const load = useCallback(async <K extends Keys>(key: K, signal: AbortSignal): Promise<Payload<K> | null> => {
    setSources(previous => ({ ...previous, [key]: { phase: "loading", data: null, error: null } }));
    try {
      const data = await summaryApi[key]({ signal });
      if (signal.aborted) return null;
      setSources(previous => ({ ...previous, [key]: { phase: "ready", data, error: null } }));
      return data as Payload<K>;
    } catch (error) {
      if (signal.aborted) return null;
      if (error instanceof ApiError && error.status === 401 && key !== "uf") {
        clearAccessToken(); setToken(null);
      }
      setSources(previous => ({ ...previous, [key]: { phase: "error", data: null, error: errorText(error) } }));
      return null;
    }
  }, []);

  useEffect(() => {
    if (mode !== "live") return;
    const abort = new AbortController(); controller.current = abort;
    setSources(initial(token ? "loading" : "auth")); setTrends({}); setMutationError(null); setNow(Date.now());
    void load("uf", abort.signal);
    if (token) void (async () => {
      const user = await load("user", abort.signal);
      if (!user || abort.signal.aborted) {
        if (!abort.signal.aborted) setSources(previous => {
          const next = { ...previous };
          for (const key of ["portfolio", "watchlist", "alerts", "patrimonyAlerts", "marketFlow", "market", "radar"] as const) next[key] = { phase: "error", data: null, error: "No se pudo validar la sesión. Reintenta o vuelve a iniciar sesión." };
          return next;
        });
        return;
      }
      await Promise.allSettled([
        load("portfolio", abort.signal), load("watchlist", abort.signal), load("alerts", abort.signal),
        load("patrimonyAlerts", abort.signal), load("market", abort.signal), load("marketFlow", abort.signal), load("radar", abort.signal),
      ]);
    })();
    return () => abort.abort();
  }, [mode, token, revision, load]);

  const selection = zoneSelection(sources.watchlist.data, sources.portfolio.data, sources.market.data);
  const trendKey = selection.names.map(name => sources.market.data?.communes.find(item => normalizeCommune(item.comuna) === normalizeCommune(name))?.comuna ?? "").filter(Boolean).join("|");
  useEffect(() => {
    if (mode !== "live") return;
    if (!token || !trendKey) { setTrends({}); return; }
    setTrends(Object.fromEntries(trendKey.split("|").map(name => [normalizeCommune(name), { phase: "loading", data: null, error: null }])));
    const abort = new AbortController();
    void Promise.allSettled(trendKey.split("|").map(async commune => {
      try {
        const trend = await summaryApi.trend(commune, { signal: abort.signal });
        if (!abort.signal.aborted) setTrends(previous => ({ ...previous, [normalizeCommune(commune)]: { phase: "ready", data: trend, error: null } }));
      } catch (error) { if (!abort.signal.aborted) setTrends(previous => ({ ...previous, [normalizeCommune(commune)]: { phase: "error", data: null, error: errorText(error) } })); }
    }));
    return () => abort.abort();
  }, [mode, token, trendKey, revision]);

  const refresh = () => setRevision(value => value + 1);
  const signIn = async (email: string, password: string) => {
    if (mode !== "live") throw new Error("Fixture visual: autenticación desactivada.");
    let response;
    try { response = await summaryApi.login(email, password); }
    catch (error) { if (error instanceof ApiError && error.status === 401) throw new ApiError("Correo o contraseña incorrectos.", 400); throw error; }
    setAccessToken(response.access_token); setToken(response.access_token);
  };
  const signOut = () => { if (mode !== "live") return; controller.current?.abort(); clearAccessToken(); setToken(null); setSources(initial("auth")); };
  const loadOpportunities = () => { if (token && controller.current && sourceRef.current.opportunities.phase !== "loading") void load("opportunities", controller.current.signal); };
  const toggleSaved = async (id: number) => {
    if (mutationLock.current || !token || sources.watchlist.phase !== "ready") return;
    mutationLock.current = true; setBusyId(id); setMutationError(null);
    const signal = controller.current!.signal;
    try {
      const saved = sources.watchlist.data?.some(item => item.listing_id === id && item.status === "active");
      if (saved) await removeFromWatchlist(id); else await saveToWatchlist(id);
      if (!signal.aborted) await Promise.allSettled([load("watchlist", signal), load("portfolio", signal), load("alerts", signal)]);
    } catch (error) { if (!signal.aborted) setMutationError(errorText(error)); }
    finally { mutationLock.current = false; setBusyId(null); }
  };
  const readAlert = async (alert: AlertView) => {
    const signal = controller.current?.signal;
    if (!signal || signal.aborted) return;
    if (alert.source === "watchlist") await summaryApi.readAlert(alert.id); else await summaryApi.readPatrimonyAlert(alert.id);
    if (!signal.aborted) await Promise.allSettled([load(alert.source === "watchlist" ? "alerts" : "patrimonyAlerts", signal), load("portfolio", signal)]);
  };
  return { fixture, sources, token, now, trends, selection, refresh, signIn, signOut, loadOpportunities, toggleSaved, busyId, mutationError, readAlert };
}
export type SummaryModel = ReturnType<typeof useSummary>;
