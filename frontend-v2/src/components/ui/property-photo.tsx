"use client";
import {useState} from "react";
import {Building2} from "lucide-react";
import {API_BASE_URL} from "@/lib/config";
import type {ThumbnailRef} from "@/types/thumbnail";
import "./property-photo.css";

import {thumbnailSrc} from "@/lib/thumbnail";

export function PropertyPhoto({thumbnail,title,className="",small=false,illustrativeSrc}: {
  thumbnail: ThumbnailRef | undefined; title: string; className?: string; small?: boolean; illustrativeSrc?: string;
}) {
  const src = thumbnailSrc(thumbnail) ?? (process.env.NODE_ENV === "development" && illustrativeSrc && /^\/images\/[a-z0-9-]+\.jpg$/.test(illustrativeSrc) ? illustrativeSrc : null);
  // Key isolates load failures across URL changes, including returning to a prior URL.
  return <Photo key={src ?? "missing"} src={src} thumbnail={thumbnail} title={title} className={className} small={small}/>;
}

function Photo({src,thumbnail,title,className,small}: {src:string|null;thumbnail:ThumbnailRef|undefined;title:string;className:string;small:boolean}) {
  const [failed,setFailed]=useState(false),[loaded,setLoaded]=useState(false);
  return <div className={`property-photo ${className}`} data-photo-state={src&&!failed?(loaded?"image":"loading"):"fallback"} aria-busy={!!src&&!failed&&!loaded}>
    {src&&!failed?<img src={src} alt={`Fotografía de la publicación · ${title}`} width={thumbnail?.width??320} height={thumbnail?.height??240}
      loading="lazy" decoding="async" referrerPolicy="no-referrer" onLoad={()=>setLoaded(true)} onError={()=>setFailed(true)}/>:<><Building2 size={small?20:40} aria-hidden="true"/>{!small&&<span>Fotografía no disponible</span>}</>}
  </div>;
}
