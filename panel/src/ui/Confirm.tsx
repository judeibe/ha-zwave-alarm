import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "../components";

interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel: string;
}
type Ask = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<Ask>(async () => false);
/** Replaces `window.confirm`: resolves true only when the user presses the destructive button. */
export const useConfirm = () => useContext(ConfirmContext);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<{ options: ConfirmOptions; resolve: (ok: boolean) => void } | null>(null);
  const ask = useCallback<Ask>((options) => new Promise((resolve) => setPending({ options, resolve })), []);
  const answer = (ok: boolean) => {
    pending?.resolve(ok);
    setPending(null);
  };
  return (
    <ConfirmContext.Provider value={ask}>
      {children}
      {pending && <ConfirmDialog {...pending.options} onAnswer={answer} />}
    </ConfirmContext.Provider>
  );
}

function ConfirmDialog({ title, message, confirmLabel, onAnswer }: ConfirmOptions & { onAnswer: (ok: boolean) => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      role="alertdialog"
      aria-labelledby="za-confirm-title"
      aria-describedby="za-confirm-message"
      onCancel={(e) => {
        e.preventDefault();
        onAnswer(false);
      }}
      className="za-root m-auto w-[min(22rem,calc(100vw-2rem))] rounded-3xl border-0 bg-white p-5 text-zinc-900 shadow-2xl backdrop:bg-black/40 backdrop:backdrop-blur-sm dark:bg-zinc-900 dark:text-zinc-100"
    >
      <h2 id="za-confirm-title" className="text-center text-[17px] font-semibold">
        {title}
      </h2>
      <p id="za-confirm-message" className="mt-1 text-center text-[15px] leading-snug text-zinc-500 dark:text-zinc-400">
        {message}
      </p>
      <div className="mt-5 grid gap-2">
        <Button variant="danger" onClick={() => onAnswer(true)}>
          {confirmLabel}
        </Button>
        <Button onClick={() => onAnswer(false)}>Cancel</Button>
      </div>
    </dialog>
  );
}
