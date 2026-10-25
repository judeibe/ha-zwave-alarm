import { vi } from "vitest";
import { Api, ApiError } from "../api";
import type { Overview } from "../types";

export const OVERVIEW: Overview = {
  panel: { state: "armed_away", armed_mode: "away", pending_delay_ends_at: null },
  fault_count: 1,
  faults: { offline: 0, low_battery: 1 },
  zones: [
    { id: "z1", name: "Downstairs", description: "Ground floor", sensors: [{ id: "s1", zwaveNodeId: 2, zoneId: "z1", name: "Front door", category: "intrusion", currentState: "normal", placement: "MAIN_DOOR", armedHome: true, armedAway: true, alertsOnly: false }] },
    { id: "z2", name: "Upstairs", sensors: [] },
  ],
  discoverable: [{ zwaveNodeId: 7, name: null, manufacturer: "Aeotec", product: "Door Sensor", status: "alive" }],
  users: [{ id: "u1", name: "Alex", role: "member", hasCode: true, haPersonId: "person.alex", haUserId: null }],
  ha_people: [
    { entity_id: "person.alex", name: "Alex", user_id: "abc" },
    { entity_id: "person.sam", name: "Sam", user_id: null },
  ],
  ha_users: [],
  keypads: [{ nodeId: 12, adapterId: "ring-keypad-v2", label: "Ring Keypad v2", connectivityStatus: "online", batteryLevel: 87 }],
  keypad_settings: { requireCodeToArm: false },
  modes: { armed_home: { entryDelaySec: 60, exitDelaySec: 60 }, armed_away: { entryDelaySec: 45, exitDelaySec: 30 } },
  locks: [],
  discoverable_locks: [],
};

/** A fake `Api` whose commands are spies; `fail` makes a command reject with a websocket error code. */
export function fakeApi(overview: Overview = OVERVIEW, fail: Record<string, string> = {}, results: Record<string, unknown> = {}) {
  const api = new Api(() => ({ connection: { sendMessagePromise: async () => undefined as never } }));
  const call = vi.fn(async (command: string, _payload?: Record<string, unknown>) => {
    if (fail[command]) throw new ApiError(fail[command], "");
    return results[command] as never;
  });
  api.call = call as unknown as Api["call"];
  api.overview = async () => overview;
  return { api, call };
}

const BE469 = {
  nodeId: 5, model: "BE469", label: "Front door lock", connectivityStatus: "online" as const, batteryLevel: 90,
  settings: { pinLength: 4 }, scheduleSlots: { weekDay: 2, yearDay: 0, dailyRepeating: 1 },
  // A BE469ZP-style lock: weekly and daily schedules, no date-range ones.
  capabilities: { secure: true, userCodes: true, userSlots: 30, schedules: { weekDay: true, yearDay: false, dailyRepeating: true }, alarmSettings: true },
};
/** An enrolled BE469ZP-style lock plus one lock that is merely paired (and securely included). */
export const WITH_LOCKS: Overview = {
  ...OVERVIEW,
  locks: [BE469],
  discoverable_locks: [{ nodeId: 9, model: "BE468", label: "Garage lock", connectivityStatus: "online", secure: true }],
};
