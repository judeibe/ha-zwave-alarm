import { useState } from "react";
import { Outlet, useNavigate, useParams } from "react-router";
import { Actions, Button, CODE_RE, CodeInput, EmptyState, ErrorBanner, Field, Pill, SectionTitle, Select } from "../components";
import { useApi } from "../context";
import { useOverview } from "../overview";
import { clearUserCode, removeUser } from "../patches";
import type { AlarmUser, HaPerson, Role } from "../types";
import { useConfirm } from "../ui/Confirm";
import { Gone } from "../ui/Gone";
import { InsetList, ListRow } from "../ui/List";
import { Sheet, useRemembered, useSheet } from "../ui/Sheet";
import { useAction } from "../useAction";

const LIST = "/people";
const codeLabel = (u: AlarmUser) => `${u.role} · code ${u.hasCode ? "set" : "not set"}`;

export function PeoplePage() {
  const { users, ha_people: people } = useOverview();
  const byPerson = new Map(users.filter((u) => u.haPersonId).map((u) => [u.haPersonId as string, u]));
  const linked = new Set(people.map((p) => p.entity_id));
  const others = users.filter((u) => !u.haPersonId || !linked.has(u.haPersonId));
  return (
    <section>
      <SectionTitle>Home Assistant people</SectionTitle>
      {!people.length ? (
        <EmptyState title="No people found">No Home Assistant person entities found.</EmptyState>
      ) : (
        <InsetList label="People">
          {people.map((p) => {
            const user = byPerson.get(p.entity_id);
            return <ListRow key={p.entity_id} to={p.entity_id} icon="people" title={p.name} subtitle={p.entity_id} trailing={user ? <Pill tone="ok">{user.role}</Pill> : <Pill>Not set up</Pill>} />;
          })}
        </InsetList>
      )}
      {others.length > 0 && (
        <>
          <SectionTitle>Other alarm users</SectionTitle>
          <InsetList label="Other alarm users">
            {others.map((u) => (
              <ListRow key={u.id} icon="people" title={u.name} subtitle={codeLabel(u)} />
            ))}
          </InsetList>
        </>
      )}
      <Outlet />
    </section>
  );
}

export function PersonSheet() {
  const navigate = useNavigate();
  const { personId } = useParams();
  const { users, ha_people: people } = useOverview();
  const person = useRemembered(people.find((p) => p.entity_id === personId));
  const user = users.find((u) => u.haPersonId === personId);
  if (!person) return <Gone to={LIST} />;
  return (
    <Sheet title={person.name} onClosed={() => navigate(LIST)}>
      <PersonForm key={person.entity_id} person={person} user={user} />
    </Sheet>
  );
}

function PersonForm({ person, user }: { person: HaPerson; user?: AlarmUser }) {
  const api = useApi();
  const confirm = useConfirm();
  const { close } = useSheet();
  const { run, error } = useAction();
  const [code, setCode] = useState("");
  const [role, setRole] = useState<Role>("member");
  const valid = CODE_RE.test(code);
  const saveCode = async (fn: () => Promise<unknown>, done: string) => {
    if (await run(fn, { done })) setCode(""); // the code never lingers in the UI
  };
  if (!user) {
    return (
      <div className="space-y-3 pt-2">
        <p className="px-1 text-[15px] text-zinc-500 dark:text-zinc-400">{person.entity_id} is not set up as an alarm user yet.</p>
        <ErrorBanner message={error} />
        <Field label="Role">
          <Select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {(["member", "administrator", "guest"] as const).map((r) => (
              <option key={r}>{r}</option>
            ))}
          </Select>
        </Field>
        <Field label="Code">
          <CodeInput placeholder="4–12 digits, optional" value={code} onChange={setCode} />
        </Field>
        <Actions>
          <Button
            variant="primary"
            className="w-full"
            disabled={code !== "" && !valid}
            onClick={async () => {
              const payload = { name: person.name, role, ha_person_id: person.entity_id, ...(person.user_id && { ha_user_id: person.user_id }), ...(valid && { code }) };
              if (await run(() => api.call("user/create", payload), { done: `${person.name} added` })) close();
            }}
          >
            Onboard
          </Button>
        </Actions>
      </div>
    );
  }
  return (
    <div className="space-y-3 pt-2">
      <div className="px-1">
        <Pill tone={user.hasCode ? "ok" : "neutral"}>{codeLabel(user)}</Pill>
      </div>
      <ErrorBanner message={error} />
      <Field label="Code">
        <CodeInput placeholder={user.hasCode ? "New code" : "4–12 digits"} value={code} onChange={setCode} />
      </Field>
      <Actions>
        <Button variant="primary" disabled={!valid} onClick={() => saveCode(() => api.call("user/set_code", { user_id: user.id, code }), "Code saved")}>
          {user.hasCode ? "Replace code" : "Set code"}
        </Button>
        {user.hasCode && (
          <Button
            variant="danger"
            onClick={async () => {
              const ok = await confirm({ title: `Clear ${person.name}'s code?`, message: "They will no longer be able to arm or disarm with a code.", confirmLabel: "Clear code" });
              if (ok) run(() => api.call("user/clear_code", { user_id: user.id }), { patch: clearUserCode(user.id), done: "Code cleared" });
            }}
          >
            Clear code
          </Button>
        )}
        <Button
          variant="danger"
          onClick={async () => {
            const ok = await confirm({ title: `Remove ${person.name}?`, message: "They will be removed from the alarm.", confirmLabel: "Remove" });
            if (ok && (await run(() => api.call("user/delete", { user_id: user.id }), { patch: removeUser(user.id), done: `${person.name} removed` }))) close();
          }}
        >
          Remove
        </Button>
      </Actions>
    </div>
  );
}
