import { useState } from "react";
import { Button, EmptyState, ErrorBanner, FIELD, Field, Hint, Pill, SectionTitle, Select, Switch } from "../components";
import { useApi } from "../context";
import { useOverview } from "../overview";
import { updateModeSchedule } from "../patches";
import type { ModeSchedule, ScheduleMode, Weekday } from "../types";
import { useConfirm } from "../ui/Confirm";
import { InsetList } from "../ui/List";
import { useAction } from "../useAction";

const DAYS: { value: Weekday; label: string }[] = [
  { value: "mon", label: "Mon" }, { value: "tue", label: "Tue" }, { value: "wed", label: "Wed" }, { value: "thu", label: "Thu" },
  { value: "fri", label: "Fri" }, { value: "sat", label: "Sat" }, { value: "sun", label: "Sun" },
];
const MODES: { value: ScheduleMode; label: string }[] = [
  { value: "disarmed", label: "Disarm" }, { value: "armed_home", label: "Arm home" }, { value: "armed_away", label: "Arm away" },
];
const modeLabel = (m: ScheduleMode) => MODES.find((x) => x.value === m)?.label ?? m;
const dayList = (days: Weekday[]) => DAYS.filter((d) => days.includes(d.value)).map((d) => d.label).join(", ");

/** Schedules that switch the alarm's mode at set times. Arming this way bypasses faulted sensors. */
export function SchedulesPage() {
  const api = useApi();
  const confirm = useConfirm();
  const { mode_schedules: schedules } = useOverview();
  const { run, error } = useAction();
  const [name, setName] = useState("");
  const [mode, setMode] = useState<ScheduleMode>("armed_home");
  const [time, setTime] = useState("22:00");
  const [days, setDays] = useState<Weekday[]>([]);
  if (!schedules) return <Hint>This alarm service doesn't have mode schedules yet. Update it to 3.6.0 or later.</Hint>;
  const valid = name.trim() !== "" && time !== "" && days.length > 0;
  const add = async () => {
    if (await run(() => api.call("mode_schedule/create", { name: name.trim(), mode, time, days }), { done: "Schedule added" })) {
      setName("");
      setDays([]);
    }
  };
  const remove = async (s: ModeSchedule) => {
    if (await confirm({ title: `Remove ${s.name}?`, message: "It will no longer change the mode.", confirmLabel: "Remove schedule" })) {
      await run(() => api.call("mode_schedule/delete", { schedule_id: s.id }), { done: "Schedule removed" });
    }
  };
  return (
    <section>
      <SectionTitle>Mode schedules</SectionTitle>
      <ErrorBanner message={error} />
      {!schedules.length ? (
        <EmptyState title="No schedules">Add one to arm or disarm the alarm automatically at set times.</EmptyState>
      ) : (
        <InsetList label="Mode schedules">
          {schedules.map((s) => (
            <li key={s.id} className="flex min-h-14 items-center gap-3 px-4 py-2.5">
              <span className="min-w-0 flex-1">
                <span className="block text-[17px] leading-snug">{s.name}</span>
                <span className="block text-[15px] leading-snug text-zinc-500 dark:text-zinc-400">
                  {modeLabel(s.mode)} at {s.time} · {dayList(s.days)}
                  {s.timeZone ? ` · ${s.timeZone}` : ""}
                </span>
              </span>
              {!s.enabled && <Pill>off</Pill>}
              <Switch
                checked={s.enabled}
                aria-label={`${s.name} enabled`}
                onChange={(next) => run(() => api.call("mode_schedule/update", { schedule_id: s.id, enabled: next }), { patch: updateModeSchedule(s.id, { enabled: next }) })}
              />
              <Button variant="danger" onClick={() => remove(s)}>
                Remove
              </Button>
            </li>
          ))}
        </InsetList>
      )}
      <SectionTitle>New schedule</SectionTitle>
      <div className="space-y-3">
        <Field label="Schedule name">
          <input className={FIELD} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Mode">
          <Select value={mode} onChange={(e) => setMode(e.target.value as ScheduleMode)}>
            {MODES.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Time">
          <input className={FIELD} type="time" value={time} onChange={(e) => setTime(e.target.value)} />
        </Field>
        <div role="group" aria-label="Days" className="flex flex-wrap gap-2">
          {DAYS.map((d) => (
            <Button key={d.value} variant={days.includes(d.value) ? "primary" : undefined} aria-pressed={days.includes(d.value)} onClick={() => setDays((cur) => (cur.includes(d.value) ? cur.filter((x) => x !== d.value) : [...cur, d.value]))}>
              {d.label}
            </Button>
          ))}
        </div>
        <Button variant="primary" className="w-full" disabled={!valid} onClick={add}>
          Add schedule
        </Button>
      </div>
    </section>
  );
}
