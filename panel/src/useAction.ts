import { useCallback, useState } from "react";
import { useRevalidator } from "react-router";
import { ApiError } from "./api";
import { useAddPatch, type Patch } from "./overview";
import { useToast } from "./ui/Toast";

interface RunOptions {
  /** Applied to the overview immediately and dropped once the request settles (rolls back on failure). */
  patch?: Patch;
  /** Toast shown on success. */
  done?: string;
}

/** Runs a mutation, then refetches the route data (which also restores truth after e.g. not_found). */
export function useAction() {
  const { revalidate } = useRevalidator();
  const addPatch = useAddPatch();
  const toast = useToast();
  const [error, setError] = useState("");
  const run = useCallback(
    async (fn: () => Promise<unknown>, { patch, done }: RunOptions = {}): Promise<boolean> => {
      const rollback = patch ? addPatch(patch) : undefined;
      let ok = true;
      try {
        await fn();
        setError("");
      } catch (err) {
        ok = false;
        setError(err instanceof ApiError ? err.message : "Unexpected error");
      }
      await revalidate();
      rollback?.();
      if (ok && done) toast(done);
      return ok;
    },
    [revalidate, addPatch, toast],
  );
  return { run, error, clearError: () => setError("") };
}
