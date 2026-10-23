import { useState } from "react";
import { ApiError } from "../api";
import { useApi } from "../context";
import { Actions, Button, Card, CardTitle, EmptyState, ErrorBanner, FIELD, Fields, Select, Hint, Pill, SectionTitle } from "../components";
import { useOverview } from "../Layout";
import type { Category, DiscoverableSensor, Sensor, Zone } from "../types";
import { useAction } from "../useAction";

/** Home Assistant's device name wins; the service's stored name is the fallback. */
const sensorName = (s: Sensor) => s.haName ?? s.name;

function ZoneSelect({ zones, value, onChange, label }: { zones: Zone[]; value: string; onChange: (v: string) => void; label: string }) {
  return (
    <Select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
      {zones.map((z) => (
        <option key={z.id} value={z.id}>
          {z.name}
        </option>
      ))}
    </Select>
  );
}

function DiscoveredRow({ d, zones, onAdd }: { d: DiscoverableSensor; zones: Zone[]; onAdd: (p: Record<string, unknown>) => void }) {
  const [name, setName] = useState(d.haName || d.name || `Node ${d.zwaveNodeId}`);
  const [category, setCategory] = useState<Category>("intrusion");
  const [zoneId, setZoneId] = useState(zones[0]?.id ?? "");
  return (
    <Card>
      <CardTitle meta={[d.manufacturer, d.product].filter(Boolean).join(" ") || "unknown device"}>Node {d.zwaveNodeId}</CardTitle>
      <div className="mt-1.5">
        <Pill tone={d.status === "alive" ? "ok" : "neutral"}>Status: {d.status}</Pill>
      </div>
      <Fields>
        <input className={`${FIELD} sm:col-span-2`} aria-label="Sensor name" value={name} onChange={(e) => setName(e.target.value)} />
        <Select aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value as Category)}>
          <option value="intrusion">Intrusion</option>
          <option value="life-safety">Life safety</option>
        </Select>
        <ZoneSelect zones={zones} value={zoneId} onChange={setZoneId} label="Zone" />
      </Fields>
      <Actions>
        <Button
          variant="primary"
          className="w-full sm:w-auto"
          disabled={!zones.length || !name.trim()}
          onClick={() => onAdd({ zone_id: zoneId, zwave_node_id: d.zwaveNodeId, name: name.trim(), category })}
        >
          Add sensor
        </Button>
      </Actions>
    </Card>
  );
}

function AssignedRow({ zone, sensor, zones, run }: { zone: Zone; sensor: Sensor; zones: Zone[]; run: ReturnType<typeof useAction>["run"] }) {
  const api = useApi();
  const [zoneId, setZoneId] = useState(zone.id);
  const name = sensorName(sensor);
  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <CardTitle meta={sensor.category}>{name}</CardTitle>
        <Pill tone={sensor.currentState === "breached" ? "alert" : "ok"}>{sensor.currentState}</Pill>
      </div>
      <Fields className="sm:grid-cols-[1fr_auto_auto]">
        <ZoneSelect zones={zones} value={zoneId} onChange={setZoneId} label={`Zone for ${name}`} />
        <Button onClick={() => run(() => api.call("sensor/update", { sensor_id: sensor.id, zone_id: zoneId }))}>Move</Button>
        <Button variant="danger" onClick={() => run(() => api.call("sensor/unassign", { sensor_id: sensor.id }))}>
          Unassign
        </Button>
      </Fields>
    </Card>
  );
}

export function SensorsPage() {
  const api = useApi();
  const { zones, discoverable, discoverable_error } = useOverview();
  const { run, error } = useAction();
  const assigned = zones.flatMap((z) => z.sensors.map((s) => ({ zone: z, sensor: s })));
  return (
    <section>
      <ErrorBanner message={error} />
      <SectionTitle>Discovered Z-Wave devices</SectionTitle>
      {!zones.length && <Hint>Create a zone first (Zones tab), then assign devices to it.</Hint>}
      {discoverable_error && <ErrorBanner message={new ApiError(discoverable_error.code, discoverable_error.message).message} />}
      {!discoverable.length && !discoverable_error && (
        <EmptyState title="No unassigned devices">No unassigned Z-Wave devices found. Include a device in Z-Wave JS, then reload.</EmptyState>
      )}
      {discoverable.map((d) => (
        <DiscoveredRow key={d.zwaveNodeId} d={d} zones={zones} onAdd={(p) => run(() => api.call("sensor/assign", p))} />
      ))}
      <SectionTitle>Assigned sensors</SectionTitle>
      {!assigned.length && <EmptyState title="No sensors yet">Add a discovered device to a zone and it will appear here.</EmptyState>}
      {assigned.map(({ zone, sensor }) => (
        <AssignedRow key={sensor.id} zone={zone} sensor={sensor} zones={zones} run={run} />
      ))}
    </section>
  );
}
