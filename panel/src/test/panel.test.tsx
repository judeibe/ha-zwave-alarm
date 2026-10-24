import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider } from "react-router";
import { ApiError } from "../api";
import { ApiContext } from "../context";
import { createTestRouter } from "../routes";
import type { Overview } from "../types";
import { fakeApi, OVERVIEW } from "./fixtures";

function setup(path = "/", fail: Record<string, string> = {}, overview: Overview = OVERVIEW) {
  const { api, call } = fakeApi(overview, fail);
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
