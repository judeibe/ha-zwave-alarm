/* Z-Wave Alarm configuration panel: sensors, zones, people and codes.
 * Plain web component (no build step). All text is inserted via textContent, never innerHTML.
 * Alarm codes are typed into a password field, sent once, and never read back: the service only reports `hasCode`.
 */
const ERRORS = {
  zone_not_empty: "The zone still has sensors or a guest assigned. Use 'Force delete' to unassign its sensors.",
  zone_in_use: "A guest is restricted to this zone. Change or remove that guest first; forcing does not help.",
  code_in_use: "Another person already uses this code. Choose a different one.",
  conflict: "That conflicts with the current configuration (for example the last administrator).",
  not_found: "That item no longer exists. The list has been refreshed.",
  invalid_request: "The service rejected the request as invalid.",
  cannot_connect: "Cannot reach the Z-Wave Alarm service.",
  invalid_auth: "The service rejected the stored token. Re-authenticate the integration.",
  forbidden: "The service denied this action.",
};
const TABS = [["sensors", "Sensors"], ["zones", "Zones"], ["people", "People"]];

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== false) el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null) el.append(c.nodeType ? c : document.createTextNode(c));
  return el;
}

class ZwaveAlarmPanel extends HTMLElement {
  constructor() {
    super();
    this._tab = "sensors";
    this._data = null;
    this._error = "";
    this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._load();
  }

  async _call(type, payload = {}) {
    try {
      const result = await this._hass.connection.sendMessagePromise({ type: `zwave_alarm/${type}`, ...payload });
      this._error = "";
      return result;
    } catch (err) {
      this._error = ERRORS[err.code] || err.message || "Unexpected error";
      throw err;
    } finally {
      if (this._error) this._render();
    }
  }

  async _load() {
    try {
      this._data = await this._call("overview");
    } catch (_) { /* error shown by _call */ }
    this._render();
  }

  async _do(type, payload) {
    let failure = "";
    try {
      await this._call(type, payload);
    } catch (_) { failure = this._error; }
    await this._load(); // also restores the true state after e.g. a not_found
    if (failure) { this._error = failure; this._render(); }
  }

  _render() {
    const root = this.shadowRoot;
    root.replaceChildren(
      h("style", {}, `
        :host { display:block; padding:16px; font-family:var(--paper-font-body1_-_font-family, sans-serif); color:var(--primary-text-color); background:var(--primary-background-color); min-height:100vh; box-sizing:border-box; }
        h1 { margin:0 0 12px; font-size:22px; } h2 { font-size:16px; margin:16px 0 8px; }
        nav button { background:none; border:0; padding:8px 14px; cursor:pointer; color:inherit; border-bottom:2px solid transparent; font-size:14px; }
        nav button.active { border-color:var(--primary-color); color:var(--primary-color); }
        .card { background:var(--card-background-color); border-radius:8px; padding:12px 16px; margin:8px 0; box-shadow:var(--ha-card-box-shadow, 0 1px 3px #0003); }
        .row { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:4px 0; }
        .muted { color:var(--secondary-text-color); font-size:13px; }
        .error { background:var(--error-color); color:#fff; padding:8px 12px; border-radius:6px; margin:8px 0; }
        input, select { padding:6px; border-radius:4px; border:1px solid var(--divider-color); background:var(--card-background-color); color:inherit; }
        button.act { padding:6px 12px; border-radius:4px; border:0; cursor:pointer; background:var(--primary-color); color:var(--text-primary-color, #fff); }
        button.danger { background:var(--error-color); }
      `),
      h("h1", {}, "Z-Wave Alarm"),
      h("nav", {}, TABS.map(([id, label]) =>
        h("button", { class: id === this._tab ? "active" : "", onclick: () => { this._tab = id; this._render(); } }, label))),
      this._error ? h("div", { class: "error", role: "alert" }, this._error) : null,
      this._data ? this[`_${this._tab}`]() : h("p", { class: "muted" }, "Loading…"),
    );
  }

  _zoneSelect(selected) {
    return h("select", {}, this._data.zones.map((z) => h("option", { value: z.id, selected: z.id === selected }, z.name)));
  }

  _sensors() {
    const { zones, discoverable } = this._data;
    const out = [h("h2", {}, "Discovered Z-Wave devices")];
    if (!zones.length) out.push(h("p", { class: "muted" }, "Create a zone first (Zones tab), then assign devices to it."));
    if (!discoverable.length) out.push(h("p", { class: "muted" }, "No unassigned Z-Wave devices found. Include a device in Z-Wave JS, then reload."));
    for (const d of discoverable) {
      const name = h("input", { value: d.name || `Node ${d.zwaveNodeId}`, "aria-label": "Sensor name" });
      const category = h("select", { "aria-label": "Category" },
        h("option", { value: "intrusion" }, "Intrusion"), h("option", { value: "life-safety" }, "Life safety"));
      const zone = this._zoneSelect();
      out.push(h("div", { class: "card" },
        h("div", {}, `Node ${d.zwaveNodeId}`, ` — ${[d.manufacturer, d.product].filter(Boolean).join(" ") || "unknown device"}`),
        h("div", { class: "muted" }, `Status: ${d.status}`),
        h("div", { class: "row" }, name, category, zone,
          h("button", { class: "act", disabled: !zones.length, onclick: () => this._do("sensor/assign",
            { zone_id: zone.value, zwave_node_id: d.zwaveNodeId, name: name.value.trim(), category: category.value }) }, "Add sensor"))));
    }
    out.push(h("h2", {}, "Assigned sensors"));
    for (const z of zones) for (const s of z.sensors) {
      const zone = this._zoneSelect(z.id);
      out.push(h("div", { class: "card" },
        h("div", {}, s.name, h("span", { class: "muted" }, ` — ${s.category}, ${s.currentState}`)),
        h("div", { class: "row" }, zone,
          h("button", { class: "act", onclick: () => this._do("sensor/update", { sensor_id: s.id, zone_id: zone.value }) }, "Move"),
          h("button", { class: "act danger", onclick: () => this._do("sensor/unassign", { sensor_id: s.id }) }, "Unassign"))));
    }
    return h("section", {}, out);
  }

  _zones() {
    const name = h("input", { placeholder: "Zone name", "aria-label": "New zone name" });
    const desc = h("input", { placeholder: "Description (optional)", "aria-label": "New zone description" });
    const out = [h("div", { class: "card" }, h("div", { class: "row" }, name, desc,
      h("button", { class: "act", onclick: () => name.value.trim() && this._do("zone/create",
        { name: name.value.trim(), ...(desc.value.trim() && { description: desc.value.trim() }) }) }, "Create zone")))];
    for (const z of this._data.zones) {
      const n = h("input", { value: z.name, "aria-label": "Zone name" });
      const d = h("input", { value: z.description || "", placeholder: "Description", "aria-label": "Zone description" });
      out.push(h("div", { class: "card" },
        h("div", { class: "row" }, n, d,
          h("button", { class: "act", onclick: () => this._do("zone/update", { zone_id: z.id, name: n.value.trim(), description: d.value.trim() || null }) }, "Save"),
          h("button", { class: "act danger", onclick: () => confirm(`Delete zone "${z.name}"?`) && this._do("zone/delete", { zone_id: z.id }) }, "Delete"),
          h("button", { class: "act danger", onclick: () => confirm(`Delete "${z.name}" and unassign its ${z.sensors.length} sensor(s)?`) && this._do("zone/delete", { zone_id: z.id, force: true }) }, "Force delete")),
        h("div", { class: "muted" }, z.sensors.length ? `Sensors: ${z.sensors.map((s) => s.name).join(", ")}` : "No sensors")));
    }
    return h("section", {}, out);
  }

  _people() {
    const { users, ha_people: people } = this._data;
    const byPerson = new Map(users.filter((u) => u.haPersonId).map((u) => [u.haPersonId, u]));
    const out = [h("h2", {}, "Home Assistant people")];
    for (const p of people) {
      const user = byPerson.get(p.entity_id);
      const code = h("input", { type: "password", inputmode: "numeric", autocomplete: "off", pattern: "[0-9]{4,12}", placeholder: user?.hasCode ? "New code" : "Code (4–12 digits)", "aria-label": `Code for ${p.name}` });
      const role = h("select", { "aria-label": "Role" }, ["member", "administrator", "guest"].map((r) => h("option", { value: r }, r)));
      const withCode = () => (/^\d{4,12}$/.test(code.value) ? code.value : null);
      const card = [h("div", {}, p.name, h("span", { class: "muted" }, ` — ${p.entity_id}`))];
      if (!user) {
        card.push(h("div", { class: "row" }, role, code, h("button", { class: "act", onclick: () => this._do("user/create",
          { name: p.name, role: role.value, ha_person_id: p.entity_id, ...(p.user_id && { ha_user_id: p.user_id }), ...(withCode() && { code: withCode() }) }) }, "Onboard")));
      } else {
        card.push(h("div", { class: "muted" }, `Alarm user: ${user.role}, code ${user.hasCode ? "set" : "not set"}`));
        card.push(h("div", { class: "row" }, code,
          h("button", { class: "act", onclick: () => withCode() && this._do("user/set_code", { user_id: user.id, code: withCode() }) }, user.hasCode ? "Replace code" : "Set code"),
          user.hasCode && h("button", { class: "act danger", onclick: () => confirm(`Clear ${p.name}'s code?`) && this._do("user/clear_code", { user_id: user.id }) }, "Clear code"),
          h("button", { class: "act danger", onclick: () => confirm(`Remove ${p.name} from the alarm?`) && this._do("user/delete", { user_id: user.id }) }, "Remove")));
      }
      out.push(h("div", { class: "card" }, card));
    }
    const linked = new Set(people.map((p) => p.entity_id));
    const others = users.filter((u) => !u.haPersonId || !linked.has(u.haPersonId));
    if (others.length) {
      out.push(h("h2", {}, "Other alarm users"));
      for (const u of others) out.push(h("div", { class: "card" }, `${u.name} — ${u.role}, code ${u.hasCode ? "set" : "not set"}`));
    }
    return h("section", {}, out);
  }
}

customElements.define("zwave-alarm-panel", ZwaveAlarmPanel);
