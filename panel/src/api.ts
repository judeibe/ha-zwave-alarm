import type { Hass, Overview } from "./types";

export const ERROR_TEXT: Record<string, string> = {
  zone_not_empty: "The zone still has sensors or a guest assigned. Use 'Force delete' to unassign its sensors.",
  zone_in_use: "A guest is restricted to this zone. Change or remove that guest first; forcing does not help.",
  code_in_use: "Another person already uses this code. Choose a different one.",
  invalid_code: "A code must be 4 to 12 digits.",
  conflict: "That conflicts with the current configuration (for example the last administrator).",
  not_found: "That item no longer exists. The list has been refreshed.",
  invalid_request: "The service rejected the request as invalid.",
  cannot_connect: "Cannot reach the Z-Wave Alarm service.",
  invalid_auth: "The service rejected the stored token. Re-authenticate the integration.",
  forbidden: "The service denied this action.",
  entry_not_found: "The Z-Wave Alarm integration is not loaded.",
};

export class ApiError extends Error {
  constructor(public code: string, message: string) {
    super(ERROR_TEXT[code] ?? (message || "Unexpected error"));
  }
}

/** Typed wrapper over the admin-only `zwave_alarm/*` websocket commands. */
export class Api {
  constructor(private readonly getHass: () => Hass) {}

  async call<T = unknown>(command: string, payload: Record<string, unknown> = {}): Promise<T> {
    try {
      return await this.getHass().connection.sendMessagePromise<T>({ type: `zwave_alarm/${command}`, ...payload });
    } catch (err) {
      const e = err as { code?: string; message?: string };
      throw new ApiError(e.code ?? "unknown", e.message ?? "");
    }
  }

  overview = () => this.call<Overview>("overview");
}
