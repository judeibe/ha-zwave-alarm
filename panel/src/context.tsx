import { createContext, useContext } from "react";
import type { Api } from "./api";

export const ApiContext = createContext<Api | null>(null);
export const useApi = (): Api => {
  const api = useContext(ApiContext);
  if (!api) throw new Error("useApi outside <ApiContext>");
  return api;
};
