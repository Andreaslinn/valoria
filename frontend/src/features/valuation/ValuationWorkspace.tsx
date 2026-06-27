"use client";

import { useEffect, useState } from "react";

import { StatusNote } from "@/components/ui/status-note";
import { ApiError } from "@/lib/api/client";
import { createValuation } from "@/lib/api/valuations";
import type { ValuationRequest, ValuationResponse } from "@/types/valuation";

import { ValuationForm } from "./ValuationForm";
import { ValuationResult } from "./ValuationResult";
import { consumeTasarPrefill, type ValuationFormPrefill } from "./prefill";

export function ValuationWorkspace() {
  const [result, setResult] = useState<ValuationResponse | null>(null);
  const [lastPayload, setLastPayload] = useState<ValuationRequest | null>(null);
  const [prefill, setPrefill] = useState<ValuationFormPrefill | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setPrefill(consumeTasarPrefill());
  }, []);

  async function handleSubmit(payload: ValuationRequest) {
    setIsSubmitting(true);
    setError(null);
    try {
      const response = await createValuation(payload);
      setLastPayload(payload);
      setResult(response);
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(340px,420px)_1fr]">
      <div className="grid gap-4">
        <ValuationForm importedPrefill={prefill} isSubmitting={isSubmitting} onSubmit={handleSubmit} />
        {error ? <StatusNote tone="warning">{error}</StatusNote> : null}
      </div>
      <ValuationResult payload={lastPayload} result={result} />
    </div>
  );
}

function errorText(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "No pudimos completar la tasacion. Intenta nuevamente.";
  }

  if (error.status === 0) {
    return error.message;
  }
  if (error.status === 401 || error.status === 403) {
    return "Tu sesion no esta vigente o no tiene permisos para tasar. Vuelve a iniciar sesion.";
  }
  if (error.status === 422) {
    return validationErrorText(error.payload);
  }
  if (error.status >= 500) {
    return "La API tuvo un problema al tasar. Intenta nuevamente en unos minutos.";
  }
  return error.message;
}

function validationErrorText(payload: unknown): string {
  if (!payload || typeof payload !== "object" || !("detail" in payload)) {
    return "Hay campos invalidos en el formulario.";
  }

  const detail = (payload as { detail?: unknown }).detail;
  if (!Array.isArray(detail)) {
    return "Hay campos invalidos en el formulario.";
  }

  const fields = detail
    .map((item) => {
      if (!item || typeof item !== "object" || !("loc" in item)) {
        return null;
      }
      const loc = (item as { loc?: unknown }).loc;
      return Array.isArray(loc) ? loc.at(-1) : null;
    })
    .filter(Boolean);

  return fields.length
    ? `Revisa estos campos: ${fields.join(", ")}.`
    : "Hay campos invalidos en el formulario.";
}
