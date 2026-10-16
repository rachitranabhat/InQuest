import { useId, type ReactNode } from "react";
import { useAppOptional } from "../../app/AppContext";
import { Tip } from "./Primitives";

/**
 * A plain-language term with its technical name and definition in a tooltip.
 * Focusable so keyboard users get the same explanation; screen readers get it as a description.
 */
export function Term({ term, children }: { term: string; children?: ReactNode }) {
  const config = useAppOptional()?.config;
  const id = useId();
  const t = config?.terms?.[term];
  if (!t) return <>{children ?? term}</>;
  return (
    <>
      <Tip content={<span><span className="font-medium">{term}</span> <span className="text-subtle">(technical: {t.technical})</span><br />{t.definition}</span>}>
        <span tabIndex={0} aria-describedby={id}
          className="cursor-help underline decoration-border-strong decoration-dotted underline-offset-[3px]">
          {children ?? term}
        </span>
      </Tip>
      <span id={id} className="sr-only">{t.definition} Technical term: {t.technical}.</span>
    </>
  );
}
