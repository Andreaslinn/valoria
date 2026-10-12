"use client";
import {useCallback,useEffect,useRef,useState} from "react";
import {portfolioApi} from "@/lib/api/portfolio";
import {summaryApi} from "@/lib/api/summary";
import {ApiError} from "@/lib/api/client";
import {getAccessToken,setAccessToken} from "@/lib/auth/token";
import type {WatchlistItem} from "@/types/watchlist";
import type {PortfolioSummary} from "@/types/summary";
export function portfolioError(e:unknown){if(e instanceof ApiError){if(e.status===401||e.status===403)return "Inicia sesión con una cuenta autorizada para ver tu cartera.";if(e.status===503)return "La UF real no está disponible. No podemos actualizar los precios ahora.";return e.message;}return "No pudimos cargar tu cartera. Intenta nuevamente.";}
export function usePortfolio(){
 const [items,setItems]=useState<WatchlistItem[]>([]),[summary,setSummary]=useState<PortfolioSummary|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState(""),[summaryError,setSummaryError]=useState(""),[actionError,setActionError]=useState(""),[message,setMessage]=useState("");
 const [user,setUser]=useState("tu espacio"),[auth,setAuth]=useState(false),[removing,setRemoving]=useState<number|null>(null);
 const controller=useRef<AbortController|null>(null),removeLock=useRef(false);
 const load=useCallback(async()=>{controller.current?.abort();const abort=new AbortController();controller.current=abort;setLoading(true);setError("");setSummaryError("");
  if(!getAccessToken()){setAuth(true);setLoading(false);setItems([]);setSummary(null);return;}
  const results=await Promise.allSettled([portfolioApi.watchlist({signal:abort.signal}),portfolioApi.summary({signal:abort.signal}),summaryApi.user({signal:abort.signal})]);
  if(abort.signal.aborted)return;
  const [watchlist,portfolio,account]=results;
  if(watchlist.status==="fulfilled")setItems(watchlist.value);else{setItems([]);setError(portfolioError(watchlist.reason));}
  if(portfolio.status==="fulfilled")setSummary(portfolio.value);else{setSummary(null);setSummaryError(portfolioError(portfolio.reason));}
  if(account.status==="fulfilled"){setUser(account.value.email.split("@")[0]);setAuth(false);}else if(account.reason instanceof ApiError&&(account.reason.status===401||account.reason.status===403))setAuth(true);
  setLoading(false);
 },[]);
 useEffect(()=>{void load();return()=>controller.current?.abort();},[load]);
 async function login(email:string,password:string){const result=await summaryApi.login(email,password);setAccessToken(result.access_token);setAuth(false);await load();}
 async function remove(id:number){if(removeLock.current)return false;removeLock.current=true;setRemoving(id);setActionError("");setMessage("");try{await portfolioApi.remove(id);setItems(values=>values.filter(i=>i.listing_id!==id));setMessage("Publicación quitada de tu seguimiento.");await load();return true;}catch(e){setActionError(portfolioError(e));return false;}finally{removeLock.current=false;setRemoving(null);}}
 return {items,summary,loading,error,summaryError,actionError,message,user,auth,removing,load,login,remove};
}
