import type {WatchlistItem} from "@/types/watchlist";
import type {PortfolioItem} from "@/types/summary";
import {finite} from "@/features/listing-url/view-model";
import {formatUf,formatClp} from "@/lib/formatters";
import type {ValuationFormPrefill} from "@/features/valuation/prefill";
export function currentUf(item:WatchlistItem){const value=item.price_uf_display??item.price_uf;return finite(value)&&value>0?value:null;}
export function currentPrice(item:WatchlistItem){const uf=currentUf(item);return uf!==null?formatUf(uf):formatClp(item.price_clp_display??item.price_clp);}
export function snapshotValue(item:PortfolioItem|undefined){return item?.avm.available&&finite(item.avm.estimated_value_uf)?item.avm.estimated_value_uf:null;}
export function statusLabel(value:string){return ({active:"Activa",inactive:"Inactiva",removed:"Retirada",sold:"Vendida",unavailable:"No disponible"} as Record<string,string>)[value]??"Estado no confirmado";}
export function portfolioPrefill(item:WatchlistItem):ValuationFormPrefill{return {targetListingId:item.listing_id,comuna:item.comuna,propertyType:["apartment","house","office"].includes(item.property_type??"")?item.property_type as ValuationFormPrefill["propertyType"]:undefined,reference:item.title,builtAreaM2:item.m2??undefined,dormitorios:item.dormitorios,banos:item.banos,estacionamientos:item.estacionamientos,publishedPriceUf:currentUf(item)??undefined,publishedPriceClp:item.price_clp_display??item.price_clp,sourceUrl:item.url??undefined};}
