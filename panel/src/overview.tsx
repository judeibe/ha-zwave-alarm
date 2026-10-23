import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { useRouteLoaderData } from "react-router";
import type { Overview } from "./types";

export type Patch = (overview: Overview) => Overview;
const PatchContext = createContext<{ add: (p: Patch) => () => void; patches: Patch[] }>({ add: () => () => {}, patches: [] });

/** Holds optimistic edits: each is applied over the loader data until its request settles, so a failure rolls back by itself. */
export function PatchProvider({ children }: { children: ReactNode }) {
  const [patches, setPatches] = useState<Patch[]>([]);
  const add = useCallback((patch: Patch) => {
    setPatches((p) => [...p, patch]);
    return () => setPatches((p) => p.filter((x) => x !== patch));
  }, []);
  const value = useMemo(() => ({ add, patches }), [add, patches]);
  return <PatchContext.Provider value={value}>{children}</PatchContext.Provider>;
}

export const useAddPatch = () => useContext(PatchContext).add;

/** The overview loaded by the root route, with any in-flight optimistic edits applied. */
export function useOverview(): Overview {
  const loaded = useRouteLoaderData("root") as Overview;
  const { patches } = useContext(PatchContext);
  return useMemo(() => patches.reduce((o, p) => p(o), loaded), [loaded, patches]);
}
