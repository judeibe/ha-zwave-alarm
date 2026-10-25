import { useCallback, useEffect, useState } from "react";
import { Button, EmptyState, ErrorBanner, Field, Pill, SectionTitle, Select } from "../components";
import { useApi } from "../context";
import type { HistoryEvent } from "../types";
import { InsetList, ListRow } from "../ui/List";

const PAGE = 50;
const KINDS: [string, string][] = [
  ["armed,disarmed,bypassed", "Arming"],
  ["alarm_triggered,alarm_cleared,breach,siren_silenced", "Alarms"],
  ["tamper,tamper_cleared,device_fault", "Faults and tamper"],
  ["code_added,code_changed,code_removed,duress_code_set,duress_code_removed,guest_code_used,lockout", "Codes"],
  ["guest_schedule_added,guest_schedule_updated,guest_schedule_removed", "Guest schedules"],
  ["mode_schedule_added,mode_schedule_updated,mode_schedule_removed,mode_schedule_applied,mode_schedule_skipped", "Mode schedules"],
];
const label = (type: string) => type.replaceAll("_", " ");
const tone = (type: string) => (/alarm_triggered|breach|tamper$|lockout/.test(type) ? "alert" : /cleared|disarmed/.test(type) ? "ok" : undefined);

/** The alarm's history, newest first: who did it, which device it concerned, and what happened. */
export function HistoryPage() {
  const api = useApi();
  const [kind, setKind] = useState("");
  const [device, setDevice] = useState("");
  const [events, setEvents] = useState<HistoryEvent[] | null>(null);
  const [more, setMore] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (before?: string) => {
      setBusy(true);
      try {
        const page = await api.call<HistoryEvent[]>("events", {
          limit: PAGE,
          ...(kind && { event_type: kind.split(",") }),
          ...(device && { device_id: device }),
          ...(before && { before }),
        });
        setEvents((cur) => (before && cur ? [...cur, ...page] : page));
        setMore(page.length === PAGE);
        setError("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load the history.");
      } finally {
        setBusy(false);
      }
    },
    [api, kind, device],
  );
  useEffect(() => {
    void load();
  }, [load]);

  // Devices seen in what is loaded: a filter for the ones that actually have history.
  const devices = [...new Map((events ?? []).filter((e) => e.deviceId).map((e) => [e.deviceId as string, e.deviceName ?? (e.deviceId as string)])).entries()];
  return (
    <section>
      <SectionTitle>History</SectionTitle>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Kind">
          <Select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">Everything</option>
            {KINDS.map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Device">
          <Select value={device} onChange={(e) => setDevice(e.target.value)}>
            <option value="">Any device</option>
            {device && !devices.some(([id]) => id === device) && <option value={device}>{device}</option>}
            {devices.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      <ErrorBanner message={error} />
      {events && !events.length && <EmptyState title="Nothing here">No history matches.</EmptyState>}
      {events && events.length > 0 && (
        <InsetList label="History">
          {events.map((e) => (
            <ListRow
              key={e.id}
              icon="alert"
              title={label(e.type)}
              subtitle={[e.deviceName, e.actor && `by ${e.actor}`, e.details, new Date(e.occurredAt).toLocaleString()].filter(Boolean).join(" · ")}
              trailing={tone(e.type) ? <Pill tone={tone(e.type)}>{tone(e.type) === "alert" ? "alert" : "ok"}</Pill> : undefined}
            />
          ))}
        </InsetList>
      )}
      {more && events && (
        <Button className="mt-3 w-full" disabled={busy} onClick={() => load(events[events.length - 1]?.id)}>
          Load older
        </Button>
      )}
    </section>
  );
}
