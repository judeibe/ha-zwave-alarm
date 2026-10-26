import { useState } from "react";
import { Outlet, useNavigate, useParams } from "react-router";
import { ApiError } from "../api";
import { Actions, Button, EmptyState, ErrorBanner, FIELD, Field, Hint, Pill, SectionTitle, Select, Switch } from "../components";
import { useApi } from "../context";
import { moveSensor, removeSensor, updateSensor } from "../patches";
import { useOverview } from "../overview";
import type { Category, ChirpTone, Placement } from "../types";
import { useConfirm } from "../ui/Confirm";
import { DetailRow, InsetList, ListRow } from "../ui/List";
import { Gone } from "../ui/Gone";
import { Sheet, useRemembered, useSheet } from "../ui/Sheet";
import { useAction } from "../useAction";

const LIST = "/sensors";

const PLACEMENTS: { value: Placement; label: string; hint: string }[] = [
  { value: "MAIN_DOOR", label: "Main door", hint: "Starts the entry delay." },
  { value: "ENTRYWAY", label: "Entryway", hint: "Motion that starts the entry delay." },
  { value: "SECONDARY_DOOR", label: "Secondary door", hint: "Alarms immediately." },
  { value: "WINDOW", label: "Window", hint: "Alarms immediately." },
  { value: "ROOM", label: "Room", hint: "Motion that alarms immediately." },
  { value: "GLASS_BREAK", label: "Glass break", hint: "Alarms immediately." },
];
const TONES: { value: ChirpTone; label: string }[] = [
  { value: "none", label: "None (silent)" }, { value: "double_beep", label: "Double beep" }, { value: "guitar", label: "Guitar" },
  { value: "wind_chimes", label: "Wind chimes" }, { value: "bing_bong", label: "Bing bong" }, { value: "doorbell", label: "Doorbell" },
];
const placementLabel = (p: Placement | null | undefined) => PLACEMENTS.find((x) => x.value === p)?.label;

function ZoneSelect({ label = "Zone", value, onChange }: { label?: string; value: string; onChange: (v: string) => void }) {
  const { zones } = useOverview();
  return (
    <Field label={label}>
      <Select value={value} onChange={(e) => onChange(e.target.value)}>
        {zones.map((z) => (
          <option key={z.id} value={z.id}>
            {z.name}
          </option>
        ))}
      </Select>
    </Field>
  );
}

export function SensorsPage() {
  const { zones, discoverable, discoverable_error } = useOverview();
  const assigned = zones.flatMap((z) => z.sensors.map((s) => ({ zone: z, sensor: s })));
  return (
    <section>
      <SectionTitle>Discovered Z-Wave devices</SectionTitle>
      {!zones.length && <Hint>Create a zone first (Zones tab), then assign devices to it.</Hint>}
      {discoverable_error && <ErrorBanner message={new ApiError(discoverable_error.code, discoverable_error.message).message} />}
      {!discoverable.length && !discoverable_error && (
        <EmptyState title="No unassigned devices">No unassigned Z-Wave devices found. Include a device in Z-Wave JS, then reload.</EmptyState>
      )}
      {discoverable.length > 0 && (
        <InsetList label="Discovered devices">
          {discoverable.map((d) => (
            <ListRow
              key={d.zwaveNodeId}
              to={`add/${d.zwaveNodeId}`}
              icon="plus"
              title={d.haName || d.name || `Node ${d.zwaveNodeId}`}
              subtitle={[d.manufacturer, d.product].filter(Boolean).join(" ") || "Unknown device"}
              trailing={<Pill tone={d.status === "alive" ? "ok" : "neutral"}>{d.status}</Pill>}
            />
          ))}
        </InsetList>
      )}
      <SectionTitle>Assigned sensors</SectionTitle>
      {!assigned.length && <EmptyState title="No sensors yet">Add a discovered device to a zone and it will appear here.</EmptyState>}
      {assigned.length > 0 && (
        <InsetList label="Assigned sensors">
          {assigned.map(({ zone, sensor }) => (
            <ListRow
              key={sensor.id}
              to={sensor.id}
              icon="sensors"
              title={sensor.haName ?? sensor.name}
              subtitle={[zone.name, sensor.category, placementLabel(sensor.placement)].filter(Boolean).join(" · ")}
              trailing={<Pill tone={sensor.currentState === "breached" ? "alert" : "ok"}>{sensor.currentState}</Pill>}
            />
          ))}
        </InsetList>
      )}
      <Outlet />
    </section>
  );
}

export function AddSensorSheet() {
  const navigate = useNavigate();
  const { nodeId } = useParams();
  const { discoverable } = useOverview();
  const device = useRemembered(discoverable.find((d) => String(d.zwaveNodeId) === nodeId));
  if (!device) return <Gone to={LIST} />;
  return (
    <Sheet title="Add sensor" onClosed={() => navigate(LIST)}>
      <AddSensorForm key={device.zwaveNodeId} device={device} />
    </Sheet>
  );
}

function AddSensorForm({ device }: { device: ReturnType<typeof useOverview>["discoverable"][number] }) {
  const api = useApi();
  const { zones } = useOverview();
  const { close } = useSheet();
  const { run, error } = useAction();
  const [name, setName] = useState(device.haName || device.name || `Node ${device.zwaveNodeId}`);
  const [category, setCategory] = useState<Category>("intrusion");
  const [zoneId, setZoneId] = useState(zones[0]?.id ?? "");
  const add = async () => {
    const ok = await run(() => api.call("sensor/assign", { zone_id: zoneId, zwave_node_id: device.zwaveNodeId, name: name.trim(), category }), { done: "Sensor added" });
    if (ok) close();
  };
  return (
    <div className="space-y-3 pt-2">
      <p className="px-1 text-[15px] text-zinc-500 dark:text-zinc-400">
        Node {device.zwaveNodeId} · {[device.manufacturer, device.product].filter(Boolean).join(" ") || "Unknown device"}
      </p>
      <ErrorBanner message={error} />
      <Field label="Sensor name">
        <input className={FIELD} value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Category">
        <Select value={category} onChange={(e) => setCategory(e.target.value as Category)}>
          <option value="intrusion">Intrusion</option>
          <option value="life-safety">Life safety</option>
        </Select>
      </Field>
      <ZoneSelect value={zoneId} onChange={setZoneId} />
      <Actions>
        <Button variant="primary" className="w-full" disabled={!zones.length || !name.trim()} onClick={add}>
          Add sensor
        </Button>
      </Actions>
    </div>
  );
}

export function SensorSheet() {
  const navigate = useNavigate();
  const { sensorId } = useParams();
  const { zones } = useOverview();
  const found = useRemembered(zones.flatMap((z) => z.sensors.map((s) => ({ zone: z, sensor: s }))).find(({ sensor }) => sensor.id === sensorId));
  if (!found) return <Gone to={LIST} />;
  return (
    <Sheet title={found.sensor.haName ?? found.sensor.name} onClosed={() => navigate(LIST)}>
      <SensorDetail zone={found.zone} sensor={found.sensor} />
    </Sheet>
  );
}

function SensorDetail({ zone, sensor }: { zone: { id: string; name: string }; sensor: ReturnType<typeof useOverview>["zones"][number]["sensors"][number] }) {
  const api = useApi();
  const confirm = useConfirm();
  const { close } = useSheet();
  const { run, error } = useAction();
  const [zoneId, setZoneId] = useState(zone.id);
  const name = sensor.haName ?? sensor.name;
  const move = () => run(() => api.call("sensor/update", { sensor_id: sensor.id, zone_id: zoneId }), { patch: moveSensor(sensor.id, zoneId), done: "Sensor moved" });
  const unassign = async () => {
    const ok = await confirm({ title: `Unassign ${name}?`, message: "It will no longer belong to a zone or trigger the alarm.", confirmLabel: "Unassign" });
    if (ok && (await run(() => api.call("sensor/unassign", { sensor_id: sensor.id }), { patch: removeSensor(sensor.id), done: "Sensor unassigned" }))) close();
  };
  return (
    <div className="space-y-3 pt-2">
      <ErrorBanner message={error} />
      <InsetList label="Details">
        <DetailRow label="State">
          <Pill tone={sensor.currentState === "breached" ? "alert" : "ok"}>{sensor.currentState}</Pill>
        </DetailRow>
        <DetailRow label="Category">{sensor.category}</DetailRow>
        {sensor.placement && <DetailRow label="Placement">{placementLabel(sensor.placement)}</DetailRow>}
        <DetailRow label="Z-Wave node">{sensor.zwaveNodeId}</DetailRow>
        {sensor.tampered != null && <DetailRow label="Tamper">{sensor.tampered ? <Pill tone="alert">tampered</Pill> : "OK"}</DetailRow>}
        {sensor.connectivityStatus && <DetailRow label="Connection">{sensor.connectivityStatus}</DetailRow>}
        {sensor.batteryLevel != null && <DetailRow label="Battery">{sensor.batteryLevel}%</DetailRow>}
      </InsetList>
      {sensor.placement && (
        <>
          <Field label="Placement">
            <Select
              value={sensor.placement}
              onChange={(e) => {
                const placement = e.target.value as Placement;
                // A new placement resets the armed flags to its defaults (motion: Away only); the reload shows them.
                run(() => api.call("sensor/update", { sensor_id: sensor.id, placement }), { patch: updateSensor(sensor.id, { placement }), done: "Placement saved" });
              }}
            >
              {PLACEMENTS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </Select>
          </Field>
          <Hint>{PLACEMENTS.find((p) => p.value === sensor.placement)?.hint}</Hint>
          {sensor.chirpTone != null && (
            <Field label="Chirp tone">
              <Select
                value={sensor.chirpTone}
                onChange={(e) => {
                  const chirpTone = e.target.value as ChirpTone;
                  run(() => api.call("sensor/update", { sensor_id: sensor.id, chirp_tone: chirpTone }), { patch: updateSensor(sensor.id, { chirpTone }), done: "Tone saved" });
                }}
              >
                {TONES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          <InsetList label="Armed in">
            {(["home", "away"] as const).map((mode) => {
              const key = mode === "home" ? "armedHome" : "armedAway";
              const label = mode === "home" ? "Armed in Home" : "Armed in Away";
              return (
                <li key={mode} className="flex min-h-14 items-center gap-3 px-4 py-2.5">
                  <span className="min-w-0 flex-1 text-[17px] leading-snug">{label}</span>
                  <Switch
                    checked={sensor[key] ?? true}
                    aria-label={label}
                    onChange={(next) => run(() => api.call("sensor/update", { sensor_id: sensor.id, armed: { [mode]: next } }), { patch: updateSensor(sensor.id, { [key]: next }), done: "Saved" })}
                  />
                </li>
              );
            })}
            <li className="flex min-h-14 items-center gap-3 px-4 py-2.5">
              <span className="min-w-0 flex-1 text-[17px] leading-snug">Alerts only (never alarms)</span>
              <Switch
                checked={sensor.alertsOnly ?? false}
                aria-label="Alerts only"
                onChange={(next) => run(() => api.call("sensor/update", { sensor_id: sensor.id, alerts_only: next }), { patch: updateSensor(sensor.id, { alertsOnly: next }), done: "Saved" })}
              />
            </li>
          </InsetList>
        </>
      )}
      <ZoneSelect value={zoneId} onChange={setZoneId} />
      <Actions>
        <Button variant="primary" disabled={zoneId === zone.id} onClick={move}>
          Move
        </Button>
        <Button variant="danger" onClick={unassign}>
          Unassign
        </Button>
      </Actions>
    </div>
  );
}
