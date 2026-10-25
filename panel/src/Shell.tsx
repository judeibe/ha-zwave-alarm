import { useContext, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useRevalidator, useRouteError } from "react-router";
import { ApiError } from "./api";
import { NarrowContext } from "./context";
import { PatchProvider } from "./overview";
import { ConfirmProvider } from "./ui/Confirm";
import { Icon, type IconName } from "./ui/Icon";
import { SkeletonList } from "./ui/Skeleton";
import { ToastProvider } from "./ui/Toast";

const TABS: readonly [string, string, IconName][] = [
  ["overview", "Overview", "overview"],
  ["sensors", "Sensors", "sensors"],
  ["zones", "Zones", "zones"],
  ["people", "People", "people"],
  ["keypads", "Keypads", "keypad"],
  ["locks", "Locks", "locks"],
  ["schedules", "Schedules", "schedule"],
  ["history", "History", "history"],
];

const ROOT = "za-root @container min-h-dvh bg-zinc-100 text-zinc-900 dark:bg-black dark:text-zinc-100";

/** HA only opens its sidebar drawer in narrow mode, and only in response to this event. */
const toggleHaMenu = (el: HTMLElement) => el.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));

/**
 * The app frame. Layout follows the panel's own width (container query), not the window's: HA's docked sidebar
 * narrows the panel without changing the window. Below `@2xl` (672px) navigation is a bottom tab bar; from there
 * up it is a sidebar. The large title collapses into a compact bar once it scrolls out of view.
 */
export function Shell() {
  const narrow = useContext(NarrowContext);
  const { pathname } = useLocation();
  const title = TABS.find(([to]) => pathname.split("/")[1] === to)?.[1] ?? "Z-Wave Alarm";
  const titleRef = useRef<HTMLHeadingElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const el = titleRef.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => setCollapsed(!entry?.isIntersecting));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <ToastProvider>
      <ConfirmProvider>
        <PatchProvider>
          <div className={ROOT}>
            <div className="flex min-h-dvh flex-col @2xl:flex-row">
              <nav
                aria-label="Sections"
                className="sticky bottom-0 z-20 order-last grid grid-cols-5 border-t border-black/5 bg-white/80 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl backdrop-saturate-150 @2xl:top-0 @2xl:order-first @2xl:h-dvh @2xl:w-56 @2xl:shrink-0 @2xl:grid-cols-1 @2xl:content-start @2xl:gap-1 @2xl:border-t-0 @2xl:border-r @2xl:p-3 dark:border-white/10 dark:bg-zinc-900/80"
              >
                <p className="hidden px-3 pt-3 pb-4 text-[15px] font-semibold tracking-tight @2xl:block">Z-Wave Alarm</p>
                {TABS.map(([to, label, icon]) => (
                  <NavLink
                    key={to}
                    to={to}
                    className={({ isActive }) =>
                      `flex min-h-14 flex-col items-center justify-center gap-0.5 rounded-xl px-2 text-[11px] font-medium outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-accent @2xl:min-h-11 @2xl:flex-row @2xl:justify-start @2xl:gap-3 @2xl:px-3 @2xl:text-[15px] dark:focus-visible:ring-accent-dark ${
                        isActive
                          ? "text-accent @2xl:bg-accent/10 dark:text-accent-dark @2xl:dark:bg-accent-dark/15"
                          : "text-zinc-500 hover:text-zinc-800 @2xl:hover:bg-black/5 dark:text-zinc-400 dark:hover:text-zinc-100 @2xl:dark:hover:bg-white/5"
                      }`
                    }
                  >
                    <Icon name={icon} className="size-6 @2xl:size-5" />
                    {label}
                  </NavLink>
                ))}
              </nav>
              <div className="min-w-0 flex-1">
                <header className="sticky top-0 z-10 bg-zinc-100/80 backdrop-blur-xl backdrop-saturate-150 dark:bg-black/70">
                  <div className="mx-auto grid h-12 max-w-3xl grid-cols-[2.75rem_1fr_2.75rem] items-center px-2 @2xl:px-6">
                    {narrow ? (
                      <button
                        ref={menuRef}
                        type="button"
                        aria-label="Open Home Assistant menu"
                        onClick={() => menuRef.current && toggleHaMenu(menuRef.current)}
                        className="grid size-11 place-items-center rounded-full outline-none hover:bg-black/5 focus-visible:ring-2 focus-visible:ring-accent dark:hover:bg-white/10 dark:focus-visible:ring-accent-dark"
                      >
                        <Icon name="menu" className="size-5" />
                      </button>
                    ) : (
                      <span />
                    )}
                    <span aria-hidden="true" className={`truncate text-center text-[17px] font-semibold transition-opacity duration-150 ${collapsed ? "opacity-100" : "opacity-0"}`}>
                      {title}
                    </span>
                    <span />
                  </div>
                  <div className={`h-px bg-black/10 transition-opacity duration-150 dark:bg-white/10 ${collapsed ? "opacity-100" : "opacity-0"}`} />
                </header>
                <main className="mx-auto w-full max-w-3xl px-4 pb-10 @2xl:px-8">
                  <h1 ref={titleRef} className="pt-1 pb-2 text-[34px] leading-tight font-bold tracking-tight [@media(max-height:500px)]:text-2xl">
                    {title}
                  </h1>
                  <Outlet />
                </main>
              </div>
            </div>
          </div>
        </PatchProvider>
      </ConfirmProvider>
    </ToastProvider>
  );
}

/** Shown by the root route while the first overview load is in flight. */
export function LoadingState() {
  return (
    <div role="status" aria-label="Loading" className={ROOT}>
      <div className="mx-auto w-full max-w-3xl px-4 pt-14">
        <div className="h-9 w-40 animate-pulse rounded-lg bg-zinc-200 motion-reduce:animate-none dark:bg-zinc-800" />
        <SkeletonList rows={4} />
      </div>
    </div>
  );
}

/** Route-level error (the overview load failed): show the message instead of a blank panel. */
export function LoadError() {
  const err = useRouteError() as Error;
  const { revalidate, state } = useRevalidator();
  return (
    <div className={ROOT}>
      <div className="mx-auto w-full max-w-3xl px-4 pt-6">
        <h1 className="text-[34px] font-bold tracking-tight">Z-Wave Alarm</h1>
        <div role="alert" className="mt-4 rounded-2xl bg-red-500/10 px-4 py-3 text-[15px] text-red-700 ring-1 ring-red-500/20 dark:text-red-300">
          {err?.message ?? "Failed to load"}
          {err instanceof ApiError && <div className="mt-1 text-[13px] opacity-70">Error code: {err.code}</div>}
        </div>
        <button
          type="button"
          disabled={state === "loading"}
          onClick={() => revalidate()}
          className="mt-4 rounded-full bg-blue-600 px-5 py-2 text-[15px] font-semibold text-white disabled:opacity-50"
        >
          Try again
        </button>
      </div>
    </div>
  );
}
