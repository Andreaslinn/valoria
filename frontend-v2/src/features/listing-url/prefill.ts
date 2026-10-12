import {safeExternalUrl} from "@/lib/navigation";
const KEY="valoria_analyzer_prefill";
export function saveAnalyzerPrefill(url:string):void {
  const safe=safeExternalUrl(url);
  if(!safe)throw new Error("URL inválida");
  const parsed=new URL(safe);
  if(parsed.username||parsed.password)throw new Error("URL inválida");
  window.sessionStorage.setItem(KEY,safe);
}
export function consumeAnalyzerPrefill():string|null {
  const value=window.sessionStorage.getItem(KEY);
  window.sessionStorage.removeItem(KEY);
  return safeExternalUrl(value);
}
