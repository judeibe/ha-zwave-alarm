import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

type Toast = { id: number; message: string };
const ToastContext = createContext<(message: string) => void>(() => {});
/** Brief confirmation of a completed action ("Zone deleted"). Failures stay inline next to the form that caused them. */
export const useToast = () => useContext(ToastContext);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(0);
  const show = useCallback((message: string) => {
    const id = next.current++;
    setToasts((t) => [...t, { id, message }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3500);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div role="status" aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-24 z-50 flex flex-col items-center gap-2 px-4 @2xl:bottom-6">
        {toasts.map((t) => (
          <div
            key={t.id}
            className="rounded-full bg-zinc-900/90 px-4 py-2.5 text-[15px] font-medium text-white shadow-lg backdrop-blur-xl transition duration-200 starting:translate-y-2 starting:opacity-0 dark:bg-zinc-100/90 dark:text-zinc-900"
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
