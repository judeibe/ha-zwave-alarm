import { StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { RouterProvider } from "react-router";
import { Api } from "./api";
import { ApiContext, NarrowContext } from "./context";
import { createPanelRouter } from "./routes";
import css from "./styles.css?inline";
import type { Hass, PanelRoute } from "./types";

const DEFAULT_PREFIX = "/zwave-alarm";

/** The custom element HA mounts (`panel_custom`); it sets `hass`, `narrow`, `route` and `panel` on it. */
export class ZwaveAlarmPanel extends HTMLElement {
  private _hass?: Hass;
  private _route?: PanelRoute;
  private _root?: Root;
  private _router?: ReturnType<typeof createPanelRouter>;
  private _narrow = false;
  private readonly _api = new Api(() => this._hass as Hass);

  set hass(hass: Hass) {
    this._hass = hass; // set on every state change; only the first one mounts
    queueMicrotask(() => this._mount()); // let HA finish setting `route` / `panel` first
  }
  set route(route: PanelRoute) {
    this._route = route;
  }
  set narrow(narrow: boolean) {
    const changed = narrow !== this._narrow;
    this._narrow = narrow;
    if (changed) this._render();
  }
  set panel(_: unknown) {}

  connectedCallback(): void {
    this._mount(); // re-attached after a disconnect: HA doesn't necessarily set `hass` again
  }

  private _mount(): void {
    if (this._root || !this._hass || !this.isConnected) return;
    const style = document.createElement("style");
    style.textContent = css;
    const host = document.createElement("div");
    this.append(style, host);
    this._root = createRoot(host);
    // HA mounts us at /<url_path>; every in-panel URL is relative to route.prefix.
    this._router = createPanelRouter(this._api, this._route?.prefix ?? DEFAULT_PREFIX);
    this._render();
  }

  private _render(): void {
    if (!this._root || !this._router) return;
    this._root.render(
      <StrictMode>
        <ApiContext.Provider value={this._api}>
          <NarrowContext.Provider value={this._narrow}>
            <RouterProvider router={this._router} />
          </NarrowContext.Provider>
        </ApiContext.Provider>
      </StrictMode>,
    );
  }

  disconnectedCallback(): void {
    this._root?.unmount();
    this._root = undefined;
    this._router?.dispose();
    this._router = undefined;
    this.replaceChildren();
  }
}

if (!customElements.get("zwave-alarm-panel")) customElements.define("zwave-alarm-panel", ZwaveAlarmPanel);
