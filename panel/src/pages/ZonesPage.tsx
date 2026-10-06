import { useState } from "react";
import { Card, ErrorBanner } from "../components";
import { useApi } from "../context";
import { useOverview } from "../Layout";
import type { Zone } from "../types";
import { useAction } from "../useAction";

function ZoneCard({ zone, run }: { zone: Zone; run: ReturnType<typeof useAction>["run"] }) {
  const api = useApi();
  const [name, setName] = useState(zone.name);
  const [description, setDescription] = useState(zone.description ?? "");
  return (
    <Card>
      <div className="za-row">
        <input aria-label="Zone name" value={name} onChange={(e) => setName(e.target.value)} />
        <input aria-label="Zone description" placeholder="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
        <button
          className="za-act"
          disabled={!name.trim()}
          onClick={() => run(() => api.call("zone/update", { zone_id: zone.id, name: name.trim(), description: description.trim() || null }))}
        >
          Save
        </button>
        <button
          className="za-act danger"
          onClick={() => window.confirm(`Delete zone "${zone.name}"?`) && run(() => api.call("zone/delete", { zone_id: zone.id }))}
        >
          Delete
        </button>
        <button
          className="za-act danger"
          onClick={() =>
            window.confirm(`Delete "${zone.name}" and unassign its ${zone.sensors.length} sensor(s)?`) &&
            run(() => api.call("zone/delete", { zone_id: zone.id, force: true }))
          }
        >
          Force delete
        </button>
      </div>
      <div className="za-muted">{zone.sensors.length ? `Sensors: ${zone.sensors.map((s) => s.name).join(", ")}` : "No sensors"}</div>
    </Card>
  );
}

export function ZonesPage() {
  const api = useApi();
  const { zones } = useOverview();
  const { run, error } = useAction();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  return (
    <section>
      <ErrorBanner message={error} />
      <Card>
        <div className="za-row">
          <input aria-label="New zone name" placeholder="Zone name" value={name} onChange={(e) => setName(e.target.value)} />
          <input aria-label="New zone description" placeholder="Description (optional)" value={description} onChange={(e) => setDescription(e.target.value)} />
          <button
            className="za-act"
            disabled={!name.trim()}
            onClick={async () => {
              const payload = { name: name.trim(), ...(description.trim() && { description: description.trim() }) };
              if (await run(() => api.call("zone/create", payload))) {
                setName("");
                setDescription("");
              }
            }}
          >
            Create zone
          </button>
        </div>
      </Card>
      {zones.map((z) => (
        <ZoneCard key={z.id} zone={z} run={run} />
      ))}
    </section>
  );
}
