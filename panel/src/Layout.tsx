import { NavLink, Outlet, useRouteError, useRouteLoaderData } from "react-router";
import type { Overview } from "./types";

/** The overview is loaded by the parent route, so child pages read it by route id. */
export const useOverview = () => useRouteLoaderData("root") as Overview;

const TABS = [
  ["sensors", "Sensors"],
  ["zones", "Zones"],
  ["people", "People"],
] as const;

export function Layout() {
  return (
    <div className="za-root">
      <h1>Z-Wave Alarm</h1>
      <nav>
        {TABS.map(([to, label]) => (
          <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "active" : "")}>
            {label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}

/** Route-level error (the overview load failed): show the message instead of a blank panel. */
export function LoadError() {
  const err = useRouteError() as Error;
  return (
    <div className="za-root">
      <h1>Z-Wave Alarm</h1>
      <div className="za-error" role="alert">
        {err?.message ?? "Failed to load"}
      </div>
    </div>
  );
}
