import type { ReactNode } from "react";

export const ErrorBanner = ({ message }: { message: string }) =>
  message ? (
    <div className="za-error" role="alert">
      {message}
    </div>
  ) : null;

export const Card = ({ children }: { children: ReactNode }) => <div className="za-card">{children}</div>;

export const CODE_RE = /^\d{4,12}$/;

/** Write-only code field: a password input whose value is cleared by the owner after submit, never displayed. */
export function CodeInput({ label, placeholder, value, onChange }: {
  label: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <input
      type="password"
      inputMode="numeric"
      autoComplete="off"
      aria-label={label}
      placeholder={placeholder}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}
