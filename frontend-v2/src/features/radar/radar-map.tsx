"use client";
import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { located, type RadarItem } from "./model";
import { formatNumber } from "@/lib/formatters";
export function RadarMap({items,selected,onSelect}:{items:RadarItem[];selected:number|null;onSelect:(id:number)=>void}) {
 const container=useRef<HTMLDivElement>(null),map=useRef<maplibregl.Map|null>(null),choose=useRef(onSelect);
 choose.current=onSelect;
 const [error,setError]=useState(false),[ready,setReady]=useState(false);
 useEffect(()=>{if(!container.current)return;let instance:maplibregl.Map;
 try{instance=new maplibregl.Map({container:container.current,style:"https://tiles.openfreemap.org/styles/dark",center:[-70.594,-33.434],zoom:12,attributionControl:{compact:true}});map.current=instance;instance.addControl(new maplibregl.NavigationControl(),"bottom-right");instance.addControl(new maplibregl.ScaleControl({maxWidth:100}),"bottom-left");instance.on("load",()=>{setReady(true);setError(false);});instance.on("error",()=>setError(true));}catch{setError(true);return;}
 const resize=new ResizeObserver(()=>instance.resize());resize.observe(container.current);
 return ()=>{resize.disconnect();map.current=null;instance.remove();};},[]);
 useEffect(()=>{if(!map.current||!ready)return;const instance=map.current;const markers=items.filter(located).map(item=>{const el=document.createElement("button");el.className=`radar-marker${item.id===selected?" selected":""}`;el.textContent=`● ${item.price==null?"Sin precio":formatNumber(item.price,0)+" UF"}`;el.setAttribute("aria-label",`Seleccionar ${item.title}, ${item.commune}`);el.setAttribute("aria-pressed",String(item.id===selected));el.addEventListener("click",()=>choose.current(item.id));return new maplibregl.Marker({element:el}).setLngLat([item.lon!,item.lat!]).addTo(instance);});return ()=>markers.forEach(marker=>marker.remove());},[items,selected,ready]);
 useEffect(()=>{if(!map.current||!ready)return;const points=items.filter(located);if(points.length){const bounds=new maplibregl.LngLatBounds();points.forEach(item=>bounds.extend([item.lon!,item.lat!]));map.current.fitBounds(bounds,{padding:100,maxZoom:13,duration:0});}},[items,ready]);
 useEffect(()=>{const item=items.find(row=>row.id===selected);if(item&&located(item)&&ready&&!map.current?.getBounds().contains([item.lon!,item.lat!]))map.current?.easeTo({center:[item.lon!,item.lat!],duration:250});},[selected,ready,items]);
 return <><div ref={container} className="radar-map-canvas" aria-label="Mapa de oportunidades en Santiago"/>{error&&<p className="radar-map-message">No se pudo cargar parte del mapa. El listado sigue disponible.</p>}<div className="radar-map-legend"><strong>Precio publicado vs. estimación</strong><span><i/> Oportunidades · {items.filter(located).length} en el mapa</span>{items.some(item=>!located(item))&&<small>{items.filter(item=>!located(item)).length} sin coordenadas · disponibles en el listado</small>}</div></>;
}
