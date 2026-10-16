import { Bot, CornerDownLeft, Minus, Sparkles, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useApp } from "../../app/AppContext";
import { ModeBadge } from "../../components/ui/Badges";
import { Button } from "../../components/ui/Button";
import { ErrorState, LoadingBlock } from "../../components/ui/Primitives";
import { useAsk, useChat } from "../../hooks/queries";
import { cx } from "../../lib/cx";
import { utcToLocal } from "../../lib/format";
import type { Claim } from "../../types/api";
import { ClaimRow } from "./ClaimRow";

const FIRST = 3;

export function CopilotPanel({ caseId, refs, onClose, autoFocus = false }: {
  caseId: string;
  refs: Record<string, { type: string; title: string }>;
  /** floating-window mode: shows a case-aware title and a minimise button */
  onClose?: () => void;
  autoFocus?: boolean;
}) {
  const { config, aiMode } = useApp();
  const { data: history, error, isLoading, refetch } = useChat(caseId);
  const ask = useAsk(caseId);
  const [q, setQ] = useState("");
  const [more, setMore] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [history?.length, ask.isPending]);

  useEffect(() => { if (autoFocus) inputRef.current?.focus(); }, [autoFocus]);
  const docked = !!onClose;

  const send = async (question: string) => {
    const text = question.trim();
    if (!text || ask.isPending) return;
    setQ("");
    try {
      await ask.mutateAsync({ question: text, mode: aiMode });
    } catch {
      setQ(text);
    }
    inputRef.current?.focus();
  };

  const suggested = config?.suggested_questions ?? [];
  const shown = more ? suggested : suggested.slice(0, FIRST);
  return (
    <section aria-labelledby="copilot-title" className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between gap-2">
        <h2 id="copilot-title" className="flex min-w-0 items-center gap-1.5 text-[14px]">
          <Sparkles aria-hidden className="size-4 shrink-0 text-analysis" />
          {docked ? <span className="truncate">INQUEST Copilot <span className="text-subtle">—</span> <span className="mono">{caseId}</span></span> : "Ask the copilot"}
        </h2>
        <span className="ml-auto shrink-0 text-[11.5px] text-subtle">{aiMode === "llm" ? "LLM mode" : "Demo mode"}</span>
        {onClose && (
          <button type="button" onClick={onClose} aria-label="Minimize copilot" title="Minimize"
            className="-mr-1 shrink-0 rounded-md p-1 text-muted transition-colors duration-150 hover:bg-hover hover:text-text">
            <Minus aria-hidden className="size-4" />
          </button>
        )}
      </div>
      <p className="mt-0.5 text-[12px] text-subtle">Answers use only this case's records; every statement is cited and checked.</p>
      <div ref={logRef} className={cx("relative mt-2 min-h-0 flex-1 space-y-2.5 overflow-y-auto", !docked && "max-h-[min(36vh,420px)]")}
        aria-live="polite" aria-relevant="additions">
        {error ? <ErrorState error={error} onRetry={() => refetch()} title="Could not load the conversation" />
          : isLoading ? <LoadingBlock label="Loading conversation" lines={2} />
          : !(history ?? []).length && !ask.isPending ? (
            <p className="text-[13px] text-muted">Ask about this case. The copilot never decides whether fraud occurred.</p>
          ) : (history ?? []).map((m) =>
            m.role === "user" ? (
              <div key={m.message_id} className="flex justify-end">
                <div className="max-w-[90%] rounded-lg bg-elevated px-2.5 py-1.5 text-[13.5px]">
                  <span className="sr-only">You asked: </span>
                  <UserRound aria-hidden className="mr-1 inline size-3.5 text-subtle" />{m.content}
                </div>
              </div>
            ) : (
              <Answer key={m.message_id} claims={m.payload.claims ?? []} mode={m.mode ?? "deterministic"} note={m.payload.note ?? null}
                at={m.created_at_utc} refs={refs} idBase={m.message_id} tools={(m.payload.tool_calls ?? []).map((t) => t.tool)} />
            ),
          )}
        {ask.isPending && (
          <div role="status" className="flex items-center gap-2 text-[13px] text-muted">
            <Bot aria-hidden className="size-4 animate-pulse text-analysis" /> Querying case records…
          </div>
        )}
        {ask.error && <ErrorState error={ask.error} title="The copilot could not answer" />}
      </div>
      <div className="mt-2">
        <div className="mb-1.5 flex flex-wrap gap-1" role="group" aria-label="Suggested questions">
          {shown.map((s) => (
            <button key={s} type="button" disabled={ask.isPending} onClick={() => send(s)}
              className="rounded-full border border-border-strong px-2 py-0.5 text-left text-[12px] text-muted transition-colors hover:border-accent hover:text-text disabled:opacity-55">
              {s}
            </button>
          ))}
          {suggested.length > FIRST && (
            <button type="button" onClick={() => setMore((m) => !m)} aria-expanded={more}
              className="rounded-full px-2 py-0.5 text-[12px] text-accent hover:text-text">
              {more ? "Fewer" : `${suggested.length - FIRST} more`}
            </button>
          )}
        </div>
        <form onSubmit={(e) => { e.preventDefault(); send(q); }} className="flex items-end gap-1.5">
          <label htmlFor="copilot-input" className="sr-only">Ask a question about this case</label>
          <textarea id="copilot-input" ref={inputRef} rows={2} maxLength={1000} className="field min-h-[40px] resize-none py-1.5 text-[13.5px]"
            placeholder="e.g. What happened on October 11?" value={q} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(q); } }} />
          <Button type="submit" variant="primary" loading={ask.isPending} disabled={!q.trim()} aria-label="Send question"
            icon={<CornerDownLeft aria-hidden className="size-4" />} />
        </form>
      </div>
    </section>
  );
}

function Answer({ claims, mode, note, at, refs, idBase, tools }: {
  claims: Claim[]; mode: string; note: string | null; at: string; refs: Record<string, { type: string; title: string }>;
  idBase: string; tools: string[];
}) {
  return (
    <article aria-label="Copilot answer" className="rounded-lg border border-analysis/30 bg-analysis/[0.04] px-1.5 py-1.5">
      <header className="mb-0.5 flex flex-wrap items-center gap-1.5 px-1 text-[11.5px] text-subtle">
        <Bot aria-hidden className="size-3.5 text-analysis" />
        <span className="font-medium text-analysis">Copilot</span>
        <ModeBadge mode={mode} />
        <span>{utcToLocal(at, false)}</span>
        {tools.length > 0 && <span className="mono truncate" title={Array.from(new Set(tools)).join(", ")}>via {new Set(tools).size} quer{new Set(tools).size === 1 ? "y" : "ies"}</span>}
      </header>
      {note && <p className="mx-1 mb-1 rounded border border-warning/50 bg-warning/5 px-2 py-1 text-[12.5px]">{note}</p>}
      <ul className="space-y-0.5">
        {claims.map((c, i) => <ClaimRow key={i} claim={c} refs={refs} idBase={`${idBase}-${i}`} />)}
      </ul>
    </article>
  );
}
