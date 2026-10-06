import { vi } from "vitest";
import { Api, ApiError } from "../api";
import type { Overview } from "../types";

export const OVERVIEW: Overview = {
  zones: [
    { id: "z1", name: "Downstairs", description: "Ground floor", sensors: [{ id: "s1", zwaveNodeId: 2, zoneId: "z1", name: "Front door", category: "intrusion", currentState: "normal" }] },
    { id: "z2", name: "Upstairs", sensors: [] },
  ],
  discoverable: [{ zwaveNodeId: 7, name: null, manufacturer: "Aeotec", product: "Door Sensor", status: "alive" }],
  users: [{ id: "u1", name: "Alex", role: "member", hasCode: true, haPersonId: "person.alex", haUserId: null }],
  ha_people: [
    { entity_id: "person.alex", name: "Alex", user_id: "abc" },
    { entity_id: "person.sam", name: "Sam", user_id: null },
  ],
  ha_users: [],
};

/** A fake `Api` whose commands are spies; `fail` makes a command reject with a websocket error code. */
export function fakeApi(overview: Overview = OVERVIEW, fail: Record<string, string> = {}) {
  const api = new Api(() => ({ connection: { sendMessagePromise: async () => undefined as never } }));
  const call = vi.fn(async (command: string, _payload?: Record<string, unknown>) => {
    if (fail[command]) throw new ApiError(fail[command], "");
    return undefined as never;
  });
  api.call = call as unknown as Api["call"];
  api.overview = async () => overview;
  return { api, call };
}
