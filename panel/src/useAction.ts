import { useCallback, useState } from "react";
import { useRevalidator } from "react-router";
import { ApiError } from "./api";

/** Runs a mutation, then refetches the route data (which also restores truth after e.g. not_found). */
export function useAction() {
  const { revalidate } = useRevalidator();
  const [error, setError] = useState("");
  const run = useCallback(
    async (fn: () => Promise<unknown>): Promise<boolean> => {
      let ok = true;
      try {
        await fn();
        setError("");
      } catch (err) {
        ok = false;
        setError(err instanceof ApiError ? err.message : "Unexpected error");
      }
      await revalidate();
      return ok;
    },
    [revalidate],
  );
  return { run, error, clearError: () => setError("") };
}
