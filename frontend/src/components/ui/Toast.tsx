import { CheckCircle2, AlertCircle, X } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { cx } from "../../lib/cx";

type Tone = "success" | "error" | "info";
interface ToastItem { id: number; tone: Tone; title: string; body?: string }
interface ToastApi { push: (t: Omit<ToastItem, "id">) => void }

const Ctx = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const n = useRef(0);
  const dismiss = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), []);
  const push = useCallback((t: Omit<ToastItem, "id">) => {
    const id = ++n.current;
    setItems((xs) => [...xs.slice(-3), { ...t, id }]);
    window.setTimeout(() => dismiss(id), t.tone === "error" ? 9000 : 5000);
  }, [dismiss]);
  const api = useMemo(() => ({ push }), [push]);
  return (
    <Ctx.Provider value={api}>
      {children}
      <div aria-live="polite" aria-atomic="false" className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2">
        {items.map((t) => (
          <div
            key={t.id}
            role={t.tone === "error" ? "alert" : "status"}
            className={cx(
              "pointer-events-auto flex items-start gap-3 rounded-lg border bg-elevated p-3 shadow-xl animate-drawer-in",
              t.tone === "success" ? "border-success/60" : t.tone === "error" ? "border-critical/60" : "border-border-strong",
            )}
          >
            {t.tone === "error" ? (
              <AlertCircle aria-hidden className="mt-0.5 size-5 shrink-0 text-critical" />
            ) : (
              <CheckCircle2 aria-hidden className="mt-0.5 size-5 shrink-0 text-success" />
            )}
            <div className="min-w-0 flex-1">
              <p className="text-[14px] font-medium">{t.title}</p>
              {t.body && <p className="mt-0.5 break-words text-[13px] text-muted">{t.body}</p>}
            </div>
            <button className="rounded p-1 text-subtle hover:bg-hover hover:text-text" aria-label="Dismiss notification" onClick={() => dismiss(t.id)}>
              <X aria-hidden className="size-4" />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast(): ToastApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("useToast outside ToastProvider");
  return v;
}
