import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider } from "react-router";
import { ApiError } from "../api";
import { ApiContext } from "../context";
import { createTestRouter } from "../routes";
import type { Overview } from "../types";
import { fakeApi, OVERVIEW, WITH_LOCKS } from "./fixtures";

function setup(path = "/", fail: Record<string, string> = {}, overview: Overview = OVERVIEW, results: Record<string, unknown> = {}) {
  const { api, call } = fakeApi(overview, fail, results);
  const router = createTestRouter(api, path);
  render(
    <ApiContext.Provider value={api}>
      <RouterProvider router={router} />
    </ApiContext.Provider>,
  );
  return { call, router, user: userEvent.setup() };
}

const sheet = () => screen.findByRole("dialog", { name: /.+/ });
const confirmDialog = () => within(screen.getByRole("alertdialog"));

describe("routing", () => {
  it("redirects / to the Overview and navigates between sections", async () => {
    const { router, user } = setup();
    expect(await screen.findByText("Armed away")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/overview");
    await user.click(screen.getByRole("link", { name: "Sensors" }));
    expect(await screen.findByText("Discovered Z-Wave devices")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Zones" }));
    expect(await screen.findByRole("button", { name: "New zone" })).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "People" }));
    expect(await screen.findByText("Home Assistant people")).toBeInTheDocument();
    await user.click(screen.getByRole("navigation", { name: "Sections" }).querySelector('a[href="/keypads"]') as HTMLElement);
    expect(await screen.findByRole("switch", { name: "Require PIN to arm" })).toBeInTheDocument();
  });

  it.each([["/zones/z1", "Zone name"], ["/people/person.sam", "Code"], ["/sensors/add/7", "Sensor name"], ["/sensors/s1", "Zone"]])(
    "deep link %s opens its sheet",
    async (path, label) => {
      setup(path);
      expect(await screen.findByLabelText(label)).toBeInTheDocument();
    },
  );

  it("sends unknown paths to the Overview, and a missing item back to its list", async () => {
    const { router } = setup("/nope");
    await screen.findByText("Armed away");
    expect(router.state.location.pathname).toBe("/overview");
    const missing = setup("/zones/gone");
    await waitFor(() => expect(missing.router.state.location.pathname).toBe("/zones"));
  });
});

describe("overview", () => {
  it("headlines the alarm state and the fault counts", async () => {
    setup("/overview");
    expect(await screen.findByText("Armed away")).toBeInTheDocument();
    expect(screen.getByText("1 fault")).toBeInTheDocument();
    expect(screen.getByText("Low battery").previousElementSibling).toHaveTextContent("1");
  });

  it("lists breached sensors as needing attention, and degrades before the first snapshot", async () => {
    const zone = OVERVIEW.zones[0]!;
    const breached = { ...OVERVIEW, zones: [{ ...zone, sensors: [{ ...zone.sensors[0]!, currentState: "breached" as const }] }] };
    setup("/overview", {}, breached);
    expect(await screen.findByText("Needs attention")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Front door/ })).toBeInTheDocument();
    document.body.replaceChildren();
    setup("/overview", {}, { ...OVERVIEW, panel: null });
    expect(await screen.findByText("Status unavailable")).toBeInTheDocument();
  });
});

describe("sensors", () => {
  it("shows the service's reason when only discovery is unavailable, and still lists sensors", async () => {
    setup("/sensors", {}, {
      ...OVERVIEW,
      discoverable: [],
      discoverable_error: { code: "service_unavailable", message: "The zwave-js driver is not ready yet; try again shortly." },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The Z-Wave Alarm service is up but its Z-Wave driver isn't ready yet. The zwave-js driver is not ready yet; try again shortly.",
    );
    expect(screen.queryByText(/No unassigned Z-Wave devices/)).not.toBeInTheDocument();
    expect(screen.getByText("Front door")).toBeInTheDocument();
  });

  it("names sensors after their Home Assistant device, falling back to the stored name", async () => {
    const zone = OVERVIEW.zones[0]!;
    const { user } = setup("/sensors", {}, {
      ...OVERVIEW,
      zones: [{ ...zone, sensors: [{ ...zone.sensors[0]!, haName: "Hallway door sensor" }] }, OVERVIEW.zones[1]!],
      discoverable: [{ ...OVERVIEW.discoverable[0]!, haName: "Garage door sensor" }],
    });
    expect(await screen.findByText("Hallway door sensor")).toBeInTheDocument();
    expect(screen.queryByText("Front door")).not.toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: /Garage door sensor/ }));
    expect(await screen.findByLabelText("Sensor name")).toHaveValue("Garage door sensor");
  });

  it("adds a discovered node to the chosen zone from its sheet", async () => {
    const { call, user } = setup("/sensors");
    await user.click(await screen.findByRole("link", { name: /Node 7/ }));
    await user.selectOptions(await screen.findByLabelText("Category"), "life-safety");
    await user.click(within(await sheet()).getByRole("button", { name: "Add sensor" }));
    expect(call).toHaveBeenCalledWith("sensor/assign", { zone_id: "z1", zwave_node_id: 7, name: "Node 7", category: "life-safety" });
  });

  it("moves an assigned sensor, then unassigns it after confirming", async () => {
    const { call, user } = setup("/sensors");
    await user.click(await screen.findByRole("link", { name: /Front door/ }));
    await user.selectOptions(await screen.findByLabelText("Zone"), "z2");
    await user.click(within(await sheet()).getByRole("button", { name: "Move" }));
    expect(call).toHaveBeenCalledWith("sensor/update", { sensor_id: "s1", zone_id: "z2" });
    await user.click(within(await sheet()).getByRole("button", { name: "Unassign" }));
    expect(call).not.toHaveBeenCalledWith("sensor/unassign", expect.anything()); // nothing happens until confirmed
    await user.click(confirmDialog().getByRole("button", { name: "Unassign" }));
    expect(call).toHaveBeenCalledWith("sensor/unassign", { sensor_id: "s1" });
  });

  it("does not unassign when the confirmation is cancelled", async () => {
    const { call, user } = setup("/sensors/s1");
    await user.click(within(await sheet()).getByRole("button", { name: "Unassign" }));
    await user.click(confirmDialog().getByRole("button", { name: "Cancel" }));
    expect(call).not.toHaveBeenCalled();
  });
});

describe("zones", () => {
  it("creates a zone with a description from the New zone sheet", async () => {
    const { call, user } = setup("/zones");
    await user.click(await screen.findByRole("button", { name: "New zone" }));
    await user.type(await screen.findByLabelText("Zone name"), "Garage");
    await user.type(screen.getByLabelText("Description (optional)"), "Detached");
    await user.click(screen.getByRole("button", { name: "Create zone" }));
    expect(call).toHaveBeenCalledWith("zone/create", { name: "Garage", description: "Detached" });
  });

  it("saves edits to a zone", async () => {
    const { call, user } = setup("/zones/z2");
    const name = await screen.findByLabelText("Zone name");
    await user.clear(name);
    await user.type(name, "Loft");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(call).toHaveBeenCalledWith("zone/update", { zone_id: "z2", name: "Loft", description: null });
  });

  it("force-deletes a zone that has sensors, after confirming", async () => {
    const { call, user } = setup("/zones/z1");
    await user.click(await screen.findByRole("button", { name: "Delete zone" }));
    expect(confirmDialog().getByText("Its 1 sensor will be unassigned.")).toBeInTheDocument();
    await user.click(confirmDialog().getByRole("button", { name: "Delete zone" }));
    expect(call).toHaveBeenCalledWith("zone/delete", { zone_id: "z1", force: true });
  });

  it("deletes an empty zone without forcing", async () => {
    const { call, user } = setup("/zones/z2");
    await user.click(await screen.findByRole("button", { name: "Delete zone" }));
    await user.click(confirmDialog().getByRole("button", { name: "Delete zone" }));
    expect(call).toHaveBeenCalledWith("zone/delete", { zone_id: "z2" });
  });

  it("shows the service's reason when a delete is refused, and keeps the sheet open", async () => {
    const { user } = setup("/zones/z2", { "zone/delete": "zone_in_use" });
    await user.click(await screen.findByRole("button", { name: "Delete zone" }));
    await user.click(confirmDialog().getByRole("button", { name: "Delete zone" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/forcing does not help/);
    expect(screen.getByLabelText("Zone name")).toBeInTheDocument();
  });
});

describe("people and codes", () => {
  it("onboards a person without a code and omits the code key", async () => {
    const { call, user } = setup("/people/person.sam");
    await user.click(await screen.findByRole("button", { name: "Onboard" }));
    const [, payload] = call.mock.calls.find(([c]) => c === "user/create")!;
    expect(payload).toEqual({ name: "Sam", role: "member", ha_person_id: "person.sam" });
    expect(payload).not.toHaveProperty("code");
  });

  it("sends a code when one is typed", async () => {
    const { call, user } = setup("/people/person.sam");
    await user.type(await screen.findByLabelText("Code"), "123456");
    await user.click(screen.getByRole("button", { name: "Onboard" }));
    expect(call).toHaveBeenCalledWith("user/create", { name: "Sam", role: "member", ha_person_id: "person.sam", code: "123456" });
  });

  it("disables Onboard and Set code for a malformed code", async () => {
    const sam = setup("/people/person.sam");
    await sam.user.type(await screen.findByLabelText("Code"), "12");
    expect(screen.getByRole("button", { name: "Onboard" })).toBeDisabled();
    document.body.replaceChildren();
    const alex = setup("/people/person.alex");
    await alex.user.type(await screen.findByLabelText("Code"), "12");
    expect(screen.getByRole("button", { name: "Replace code" })).toBeDisabled();
  });

  it("sets a code, then clears the field and never shows the code", async () => {
    const { call, user } = setup("/people/person.alex");
    const input = (await screen.findByLabelText("Code")) as HTMLInputElement;
    expect(input.type).toBe("password");
    await user.type(input, "654321");
    await user.click(screen.getByRole("button", { name: "Replace code" }));
    expect(call).toHaveBeenCalledWith("user/set_code", { user_id: "u1", code: "654321" });
    await waitFor(() => expect(input.value).toBe(""));
    expect(document.body.textContent).not.toContain("654321");
  });

  it("keeps the typed code and shows code_in_use on conflict", async () => {
    const { user } = setup("/people/person.alex", { "user/set_code": "code_in_use" });
    const input = (await screen.findByLabelText("Code")) as HTMLInputElement;
    await user.type(input, "654321");
    await user.click(screen.getByRole("button", { name: "Replace code" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Another person already uses this code/);
    expect(input.value).toBe("654321");
  });

  it("clears a code and removes a user, each after confirming", async () => {
    const { call, user } = setup("/people/person.alex");
    await user.click(await screen.findByRole("button", { name: "Clear code" }));
    await user.click(confirmDialog().getByRole("button", { name: "Clear code" }));
    expect(call).toHaveBeenCalledWith("user/clear_code", { user_id: "u1" });
    await user.click(screen.getByRole("button", { name: "Remove" }));
    await user.click(confirmDialog().getByRole("button", { name: "Remove" }));
    expect(call).toHaveBeenCalledWith("user/delete", { user_id: "u1" });
  });
});

describe("load failure", () => {
  it("explains an unknown_error, shows its code and offers a retry", async () => {
    const { api } = fakeApi();
    api.overview = async () => {
      throw new ApiError("unknown_error", "Unknown error");
    };
    render(
      <ApiContext.Provider value={api}>
        <RouterProvider router={createTestRouter(api, "/")} />
      </ApiContext.Provider>,
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/unexpected error handling this request/i);
    expect(alert).toHaveTextContent("unknown_error");
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });
});

describe("keypads", () => {
  it("lists each keypad with its status and battery", async () => {
    setup("/keypads");
    expect(await screen.findByText("Ring Keypad v2")).toBeInTheDocument();
    expect(screen.getByText("Node 12 · battery 87%")).toBeInTheDocument();
    expect(screen.getByText("Online")).toBeInTheDocument();
  });

  it("explains when no keypad has been found", async () => {
    setup("/keypads", {}, { ...OVERVIEW, keypads: [] });
    expect(await screen.findByText("No keypads found")).toBeInTheDocument();
  });

  it("turns the PIN requirement on and sends it to the service", async () => {
    const { call, user } = setup("/keypads");
    const toggle = await screen.findByRole("switch", { name: "Require PIN to arm" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    await user.click(toggle);
    expect(call).toHaveBeenCalledWith("keypad_settings/update", { require_code_to_arm: true });
    expect(await screen.findByText("Arming now needs a PIN")).toBeInTheDocument();
  });

  it("turns it off again when it is on", async () => {
    const { call, user } = setup("/keypads", {}, { ...OVERVIEW, keypad_settings: { requireCodeToArm: true } });
    const toggle = await screen.findByRole("switch", { name: "Require PIN to arm" });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    await user.click(toggle);
    expect(call).toHaveBeenCalledWith("keypad_settings/update", { require_code_to_arm: false });
  });

  it("shows the service's refusal and leaves the switch as it was", async () => {
    const { user } = setup("/keypads", { "keypad_settings/update": "forbidden" });
    const toggle = await screen.findByRole("switch", { name: "Require PIN to arm" });
    await user.click(toggle);
    expect(await screen.findByRole("alert")).toHaveTextContent("The service denied this action.");
    expect(screen.getByRole("switch", { name: "Require PIN to arm" })).toHaveAttribute("aria-checked", "false");
  });

  it("hides the switch when the service does not report keypad settings", async () => {
    setup("/keypads", {}, { ...OVERVIEW, keypad_settings: null });
    expect(await screen.findByText(/Keypad settings are not available yet/)).toBeInTheDocument();
    expect(screen.queryByRole("switch")).toBeNull();
  });
});

describe("locks", () => {
  const users = [{ userId: 1, status: "enabled" }, { userId: 2, status: "available" }];
  const slots = { user_id: 1, kinds: { weekDay: [{ slot_id: 1, schedule: null }, { slot_id: 2, schedule: null }], dailyRepeating: [{ slot_id: 1, schedule: null }] } };

  it("lists enrolled locks and offers paired ones for enrolment, without listing them as devices", async () => {
    const { call, user } = setup("/locks", {}, WITH_LOCKS);
    expect(await screen.findByText("Front door lock")).toBeInTheDocument();
    expect(screen.getByText("Paired, not added")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /lock/i }).some((l) => l.textContent?.includes("Garage lock"))).toBe(false);
    await user.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("lock/enroll", { node_id: 9 }));
  });

  it("says so when no lock is enrolled", async () => {
    setup("/locks");
    expect(await screen.findByText("No locks in the alarm system")).toBeInTheDocument();
  });

  it("sets a user code with the lock's PIN length", async () => {
    const { call, user } = setup("/locks/5", {}, WITH_LOCKS, { "lock/users": users, "lock/schedules": slots });
    await user.click((await screen.findAllByRole("button", { name: "Set" }))[0]!);
    const input = await screen.findByLabelText("Code for user 2");
    await user.type(input, "123");
    expect(screen.getByRole("button", { name: "Save code" })).toBeDisabled();
    await user.type(input, "4");
    await user.click(screen.getByRole("button", { name: "Save code" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("lock/user/set_code", { node_id: 5, user_id: 2, code: "1234" }));
  });

  it("only offers the schedule kinds the lock supports", async () => {
    setup("/locks/5", {}, WITH_LOCKS, { "lock/users": users, "lock/schedules": slots });
    expect(await screen.findByText("Weekly 1")).toBeInTheDocument();
    expect(screen.getByText("Daily repeating 1")).toBeInTheDocument();
    expect(screen.queryByText(/Date range/)).not.toBeInTheDocument();
  });

  it("saves a weekly schedule", async () => {
    const { call, user } = setup("/locks/5", {}, WITH_LOCKS, { "lock/users": users, "lock/schedules": slots });
    await screen.findByText("Weekly 1");
    await user.click(within(await sheet()).getAllByRole("button", { name: "Add" })[0]!);
    await user.click(await screen.findByRole("button", { name: "Save schedule" }));
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith("lock/schedule/set", {
        node_id: 5, user_id: 1, kind: "weekDay", slot_id: 1,
        schedule: { weekday: 1, startHour: 8, startMinute: 0, stopHour: 17, stopMinute: 0 },
      }),
    );
  });

  it("removes a lock from the alarm after confirmation", async () => {
    const { call, user } = setup("/locks/5", {}, WITH_LOCKS, { "lock/users": users, "lock/schedules": slots });
    await user.click(await screen.findByRole("button", { name: "Remove from alarm" }));
    await user.click(confirmDialog().getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("lock/unenroll", { node_id: 5 }));
  });

  it("tells the user when the lock could not be cleared on removal", async () => {
    const reply = { node_id: 5, cleared: false, failures: ["user code 3: lock did not answer"] };
    const { user } = setup("/locks/5", {}, WITH_LOCKS, { "lock/users": users, "lock/schedules": slots, "lock/unenroll": reply });
    await user.click(await screen.findByRole("button", { name: "Remove from alarm" }));
    await user.click(confirmDialog().getByRole("button", { name: "Remove" }));
    expect(await screen.findByText(/could not be cleared: user code 3: lock did not answer/)).toBeInTheDocument();
  });

  it("says a schedule kind is not reported yet instead of offering it", async () => {
    const lock = WITH_LOCKS.locks[0]!;
    const pending = { ...lock, capabilities: { ...lock.capabilities, schedules: { weekDay: true, yearDay: null, dailyRepeating: false } } };
    setup("/locks/5", {}, { ...WITH_LOCKS, locks: [pending] }, { "lock/users": users, "lock/schedules": slots });
    expect(await screen.findByText("Weekly 1")).toBeInTheDocument();
    expect(screen.getByText(/Date range schedules: not reported by the lock yet/)).toBeInTheDocument();
    expect(screen.queryByText("Daily repeating 1")).not.toBeInTheDocument();
  });

  it("will not add a paired lock that was included without security", async () => {
    const insecure = { nodeId: 9, model: "BE468", label: "Garage lock", connectivityStatus: "online" as const, secure: false };
    setup("/locks", {}, { ...WITH_LOCKS, discoverable_locks: [insecure] });
    expect(await screen.findByText(/Not securely included/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  });

  it("hides codes and schedules, and explains why, for an enrolled lock without S0/S2", async () => {
    const lock = WITH_LOCKS.locks[0]!;
    const insecure = { ...lock, capabilities: { ...lock.capabilities, secure: false } };
    setup("/locks/5", {}, { ...WITH_LOCKS, locks: [insecure] });
    expect(await screen.findByText(/included without S0\/S2/)).toBeInTheDocument();
    expect(screen.queryByText("Users and codes")).not.toBeInTheDocument();
    expect(screen.queryByText("Access schedules")).not.toBeInTheDocument();
  });

  it("hides user codes and schedules on a lock that has neither", async () => {
    const bare = { ...WITH_LOCKS.locks[0]!, capabilities: { ...WITH_LOCKS.locks[0]!.capabilities, userCodes: false, schedules: { weekDay: false, yearDay: false, dailyRepeating: false } } };
    setup("/locks/5", {}, { ...WITH_LOCKS, locks: [bare] });
    expect(await screen.findByText("This lock does not support user codes.")).toBeInTheDocument();
    expect(screen.getByText("This lock does not support access schedules.")).toBeInTheDocument();
  });
});

describe("modes and placements", () => {
  it("shows each mode's delays and saves a changed one", async () => {
    const { call, user } = setup("/");
    const exit = await screen.findByLabelText("Away exit delay");
    expect(exit).toHaveValue("30");
    await user.clear(exit);
    await user.type(exit, "90{Enter}");
    expect(call).toHaveBeenCalledWith("modes/update", { armed_away: { exitDelaySec: 90 } });
  });

  it("does not send a delay above 180 seconds", async () => {
    const { call, user } = setup("/");
    const entry = await screen.findByLabelText("Home entry delay");
    await user.clear(entry);
    await user.type(entry, "181{Enter}");
    expect(entry).toHaveAttribute("aria-invalid", "true");
    expect(call).not.toHaveBeenCalledWith("modes/update", expect.anything());
  });

  it("hides the delays when the service predates them", async () => {
    setup("/", {}, { ...OVERVIEW, modes: null });
    await screen.findByText("Armed away");
    expect(screen.queryByText("Entry and exit delays")).not.toBeInTheDocument();
  });

  it("changes a sensor's placement", async () => {
    const { call, user } = setup("/sensors/s1");
    await user.selectOptions(await screen.findByRole("combobox", { name: "Placement" }), "WINDOW");
    expect(call).toHaveBeenCalledWith("sensor/update", { sensor_id: "s1", placement: "WINDOW" });
  });

  it("turns a sensor off for Home only", async () => {
    const { call, user } = setup("/sensors/s1");
    await user.click(await screen.findByRole("switch", { name: "Armed in Home" }));
    expect(call).toHaveBeenCalledWith("sensor/update", { sensor_id: "s1", armed: { home: false } });
  });
});
