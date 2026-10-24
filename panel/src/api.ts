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
  service_unavailable: "The Z-Wave Alarm service is up but its Z-Wave driver isn't ready yet.",
  invalid_auth: "The service rejected the stored token. Re-authenticate the integration.",
  forbidden: "The service denied this action.",
  lock_not_enrolled: "That lock is not part of the alarm system. Add it first.",
  lock_not_secure: "This lock was included without S0/S2 security, so its codes and schedules cannot be managed. Exclude it and include it again with S0 or S2.",
  lock_schedule_unknown: "The lock has not reported its schedule slots yet. Wake it with a keypad touch, then try again.",
  lock_unsupported: "This lock does not support that.",
  lock_unavailable: "The lock did not answer. Wake it with a keypad touch and try again.",
  entry_not_found: "The Z-Wave Alarm integration is not loaded.",
  unknown_error: "Home Assistant hit an unexpected error handling this request. Check the Home Assistant log for the zwave_alarm integration.",
};

export class ApiError extends Error {
  constructor(public code: string, message: string) {
    // The service says why it is unavailable (e.g. the driver is still starting): keep that as detail.
    const text = ERROR_TEXT[code];
    super(code === "service_unavailable" && message ? `${text} ${message}` : (text ?? (message || "Unexpected error")));
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
