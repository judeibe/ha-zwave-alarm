import { useState } from "react";
import { FIELD, Hint, Pill, SectionTitle } from "../components";
import { useApi } from "../context";
import { setModeDelays } from "../patches";
import { useAction } from "../useAction";
import type { ArmedModeKey, ModeDelays } from "../types";
import { useOverview } from "../overview";
import { Icon, type IconName } from "../ui/Icon";
import { InsetList, ListRow } from "../ui/List";
import type { PanelSummary } from "../types";

const STATES: Record<NonNullable<PanelSummary["state"]>, { label: string; icon: IconName; tone: string }> = {
  disarmed: { label: "Disarmed", icon: "shield", tone: "bg-zinc-500/10 text-zinc-600 dark:text-zinc-300" },
  armed_home: { label: "Armed home", icon: "shield-check", tone: "bg-accent/10 text-accent dark:bg-accent-dark/15 dark:text-accent-dark" },
  armed_away: { label: "Armed away", icon: "shield-check", tone: "bg-accent/10 text-accent dark:bg-accent-dark/15 dark:text-accent-dark" },
  arming: { label: "Arming", icon: "shield", tone: "bg-amber-500/10 text-amber-600 dark:text-amber-400" },
  pending: { label: "Entry delay", icon: "alert", tone: "bg-amber-500/10 text-amber-600 dark:text-amber-400" },
  triggered: { label: "Alarm triggered", icon: "alert", tone: "bg-red-500/10 text-red-600 dark:text-red-400" },
};

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

function Stat({ label, value, alert }: { label: string; value: number; alert?: boolean }) {
  return (
    <div className="rounded-2xl bg-white p-4 shadow-card ring-1 ring-black/5 dark:bg-zinc-900 dark:ring-white/10">
      <div className={`text-[28px] leading-none font-bold tabular-nums ${alert && value > 0 ? "text-red-600 dark:text-red-400" : ""}`}>{value}</div>
      <div className="mt-1.5 text-[13px] font-medium text-zinc-500 dark:text-zinc-400">{label}</div>
    </div>
  );
}

/** The dashboard: what the alarm is doing right now and whether anything needs attention. */
export function OverviewPage() {
  const { panel, zones, fault_count, faults } = useOverview();
  const sensors = zones.flatMap((z) => z.sensors.map((s) => ({ zone: z, sensor: s })));
  const breached = sensors.filter(({ sensor }) => sensor.currentState === "breached");
  const state = panel?.state ? STATES[panel.state] : null;
  return (
    <section>
      <div className="my-3 flex items-center gap-4 rounded-3xl bg-white p-5 shadow-card ring-1 ring-black/5 dark:bg-zinc-900 dark:ring-white/10">
        <span className={`grid size-14 shrink-0 place-items-center rounded-2xl ${state?.tone ?? "bg-zinc-500/10 text-zinc-500"}`}>
          <Icon name={state?.icon ?? "shield"} className="size-7" />
        </span>
        <div className="min-w-0">
          <p className="text-[22px] leading-tight font-semibold">{state?.label ?? "Status unavailable"}</p>
          <p className="text-[15px] text-zinc-500 dark:text-zinc-400">
            {panel ? `${plural(zones.length, "zone")} · ${plural(sensors.length, "sensor")}` : "Waiting for the alarm service"}
          </p>
        </div>
        <div className="ml-auto shrink-0">
          {fault_count > 0 ? <Pill tone="alert">{plural(fault_count, "fault")}</Pill> : <Pill tone="ok">All healthy</Pill>}
        </div>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Breached" value={breached.length} alert />
        <Stat label="Offline" value={faults.offline} alert />
        <Stat label="Low battery" value={faults.low_battery} alert />
      </div>
      {breached.length > 0 && (
        <>
          <SectionTitle>Needs attention</SectionTitle>
          <InsetList label="Breached sensors">
            {breached.map(({ zone, sensor }) => (
              <ListRow key={sensor.id} to={`/sensors/${sensor.id}`} icon="alert" title={sensor.haName ?? sensor.name} subtitle={zone.name} trailing={<Pill tone="alert">breached</Pill>} />
            ))}
          </InsetList>
        </>
      )}
      {!zones.length && <Hint>No zones yet. Create one under Zones, then assign your Z-Wave sensors to it.</Hint>}
      <ModeDelaysSection />
    </section>
  );
}

const MODE_LABEL: Record<ArmedModeKey, string> = { armed_home: "Home", armed_away: "Away" };
const DELAY_MAX = 180;

function DelayField({ mode, field, label, value }: { mode: ArmedModeKey; field: keyof ModeDelays; label: string; value: number }) {
  const api = useApi();
  const { run, error } = useAction();
  const [draft, setDraft] = useState(String(value));
  const parsed = Number(draft);
  const valid = draft.trim() !== "" && Number.isInteger(parsed) && parsed >= 0 && parsed <= DELAY_MAX;
  const save = () => {
    if (valid && parsed !== value) run(() => api.call("modes/update", { [mode]: { [field]: parsed } }), { patch: setModeDelays(mode, { [field]: parsed }), done: "Delay saved" });
  };
  return (
    <li className="flex min-h-14 items-center gap-3 px-4 py-2.5">
      <label htmlFor={`${mode}-${field}`} className="min-w-0 flex-1 text-[17px] leading-snug">
        {label}
        {error && <span className="block text-[15px] text-red-600 dark:text-red-400">{error}</span>}
      </label>
      <input
        id={`${mode}-${field}`}
        className={`${FIELD} w-24 text-right`}
        inputMode="numeric"
        aria-invalid={!valid}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
      />
      <span className="text-[15px] text-zinc-500 dark:text-zinc-400">s</span>
    </li>
  );
}

/** Entry and exit delay per armed mode (0-180 s). One value per mode applies to every sensor placed on a door or entryway. */
export function ModeDelaysSection() {
  const { modes } = useOverview();
  if (!modes) return null;
  return (
    <>
      <SectionTitle>Entry and exit delays</SectionTitle>
      {(Object.keys(MODE_LABEL) as ArmedModeKey[]).map((mode) => (
        <InsetList key={mode} label={`${MODE_LABEL[mode]} delays`}>
          <DelayField mode={mode} field="exitDelaySec" label={`${MODE_LABEL[mode]} exit delay`} value={modes[mode].exitDelaySec} />
          <DelayField mode={mode} field="entryDelaySec" label={`${MODE_LABEL[mode]} entry delay`} value={modes[mode].entryDelaySec} />
        </InsetList>
      ))}
      <Hint>0 to 180 seconds. At 0, door and entryway sensors alarm immediately.</Hint>
    </>
  );
}
