import { useCallback, useEffect, useState } from "react";
import { Outlet, useNavigate, useParams } from "react-router";
import { ApiError } from "../api";
import { Actions, Button, EmptyState, ErrorBanner, Field, FIELD, Hint, Pill, SectionTitle, Select } from "../components";
import { CodeInput } from "../components";
import { useApi } from "../context";
import { useOverview } from "../overview";
import type { DailyRepeatingSchedule, Lock, LockSchedule, LockUserStatus, ScheduleKind, UnenrollReply, WeekDaySchedule, YearDaySchedule } from "../types";
import { useConfirm } from "../ui/Confirm";
import { useToast } from "../ui/Toast";
import { Gone } from "../ui/Gone";
import { InsetList, ListRow } from "../ui/List";
import { Sheet, useRemembered } from "../ui/Sheet";
import { useAction } from "../useAction";
import { LockAutomation } from "./LockAutomation";

const LIST = "/locks";
const lockName = (l: { nodeId: number; label?: string | null }) => l.label || `Lock ${l.nodeId}`;
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const pad = (n: number) => String(n).padStart(2, "0");
const time = (h: number, m: number) => `${pad(h)}:${pad(m)}`;
const parseTime = (v: string): [number, number] => {
  const [h = 0, m = 0] = v.split(":").map(Number);
  return [h, m];
};

export function LocksPage() {
  const api = useApi();
  const { run, error } = useAction();
  const { locks, discoverable_locks, discoverable_locks_error } = useOverview();
  return (
    <section>
      <SectionTitle>Alarm locks</SectionTitle>
      <ErrorBanner message={error} />
      {!locks.length ? (
        <EmptyState title="No locks in the alarm system">Add a paired Schlage lock below. Only locks you add here become devices in Home Assistant.</EmptyState>
      ) : (
        <InsetList label="Locks">
          {locks.map((l) => (
            <ListRow
              key={l.nodeId}
              to={String(l.nodeId)}
              icon="locks"
              title={lockName(l)}
              subtitle={`${l.model ?? "Schlage"} · ${typeof l.batteryLevel === "number" ? `Battery ${l.batteryLevel}%` : "Battery unknown"}`}
              trailing={<Pill tone={l.connectivityStatus === "online" ? "ok" : "neutral"}>{l.connectivityStatus === "online" ? "Online" : "Offline"}</Pill>}
            />
          ))}
        </InsetList>
      )}
      {discoverable_locks_error && <ErrorBanner message={`Could not look for paired locks. ${discoverable_locks_error.message}`} />}
      {!!discoverable_locks.length && (
        <>
          <SectionTitle>Paired, not added</SectionTitle>
          <InsetList label="Paired locks">
            {discoverable_locks.map((l) => (
              <ListRow
                key={l.nodeId}
                icon="locks"
                title={lockName(l)}
                subtitle={l.secure === false ? "Not securely included. Exclude it and include it again with S0 or S2." : (l.model ?? "Schlage")}
                trailing={
                  <Button variant="primary" disabled={l.secure === false} onClick={() => run(() => api.call("lock/enroll", { node_id: l.nodeId }), { done: `${lockName(l)} added` })}>
                    Add
                  </Button>
                }
              />
            ))}
          </InsetList>
        </>
      )}
      <Outlet />
    </section>
  );
}

export function LockSheet() {
  const navigate = useNavigate();
  const { nodeId } = useParams();
  const { locks } = useOverview();
  const lock = useRemembered(locks.find((l) => String(l.nodeId) === nodeId));
  if (!lock) return <Gone to={LIST} />;
  return (
    <Sheet title={lockName(lock)} onClosed={() => navigate(LIST)}>
      <LockDetails key={lock.nodeId} lock={lock} onRemoved={() => navigate(LIST)} />
    </Sheet>
  );
}

function LockDetails({ lock, onRemoved }: { lock: Lock; onRemoved: () => void }) {
  const api = useApi();
  const confirm = useConfirm();
  const toast = useToast();
  const { run, error } = useAction();
  const caps = lock.capabilities;
  return (
    <div className="space-y-4 pt-2">
      <ErrorBanner message={error} />
      <InsetList label="Status">
        <ListRow title="Model" trailing={<span className="text-[15px] text-zinc-400">{lock.model ?? "Unknown"}</span>} />
        <ListRow title="Connectivity" trailing={<Pill tone={lock.connectivityStatus === "online" ? "ok" : "neutral"}>{lock.connectivityStatus === "online" ? "Online" : "Offline"}</Pill>} />
        <ListRow title="Z-Wave node" trailing={<span className="text-[15px] text-zinc-400">{lock.nodeId}</span>} />
      </InsetList>
      {lock.modeSettings && <LockAutomation lock={lock} settings={lock.modeSettings} />}
      {caps.secure === false && <ErrorBanner message="This lock was included without S0/S2, so its codes and schedules cannot be managed. Exclude it and include it again securely." />}
      {caps.secure !== false && (caps.userCodes ? <LockUsers lock={lock} /> : <Hint>This lock does not support user codes.</Hint>)}
      {caps.secure !== false && (SCHEDULE_KINDS.some((k) => caps.schedules[k] !== false) ? <LockSchedules lock={lock} /> : <Hint>This lock does not support access schedules.</Hint>)}
      <Actions>
        <Button
          variant="danger"
          onClick={async () => {
            const ok = await confirm({ title: `Remove ${lockName(lock)}?`, message: "Its user codes and schedules are erased from the lock first. It stays paired with Z-Wave, but leaves the alarm system and its device is removed from Home Assistant.", confirmLabel: "Remove" });
            if (!ok) return;
            let reply: UnenrollReply | undefined;
            if (!(await run(async () => void (reply = await api.call<UnenrollReply>("lock/unenroll", { node_id: lock.nodeId }))))) return;
            // The lock is gone from the alarm either way; say so when its codes and schedules could not be wiped.
            toast(reply?.cleared === false ? `${lockName(lock)} removed, but its codes and schedules could not be cleared: ${reply.failures.join("; ") || "the lock did not answer"}` : `${lockName(lock)} removed`);
            onRemoved();
          }}
        >
          Remove from alarm
        </Button>
      </Actions>
    </div>
  );
}

/** Loads `command` once per `deps` change, exposing a reload; errors become a message instead of throwing. */
function useLoaded<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const reload = useCallback(async () => {
    try {
      setData(await load());
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unexpected error");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => void reload(), [reload]);
  return { data, error, reload };
}

const STATUS_TEXT: Record<LockUserStatus, string> = { enabled: "Code active", disabled: "Code disabled", available: "Empty" };

function LockUsers({ lock }: { lock: Lock }) {
  const api = useApi();
  const confirm = useConfirm();
  const { run, error: actionError } = useAction();
  const { data, error, reload } = useLoaded(() => api.call<{ userId: number; status: LockUserStatus }[]>("lock/users", { node_id: lock.nodeId }), [lock.nodeId]);
  const [slot, setSlot] = useState<number | null>(null);
  const [code, setCode] = useState("");
  const pin = lock.settings?.pinLength ?? null;
  const valid = pin ? new RegExp(`^\\d{${pin}}$`).test(code) : /^\d{4,8}$/.test(code);
  const current = data?.find((u) => u.userId === slot);
  const done = () => {
    setCode("");
    reload();
  };
  return (
    <div className="space-y-3">
      <SectionTitle>Users and codes</SectionTitle>
      <ErrorBanner message={error || actionError} />
      <InsetList label="Lock users">
        {(data ?? []).map((u) => (
          <ListRow key={u.userId} title={`User ${u.userId}`} subtitle={STATUS_TEXT[u.status]} trailing={<Button onClick={() => { setSlot(u.userId); setCode(""); }}>{u.status === "available" ? "Set" : "Edit"}</Button>} />
        ))}
      </InsetList>
      {slot !== null && current && (
        <div className="space-y-3">
          <Field label={`Code for user ${slot}`}>
            <CodeInput placeholder={pin ? `${pin} digits` : "4–8 digits"} value={code} onChange={setCode} />
          </Field>
          <Actions>
            <Button variant="primary" disabled={!valid} onClick={async () => (await run(() => api.call("lock/user/set_code", { node_id: lock.nodeId, user_id: slot, code }), { done: "Code saved" })) && done()}>
              Save code
            </Button>
            {current.status !== "available" && (
              <Button
                variant="danger"
                onClick={async () => {
                  const ok = await confirm({ title: `Clear user ${slot}'s code?`, message: "The code stops working on the lock.", confirmLabel: "Clear code" });
                  if (ok && (await run(() => api.call("lock/user/clear_code", { node_id: lock.nodeId, user_id: slot }), { done: "Code cleared" }))) done();
                }}
              >
                Clear code
              </Button>
            )}
          </Actions>
        </div>
      )}
    </div>
  );
}

interface Slots {
  user_id: number;
  kinds: Partial<Record<ScheduleKind, { slot_id: number; schedule: LockSchedule | null }[]>>;
  /** Kinds the lock has not reported yet. */
  unknown?: ScheduleKind[];
}

const describe = (kind: ScheduleKind, s: LockSchedule | null): string => {
  if (!s) return "Empty";
  if (kind === "weekDay") {
    const w = s as WeekDaySchedule;
    return `${DAYS[w.weekday]} ${time(w.startHour, w.startMinute)}–${time(w.stopHour, w.stopMinute)}`;
  }
  if (kind === "dailyRepeating") {
    const d = s as DailyRepeatingSchedule;
    return `${d.weekdays.map((x) => DAYS[x]).join(", ")} from ${time(d.startHour, d.startMinute)} for ${time(d.durationHour, d.durationMinute)}`;
  }
  const y = s as YearDaySchedule;
  return `20${pad(y.startYear)}-${pad(y.startMonth)}-${pad(y.startDay)} ${time(y.startHour, y.startMinute)} → 20${pad(y.stopYear)}-${pad(y.stopMonth)}-${pad(y.stopDay)} ${time(y.stopHour, y.stopMinute)}`;
};

const KIND_LABEL: Record<ScheduleKind, string> = { weekDay: "Weekly", dailyRepeating: "Daily repeating", yearDay: "Date range" };
const SCHEDULE_KINDS: ScheduleKind[] = ["weekDay", "dailyRepeating", "yearDay"];

function LockSchedules({ lock }: { lock: Lock }) {
  const api = useApi();
  const { run, error: actionError } = useAction();
  const [userId, setUserId] = useState(1);
  const { data, error, reload } = useLoaded(() => api.call<Slots>("lock/schedules", { node_id: lock.nodeId, user_id: userId }), [lock.nodeId, userId]);
  const [edit, setEdit] = useState<{ kind: ScheduleKind; slot: number } | null>(null);
  // Supported kinds get an editor; kinds the lock has not reported yet say so; unsupported ones are hidden.
  const kinds = SCHEDULE_KINDS.filter((k) => lock.capabilities.schedules[k] === true);
  const unreported = SCHEDULE_KINDS.filter((k) => lock.capabilities.schedules[k] === null);
  return (
    <div className="space-y-3">
      <SectionTitle>Access schedules</SectionTitle>
      <ErrorBanner message={error || actionError} />
      <Field label="User slot">
        <Select value={userId} onChange={(e) => { setUserId(Number(e.target.value)); setEdit(null); }}>
          {Array.from({ length: lock.capabilities.userSlots }, (_, i) => i + 1).map((n) => (
            <option key={n} value={n}>{`User ${n}`}</option>
          ))}
        </Select>
      </Field>
      <Actions>
        <Button onClick={() => run(() => api.call("lock/schedule/enabled", { node_id: lock.nodeId, user_id: userId, enabled: true }), { done: "Schedules enforced" })}>Enforce schedules</Button>
        <Button onClick={() => run(() => api.call("lock/schedule/enabled", { node_id: lock.nodeId, user_id: userId, enabled: false }), { done: "Schedules not enforced" })}>Always allow</Button>
      </Actions>
      {kinds.map((kind) => (
        <InsetList key={kind} label={KIND_LABEL[kind]}>
          {(data?.kinds[kind] ?? []).map(({ slot_id, schedule }) => (
            <ListRow key={slot_id} title={`${KIND_LABEL[kind]} ${slot_id}`} subtitle={describe(kind, schedule)} trailing={<Button onClick={() => setEdit({ kind, slot: slot_id })}>{schedule ? "Edit" : "Add"}</Button>} />
          ))}
        </InsetList>
      ))}
      {unreported.length > 0 && (
        <Hint>{`${unreported.map((k) => KIND_LABEL[k]).join(", ")} schedules: not reported by the lock yet. Wake it with a keypad touch and reopen this.`}</Hint>
      )}
      {edit && (
        <ScheduleEditor
          key={`${edit.kind}-${edit.slot}-${userId}`}
          kind={edit.kind}
          initial={data?.kinds[edit.kind]?.find((s) => s.slot_id === edit.slot)?.schedule ?? null}
          onSave={async (schedule) => {
            if (await run(() => api.call("lock/schedule/set", { node_id: lock.nodeId, user_id: userId, kind: edit.kind, slot_id: edit.slot, schedule }), { done: "Schedule saved" })) {
              setEdit(null);
              reload();
            }
          }}
          onClear={async () => {
            if (await run(() => api.call("lock/schedule/clear", { node_id: lock.nodeId, user_id: userId, kind: edit.kind, slot_id: edit.slot }), { done: "Schedule cleared" })) {
              setEdit(null);
              reload();
            }
          }}
          onCancel={() => setEdit(null)}
        />
      )}
    </div>
  );
}

function ScheduleEditor({ kind, initial, onSave, onClear, onCancel }: {
  kind: ScheduleKind;
  initial: LockSchedule | null;
  onSave: (s: LockSchedule) => void;
  onClear: () => void;
  onCancel: () => void;
}) {
  const w = initial as WeekDaySchedule | null;
  const d = initial as DailyRepeatingSchedule | null;
  const y = initial as YearDaySchedule | null;
  const [weekday, setWeekday] = useState(w?.weekday ?? 1);
  const [weekdays, setWeekdays] = useState<number[]>(d?.weekdays ?? [1, 2, 3, 4, 5]);
  const [start, setStart] = useState(initial && kind !== "yearDay" ? time((w ?? d)!.startHour, (w ?? d)!.startMinute) : "08:00");
  const [stop, setStop] = useState(w ? time(w.stopHour, w.stopMinute) : "17:00");
  const [duration, setDuration] = useState(d ? time(d.durationHour, d.durationMinute) : "09:00");
  const iso = (yr: number, mo: number, dy: number, h: number, mi: number) => `20${pad(yr)}-${pad(mo)}-${pad(dy)}T${time(h, mi)}`;
  const [from, setFrom] = useState(y ? iso(y.startYear, y.startMonth, y.startDay, y.startHour, y.startMinute) : "");
  const [to, setTo] = useState(y ? iso(y.stopYear, y.stopMonth, y.stopDay, y.stopHour, y.stopMinute) : "");

  const parts = (v: string) => {
    const [date = "", t = ""] = v.split("T");
    const [yr = 0, mo = 0, dy = 0] = date.split("-").map(Number);
    const [h, mi] = parseTime(t);
    return { yr: yr % 100, mo, dy, h, mi };
  };
  const build = (): LockSchedule | null => {
    const [sh, sm] = parseTime(start);
    if (kind === "weekDay") {
      const [eh, em] = parseTime(stop);
      return eh * 60 + em > sh * 60 + sm ? { weekday, startHour: sh, startMinute: sm, stopHour: eh, stopMinute: em } : null;
    }
    if (kind === "dailyRepeating") {
      const [dh, dm] = parseTime(duration);
      return weekdays.length && dh * 60 + dm > 0 ? { weekdays: [...weekdays].sort(), startHour: sh, startMinute: sm, durationHour: dh, durationMinute: dm } : null;
    }
    if (!from || !to || to <= from) return null;
    const a = parts(from);
    const b = parts(to);
    return { startYear: a.yr, startMonth: a.mo, startDay: a.dy, startHour: a.h, startMinute: a.mi, stopYear: b.yr, stopMonth: b.mo, stopDay: b.dy, stopHour: b.h, stopMinute: b.mi };
  };
  const schedule = build();
  return (
    <div className="space-y-3 rounded-2xl bg-white p-3 dark:bg-zinc-900">
      {kind === "weekDay" && (
        <Field label="Day">
          <Select value={weekday} onChange={(e) => setWeekday(Number(e.target.value))}>
            {DAYS.map((n, i) => <option key={n} value={i}>{n}</option>)}
          </Select>
        </Field>
      )}
      {kind === "dailyRepeating" && (
        <div className="flex flex-wrap gap-2" role="group" aria-label="Days">
          {DAYS.map((n, i) => (
            <Button key={n} variant={weekdays.includes(i) ? "primary" : "secondary"} aria-pressed={weekdays.includes(i)} onClick={() => setWeekdays((cur) => (cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i]))}>
              {n}
            </Button>
          ))}
        </div>
      )}
      {kind !== "yearDay" ? (
        <>
          <Field label="Starts"><input className={FIELD} type="time" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
          {kind === "weekDay" ? (
            <Field label="Ends"><input className={FIELD} type="time" value={stop} onChange={(e) => setStop(e.target.value)} /></Field>
          ) : (
            <Field label="Lasts (hours:minutes)"><input className={FIELD} type="time" value={duration} onChange={(e) => setDuration(e.target.value)} /></Field>
          )}
        </>
      ) : (
        <>
          <Field label="From"><input className={FIELD} type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label="Until"><input className={FIELD} type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
        </>
      )}
      <Actions>
        <Button variant="primary" disabled={!schedule} onClick={() => schedule && onSave(schedule)}>Save schedule</Button>
        {initial && <Button variant="danger" onClick={onClear}>Clear</Button>}
        <Button onClick={onCancel}>Cancel</Button>
      </Actions>
    </div>
  );
}
