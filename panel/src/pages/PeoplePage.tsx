import { useState } from "react";
import { Actions, Button, Card, CardTitle, CODE_RE, CodeInput, EmptyState, ErrorBanner, Fields, Select, Pill, SectionTitle } from "../components";
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
      <CardTitle meta={person.entity_id}>{person.name}</CardTitle>
      {!user ? (
        <>
          <Fields>
            <Select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {(["member", "administrator", "guest"] as const).map((r) => (
                <option key={r}>{r}</option>
              ))}
            </Select>
            <CodeInput label={`Code for ${person.name}`} placeholder="Code (4–12 digits, optional)" value={code} onChange={setCode} />
          </Fields>
          <Actions>
            <Button
              variant="primary"
              className="w-full sm:w-auto"
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
            </Button>
          </Actions>
        </>
      ) : (
        <>
          <div className="mt-1.5">
            <Pill tone={user.hasCode ? "ok" : "neutral"}>
              Alarm user: {user.role}, code {user.hasCode ? "set" : "not set"}
            </Pill>
          </div>
          <Fields>
            <CodeInput label={`Code for ${person.name}`} placeholder={user.hasCode ? "New code" : "Code (4–12 digits)"} value={code} onChange={setCode} />
          </Fields>
          <Actions>
            <Button variant="primary" disabled={!valid} onClick={() => submit(() => api.call("user/set_code", { user_id: user.id, code }))}>
              {user.hasCode ? "Replace code" : "Set code"}
            </Button>
            {user.hasCode && (
              <Button variant="danger" onClick={() => window.confirm(`Clear ${person.name}'s code?`) && run(() => api.call("user/clear_code", { user_id: user.id }))}>
                Clear code
              </Button>
            )}
            <Button variant="danger" onClick={() => window.confirm(`Remove ${person.name} from the alarm?`) && run(() => api.call("user/delete", { user_id: user.id }))}>
              Remove
            </Button>
          </Actions>
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
      <SectionTitle>Home Assistant people</SectionTitle>
      {!people.length && <EmptyState title="No people found">No Home Assistant person entities found.</EmptyState>}
      {people.map((p) => (
        <PersonCard key={p.entity_id} person={p} user={byPerson.get(p.entity_id)} run={run} />
      ))}
      {others.length > 0 && <SectionTitle>Other alarm users</SectionTitle>}
      {others.map((u) => (
        <Card key={u.id}>
          <CardTitle meta={`${u.role}, code ${u.hasCode ? "set" : "not set"}`}>{u.name}</CardTitle>
        </Card>
      ))}
    </section>
  );
}
