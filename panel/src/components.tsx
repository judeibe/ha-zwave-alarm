import type { ButtonHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

export const ErrorBanner = ({ message }: { message: string }) =>
  message ? (
    <div
      role="alert"
      className="my-3 rounded-2xl bg-red-500/10 px-4 py-3 text-[15px] leading-snug text-red-700 ring-1 ring-red-500/20 dark:text-red-300"
    >
      {message}
    </div>
  ) : null;

/** Rounded, softly shadowed surface. `za-card` is a stable hook for tests. */
export const Card = ({ children }: { children: ReactNode }) => (
  <div className="za-card my-3 rounded-3xl bg-white p-4 shadow-card ring-1 ring-black/5 sm:p-5 dark:bg-zinc-900 dark:ring-white/10">
    {children}
  </div>
);

export const SectionTitle = ({ children }: { children: ReactNode }) => (
  <h2 className="mt-8 mb-1 px-2 text-[13px] font-semibold tracking-wide text-zinc-500 uppercase first:mt-2 dark:text-zinc-400">
    {children}
  </h2>
);

export const Hint = ({ children }: { children: ReactNode }) => (
  <p className="px-2 py-1 text-[15px] leading-snug text-zinc-500 dark:text-zinc-400">{children}</p>
);

export const EmptyState = ({ title, children }: { title: string; children?: ReactNode }) => (
  <div className="my-3 rounded-3xl border border-dashed border-zinc-300 px-6 py-8 text-center dark:border-zinc-700">
    <p className="text-[17px] font-semibold text-zinc-800 dark:text-zinc-100">{title}</p>
    {children && <p className="mt-1 text-[15px] text-zinc-500 dark:text-zinc-400">{children}</p>}
  </div>
);

const FOCUS =
  "outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-accent-dark dark:focus-visible:ring-offset-zinc-900";

const BUTTON = {
  primary: "bg-accent text-white hover:brightness-110 active:brightness-95 dark:bg-accent-dark",
  secondary: "bg-zinc-100 text-zinc-900 hover:bg-zinc-200 active:bg-zinc-300 dark:bg-zinc-800 dark:text-zinc-100 dark:hover:bg-zinc-700",
  danger: "bg-red-500/10 text-red-600 hover:bg-red-500/20 active:bg-red-500/25 dark:text-red-400",
} as const;

export function Button({ variant = "secondary", className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof BUTTON }) {
  return (
    <button
      type="button"
      className={`inline-flex min-h-11 min-w-11 items-center border-0 justify-center rounded-xl px-4 text-[15px] font-semibold transition duration-150 disabled:opacity-40 ${FOCUS} ${BUTTON[variant]} ${className}`}
      {...props}
    />
  );
}

export const FIELD = `block min-h-11 w-full rounded-xl border-0 bg-zinc-100 px-3.5 text-base text-zinc-900 placeholder:text-zinc-400 transition duration-150 dark:bg-zinc-800 dark:text-zinc-100 dark:placeholder:text-zinc-500 ${FOCUS}`;

/** Native select (keeps the platform picker on phones) with our own chevron, inset from the right edge. */
export function Select({ className = "", children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className={`relative ${className}`}>
      <select className={`${FIELD} appearance-none pr-11`} {...props}>
        {children}
      </select>
      <svg
        aria-hidden="true"
        viewBox="0 0 20 20"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="pointer-events-none absolute top-1/2 right-4 size-4 -translate-y-1/2 text-zinc-400 dark:text-zinc-500"
      >
        <path d="m5 7.5 5 5 5-5" />
      </svg>
    </div>
  );
}

/** Form controls laid out in a responsive grid: one column on a phone, two or more from `sm` up. */
export const Fields = ({ children, className = "" }: { children: ReactNode; className?: string }) => (
  <div className={`mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-2 ${className}`}>{children}</div>
);

export const Actions = ({ children }: { children: ReactNode }) => (
  <div className="mt-3 flex flex-wrap items-center gap-2">{children}</div>
);

export const CardTitle = ({ children, meta }: { children: ReactNode; meta?: ReactNode }) => (
  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
    <span className="text-[17px] font-semibold text-zinc-900 dark:text-zinc-50">{children}</span>
    {meta && <span className="text-[15px] text-zinc-500 dark:text-zinc-400">{meta}</span>}
  </div>
);

const PILL = {
  ok: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  alert: "bg-red-500/10 text-red-600 dark:text-red-400",
  neutral: "bg-zinc-500/10 text-zinc-600 dark:text-zinc-300",
} as const;

export const Pill = ({ tone = "neutral", children }: { tone?: keyof typeof PILL; children: ReactNode }) => (
  <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[13px] font-semibold ${PILL[tone]}`}>{children}</span>
);

/** A visible label above a control; wrapping the control also gives it its accessible name. */
export const Field = ({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) => (
  <label className={`block ${className}`}>
    <span className="mb-1 block px-1 text-[13px] font-medium text-zinc-500 dark:text-zinc-400">{label}</span>
    {children}
  </label>
);

export const CODE_RE = /^\d{4,12}$/;

/** Write-only code field: a password input whose value is cleared by the owner after submit, never displayed. */
export function CodeInput({ placeholder, value, onChange }: {
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <input
      className={FIELD}
      type="password"
      inputMode="numeric"
      autoComplete="off"
      placeholder={placeholder}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}
