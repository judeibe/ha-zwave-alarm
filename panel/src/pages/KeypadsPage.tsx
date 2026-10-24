import { Link } from "react-router";
import { ErrorBanner, Hint, Pill, SectionTitle, EmptyState, Switch } from "../components";
import { useApi } from "../context";
import { useOverview } from "../overview";
import { setKeypadRequireCode } from "../patches";
import type { Keypad } from "../types";
import { InsetList, ListRow } from "../ui/List";
import { useAction } from "../useAction";

const status = (k: Keypad) => (k.connectivityStatus === "online" ? "Online" : "Offline");
const battery = (k: Keypad) => (k.batteryLevel === null ? "" : ` · battery ${k.batteryLevel}%`);

/** The keypads the alarm service found, and whether arming from them needs a PIN. */
export function KeypadsPage() {
  const api = useApi();
  const { keypads, keypad_settings: settings } = useOverview();
  const { run, error } = useAction();
  return (
    <section>
      <SectionTitle>Keypads</SectionTitle>
      {!keypads.length ? (
        <EmptyState title="No keypads found">
          Include a Ring Keypad v2 with S2 security in Z-Wave and it appears here automatically.
        </EmptyState>
      ) : (
        <InsetList label="Keypads">
          {keypads.map((k) => (
            <ListRow
              key={k.nodeId}
              icon="keypad"
              title={k.label}
              subtitle={`Node ${k.nodeId}${battery(k)}`}
              trailing={<Pill tone={k.connectivityStatus === "online" ? "ok" : "alert"}>{status(k)}</Pill>}
            />
          ))}
        </InsetList>
      )}
      <SectionTitle>Arming</SectionTitle>
      <ErrorBanner message={error} />
      {settings ? (
        <InsetList label="Keypad arming">
          <li className="flex min-h-14 items-center gap-3 px-4 py-2.5">
            <span className="min-w-0 flex-1">
              <span id="pin-to-arm" className="block text-[17px] leading-snug">Require PIN to arm</span>
              <span id="pin-to-arm-hint" className="block text-[15px] leading-snug text-zinc-500 dark:text-zinc-400">
                {settings.requireCodeToArm ? "Type a PIN, then press Arm Away or Arm Home." : "Arm Away and Arm Home arm without a PIN."}
              </span>
            </span>
            <Switch
              checked={settings.requireCodeToArm}
              aria-label="Require PIN to arm"
              aria-describedby="pin-to-arm-hint"
              onChange={(next) =>
                run(() => api.call("keypad_settings/update", { require_code_to_arm: next }), {
                  patch: setKeypadRequireCode(next),
                  done: next ? "Arming now needs a PIN" : "Arming no longer needs a PIN",
                })
              }
            />
          </li>
        </InsetList>
      ) : (
        <Hint>Keypad settings are not available yet. They need the Z-Wave Alarm service with keypad settings and a connection to it.</Hint>
      )}
      <Hint>
        Disarming from a keypad always needs a PIN. PINs belong to people: set or change them on the{" "}
        <Link to="/people" className="font-medium text-accent underline dark:text-accent-dark">People</Link> page.
      </Hint>
    </section>
  );
}
