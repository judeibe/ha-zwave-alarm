import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Icon } from "./Icon";
import { lockScroll } from "./scrollLock";

const CLOSE_MS = 200;

const SheetContext = createContext<{ close: () => void }>({ close: () => {} });
/** Lets content inside a sheet dismiss it (with the exit animation) after a successful action. */
export const useSheet = () => useContext(SheetContext);

/**
 * A modal sheet on a native <dialog>: slides up from the bottom on phones and in from the right from `md` up.
 * `onClosed` runs after the exit animation (the pages use it to navigate back to the list route).
 */
export function Sheet({ title, onClosed, children }: { title: string; onClosed: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [closing, setClosing] = useState(false);
  const titleId = useId();
  const onClosedRef = useRef(onClosed);
  onClosedRef.current = onClosed;

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    dialog.focus(); // keep focus inside the sheet without ringing the first control
    const unlock = lockScroll(dialog);
    return () => {
      unlock();
      if (dialog.open) dialog.close();
    };
  }, []);

  const close = useCallback(() => {
    setClosing(true);
    setTimeout(() => onClosedRef.current(), CLOSE_MS);
  }, []);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      tabIndex={-1}
      onCancel={(e) => {
        e.preventDefault(); // Escape: animate out instead of vanishing
        close();
      }}
      onClick={(e) => e.target === ref.current && close()} // a click on the backdrop targets the dialog itself
      className={`fixed inset-x-0 top-auto bottom-0 m-0 max-h-[92dvh] w-full max-w-none overflow-hidden rounded-t-3xl border-0 outline-none bg-zinc-100 p-0 text-zinc-900 shadow-2xl transition-transform duration-200 ease-out backdrop:bg-black/40 backdrop:backdrop-blur-sm starting:open:translate-y-full md:inset-y-0 md:right-0 md:left-auto md:max-h-none md:h-dvh md:w-[28rem] md:rounded-t-none md:rounded-l-3xl md:starting:open:translate-x-full md:starting:open:translate-y-0 dark:bg-zinc-950 dark:text-zinc-100 ${
        closing ? "translate-y-full md:translate-x-full md:translate-y-0" : ""
      }`}
    >
      <SheetContext.Provider value={{ close }}>
        <div className="za-root flex max-h-[inherit] flex-col md:h-full md:max-h-none">
          <div className="grid shrink-0 grid-cols-[2.75rem_1fr_2.75rem] items-center px-2 pt-2">
            <span />
            <h2 id={titleId} className="truncate text-center text-[17px] font-semibold">
              {title}
            </h2>
            <button
              type="button"
              aria-label="Close"
              onClick={close}
              className="grid size-11 place-items-center rounded-full text-zinc-500 outline-none hover:bg-black/5 focus-visible:ring-2 focus-visible:ring-accent dark:text-zinc-400 dark:hover:bg-white/10 dark:focus-visible:ring-accent-dark"
            >
              <Icon name="close" className="size-5" />
            </button>
          </div>
          <div className="overflow-y-auto overscroll-contain px-4 pb-[max(1.25rem,env(safe-area-inset-bottom))]">{children}</div>
        </div>
      </SheetContext.Provider>
    </dialog>
  );
}

/** Keeps showing an item after it disappears (e.g. optimistically removed) so the sheet can animate out intact. */
export function useRemembered<T>(item: T | undefined): T | undefined {
  const last = useRef(item);
  if (item !== undefined) last.current = item;
  return item ?? last.current;
}
