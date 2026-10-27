import { render, screen, waitFor } from "@testing-library/react";
import { RouterProvider } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiContext } from "../context";
import { createTestRouter } from "../routes";
import type { Overview } from "../types";
import { fakeApi, WITH_LOCKS } from "./fixtures";

/**
 * Every page, rendered with the newest fields all present (what a current service sends), must come up with
 * content and without a single console error, warning, unhandled rejection or failed request. This stands in for
 * opening each page in a browser: it exercises the real components, router and API layer against a fake service.
 */
const FULL: Overview = {
  ...WITH_LOCKS,
  modes: {
    armed_home: { entryDelaySec: 60, exitDelaySec: 0, chirpsEnabled: false },
    armed_away: { entryDelaySec: 60, exitDelaySec: 60, chirpsEnabled: true },
    disarmed: { chirpsEnabled: false },
  },
  keypad_settings: { requireCodeToArm: true, volume: 60 },
  panel: { state: "disarmed", armed_mode: null, pending_delay_ends_at: null },
  alarm_events: [{ id: "e1", type: "BURGLARY", service: null, triggerDeviceId: "s1", startedAt: 1, sirenState: "sounding", dispatchState: "held" }],
  sirens: [{ nodeId: 14, kind: "OUTDOOR", name: "Garden siren", durationSec: 180, createdAt: 1 }],
  mode_schedules: [{ id: "m1", name: "Night", mode: "armed_home", time: "22:00", days: ["mon", "tue"], enabled: true, timeZone: "America/Chicago", lastRunAt: 5 }],
  zones: WITH_LOCKS.zones.map((z) => ({
    ...z,
    sensors: z.sensors.map((s) => ({ ...s, placement: "MAIN_DOOR" as const, armedHome: true, armedAway: true, alertsOnly: false, tampered: false, chirpTone: "double_beep" as const })),
  })),
  users: [
    { id: "u1", name: "Alex", role: "administrator", hasCode: true, hasDuressCode: true, haPersonId: "person.alex", haUserId: null, lockSlots: [{ nodeId: 5, slot: 3, status: "synced" }] },
    { id: "g1", name: "Guest", role: "guest", hasCode: true, hasDuressCode: false, haPersonId: null, haUserId: null },
    { id: "i1", name: "Pat", role: "installer", hasCode: true, guestExpiresAt: 1700172800000, haPersonId: null, haUserId: null },
  ],
  locks: WITH_LOCKS.locks.map((l) => ({
    ...l,
    modeSettings: { armOnLockWithCode: true, armOnOneTouch: false, disarmOnUnlock: true, actions: { disarmed: null, armed_home: "lock", armed_away: "lock" } },
  })),
};
const event = (n: number) => ({ id: `e${n}`, type: "lock_locked", source: "system", sourceUserId: null, details: null, occurredAt: 1700000000000 + n, actor: "System", deviceId: "node-5", deviceName: "Front door lock" });
const RESULTS = {
  events: [event(1), event(2)],
  "guest_schedule/list": [{ id: "s1", userId: "g1", name: "Cleaners", days: ["mon"], allDay: false, start: "08:00", end: "17:30", timeZone: null }],
};

const PAGES: [string, RegExp | string][] = [
  ["/overview", "Entry and exit delays"],
  ["/sensors", "Assigned sensors"],
  ["/sensors/s1", "Chirp tone"],
  ["/zones", "Downstairs"],
  ["/people", "Home Assistant people"],
  ["/people/person.alex", "Duress code"],
  ["/keypads", "Keypad volume"],
  [`/locks/${WITH_LOCKS.locks[0]!.nodeId}`, "Alarm automation"],
  ["/schedules", "Mode schedules"],
  ["/history", "History"],
];

describe("every page renders without errors", () => {
  let errors: unknown[][];
  beforeEach(() => {
    errors = [];
    vi.spyOn(console, "error").mockImplementation((...args) => void errors.push(args));
    vi.spyOn(console, "warn").mockImplementation((...args) => void errors.push(args));
  });
  afterEach(() => vi.restoreAllMocks());

  it.each(PAGES)("%s", async (path, expected) => {
    const { api, call } = fakeApi(FULL, {}, RESULTS);
    const rejections: unknown[] = [];
    const onRejection = (e: PromiseRejectionEvent) => rejections.push(e.reason);
    window.addEventListener("unhandledrejection", onRejection);
    const view = render(
      <ApiContext.Provider value={api}>
        <RouterProvider router={createTestRouter(api, path)} />
      </ApiContext.Provider>,
    );
    expect((await screen.findAllByText(expected)).length).toBeGreaterThan(0);
    await waitFor(() => expect(view.baseElement.textContent!.trim().length).toBeGreaterThan(20)); // not blank
    await new Promise((r) => setTimeout(r, 50)); // let effects (history, schedules) settle
    window.removeEventListener("unhandledrejection", onRejection);
    expect(errors).toEqual([]);
    expect(rejections).toEqual([]);
    // Reading a page must never write: only list/overview-style commands were sent.
    const writes = call.mock.calls.map(([c]) => c).filter((c) => /\/(create|update|delete|set_|clear_|enroll|unenroll|put)/.test(c) || ["arm", "panic", "silence"].includes(c));
    expect(writes).toEqual([]);
  });
});
