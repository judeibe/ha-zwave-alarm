import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider } from "react-router";
import { ApiContext } from "../context";
import { createTestRouter } from "../routes";
import { fakeApi, OVERVIEW } from "./fixtures";

function setup(path = "/", fail: Record<string, string> = {}) {
  const { api, call } = fakeApi(OVERVIEW, fail);
  const router = createTestRouter(api, path);
  render(
    <ApiContext.Provider value={api}>
      <RouterProvider router={router} />
    </ApiContext.Provider>,
  );
  return { call, router, user: userEvent.setup() };
}

beforeEach(() => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("routing", () => {
  it("redirects / to the Sensors tab and navigates between tabs", async () => {
    const { router, user } = setup();
    expect(await screen.findByText("Discovered Z-Wave devices")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/sensors");
    await user.click(screen.getByRole("link", { name: "Zones" }));
    expect(await screen.findByLabelText("New zone name")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "People" }));
    expect(await screen.findByText("Home Assistant people")).toBeInTheDocument();
  });

  it.each([["/zones", "New zone name"], ["/people", "Code for Sam"]])("deep link %s renders its page", async (path, label) => {
    setup(path);
    expect(await screen.findByLabelText(label)).toBeInTheDocument();
  });

  it("sends unknown paths to Sensors", async () => {
    const { router } = setup("/nope");
    await screen.findByText("Discovered Z-Wave devices");
    expect(router.state.location.pathname).toBe("/sensors");
  });
});

describe("sensors", () => {
  it("adds a discovered node to the chosen zone", async () => {
    const { call, user } = setup("/sensors");
    await user.selectOptions(await screen.findByLabelText("Category"), "life-safety");
    await user.click(screen.getByRole("button", { name: "Add sensor" }));
    expect(call).toHaveBeenCalledWith("sensor/assign", { zone_id: "z1", zwave_node_id: 7, name: "Node 7", category: "life-safety" });
  });

  it("moves and unassigns an assigned sensor", async () => {
    const { call, user } = setup("/sensors");
    await user.selectOptions(await screen.findByLabelText("Zone for Front door"), "z2");
    await user.click(screen.getByRole("button", { name: "Move" }));
    expect(call).toHaveBeenCalledWith("sensor/update", { sensor_id: "s1", zone_id: "z2" });
    await user.click(screen.getByRole("button", { name: "Unassign" }));
    expect(call).toHaveBeenCalledWith("sensor/unassign", { sensor_id: "s1" });
  });
});

describe("zones", () => {
  it("creates a zone with a description", async () => {
    const { call, user } = setup("/zones");
    await user.type(await screen.findByLabelText("New zone name"), "Garage");
    await user.type(screen.getByLabelText("New zone description"), "Detached");
    await user.click(screen.getByRole("button", { name: "Create zone" }));
    expect(call).toHaveBeenCalledWith("zone/create", { name: "Garage", description: "Detached" });
  });

  it("force-deletes", async () => {
    const { call, user } = setup("/zones");
    await screen.findByDisplayValue("Downstairs");
    await user.click(screen.getAllByRole("button", { name: "Force delete" })[0]!);
    expect(call).toHaveBeenCalledWith("zone/delete", { zone_id: "z1", force: true });
  });

  it.each([
    ["zone_not_empty", /Use 'Force delete'/],
    ["zone_in_use", /forcing does not help/],
  ])("shows the %s message", async (code, text) => {
    const { user } = setup("/zones", { "zone/delete": code });
    await screen.findByDisplayValue("Downstairs");
    await user.click(screen.getAllByRole("button", { name: "Delete" })[0]!);
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });
});

describe("people and codes", () => {
  it("onboards a person without a code and omits the code key", async () => {
    const { call, user } = setup("/people");
    await user.click(await screen.findByRole("button", { name: "Onboard" }));
    const [, payload] = call.mock.calls.find(([c]) => c === "user/create")!;
    expect(payload).toEqual({ name: "Sam", role: "member", ha_person_id: "person.sam" });
    expect(payload).not.toHaveProperty("code");
  });

  it("links the HA user id and sends a code when one is typed", async () => {
    const { call, user } = setup("/people");
    // Alex is already onboarded, so make Sam the target and check the optional code path
    await user.type(await screen.findByLabelText("Code for Sam"), "123456");
    await user.click(screen.getByRole("button", { name: "Onboard" }));
    expect(call).toHaveBeenCalledWith("user/create", { name: "Sam", role: "member", ha_person_id: "person.sam", code: "123456" });
  });

  it("disables Onboard and Set code for a malformed code", async () => {
    const { user } = setup("/people");
    await user.type(await screen.findByLabelText("Code for Sam"), "12");
    expect(screen.getByRole("button", { name: "Onboard" })).toBeDisabled();
    const alexCard = screen.getByText(/person\.alex/).closest(".za-card") as HTMLElement;
    expect(within(alexCard).getByRole("button", { name: "Replace code" })).toBeDisabled();
  });

  it("sets a code, then clears the field and never shows the code", async () => {
    const { call, user } = setup("/people");
    const alexCard = (await screen.findByText(/person\.alex/)).closest(".za-card") as HTMLElement;
    const input = within(alexCard).getByLabelText("Code for Alex") as HTMLInputElement;
    expect(input.type).toBe("password");
    await user.type(input, "654321");
    await user.click(within(alexCard).getByRole("button", { name: "Replace code" }));
    expect(call).toHaveBeenCalledWith("user/set_code", { user_id: "u1", code: "654321" });
    await waitFor(() => expect(input.value).toBe(""));
    expect(document.body.textContent).not.toContain("654321");
  });

  it("keeps the typed code and shows code_in_use on conflict", async () => {
    const { user } = setup("/people", { "user/set_code": "code_in_use" });
    const alexCard = (await screen.findByText(/person\.alex/)).closest(".za-card") as HTMLElement;
    const input = within(alexCard).getByLabelText("Code for Alex") as HTMLInputElement;
    await user.type(input, "654321");
    await user.click(within(alexCard).getByRole("button", { name: "Replace code" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Another person already uses this code/);
    expect(input.value).toBe("654321");
  });

  it("clears a code and removes a user", async () => {
    const { call, user } = setup("/people");
    await user.click(await screen.findByRole("button", { name: "Clear code" }));
    expect(call).toHaveBeenCalledWith("user/clear_code", { user_id: "u1" });
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(call).toHaveBeenCalledWith("user/delete", { user_id: "u1" });
  });
});
