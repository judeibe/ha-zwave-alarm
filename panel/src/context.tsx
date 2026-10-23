import { createContext, useContext } from "react";
import type { Api } from "./api";

export const ApiContext = createContext<Api | null>(null);
export const useApi = (): Api => {
  const api = useContext(ApiContext);
  if (!api) throw new Error("ApiContext missing");
  return api;
};

/** HA's `narrow` flag for the panel (its window is under 870px wide); decides whether we show HA's menu button. */
export const NarrowContext = createContext(false);
