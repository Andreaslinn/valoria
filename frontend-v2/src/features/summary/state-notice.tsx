import { Button } from "@/components/ui/primitives";
import type { Resource } from "./use-summary";
export type SummaryActions = { retry: () => void; login: () => void };
export function StateNotice({ resource, empty, retry, login }: { resource: Resource<unknown>; empty: string } & SummaryActions) {
  const message = resource.phase === "loading" ? "Cargando datos de Valoria…" : resource.phase === "auth" ? "Inicia sesión para ver tus datos." : resource.phase === "error" ? resource.error : empty;
  return <div className="data-state" role="status" aria-live="polite"><p>{message}</p>{resource.phase === "auth" ? <Button onClick={login}>Iniciar sesión</Button> : resource.phase === "error" ? <Button onClick={retry}>Reintentar</Button> : null}</div>;
}

