import { Sparkles } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { cx } from "../../lib/cx";
import { CopilotPanel } from "./CopilotPanel";
import { useSelection } from "./selection";

const read = (k: string) => { try { return localStorage.getItem(k) === "1"; } catch { return false; } };
const write = (k: string, v: boolean) => { try { localStorage.setItem(k, v ? "1" : "0"); } catch { /* storage unavailable */ } };

/**
 * Floating launcher + chat window shared by the case copilot and the dashboard help.
 * The panel stays mounted while minimised, so a half-typed question survives.
 */
export function FloatingCopilot({ storageKey, right = "1.25rem", label, escapeBlocked = false, children }: {
  storageKey: string;
  right?: string;
  /** accessible name of the launcher, e.g. "INQUEST Copilot" */
  label: string;
  /** another overlay (the evidence drawer) owns Escape */
  escapeBlocked?: boolean;
  children: (p: { onClose: () => void; autoFocus: boolean }) => ReactNode;
}) {
  const [open, setOpen] = useState(() => read(storageKey));
  const [focusInput, setFocusInput] = useState(false);
  const launcher = useRef<HTMLButtonElement>(null);
  useEffect(() => write(storageKey, open), [storageKey, open]);
  const show = () => { setFocusInput(true); setOpen(true); };
  const hide = () => { setOpen(false); setFocusInput(false); requestAnimationFrame(() => launcher.current?.focus()); };
  return (
    <>
      <div id="prism-copilot" role="dialog" aria-modal="false" aria-labelledby="copilot-title" hidden={!open}
        onKeyDown={(e) => { if (e.key === "Escape" && !escapeBlocked) { e.stopPropagation(); hide(); } }}
        className="copilot-window fixed bottom-[5.25rem] z-30 flex h-[min(560px,calc(100dvh-9rem))] w-[min(400px,calc(100vw-2.5rem))] flex-col rounded-xl border border-analysis/35 bg-surface p-3"
        style={{ right }}>
        {children({ onClose: hide, autoFocus: open && focusInput })}
      </div>
      <button ref={launcher} type="button" onClick={open ? hide : show} aria-expanded={open} aria-controls="prism-copilot"
        aria-label={open ? `Minimize ${label}` : `Open ${label}`} title={open ? "Minimize" : `Ask ${label}`}
        className={cx(
          "copilot-launcher fixed bottom-5 z-30 flex size-12 items-center justify-center rounded-full border border-analysis/50 bg-elevated text-analysis",
          "transition-[box-shadow,background-color,border-color] duration-200 hover:border-analysis motion-reduce:transition-none",
          open && "border-analysis",
        )}
        style={{ right }}>
        <Sparkles aria-hidden className="size-5" />
      </button>
    </>
  );
}

/**
 * Case copilot: keyed by case in the workspace, and the conversation is loaded per case from the API, so cases
 * never mix. While the evidence drawer is open the widget moves to the drawer's left so cited evidence stays visible.
 */
export function CopilotDock({ caseId, refs, clearRight }: {
  caseId: string;
  refs: Record<string, { type: string; title: string }>;
  /** width of a right-hand column the widget must not cover (the Review decision panel) */
  clearRight?: string;
}) {
  const sel = useSelection();
  const right = sel.drawerOpen ? "calc(min(460px, 100vw) + 1.5rem)" : clearRight ? `calc(${clearRight} + 1.75rem)` : "1.25rem";
  return (
    <FloatingCopilot storageKey="prism.copilotOpen" right={right} label="INQUEST Copilot" escapeBlocked={sel.drawerOpen}>
      {({ onClose, autoFocus }) => <CopilotPanel caseId={caseId} refs={refs} onClose={onClose} autoFocus={autoFocus} />}
    </FloatingCopilot>
  );
}
