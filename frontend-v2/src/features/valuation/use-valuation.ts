"use client";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api/client";
import { createValuation, downloadValuationReport } from "@/lib/api/valuations";
import { summaryApi } from "@/lib/api/summary";
import { getAccessToken, setAccessToken } from "@/lib/auth/token";
import type { ValuationRequest, ValuationResponse } from "@/types/valuation";

export function valuationError(error: unknown): string {
  if (!(error instanceof ApiError)) return "No pudimos completar la tasación. Intenta nuevamente.";
  if (error.status === 401 || error.status === 403) return "Inicia sesión para continuar con la tasación.";
  if (error.status === 503) return "La UF real no está disponible o no está vigente. Intenta nuevamente más tarde.";
  if (error.status === 422) return "Revisa los datos ingresados. La API no pudo validar esta propiedad.";
  return error.message;
}

export function useValuation() {
  const [result, setResult] = useState<ValuationResponse|null>(null);
  const [payload, setPayload] = useState<ValuationRequest|null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [user, setUser] = useState("tu espacio"), [auth, setAuth] = useState(false);
  const [downloading, setDownloading] = useState(false), [reportError, setReportError] = useState("");
  const request = useRef<AbortController|null>(null), lock = useRef(false);
  useEffect(() => {
    const abort = new AbortController();
    setAuth(!getAccessToken());
    if (getAccessToken()) void summaryApi.user({signal:abort.signal}).then(data=>setUser(data.email.split("@")[0])).catch(e=>{if(!abort.signal.aborted && e instanceof ApiError && e.status===401)setAuth(true);});
    return ()=>{abort.abort();request.current?.abort();};
  },[]);
  async function submit(input: ValuationRequest) {
    if (lock.current) return;
    if (!getAccessToken()) { setAuth(true); setError("Inicia sesión para tasar esta propiedad."); return; }
    lock.current=true; setBusy(true); setError(""); setReportError(""); setResult(null); setPayload(input);
    const abort = new AbortController(); request.current=abort;
    try { const data=await createValuation(input,abort.signal); if(!abort.signal.aborted)setResult(data); }
    catch(e) {if(!abort.signal.aborted){setError(valuationError(e));if(e instanceof ApiError && (e.status===401||e.status===403))setAuth(true);}}
    finally {lock.current=false;if(!abort.signal.aborted)setBusy(false);}
  }
  async function login(email: string,password: string) {const data=await summaryApi.login(email,password);setAccessToken(data.access_token);setUser(email.split("@")[0]);setAuth(false);setError("");}
  async function download() {
    if(!payload||!result||downloading)return;
    setDownloading(true);setReportError("");
    try{await downloadValuationReport(payload,result);}catch(e){setReportError(valuationError(e));}finally{setDownloading(false);}
  }
  return {result,payload,busy,error,user,auth,submit,login,download,downloading,reportError};
}
