import { useCallback, useEffect, useState } from "react";
import { Button, ErrorBanner, FIELD, Field, Hint, SectionTitle, Switch } from "../components";
import { useApi } from "../context";
import type { GuestSchedule, Weekday } from "../types";
import { useConfirm } from "../ui/Confirm";
import { InsetList, ListRow } from "../ui/List";
import { useAction } from "../useAction";

const DAYS: { value: Weekday; label: string }[] = [
  { value: "mon", label: "Mon" }, { value: "tue", label: "Tue" }, { value: "wed", label: "Wed" }, { value: "thu", label: "Thu" },
  { value: "fri", label: "Fri" }, { value: "sat", label: "Sat" }, { value: "sun", label: "Sun" },
];

const describe = (s: GuestSchedule) =>
  `${s.days.map((d) => DAYS.find((x) => x.value === d)?.label ?? d).join(", ")} · ${s.allDay ? "all day" : `${s.start}–${s.end}`}`;

/** A guest's keypad schedules: outside every one the keypad refuses their code. Locks do not enforce them. */
export function GuestSchedules({ userId, name }: { userId: string; name: string }) {
  const api = useApi();
  const confirm = useConfirm();
  const { run, error } = useAction();
  const [schedules, setSchedules] = useState<GuestSchedule[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [title, setTitle] = useState("");
  const [days, setDays] = useState<Weekday[]>([]);
  const [allDay, setAllDay] = useState(false);
  const [start, setStart] = useState("08:00");
  const [end, setEnd] = useState("17:00");

  const load = useCallback(async () => {
    try {
      setSchedules(await api.call<GuestSchedule[]>("guest_schedule/list", { user_id: userId }));
      setLoadError("");
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Could not load the schedules.");
    }
  }, [api, userId]);
  useEffect(() => {
    void load();
  }, [load]);

  const valid = title.trim() !== "" && days.length > 0 && (allDay || (start !== "" && end !== "" && start !== end));
  const add = async () => {
    const payload = { user_id: userId, name: title.trim(), days, all_day: allDay, ...(allDay ? {} : { start, end }) };
    if (await run(() => api.call("guest_schedule/create", payload), { done: "Schedule added" })) {
      setTitle("");
      setDays([]);
      await load();
    }
  };
  const remove = async (s: GuestSchedule) => {
    if (await confirm({ title: `Remove ${s.name}?`, message: `${name} can use their code at any time if no schedule is left.`, confirmLabel: "Remove schedule" })) {
      if (await run(() => api.call("guest_schedule/delete", { user_id: userId, schedule_id: s.id }), { done: "Schedule removed" })) await load();
    }
  };
  return (
    <div className="space-y-3">
      <SectionTitle>Keypad schedule</SectionTitle>
      <ErrorBanner message={loadError || error} />
      {schedules && !schedules.length && <Hint>No schedule: {name}'s code works at any time. Add one to limit when it works on the keypad (locks ignore schedules).</Hint>}
      {schedules && schedules.length > 0 && (
        <InsetList label="Schedules">
          {schedules.map((s) => (
            <ListRow key={s.id} icon="people" title={s.name} subtitle={describe(s)} trailing={<Button variant="danger" onClick={() => remove(s)}>Remove</Button>} />
          ))}
        </InsetList>
      )}
      <Field label="Schedule name">
        <input className={FIELD} value={title} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      <div role="group" aria-label="Days" className="flex flex-wrap gap-2">
        {DAYS.map((d) => (
          <Button key={d.value} variant={days.includes(d.value) ? "primary" : undefined} aria-pressed={days.includes(d.value)} onClick={() => setDays((cur) => (cur.includes(d.value) ? cur.filter((x) => x !== d.value) : [...cur, d.value]))}>
            {d.label}
          </Button>
        ))}
      </div>
      <div className="flex min-h-14 items-center gap-3 px-1">
        <span className="min-w-0 flex-1 text-[17px] leading-snug">All day</span>
        <Switch checked={allDay} aria-label="All day" onChange={setAllDay} />
      </div>
      {!allDay && (
        <div className="grid grid-cols-2 gap-3">
          <Field label="From">
            <input className={FIELD} type="time" value={start} onChange={(e) => setStart(e.target.value)} />
          </Field>
          <Field label="Until">
            <input className={FIELD} type="time" value={end} onChange={(e) => setEnd(e.target.value)} />
          </Field>
        </div>
      )}
      {!allDay && start !== "" && start === end && <Hint>The start and end must differ. An end before the start runs overnight.</Hint>}
      <Button variant="primary" className="w-full" disabled={!valid} onClick={add}>
        Add schedule
      </Button>
    </div>
  );
}
