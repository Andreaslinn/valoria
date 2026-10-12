import {apiClient,type RequestOptions} from "./client";
import {summaryApi} from "./summary";
import type {WatchlistStatus} from "@/types/watchlist";
export const portfolioApi={
  watchlist:summaryApi.watchlist,
  summary:summaryApi.portfolio,
  remove:(listingId:number,options?:RequestOptions)=>apiClient.delete<WatchlistStatus>(`/api/v1/watchlist/${listingId}`,options),
};
