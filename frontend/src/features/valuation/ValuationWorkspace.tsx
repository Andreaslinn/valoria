"use client";

import { useEffect, useRef, useState } from "react";

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
  const resultRef = useRef<HTMLDivElement>(null);
  const formRef = useRef<HTMLDivElement>(null);

  useEffect(() => setPrefill(consumeTasarPrefill()), []);

  useEffect(() => {
    if (result && window.matchMedia("(max-width: 1023px)").matches) {
      resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [result]);

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
    <div className="grid gap-5">
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
        <div ref={formRef} className="grid gap-4">
          <ValuationForm importedPrefill={prefill} isSubmitting={isSubmitting} onSubmit={handleSubmit} />
          {error ? <StatusNote tone="warning">{error}</StatusNote> : null}
        </div>
        <div ref={resultRef}>
          <ValuationResult onEdit={() => formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })} payload={lastPayload} result={result} />
        </div>
      </div>
    </div>
  );
}

function errorText(error: unknown): string {
  if (!(error instanceof ApiError)) return "No pudimos completar la tasación. Intenta nuevamente.";
  if (error.status === 0) return error.message;
  if (error.status === 401 || error.status === 403) return "Tu sesión no está vigente o no tiene permisos para tasar. Vuelve a iniciar sesión.";
  if (error.status === 422) return "Revisa los campos ingresados e inténtalo nuevamente.";
  if (error.status >= 500) return "No pudimos completar la tasación. Intenta nuevamente en unos minutos.";
  return error.message;
}
