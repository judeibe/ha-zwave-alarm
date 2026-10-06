import { screen } from "@testing-library/react";
import "../main";
import type { ZwaveAlarmPanel } from "../main";
import type { Hass } from "../types";
import { OVERVIEW } from "./fixtures";

const hass = () => {
  const sendMessagePromise = vi.fn(async () => OVERVIEW);
  return { connection: { sendMessagePromise } as unknown as Hass["connection"], sendMessagePromise };
};

function mount(path: string, prefix = "/zwave-alarm") {
  window.history.pushState({}, "", path);
  const el = document.createElement("zwave-alarm-panel") as ZwaveAlarmPanel;
  el.route = { prefix, path: path.slice(prefix.length) };
  document.body.append(el);
  const h = hass();
  el.hass = { connection: h.connection };
  return { el, h };
}

afterEach(() => {
  document.body.replaceChildren();
});

describe("custom element contract", () => {
  it("renders the router under route.prefix and sends admin-only commands through hass.connection", async () => {
    const { h } = mount("/zwave-alarm/zones");
    expect(await screen.findByLabelText("New zone name")).toBeInTheDocument(); // deep link survives a (re)load
    expect(h.sendMessagePromise).toHaveBeenCalledWith({ type: "zwave_alarm/overview" });
  });

  it("redirects the bare prefix to /sensors", async () => {
    mount("/zwave-alarm");
    await screen.findByText("Discovered Z-Wave devices");
    expect(window.location.pathname).toBe("/zwave-alarm/sensors");
  });

  it("honours a different prefix", async () => {
    mount("/other/people", "/other");
    expect(await screen.findByText("Home Assistant people")).toBeInTheDocument();
  });

  it("ignores later hass updates (mounts once) and remounts when re-attached", async () => {
    const { el, h } = mount("/zwave-alarm/sensors");
    await screen.findByText("Discovered Z-Wave devices");
    el.hass = hass();
    expect(document.querySelectorAll("nav").length).toBe(1);
    el.remove();
    expect(el.childElementCount).toBe(0);
    document.body.append(el);
    expect(await screen.findByText("Discovered Z-Wave devices")).toBeInTheDocument();
    expect(h.sendMessagePromise).toHaveBeenCalled();
  });
});
