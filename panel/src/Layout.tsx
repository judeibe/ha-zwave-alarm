import { NavLink, Outlet, useRouteError, useRouteLoaderData } from "react-router";
import type { Overview } from "./types";

/** The overview is loaded by the parent route, so child pages read it by route id. */
export const useOverview = () => useRouteLoaderData("root") as Overview;

const TABS = [
  ["sensors", "Sensors"],
  ["zones", "Zones"],
  ["people", "People"],
] as const;

// Safe-area padding keeps content clear of the notch / home indicator when a phone is in landscape.
const SHELL =
  "za-root min-h-dvh bg-zinc-100 pr-[max(1rem,env(safe-area-inset-right))] pb-[max(2rem,env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] text-zinc-900 sm:px-6 dark:bg-black dark:text-zinc-100";

export function Layout() {
  return (
    <div className={SHELL}>
      <div className="mx-auto w-full max-w-3xl">
        {/* Sticky translucent header; on short (landscape) viewports it scrolls away to give the content the height. */}
        <header className="sticky top-0 z-10 -mx-4 bg-zinc-100/80 px-4 pt-4 pb-3 backdrop-blur-xl backdrop-saturate-150 sm:-mx-6 sm:px-6 [@media(max-height:500px)]:static dark:bg-black/70">
          <h1 className="text-[28px] leading-tight font-bold tracking-tight sm:text-[34px] [@media(max-height:500px)]:text-2xl">Z-Wave Alarm</h1>
          <nav aria-label="Sections" className="mt-3 flex rounded-xl bg-zinc-200/70 p-0.5 dark:bg-zinc-800/80">
            {TABS.map(([to, label]) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `flex min-h-11 flex-1 items-center justify-center rounded-[10px] px-3 text-[15px] font-semibold transition duration-150 outline-none focus-visible:ring-2 focus-visible:ring-accent dark:focus-visible:ring-accent-dark ${
                    isActive
                      ? "bg-white text-zinc-900 shadow-sm dark:bg-zinc-600 dark:text-white"
                      : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-300 dark:hover:text-white"
                  }`
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
        </header>
        <main className="pt-1">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

/** Shown by the root route while the first overview load is in flight. */
export function LoadingState() {
  return (
    <div role="status" className={`${SHELL} flex items-center justify-center gap-3 text-[15px] text-zinc-500`}>
      <span className="size-5 animate-spin rounded-full border-2 border-zinc-300 border-t-accent motion-reduce:animate-none dark:border-zinc-700 dark:border-t-accent-dark" />
      Loading…
    </div>
  );
}

/** Route-level error (the overview load failed): show the message instead of a blank panel. */
export function LoadError() {
  const err = useRouteError() as Error;
  return (
    <div className={SHELL}>
      <div className="mx-auto w-full max-w-3xl pt-4">
        <h1 className="text-[28px] font-bold tracking-tight">Z-Wave Alarm</h1>
        <div role="alert" className="mt-4 rounded-2xl bg-red-500/10 px-4 py-3 text-[15px] text-red-700 ring-1 ring-red-500/20 dark:text-red-300">
          {err?.message ?? "Failed to load"}
        </div>
      </div>
    </div>
  );
}
