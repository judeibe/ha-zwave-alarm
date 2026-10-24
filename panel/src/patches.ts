import type { Overview, Zone } from "./types";
import type { Patch } from "./overview";

const mapZones = (o: Overview, fn: (z: Zone) => Zone | null): Overview => ({ ...o, zones: o.zones.flatMap((z) => fn(z) ?? []) });

/** Optimistic edits: each mirrors what the service will do, and is dropped once the real reload lands. */
export const removeSensor = (sensorId: string): Patch => (o) =>
  mapZones(o, (z) => ({ ...z, sensors: z.sensors.filter((s) => s.id !== sensorId) }));

export const moveSensor = (sensorId: string, zoneId: string): Patch => (o) => {
  const sensor = o.zones.flatMap((z) => z.sensors).find((s) => s.id === sensorId);
  if (!sensor) return o;
  return mapZones(o, (z) => ({
    ...z,
    sensors: [...z.sensors.filter((s) => s.id !== sensorId), ...(z.id === zoneId ? [{ ...sensor, zoneId }] : [])],
  }));
};

export const removeZone = (zoneId: string): Patch => (o) => mapZones(o, (z) => (z.id === zoneId ? null : z));

export const updateZone = (zoneId: string, changes: Partial<Pick<Zone, "name" | "description">>): Patch => (o) =>
  mapZones(o, (z) => (z.id === zoneId ? { ...z, ...changes } : z));

export const setKeypadRequireCode = (requireCodeToArm: boolean): Patch => (o) => ({
  ...o,
  keypad_settings: { ...o.keypad_settings, requireCodeToArm },
});

export const removeUser = (userId: string): Patch => (o) => ({ ...o, users: o.users.filter((u) => u.id !== userId) });

export const clearUserCode = (userId: string): Patch => (o) => ({
  ...o,
  users: o.users.map((u) => (u.id === userId ? { ...u, hasCode: false } : u)),
});
