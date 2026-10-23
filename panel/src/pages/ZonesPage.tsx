import { useState } from "react";
import { Outlet, useNavigate, useParams } from "react-router";
import { Actions, Button, EmptyState, ErrorBanner, FIELD, Field, SectionTitle } from "../components";
import { useApi } from "../context";
import { useOverview } from "../overview";
import { removeZone, updateZone } from "../patches";
import type { Zone } from "../types";
import { useConfirm } from "../ui/Confirm";
import { Gone } from "../ui/Gone";
import { InsetList, ListRow } from "../ui/List";
import { Sheet, useRemembered, useSheet } from "../ui/Sheet";
import { useAction } from "../useAction";

const LIST = "/zones";
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export function ZonesPage() {
  const { zones } = useOverview();
  const navigate = useNavigate();
  return (
    <section>
      <div className="flex items-center justify-between">
        <SectionTitle>All zones</SectionTitle>
        <Button variant="primary" onClick={() => navigate("new")}>
          New zone
        </Button>
      </div>
      {!zones.length ? (
        <EmptyState title="No zones yet">Zones group sensors by area, such as Downstairs or Garage. Create your first one to get started.</EmptyState>
      ) : (
        <InsetList label="Zones">
          {zones.map((z) => (
            <ListRow key={z.id} to={z.id} icon="zones" title={z.name} subtitle={z.description || plural(z.sensors.length, "sensor")} trailing={<span className="text-[15px] text-zinc-400">{z.sensors.length}</span>} />
          ))}
        </InsetList>
      )}
      <Outlet />
    </section>
  );
}

export function NewZoneSheet() {
  const navigate = useNavigate();
  return (
    <Sheet title="New zone" onClosed={() => navigate(LIST)}>
      <NewZoneForm />
    </Sheet>
  );
}

function NewZoneForm() {
  const api = useApi();
  const { close } = useSheet();
  const { run, error } = useAction();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const create = async () => {
    const payload = { name: name.trim(), ...(description.trim() && { description: description.trim() }) };
    if (await run(() => api.call("zone/create", payload), { done: "Zone created" })) close();
  };
  return (
    <div className="space-y-3 pt-2">
      <ErrorBanner message={error} />
      <Field label="Zone name">
        <input className={FIELD} placeholder="Downstairs" value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Description (optional)">
        <input className={FIELD} placeholder="Ground floor" value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <Actions>
        <Button variant="primary" className="w-full" disabled={!name.trim()} onClick={create}>
          Create zone
        </Button>
      </Actions>
    </div>
  );
}

export function ZoneSheet() {
  const navigate = useNavigate();
  const { zoneId } = useParams();
  const { zones } = useOverview();
  const zone = useRemembered(zones.find((z) => z.id === zoneId));
  if (!zone) return <Gone to={LIST} />;
  return (
    <Sheet title={zone.name} onClosed={() => navigate(LIST)}>
      <ZoneForm key={zone.id} zone={zone} />
    </Sheet>
  );
}

function ZoneForm({ zone }: { zone: Zone }) {
  const api = useApi();
  const confirm = useConfirm();
  const { close } = useSheet();
  const { run, error } = useAction();
  const [name, setName] = useState(zone.name);
  const [description, setDescription] = useState(zone.description ?? "");
  const save = () => {
    const changes = { name: name.trim(), description: description.trim() || null };
    return run(() => api.call("zone/update", { zone_id: zone.id, ...changes }), { patch: updateZone(zone.id, changes), done: "Zone saved" });
  };
  const remove = async () => {
    const n = zone.sensors.length;
    const ok = await confirm({
      title: `Delete ${zone.name}?`,
      message: n ? `Its ${plural(n, "sensor")} will be unassigned.` : "This zone has no sensors.",
      confirmLabel: "Delete zone",
    });
    // A zone with sensors only deletes when forced, so one confirmed flow covers both cases.
    if (ok && (await run(() => api.call("zone/delete", { zone_id: zone.id, ...(n && { force: true }) }), { patch: removeZone(zone.id), done: "Zone deleted" }))) close();
  };
  return (
    <div className="space-y-3 pt-2">
      <ErrorBanner message={error} />
      <Field label="Zone name">
        <input className={FIELD} value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Description">
        <input className={FIELD} placeholder="Optional" value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      {zone.sensors.length > 0 && (
        <InsetList label="Sensors in this zone">
          {zone.sensors.map((s) => (
            <ListRow key={s.id} to={`/sensors/${s.id}`} icon="sensors" title={s.haName ?? s.name} subtitle={s.category} />
          ))}
        </InsetList>
      )}
      <Actions>
        <Button variant="primary" disabled={!name.trim()} onClick={save}>
          Save
        </Button>
        <Button variant="danger" onClick={remove}>
          Delete zone
        </Button>
      </Actions>
    </div>
  );
}
