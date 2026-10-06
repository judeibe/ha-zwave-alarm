import { useState } from "react";
import { useApi } from "../context";
import { Card, ErrorBanner } from "../components";
import { useOverview } from "../Layout";
import type { Category, DiscoverableSensor, Zone } from "../types";
import { useAction } from "../useAction";

function ZoneSelect({ zones, value, onChange, label }: { zones: Zone[]; value: string; onChange: (v: string) => void; label: string }) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
      {zones.map((z) => (
        <option key={z.id} value={z.id}>
          {z.name}
        </option>
      ))}
    </select>
  );
}

function DiscoveredRow({ d, zones, onAdd }: { d: DiscoverableSensor; zones: Zone[]; onAdd: (p: Record<string, unknown>) => void }) {
  const [name, setName] = useState(d.name || `Node ${d.zwaveNodeId}`);
  const [category, setCategory] = useState<Category>("intrusion");
  const [zoneId, setZoneId] = useState(zones[0]?.id ?? "");
  return (
    <Card>
      <div>
        Node {d.zwaveNodeId} — {[d.manufacturer, d.product].filter(Boolean).join(" ") || "unknown device"}
      </div>
      <div className="za-muted">Status: {d.status}</div>
      <div className="za-row">
        <input aria-label="Sensor name" value={name} onChange={(e) => setName(e.target.value)} />
        <select aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value as Category)}>
          <option value="intrusion">Intrusion</option>
          <option value="life-safety">Life safety</option>
        </select>
        <ZoneSelect zones={zones} value={zoneId} onChange={setZoneId} label="Zone" />
        <button
          className="za-act"
          disabled={!zones.length || !name.trim()}
          onClick={() => onAdd({ zone_id: zoneId, zwave_node_id: d.zwaveNodeId, name: name.trim(), category })}
        >
          Add sensor
        </button>
      </div>
    </Card>
  );
}

function AssignedRow({ zone, sensor, zones, run }: { zone: Zone; sensor: Zone["sensors"][number]; zones: Zone[]; run: ReturnType<typeof useAction>["run"] }) {
  const api = useApi();
  const [zoneId, setZoneId] = useState(zone.id);
  return (
    <Card>
      <div>
        {sensor.name} <span className="za-muted">— {sensor.category}, {sensor.currentState}</span>
      </div>
      <div className="za-row">
        <ZoneSelect zones={zones} value={zoneId} onChange={setZoneId} label={`Zone for ${sensor.name}`} />
        <button className="za-act" onClick={() => run(() => api.call("sensor/update", { sensor_id: sensor.id, zone_id: zoneId }))}>
          Move
        </button>
        <button className="za-act danger" onClick={() => run(() => api.call("sensor/unassign", { sensor_id: sensor.id }))}>
          Unassign
        </button>
      </div>
    </Card>
  );
}

export function SensorsPage() {
  const api = useApi();
  const { zones, discoverable } = useOverview();
  const { run, error } = useAction();
  return (
    <section>
      <ErrorBanner message={error} />
      <h2>Discovered Z-Wave devices</h2>
      {!zones.length && <p className="za-muted">Create a zone first (Zones tab), then assign devices to it.</p>}
      {!discoverable.length && <p className="za-muted">No unassigned Z-Wave devices found. Include a device in Z-Wave JS, then reload.</p>}
      {discoverable.map((d) => (
        <DiscoveredRow key={d.zwaveNodeId} d={d} zones={zones} onAdd={(p) => run(() => api.call("sensor/assign", p))} />
      ))}
      <h2>Assigned sensors</h2>
      {zones.flatMap((z) => z.sensors.map((s) => <AssignedRow key={s.id} zone={z} sensor={s} zones={zones} run={run} />))}
    </section>
  );
}
