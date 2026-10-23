import { useState } from "react";
import { Actions, Button, Card, EmptyState, ErrorBanner, FIELD, Fields } from "../components";
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
      <Fields>
        <input className={FIELD} aria-label="Zone name" value={name} onChange={(e) => setName(e.target.value)} />
        <input className={FIELD} aria-label="Zone description" placeholder="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
      </Fields>
      <p className="mt-3 text-[15px] text-zinc-500 dark:text-zinc-400">
        {zone.sensors.length ? `Sensors: ${zone.sensors.map((s) => s.haName ?? s.name).join(", ")}` : "No sensors"}
      </p>
      <Actions>
        <Button
          variant="primary"
          disabled={!name.trim()}
          onClick={() => run(() => api.call("zone/update", { zone_id: zone.id, name: name.trim(), description: description.trim() || null }))}
        >
          Save
        </Button>
        <Button variant="danger" onClick={() => window.confirm(`Delete zone "${zone.name}"?`) && run(() => api.call("zone/delete", { zone_id: zone.id }))}>
          Delete
        </Button>
        <Button
          variant="danger"
          onClick={() =>
            window.confirm(`Delete "${zone.name}" and unassign its ${zone.sensors.length} sensor(s)?`) &&
            run(() => api.call("zone/delete", { zone_id: zone.id, force: true }))
          }
        >
          Force delete
        </Button>
      </Actions>
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
        <Fields>
          <input className={FIELD} aria-label="New zone name" placeholder="Zone name" value={name} onChange={(e) => setName(e.target.value)} />
          <input className={FIELD} aria-label="New zone description" placeholder="Description (optional)" value={description} onChange={(e) => setDescription(e.target.value)} />
        </Fields>
        <Actions>
          <Button
            variant="primary"
            className="w-full sm:w-auto"
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
          </Button>
        </Actions>
      </Card>
      {!zones.length && <EmptyState title="No zones yet">Name your first zone above, such as Downstairs or Garage.</EmptyState>}
      {zones.map((z) => (
        <ZoneCard key={z.id} zone={z} run={run} />
      ))}
    </section>
  );
}
