import { useState } from "react";
import { Outlet, useNavigate, useParams } from "react-router";
import { Actions, Button, CodeInput, EmptyState, ErrorBanner, Field, Pill, SectionTitle, Select } from "../components";
import { useApi } from "../context";
import { useOverview } from "../overview";
import { clearUserCode, removeUser, setDuressCode } from "../patches";
import type { AlarmUser, HaPerson, Role } from "../types";
import { useConfirm } from "../ui/Confirm";
import { Gone } from "../ui/Gone";
import { InsetList, ListRow } from "../ui/List";
import { Sheet, useRemembered, useSheet } from "../ui/Sheet";
import { useAction } from "../useAction";

const LIST = "/people";
/** A person's code is exactly four digits (a lock's has its own 4-8 digit rule, in the Locks tab). */
const USER_CODE_RE = /^\d{4}$/;
const expiry = (u: AlarmUser) => (u.guestExpiresAt ? `Access ends ${new Date(u.guestExpiresAt).toLocaleString()}` : "");
const codeLabel = (u: AlarmUser) =>
  [`${u.role} · code ${u.hasCode ? "set" : "not set"}`, u.hasDuressCode && "duress code set", u.role === "installer" && expiry(u)].filter(Boolean).join(" · ");
const ROLE_HINT: Partial<Record<Role, string>> = { installer: "An installer can arm and disarm for 48 hours, then the service removes the access." };

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
  const [confirmCode, setConfirmCode] = useState("");
  const [duress, setDuress] = useState("");
  const [confirmDuress, setConfirmDuress] = useState("");
  const [role, setRole] = useState<Role>("member");
  // Entered twice, like Ring: the code is only valid once the confirmation matches.
  const valid = USER_CODE_RE.test(code) && confirmCode === code;
  const duressValid = USER_CODE_RE.test(duress) && confirmDuress === duress;
  const saveCode = async (fn: () => Promise<unknown>, done: string) => {
    if (await run(fn, { done })) {
      // the codes never linger in the UI
      setCode("");
      setConfirmCode("");
    }
  };
  if (!user) {
    return (
      <div className="space-y-3 pt-2">
        <p className="px-1 text-[15px] text-zinc-500 dark:text-zinc-400">{person.entity_id} is not set up as an alarm user yet.</p>
        <ErrorBanner message={error} />
        <Field label="Role">
          <Select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {(["member", "administrator", "guest", "installer"] as const).map((r) => (
              <option key={r}>{r}</option>
            ))}
          </Select>
        </Field>
        {ROLE_HINT[role] && <p className="px-1 text-[15px] text-zinc-500 dark:text-zinc-400">{ROLE_HINT[role]}</p>}
        <Field label="Code">
          <CodeInput placeholder="4 digits, optional" value={code} onChange={setCode} />
        </Field>
        {code !== "" && (
          <Field label="Confirm code">
            <CodeInput placeholder="Enter it again" value={confirmCode} onChange={setConfirmCode} />
          </Field>
        )}
        <Actions>
          <Button
            variant="primary"
            className="w-full"
            disabled={code !== "" && !valid}
            onClick={async () => {
              const payload = { name: person.name, role, ha_person_id: person.entity_id, ...(person.user_id && { ha_user_id: person.user_id }), ...(valid && { code, confirm_code: confirmCode }) };
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
      {expiry(user) && <p className="px-1 text-[15px] text-zinc-500 dark:text-zinc-400">{expiry(user)}</p>}
      <Field label="Code">
        <CodeInput placeholder={user.hasCode ? "New code" : "4 digits"} value={code} onChange={setCode} />
      </Field>
      <Field label="Confirm code">
        <CodeInput placeholder="Enter it again" value={confirmCode} onChange={setConfirmCode} />
      </Field>
      <Actions>
        <Button variant="primary" disabled={!valid} onClick={() => saveCode(() => api.call("user/set_code", { user_id: user.id, code, confirm_code: confirmCode }), "Code saved")}>
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
      </Actions>
      {user.role === "administrator" && user.hasDuressCode !== undefined && (
        <>
          <p className="px-1 text-[15px] text-zinc-500 dark:text-zinc-400">
            Duress code ({user.hasDuressCode ? "set" : "not set"}): entering it on a keypad disarms visibly but silently asks for police.
          </p>
          <Field label="Duress code">
            <CodeInput placeholder={user.hasDuressCode ? "New duress code" : "4 digits"} value={duress} onChange={setDuress} />
          </Field>
          <Field label="Confirm duress code">
            <CodeInput placeholder="Enter it again" value={confirmDuress} onChange={setConfirmDuress} />
          </Field>
          <Actions>
            <Button
              variant="primary"
              disabled={!duressValid}
              onClick={async () => {
                if (await run(() => api.call("user/set_duress_code", { user_id: user.id, code: duress, confirm_code: confirmDuress }), { patch: setDuressCode(user.id, true), done: "Duress code saved" })) {
                  setDuress("");
                  setConfirmDuress("");
                }
              }}
            >
              {user.hasDuressCode ? "Replace duress code" : "Set duress code"}
            </Button>
            {user.hasDuressCode && (
              <Button
                variant="danger"
                onClick={async () => {
                  const ok = await confirm({ title: `Clear ${person.name}'s duress code?`, message: "Entering it will no longer raise a duress alarm.", confirmLabel: "Clear duress code" });
                  if (ok) run(() => api.call("user/clear_duress_code", { user_id: user.id }), { patch: setDuressCode(user.id, false), done: "Duress code cleared" });
                }}
              >
                Clear duress code
              </Button>
            )}
          </Actions>
        </>
      )}
      <Actions>
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
