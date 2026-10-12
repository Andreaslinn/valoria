"use client";

import { Bell, ChevronDown, ChevronRight, Folder, House, Link2, MapPin, Plus, Search, Target, TrendingUp } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/primitives";
import { usePathname } from "next/navigation";
import { legacyRoute } from "@/lib/navigation";
import { matchesPropertySearch } from "@/lib/search";
import { apiClient } from "@/lib/api/client";
import { getAccessToken, observeSessionChange } from "@/lib/auth/token";
import type { WatchlistItem } from "@/types/watchlist";

export type ShellData = { user: string; alertCount: string; searchItems: { id: number; title: string; description: string; url: string | null }[]; searchStatus: string; locationNote: string };
export type ShowDetail = (title: string, description: string) => void;

function Sidebar({ onNavigate, data }: { onNavigate: (label: string) => void; data: ShellData }) {
  const pathname = usePathname();
  const active = pathname.startsWith("/alerts") ? "Alertas" : pathname.startsWith("/portfolio") ? "Mi cartera" : pathname.startsWith("/analizar-url") ? "Analizar URL" : pathname.startsWith("/tasar") ? "Tasar" : pathname.startsWith("/radar") ? "Radar" : "Resumen";
  const navigation = [
    { label: "Resumen", icon: House }, { label: "Radar", icon: Target },
    { label: "Tasar", icon: TrendingUp }, { label: "Analizar URL", icon: Link2 },
    { label: "Mi cartera", icon: Folder }, { label: "Alertas", icon: Bell },
  ];
  return <aside className="sidebar">
    <a href="/" className="brand" aria-label="Valoria, resumen">
      <div className="brand-name"><svg className="brand-mark" viewBox="0 0 48 38" aria-hidden="true"><defs><linearGradient id="brand-silver" x2="0" y2="1"><stop stopColor="#f2f4f6"/><stop offset="1" stopColor="#8e969c"/></linearGradient></defs><path fill="var(--color-accent)" d="M1 5h12l13 29H14z"/><path fill="url(#brand-silver)" d="M34 5h12L35 28H23z"/></svg><span>valoria</span></div>
      <span className="brand-tagline">INTELIGENCIA INMOBILIARIA</span>
    </a>
    <nav aria-label="Navegación principal">{navigation.map(({ label, icon: Icon }) =>
      <a key={label} href={label === "Resumen" ? "/resumen" : label === "Radar" ? "/radar" : legacyRoute(label) ?? "#resumen"} className={`nav-item${label === active ? " active" : ""}`} aria-current={label === active ? "page" : undefined} >
        <Icon size={21} strokeWidth={1.5}/><span>{label}</span>{label === "Alertas" && <span className="nav-count">{data.alertCount}</span>}
      </a>
    )}</nav>
    <div className="sidebar-bottom"><button className="profile" onClick={() => onNavigate("Workspace personal")}><span className="avatar">{data.user.charAt(0).toUpperCase()}</span><span><strong>{data.user}</strong><small>Workspace personal</small></span><ChevronRight size={17}/></button>
      <blockquote>“Mejores decisiones<br/>para un mejor Santiago.”<span>—</span></blockquote>
    </div>
  </aside>;
}

function TopBar({ onNavigate, showDetail, data }: { onNavigate: (label: string) => void; showDetail: ShowDetail; data: ShellData }) {
  const searchRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [focused, setFocused] = useState(false);
  const [searchItems,setSearchItems]=useState<ShellData["searchItems"]>([]);
  const [searchLoaded,setSearchLoaded]=useState(false),[searchError,setSearchError]=useState("");
  useEffect(()=>{if(!focused||searchLoaded||!getAccessToken())return;const abort=new AbortController();
    void apiClient.get<WatchlistItem[]>("/api/v1/watchlist",{signal:abort.signal}).then(items=>{if(!abort.signal.aborted){setSearchItems(items.map(item=>({id:item.listing_id,title:item.title,description:item.comuna,url:item.url})));setSearchLoaded(true);}}).catch(()=>{if(!abort.signal.aborted){setSearchError("No se pudo cargar la búsqueda de tu cartera.");setSearchLoaded(true);}});
    return()=>abort.abort();
  },[focused,searchLoaded]);
  useEffect(()=>{const reset=()=>{setSearchItems([]);setSearchLoaded(false);setSearchError("");setQuery("");setFocused(false);};window.addEventListener("storage",reset);return()=>window.removeEventListener("storage",reset);},[]);
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); searchRef.current?.focus(); }
      if (event.key === "Escape") { setFocused(false); searchRef.current?.blur(); }
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);
  const candidates=[...new Map([...data.searchItems,...searchItems].map(item=>[item.id,item])).values()];
  const results = candidates.filter(item => matchesPropertySearch(item,query)).slice(0,20);
  return <header className="topbar">
    <button className="location" onClick={() => showDetail("Santiago, Chile", data.locationNote)}><MapPin size={16}/><span>Santiago, Chile</span><ChevronDown size={14}/></button>
    <div className="search-container" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false); }}>
      <div className="search-field"><Search size={21} strokeWidth={1.6}/><input ref={searchRef} aria-label="Buscar propiedad, comuna o anuncio" placeholder="Buscar propiedad, comuna o anuncio" value={query} onChange={e => setQuery(e.target.value)} onFocus={() => setFocused(true)}/><kbd>⌘ K</kbd></div>
      {focused && query.trim() && <div className="search-results"><small>PROPIEDADES DE TU CARTERA</small>{results.length ? results.map(item => <button key={item.id} onClick={() => { setFocused(false); showDetail(item.title, item.description); }}>{item.title}<ChevronRight size={16}/></button>) : <p>{searchError || (searchLoaded?"No hay coincidencias en tu cartera.":data.searchStatus||"Cargando búsqueda…")}</p>}</div>}
    </div>
    <div className="topbar-actions"><button className="notification-button" aria-label={`Ver novedades: ${data.alertCount}`} onClick={() => onNavigate("Alertas")}><Bell size={23} strokeWidth={1.5}/>{Number(data.alertCount) > 0 && <i/>}</button><Button className="button-primary" onClick={() => onNavigate("Analizar propiedad")}><Plus size={20}/>Analizar propiedad</Button></div>
  </header>;
}

export function AppShell({ children, onNavigate, showDetail, data }: { children: ReactNode; onNavigate: (label: string) => void; showDetail: ShowDetail; data: ShellData }) {
  const pathname = usePathname();
  useEffect(() => observeSessionChange(() => window.location.reload()), []);
  const section = pathname.startsWith("/alerts") ? "alerts" : pathname.startsWith("/portfolio") ? "portfolio" : pathname.startsWith("/analizar-url") ? "analizar-url" : pathname.startsWith("/tasar") ? "tasar" : pathname.startsWith("/radar") ? "radar" : "resumen";
  return <div className="app-shell"><a className="skip-link" href={`#${section}`}>Ir a {section}</a><Sidebar onNavigate={onNavigate} data={data}/><div className="main-shell"><TopBar onNavigate={onNavigate} showDetail={showDetail} data={data}/><main id={section}>{children}</main></div></div>;
}
