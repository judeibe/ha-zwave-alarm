import { ErrorBanner, Hint, SectionTitle, Select, Switch } from "../components";
import { useApi } from "../context";
import { updateLockModeSettings } from "../patches";
import type { Lock, LockAction, LockModeSettings, ScheduleMode } from "../types";
import { InsetList } from "../ui/List";
import { useAction } from "../useAction";

const TOGGLES: { field: "armOnLockWithCode" | "armOnOneTouch" | "disarmOnUnlock"; key: string; label: string; hint: string }[] = [
  { field: "armOnLockWithCode", key: "arm_on_lock_with_code", label: "Arm away when locked with a code", hint: "Locking at the lock with a person's code arms Away." },
  { field: "armOnOneTouch", key: "arm_on_one_touch", label: "Arm away on one-touch lock", hint: "The lock's one-touch button arms Away, where the lock supports it." },
  { field: "disarmOnUnlock", key: "disarm_on_unlock", label: "Disarm when unlocked with a code", hint: "Unlocking with a person's code disarms the alarm." },
];
const MODES: { mode: ScheduleMode; label: string }[] = [
  { mode: "disarmed", label: "When the alarm is disarmed" },
  { mode: "armed_home", label: "When the alarm arms Home" },
  { mode: "armed_away", label: "When the alarm arms Away" },
];
const toOption = (a: LockAction | undefined) => a ?? "none";

/** What this lock does with the alarm. Changing it needs an administrator or installer on the service. */
export function LockAutomation({ lock, settings }: { lock: Lock; settings: LockModeSettings }) {
  const api = useApi();
  const { run, error } = useAction();
  const toggle = (t: (typeof TOGGLES)[number], next: boolean) =>
    run(() => api.call("lock/mode_settings", { node_id: lock.nodeId, [t.key]: next }), { patch: updateLockModeSettings(lock.nodeId, { [t.field]: next }), done: "Saved" });
  const setAction = (mode: ScheduleMode, option: string) => {
    const action: LockAction = option === "none" ? null : (option as "lock" | "unlock");
    return run(() => api.call("lock/mode_settings", { node_id: lock.nodeId, actions: { [mode]: action } }), { patch: updateLockModeSettings(lock.nodeId, { actions: { [mode]: action } }), done: "Saved" });
  };
  return (
    <div className="space-y-3">
      <SectionTitle>Alarm automation</SectionTitle>
      <ErrorBanner message={error} />
      <InsetList label="Lock and alarm">
        {TOGGLES.map((t) => (
          <li key={t.field} className="flex min-h-14 items-center gap-3 px-4 py-2.5">
            <span className="min-w-0 flex-1">
              <span className="block text-[17px] leading-snug">{t.label}</span>
              <span className="block text-[15px] leading-snug text-zinc-500 dark:text-zinc-400">{t.hint}</span>
            </span>
            <Switch checked={settings[t.field]} aria-label={t.label} onChange={(next) => toggle(t, next)} />
          </li>
        ))}
      </InsetList>
      {MODES.map(({ mode, label }) => (
        <div key={mode}>
          <label className="mb-1 block px-1 text-[15px] font-medium" htmlFor={`${lock.nodeId}-${mode}`}>
            {label}
          </label>
          <Select id={`${lock.nodeId}-${mode}`} value={toOption(settings.actions[mode])} onChange={(e) => setAction(mode, e.target.value)}>
            <option value="none">Do nothing</option>
            <option value="lock">Lock the door</option>
            <option value="unlock">Unlock the door</option>
          </Select>
        </div>
      ))}
      <Hint>Only codes created in this app arm or disarm; codes programmed on the lock itself do not.</Hint>
    </div>
  );
}
