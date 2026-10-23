import type { ReactNode } from "react";
import { Link } from "react-router";
import { Icon, type IconName } from "./Icon";

/** iOS-style inset grouped list: one rounded surface, hairline separators between rows. */
export const InsetList = ({ children, label }: { children: ReactNode; label?: string }) => (
  <ul
    aria-label={label}
    className="my-3 divide-y divide-zinc-200/70 overflow-hidden rounded-2xl bg-white shadow-card ring-1 ring-black/5 dark:divide-white/10 dark:bg-zinc-900 dark:ring-white/10"
  >
    {children}
  </ul>
);

const ROW = "flex min-h-14 w-full items-center gap-3 px-4 py-2.5 text-left";
const INTERACTIVE =
  "transition-colors duration-150 outline-none hover:bg-zinc-50 active:bg-zinc-100 focus-visible:bg-zinc-50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent dark:hover:bg-white/5 dark:active:bg-white/10 dark:focus-visible:bg-white/5 dark:focus-visible:ring-accent-dark";

export function ListRow({ to, icon, title, subtitle, trailing }: {
  to?: string;
  icon?: IconName;
  title: ReactNode;
  subtitle?: ReactNode;
  trailing?: ReactNode;
}) {
  const body = (
    <>
      {icon && (
        <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-accent/10 text-accent dark:bg-accent-dark/15 dark:text-accent-dark">
          <Icon name={icon} className="size-5" />
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[17px] leading-snug text-zinc-900 dark:text-zinc-50">{title}</span>
        {subtitle && <span className="block truncate text-[15px] leading-snug text-zinc-500 dark:text-zinc-400">{subtitle}</span>}
      </span>
      {trailing}
      {to && <Icon name="chevron" className="size-4 shrink-0 text-zinc-300 dark:text-zinc-600" />}
    </>
  );
  return (
    <li>
      {to ? (
        <Link to={to} className={`${ROW} ${INTERACTIVE}`}>
          {body}
        </Link>
      ) : (
        <div className={ROW}>{body}</div>
      )}
    </li>
  );
}

/** A label-and-value row for read-only details inside a sheet. */
export const DetailRow = ({ label, children }: { label: string; children: ReactNode }) => (
  <li className="flex min-h-11 items-center justify-between gap-4 px-4 py-2 text-[17px]">
    <span className="text-zinc-500 dark:text-zinc-400">{label}</span>
    <span className="min-w-0 truncate text-right text-zinc-900 dark:text-zinc-50">{children}</span>
  </li>
);
