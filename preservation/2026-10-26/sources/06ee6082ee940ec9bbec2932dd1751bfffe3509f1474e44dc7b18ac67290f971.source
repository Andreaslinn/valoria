"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { getRadarOpportunities } from "@/lib/api/radar";
import { ApiError } from "@/lib/api/client";
import { summaryApi } from "@/lib/api/summary";
import { saveToWatchlist, removeFromWatchlist } from "@/lib/api/watchlist";
import { getAccessToken, setAccessToken, clearAccessToken } from "@/lib/auth/token";
import { errorText } from "@/features/summary/use-summary";
import { opportunity, savedProperty, type RadarItem } from "./model";
export function useRadar() {
 const [requested,setRequested]=useState(false);
 const [fixture,setFixture]=useState(false),[items,setItems]=useState<RadarItem[]>([]),[saved,setSaved]=useState<RadarItem[]>([]),[savedReady,setSavedReady]=useState(false),[user,setUser]=useState("tu espacio"),[uf,setUf]=useState<number|null>(null),[error,setError]=useState(""),[saveError,setSaveError]=useState(""),[phase,setPhase]=useState("loading"),[busy,setBusy]=useState(false),[revision,setRevision]=useState(0);
 const fixtureRef=useRef(false), lock=useRef(false);
 const refresh=useCallback(()=>setRevision(value=>value+1),[]);
 useEffect(()=>{
  const abort=new AbortController();
  if(process.env.NODE_ENV === "development" && new URLSearchParams(location.search).get("fixture")==="radar") {
   void import("./fixture").then(({radarFixture})=>{if(abort.signal.aborted)return;fixtureRef.current=true;setFixture(true);setItems(radarFixture);setSaved([radarFixture[1]]);setSavedReady(true);setUf(39820);setUser("Heiko");setPhase("ready");});return ()=>abort.abort();
  }
  setError("");setSaveError("");setSavedReady(false);setItems([]);setSaved([]);
  void summaryApi.uf({signal:abort.signal}).then(data=>{if(!abort.signal.aborted)setUf(data.is_fallback?null:data.rate_clp);}).catch(()=>{});
  if(!getAccessToken()){setPhase("auth");return ()=>abort.abort();}
  setPhase(requested ? "loading" : "idle");
  void summaryApi.user({signal:abort.signal}).then(data=>{if(!abort.signal.aborted)setUser(data.email.split("@")[0]);}).catch(e=>{if(!abort.signal.aborted && e instanceof ApiError && e.status===401){clearAccessToken();setPhase("auth");}});
  void summaryApi.watchlist({signal:abort.signal}).then(data=>{if(!abort.signal.aborted){setSaved(data.filter(row=>row.status==="active").map(savedProperty));setSavedReady(true);}}).catch(e=>{if(!abort.signal.aborted)setSaveError(errorText(e));});
  if(requested) void getRadarOpportunities({signal:abort.signal}).then(data=>{if(!abort.signal.aborted){setItems(data.map(opportunity).filter((row):row is RadarItem=>row!==null));setPhase("ready");}}).catch(e=>{if(!abort.signal.aborted){setError(errorText(e));if(e instanceof ApiError && e.status===401){clearAccessToken();setPhase("auth");}else setPhase("error");}});
  return ()=>abort.abort();
 },[revision,requested]);
 async function login(email:string,password:string){const session=await summaryApi.login(email,password);setAccessToken(session.access_token);refresh();}
 async function toggle(item:RadarItem){if(lock.current||!savedReady)return;lock.current=true;setBusy(true);setSaveError("");const exists=saved.some(row=>row.id===item.id);
 try{if(!fixtureRef.current){if(exists)await removeFromWatchlist(item.id);else await saveToWatchlist(item.id);}setSaved(rows=>exists?rows.filter(row=>row.id!==item.id):[...rows,item]);}catch(e){setSaveError(errorText(e));}finally{lock.current=false;setBusy(false);}}
 return {fixture,items,saved,savedReady,user,uf,error,saveError,phase,busy,refresh,search:()=>setRequested(true),login,toggle};
}
