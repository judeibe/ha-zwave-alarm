import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider } from "react-router";
import { ApiError } from "../api";
import { ApiContext } from "../context";
import { createTestRouter } from "../routes";
import type { Overview, Zone } from "../types";
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
    await user.type(await screen.findByLabelText("Code"), "1234");
    await user.type(await screen.findByLabelText("Confirm code"), "1234");
    await user.click(screen.getByRole("button", { name: "Onboard" }));
    expect(call).toHaveBeenCalledWith("user/create", { name: "Sam", role: "member", ha_person_id: "person.sam", code: "1234", confirm_code: "1234" });
  });

  it("disables Onboard and Set code for a malformed code", async () => {
    const sam = setup("/people/person.sam");
    await sam.user.type(await screen.findByLabelText("Code"), "12");
    expect(screen.getByRole("button", { name: "Onboard" })).toBeDisabled();
    document.body.replaceChildren();
    const alex = setup("/people/person.alex");
    await alex.user.type(await screen.findByLabelText("Code"), "12");
    expect(screen.getByRole("button", { name: "Replace code" })).toBeDisabled();
    await alex.user.clear(screen.getByLabelText("Code"));
    await alex.user.type(screen.getByLabelText("Code"), "12345"); // five digits is too many for a person
    await alex.user.type(screen.getByLabelText("Confirm code"), "12345");
    expect(screen.getByRole("button", { name: "Replace code" })).toBeDisabled();
  });

  it("sets a code, then clears the field and never shows the code", async () => {
    const { call, user } = setup("/people/person.alex");
    const input = (await screen.findByLabelText("Code")) as HTMLInputElement;
    expect(input.type).toBe("password");
    await user.type(input, "6543");
    await user.type(screen.getByLabelText("Confirm code"), "6543");
    await user.click(screen.getByRole("button", { name: "Replace code" }));
    expect(call).toHaveBeenCalledWith("user/set_code", { user_id: "u1", code: "6543", confirm_code: "6543" });
    await waitFor(() => expect(input.value).toBe(""));
    expect((screen.getByLabelText("Confirm code") as HTMLInputElement).value).toBe("");
    expect(document.body.textContent).not.toContain("6543");
  });

  it("keeps the typed code and shows code_in_use on conflict", async () => {
    const { user } = setup("/people/person.alex", { "user/set_code": "code_in_use" });
    const input = (await screen.findByLabelText("Code")) as HTMLInputElement;
    await user.type(input, "6543");
    await user.type(screen.getByLabelText("Confirm code"), "6543");
    await user.click(screen.getByRole("button", { name: "Replace code" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Another person already uses this code/);
    expect(input.value).toBe("6543");
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

describe("duress code and installers", () => {
  const admin = { ...OVERVIEW, users: [{ id: "u1", name: "Alex", role: "administrator" as const, hasCode: true, hasDuressCode: false, haPersonId: "person.alex", haUserId: null }] };

  it("only offers a duress code to an administrator who can have one", async () => {
    setup("/people/person.alex"); // OVERVIEW's Alex is a member
    await screen.findByLabelText("Code");
    expect(screen.queryByLabelText("Duress code")).not.toBeInTheDocument();
  });

  it("sets a duress code with its confirmation and clears the fields", async () => {
    const { call, user } = setup("/people/person.alex", {}, admin);
    const input = (await screen.findByLabelText("Duress code")) as HTMLInputElement;
    await user.type(input, "2468");
    expect(screen.getByRole("button", { name: "Set duress code" })).toBeDisabled(); // not confirmed yet
    await user.type(screen.getByLabelText("Confirm duress code"), "2468");
    await user.click(screen.getByRole("button", { name: "Set duress code" }));
    expect(call).toHaveBeenCalledWith("user/set_duress_code", { user_id: "u1", code: "2468", confirm_code: "2468" });
    await waitFor(() => expect(input.value).toBe(""));
    expect(document.body.textContent).not.toContain("2468");
  });

  it("clears an existing duress code after confirming", async () => {
    const withDuress = { ...admin, users: [{ ...admin.users[0]!, hasDuressCode: true }] };
    const { call, user } = setup("/people/person.alex", {}, withDuress);
    await user.click(await screen.findByRole("button", { name: "Clear duress code" }));
    await user.click(confirmDialog().getByRole("button", { name: "Clear duress code" }));
    expect(call).toHaveBeenCalledWith("user/clear_duress_code", { user_id: "u1" });
  });

  it("shows the duress code in the list and an installer's access expiry", async () => {
    const listed = { ...admin, users: [{ id: "u2", name: "Pat", role: "installer" as const, hasCode: true, hasDuressCode: false, guestExpiresAt: 1700172800000, haPersonId: null, haUserId: null }, { id: "u3", name: "Root", role: "administrator" as const, hasCode: true, hasDuressCode: true, haPersonId: null, haUserId: null }] };
    setup("/people", {}, listed);
    expect(await screen.findByText(/installer · code set · Access ends/)).toBeInTheDocument();
    expect(screen.getByText(/administrator · code set · duress code set/)).toBeInTheDocument();
  });

  it("onboards an installer and says it lasts 48 hours", async () => {
    const { call, user } = setup("/people/person.sam");
    await user.selectOptions(await screen.findByLabelText("Role"), "installer");
    expect(screen.getByText(/48 hours/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Onboard" }));
    expect(call).toHaveBeenCalledWith("user/create", { name: "Sam", role: "installer", ha_person_id: "person.sam" });
  });

  it("explains a full code list", async () => {
    const { user } = setup("/people/person.alex", { "user/set_code": "code_limit" });
    await user.type(await screen.findByLabelText("Code"), "6543");
    await user.type(screen.getByLabelText("Confirm code"), "6543");
    await user.click(screen.getByRole("button", { name: "Replace code" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/most codes it allows/);
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

describe("arming", () => {
  const disarmed = { ...OVERVIEW, panel: { state: "disarmed" as const, armed_mode: null, pending_delay_ends_at: null } };
  const faulted = { sensorId: "s1", name: "Front door", zoneId: "z1", reason: "open" };

  it("arms straight away when nothing is faulted", async () => {
    const { call, user } = setup("/", {}, disarmed, { arm: { needs_bypass: [] } });
    await user.click(await screen.findByRole("button", { name: "Arm away" }));
    expect(call).toHaveBeenCalledWith("arm", { mode: "armed_away" });
  });

  it("lists faulted sensors and arms again with them bypassed once confirmed", async () => {
    const { call, user } = setup("/", {}, disarmed, { arm: { needs_bypass: [faulted] } });
    await user.click(await screen.findByRole("button", { name: "Arm home" }));
    expect(await screen.findByText(/Front door \(open\)/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Bypass and arm" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("arm", { mode: "armed_home", bypass: ["s1"] }));
  });

  it("does not arm when the person declines the bypass", async () => {
    const { call, user } = setup("/", {}, disarmed, { arm: { needs_bypass: [faulted] } });
    await user.click(await screen.findByRole("button", { name: "Arm home" }));
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(call).not.toHaveBeenCalledWith("arm", expect.objectContaining({ bypass: expect.anything() }));
  });

  it("offers no arm buttons while armed", async () => {
    setup("/");
    await screen.findByText("Armed away");
    expect(screen.queryByRole("button", { name: "Arm home" })).not.toBeInTheDocument();
  });
});

describe("alarm events", () => {
  const event = { id: "e1", type: "BURGLARY", service: null, triggerDeviceId: "s1", startedAt: 1, sirenState: "sounding", dispatchState: "held" } as const;

  it("lists open events and silences a sounding siren", async () => {
    const { call, user } = setup("/", {}, { ...OVERVIEW, alarm_events: [event] }, { silence: { silenced: [] } });
    expect(await screen.findByText("Burglary")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Silence siren" }));
    expect(call).toHaveBeenCalledWith("silence");
  });

  it("offers no silence button once the siren is silenced", async () => {
    setup("/", {}, { ...OVERVIEW, alarm_events: [{ ...event, sirenState: "silenced" }] });
    await screen.findByText("Burglary");
    expect(screen.queryByRole("button", { name: "Silence siren" })).not.toBeInTheDocument();
  });

  it("asks before raising a panic alarm and sends nothing when declined", async () => {
    const { call, user } = setup("/");
    await user.click(await screen.findByRole("button", { name: "Fire" }));
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(call).not.toHaveBeenCalledWith("panic", expect.anything());
  });

  it("raises the alarm once confirmed", async () => {
    const { call, user } = setup("/");
    await user.click(await screen.findByRole("button", { name: "Medical" }));
    await user.click(await screen.findByRole("button", { name: "Raise medical alarm" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("panic", { kind: "MEDICAL" }));
  });
});

describe("sirens and tamper", () => {
  const siren = { nodeId: 14, kind: "OUTDOOR", name: "Garden siren", durationSec: 180, createdAt: 1 } as const;

  it("lists the enrolled sirens with their duration", async () => {
    setup("/", {}, { ...OVERVIEW, sirens: [siren] });
    expect(await screen.findByText("Garden siren")).toBeInTheDocument();
    expect(screen.getByText(/Outdoor · node 14 · sounds 180 s/)).toBeInTheDocument();
  });

  it("shows no siren section when none is enrolled", async () => {
    setup("/");
    await screen.findByText("Armed away");
    expect(screen.queryByText("Sirens")).not.toBeInTheDocument();
  });

  it("removes a siren once confirmed", async () => {
    const { call, user } = setup("/", {}, { ...OVERVIEW, sirens: [siren] });
    await user.click(await screen.findByRole("button", { name: "Remove" }));
    await user.click(await within(await screen.findByRole("alertdialog")).findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("siren/delete", { node_id: 14 }));
  });

  it("shows a tampered sensor on its sheet", async () => {
    const [downstairs, upstairs] = OVERVIEW.zones as [Zone, Zone];
    const tampered: Overview = { ...OVERVIEW, zones: [{ ...downstairs, sensors: downstairs.sensors.map((x) => ({ ...x, tampered: true })) }, upstairs] };
    setup("/sensors/s1", {}, tampered);
    expect(await screen.findByText("tampered")).toBeInTheDocument();
  });
});

describe("guest schedules", () => {
  const guest = { ...OVERVIEW, users: [{ id: "g1", name: "Alex", role: "guest" as const, hasCode: true, haPersonId: "person.alex", haUserId: null }] };
  const cleaners = { id: "sch1", userId: "g1", name: "Cleaners", days: ["mon", "thu"], allDay: false, start: "08:00", end: "17:30", timeZone: "America/Chicago" };

  it("offers schedules only to a guest", async () => {
    setup("/people/person.alex"); // a member
    await screen.findByLabelText("Code");
    expect(screen.queryByText("Keypad schedule")).not.toBeInTheDocument();
  });

  it("lists a guest's schedules, or says there is unlimited access", async () => {
    setup("/people/person.alex", {}, guest, { "guest_schedule/list": [cleaners] });
    expect(await screen.findByText("Cleaners")).toBeInTheDocument();
    expect(screen.getByText("Mon, Thu · 08:00–17:30")).toBeInTheDocument();
    document.body.replaceChildren();
    setup("/people/person.alex", {}, guest, { "guest_schedule/list": [] });
    expect(await screen.findByText(/code works at any time/)).toBeInTheDocument();
  });

  it("adds a timed schedule with the days picked", async () => {
    const { call, user } = setup("/people/person.alex", {}, guest, { "guest_schedule/list": [] });
    await user.type(await screen.findByLabelText("Schedule name"), "Cleaners");
    expect(screen.getByRole("button", { name: "Add schedule" })).toBeDisabled(); // no day yet
    await user.click(screen.getByRole("button", { name: "Mon" }));
    await user.click(screen.getByRole("button", { name: "Thu" }));
    await user.click(screen.getByRole("button", { name: "Add schedule" }));
    expect(call).toHaveBeenCalledWith("guest_schedule/create", { user_id: "g1", name: "Cleaners", days: ["mon", "thu"], all_day: false, start: "08:00", end: "17:00" });
  });

  it("sends no times for an all-day schedule", async () => {
    const { call, user } = setup("/people/person.alex", {}, guest, { "guest_schedule/list": [] });
    await user.type(await screen.findByLabelText("Schedule name"), "Weekend");
    await user.click(screen.getByRole("button", { name: "Sat" }));
    await user.click(screen.getByRole("switch", { name: "All day" }));
    expect(screen.queryByLabelText("From")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add schedule" }));
    expect(call).toHaveBeenCalledWith("guest_schedule/create", { user_id: "g1", name: "Weekend", days: ["sat"], all_day: true });
  });

  it("will not add a schedule whose start and end are the same", async () => {
    const { user } = setup("/people/person.alex", {}, guest, { "guest_schedule/list": [] });
    await user.type(await screen.findByLabelText("Schedule name"), "x");
    await user.click(screen.getByRole("button", { name: "Mon" }));
    await user.clear(screen.getByLabelText("Until"));
    await user.type(screen.getByLabelText("Until"), "08:00");
    expect(screen.getByRole("button", { name: "Add schedule" })).toBeDisabled();
    expect(screen.getByText(/must differ/)).toBeInTheDocument();
  });

  it("removes a schedule once confirmed", async () => {
    const { call, user } = setup("/people/person.alex", {}, guest, { "guest_schedule/list": [cleaners] });
    await screen.findByText("Cleaners");
    await user.click(within(screen.getByRole("list", { name: "Schedules" })).getByRole("button", { name: "Remove" }));
    await user.click(confirmDialog().getByRole("button", { name: "Remove schedule" }));
    expect(call).toHaveBeenCalledWith("guest_schedule/delete", { user_id: "g1", schedule_id: "sch1" });
  });

  it("shows the service's refusal", async () => {
    const { user } = setup("/people/person.alex", { "guest_schedule/create": "invalid_request" }, guest, { "guest_schedule/list": [] });
    await user.type(await screen.findByLabelText("Schedule name"), "x");
    await user.click(screen.getByRole("button", { name: "Mon" }));
    await user.click(screen.getByRole("button", { name: "Add schedule" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/rejected the request/);
  });
});

describe("history", () => {
  const ev = (n: number, extra = {}) => ({ id: `e${n}`, type: "tamper", source: "system", sourceUserId: null, details: "Cover removed", occurredAt: 1700000000000 + n, actor: null, deviceId: "s1", deviceName: "Front door", ...extra });

  it("lists events with the device, who did it and the details", async () => {
    setup("/history", {}, OVERVIEW, { events: [ev(1), ev(2, { id: "e2", type: "code_changed", actor: "Alex", details: "Alex's code", deviceId: null, deviceName: null })] });
    expect(await screen.findByText("tamper")).toBeInTheDocument();
    expect(screen.getByText(/Front door · Cover removed/)).toBeInTheDocument();
    expect(screen.getByText(/by Alex · Alex's code/)).toBeInTheDocument();
  });

  it("asks for the first page, then filters by kind and device", async () => {
    const { call, user } = setup("/history", {}, OVERVIEW, { events: [ev(1)] });
    await screen.findByText("tamper");
    expect(call).toHaveBeenCalledWith("events", { limit: 50 });
    await user.selectOptions(screen.getByLabelText("Kind"), "Codes");
    await waitFor(() => expect(call).toHaveBeenCalledWith("events", expect.objectContaining({ event_type: expect.arrayContaining(["code_added", "duress_code_set"]) })));
    await user.selectOptions(screen.getByLabelText("Device"), "Front door");
    await waitFor(() => expect(call).toHaveBeenCalledWith("events", expect.objectContaining({ device_id: "s1" })));
  });

  it("pages older events with the id of the oldest one shown", async () => {
    const full = Array.from({ length: 50 }, (_, i) => ev(i, { id: `e${i}` }));
    const { call, user } = setup("/history", {}, OVERVIEW, { events: full });
    await user.click(await screen.findByRole("button", { name: "Load older" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("events", { limit: 50, before: "e49" }));
  });

  it("offers no older page when the first one is short", async () => {
    setup("/history", {}, OVERVIEW, { events: [ev(1)] });
    await screen.findByText("tamper");
    expect(screen.queryByRole("button", { name: "Load older" })).not.toBeInTheDocument();
  });

  it("says when nothing matches, and shows a load failure", async () => {
    setup("/history", {}, OVERVIEW, { events: [] });
    expect(await screen.findByText("Nothing here")).toBeInTheDocument();
    document.body.replaceChildren();
    setup("/history", { events: "cannot_connect" });
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});

describe("mode schedules", () => {
  const night = { id: "m1", name: "Night", mode: "armed_home" as const, time: "22:00", days: ["mon", "tue"] as const, enabled: true, timeZone: "America/Chicago", lastRunAt: null };
  const withNight = { ...OVERVIEW, mode_schedules: [{ ...night, days: [...night.days] }] };

  it("lists schedules with mode, time, days and zone", async () => {
    setup("/schedules", {}, withNight);
    expect(await screen.findByText("Night")).toBeInTheDocument();
    expect(screen.getByText("Arm home at 22:00 · Mon, Tue · America/Chicago")).toBeInTheDocument();
  });

  it("explains an older service without mode schedules", async () => {
    setup("/schedules");
    expect(await screen.findByText(/3\.6\.0/)).toBeInTheDocument();
  });

  it("turns a schedule off", async () => {
    const { call, user } = setup("/schedules", {}, withNight);
    await user.click(await screen.findByRole("switch", { name: "Night enabled" }));
    expect(call).toHaveBeenCalledWith("mode_schedule/update", { schedule_id: "m1", enabled: false });
  });

  it("adds a schedule once it has a name and a day", async () => {
    const { call, user } = setup("/schedules", {}, { ...OVERVIEW, mode_schedules: [] });
    expect(await screen.findByRole("button", { name: "Add schedule" })).toBeDisabled();
    await user.type(screen.getByLabelText("Schedule name"), "Morning");
    await user.selectOptions(screen.getByLabelText("Mode"), "Disarm");
    await user.click(screen.getByRole("button", { name: "Mon" }));
    await user.click(screen.getByRole("button", { name: "Add schedule" }));
    expect(call).toHaveBeenCalledWith("mode_schedule/create", { name: "Morning", mode: "disarmed", time: "22:00", days: ["mon"] });
  });

  it("explains a clashing schedule", async () => {
    const { user } = setup("/schedules", { "mode_schedule/create": "schedule_conflict" }, { ...OVERVIEW, mode_schedules: [] });
    await user.type(await screen.findByLabelText("Schedule name"), "x");
    await user.click(screen.getByRole("button", { name: "Tue" }));
    await user.click(screen.getByRole("button", { name: "Add schedule" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/same time/);
  });

  it("removes a schedule once confirmed", async () => {
    const { call, user } = setup("/schedules", {}, withNight);
    await user.click(await screen.findByRole("button", { name: "Remove" }));
    await user.click(confirmDialog().getByRole("button", { name: "Remove schedule" }));
    expect(call).toHaveBeenCalledWith("mode_schedule/delete", { schedule_id: "m1" });
  });
});
