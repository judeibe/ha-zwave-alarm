import { useState } from "react";
import { Card, CODE_RE, CodeInput, ErrorBanner } from "../components";
import { useApi } from "../context";
import { useOverview } from "../Layout";
import type { AlarmUser, HaPerson, Role } from "../types";
import { useAction } from "../useAction";

function PersonCard({ person, user, run }: { person: HaPerson; user?: AlarmUser; run: ReturnType<typeof useAction>["run"] }) {
  const api = useApi();
  const [code, setCode] = useState("");
  const [role, setRole] = useState<Role>("member");
  const valid = CODE_RE.test(code);
  const submit = async (fn: () => Promise<unknown>) => {
    const ok = await run(fn);
    if (ok) setCode(""); // the code never lingers in the UI
  };
  return (
    <Card>
      <div>
        {person.name} <span className="za-muted">— {person.entity_id}</span>
      </div>
      {!user ? (
        <div className="za-row">
          <select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {(["member", "administrator", "guest"] as const).map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
          <CodeInput label={`Code for ${person.name}`} placeholder="Code (4–12 digits, optional)" value={code} onChange={setCode} />
          <button
            className="za-act"
            disabled={code !== "" && !valid}
            onClick={() =>
              submit(() =>
                api.call("user/create", {
                  name: person.name,
                  role,
                  ha_person_id: person.entity_id,
                  ...(person.user_id && { ha_user_id: person.user_id }),
                  ...(valid && { code }),
                }),
              )
            }
          >
            Onboard
          </button>
        </div>
      ) : (
        <>
          <div className="za-muted">
            Alarm user: {user.role}, code {user.hasCode ? "set" : "not set"}
          </div>
          <div className="za-row">
            <CodeInput label={`Code for ${person.name}`} placeholder={user.hasCode ? "New code" : "Code (4–12 digits)"} value={code} onChange={setCode} />
            <button className="za-act" disabled={!valid} onClick={() => submit(() => api.call("user/set_code", { user_id: user.id, code }))}>
              {user.hasCode ? "Replace code" : "Set code"}
            </button>
            {user.hasCode && (
              <button
                className="za-act danger"
                onClick={() => window.confirm(`Clear ${person.name}'s code?`) && run(() => api.call("user/clear_code", { user_id: user.id }))}
              >
                Clear code
              </button>
            )}
            <button
              className="za-act danger"
              onClick={() => window.confirm(`Remove ${person.name} from the alarm?`) && run(() => api.call("user/delete", { user_id: user.id }))}
            >
              Remove
            </button>
          </div>
        </>
      )}
    </Card>
  );
}

export function PeoplePage() {
  const { users, ha_people: people } = useOverview();
  const { run, error } = useAction();
  const byPerson = new Map(users.filter((u) => u.haPersonId).map((u) => [u.haPersonId as string, u]));
  const linked = new Set(people.map((p) => p.entity_id));
  const others = users.filter((u) => !u.haPersonId || !linked.has(u.haPersonId));
  return (
    <section>
      <ErrorBanner message={error} />
      <h2>Home Assistant people</h2>
      {!people.length && <p className="za-muted">No Home Assistant person entities found.</p>}
      {people.map((p) => (
        <PersonCard key={p.entity_id} person={p} user={byPerson.get(p.entity_id)} run={run} />
      ))}
      {others.length > 0 && <h2>Other alarm users</h2>}
      {others.map((u) => (
        <Card key={u.id}>
          {u.name} — {u.role}, code {u.hasCode ? "set" : "not set"}
        </Card>
      ))}
    </section>
  );
}
