import { Bot, CornerDownLeft, Minus, Sparkles, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { useApp } from "../../app/AppContext";
import { Button } from "../../components/ui/Button";
import { ErrorState } from "../../components/ui/Primitives";
import { api } from "../../lib/api";
import type { GuideAnswer } from "../../types/api";
import { FloatingCopilot } from "./CopilotDock";

const FIRST = 3;
type Msg = { id: number; q: string; a: GuideAnswer | null; error?: unknown };

/** Dashboard copilot: help with PRISM itself. Calls /api/guide, which has no access to case or identity records. */
export function GuideDock() {
  return (
    <FloatingCopilot storageKey="prism.guideOpen" label="INQUEST Copilot">
      {({ onClose, autoFocus }) => <GuidePanel onClose={onClose} autoFocus={autoFocus} />}
    </FloatingCopilot>
  );
}

function GuidePanel({ onClose, autoFocus }: { onClose: () => void; autoFocus: boolean }) {
  const { config } = useApp();
  const [msgs, setMsgs] = useState<Msg[]>([]);       // this page visit only; nothing is stored
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [more, setMore] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { if (autoFocus) inputRef.current?.focus(); }, [autoFocus]);
  useEffect(() => { const el = logRef.current; if (el) el.scrollTop = el.scrollHeight; }, [msgs.length, busy]);

  const send = async (question: string) => {
    const text = question.trim();
    if (!text || busy) return;
    setQ("");
    setBusy(true);
    const id = Date.now();
    try {
      const a = await api.guide(text);
      setMsgs((m) => [...m, { id, q: text, a }]);
    } catch (e) {
      setMsgs((m) => [...m, { id, q: text, a: null, error: e }]);
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  };
  const suggested = config?.guide_suggested_questions ?? [];
  const shown = more ? suggested : suggested.slice(0, FIRST);

  return (
    <section aria-labelledby="copilot-title" className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between gap-2">
        <h2 id="copilot-title" className="flex min-w-0 items-center gap-1.5 text-[14px]">
          <Sparkles aria-hidden className="size-4 shrink-0 text-analysis" />
          <span className="truncate">INQUEST Copilot <span className="text-subtle">—</span> Dashboard help</span>
        </h2>
        <button type="button" onClick={onClose} aria-label="Minimize copilot" title="Minimize"
          className="-mr-1 ml-auto shrink-0 rounded-md p-1 text-muted transition-colors duration-150 hover:bg-hover hover:text-text">
          <Minus aria-hidden className="size-4" />
        </button>
      </div>
      <p className="mt-0.5 text-[12px] text-subtle">Explains pages, terms and the review workflow. It has no access to case records; open a case to ask about it.</p>
      <div ref={logRef} className="mt-2 min-h-0 flex-1 space-y-2.5 overflow-y-auto" aria-live="polite" aria-relevant="additions">
        {!msgs.length && !busy && <p className="text-[13px] text-muted">Ask how INQUEST works, or pick a suggestion below.</p>}
        {msgs.map((m) => (
          <div key={m.id} className="space-y-1.5">
            <div className="flex justify-end">
              <div className="max-w-[90%] rounded-lg bg-elevated px-2.5 py-1.5 text-[13.5px]">
                <span className="sr-only">You asked: </span><UserRound aria-hidden className="mr-1 inline size-3.5 text-subtle" />{m.q}
              </div>
            </div>
            {m.error ? <ErrorState error={m.error} title="Help is unavailable" /> : m.a && (
              <article aria-label="Copilot answer" className="rounded-lg border border-analysis/30 bg-analysis/[0.04] px-2.5 py-1.5 text-[13.5px]">
                <header className="mb-0.5 flex items-center gap-1.5 text-[11.5px] text-subtle">
                  <Bot aria-hidden className="size-3.5 text-analysis" /><span className="font-medium text-analysis">Copilot</span>
                  <span>Help · no case data</span>
                </header>
                {m.a.answer.map((p, i) => <p key={i} className="mt-1 first:mt-0">{p}</p>)}
                {m.a.links.length > 0 && (
                  <p className="mt-1.5 flex flex-wrap gap-x-3">{m.a.links.map((l) => <Link key={l.to} to={l.to} className="text-[13px]">{l.label}</Link>)}</p>
                )}
              </article>
            )}
          </div>
        ))}
        {busy && <div role="status" className="flex items-center gap-2 text-[13px] text-muted"><Bot aria-hidden className="size-4 animate-pulse text-analysis" /> Looking that up…</div>}
      </div>
      <div className="mt-2">
        <div className="mb-1.5 flex flex-wrap gap-1" role="group" aria-label="Suggested questions">
          {shown.map((s) => (
            <button key={s} type="button" disabled={busy} onClick={() => send(s)}
              className="rounded-full border border-border-strong px-2 py-0.5 text-left text-[12px] text-muted transition-colors hover:border-accent hover:text-text disabled:opacity-55">
              {s}
            </button>
          ))}
          {suggested.length > FIRST && (
            <button type="button" onClick={() => setMore((v) => !v)} aria-expanded={more} className="rounded-full px-2 py-0.5 text-[12px] text-accent hover:text-text">
              {more ? "Fewer" : `${suggested.length - FIRST} more`}
            </button>
          )}
        </div>
        <form onSubmit={(e) => { e.preventDefault(); send(q); }} className="flex items-end gap-1.5">
          <label htmlFor="copilot-input" className="sr-only">Ask a question about INQUEST</label>
          <textarea id="copilot-input" ref={inputRef} rows={2} maxLength={1000} className="field min-h-[40px] resize-none py-1.5 text-[13.5px]"
            placeholder="e.g. What does the alert score mean?" value={q} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(q); } }} />
          <Button type="submit" variant="primary" loading={busy} disabled={!q.trim()} aria-label="Send question" icon={<CornerDownLeft aria-hidden className="size-4" />} />
        </form>
      </div>
    </section>
  );
}
