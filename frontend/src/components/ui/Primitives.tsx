import * as RDialog from "@radix-ui/react-dialog";
import * as RTooltip from "@radix-ui/react-tooltip";
import { AlertCircle, Inbox, RotateCcw, X } from "lucide-react";
import type { ReactNode } from "react";
import { cx } from "../../lib/cx";
import { Button } from "./Button";

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cx("skeleton", className)} />;
}

export function LoadingBlock({ label = "Loading", lines = 4 }: { label?: string; lines?: number }) {
  return (
    <div role="status" aria-live="polite" className="space-y-2 p-4">
      <span className="sr-only">{label}…</span>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={cx("h-4", i % 3 === 2 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  );
}

export function ErrorState({ error, onRetry, title = "Something went wrong" }: { error: unknown; onRetry?: () => void; title?: string }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className="m-4 flex items-start gap-3 rounded-lg border border-critical/50 bg-critical/5 p-4">
      <AlertCircle aria-hidden className="mt-0.5 size-5 shrink-0 text-critical" />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-text">{title}</p>
        <p className="mt-1 break-words text-[14px] text-muted">{msg}</p>
        {onRetry && (
          <Button size="sm" className="mt-3" onClick={onRetry} icon={<RotateCcw aria-hidden className="size-4" />}>
            Try again
          </Button>
        )}
      </div>
    </div>
  );
}

export function EmptyState({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-10 text-center">
      <div className="mb-3 text-subtle">{icon ?? <Inbox aria-hidden className="size-7" />}</div>
      <p className="font-medium text-text">{title}</p>
      {children && <div className="mt-1 max-w-md text-[14px] text-muted">{children}</div>}
    </div>
  );
}

export function Tip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <RTooltip.Root delayDuration={300}>
      <RTooltip.Trigger asChild>{children}</RTooltip.Trigger>
      <RTooltip.Portal>
        <RTooltip.Content
          sideOffset={6}
          className="z-50 max-w-xs rounded-md border border-border-strong bg-elevated px-2.5 py-1.5 text-[13px] text-text shadow-lg animate-fade-in"
        >
          {content}
          <RTooltip.Arrow className="fill-elevated" />
        </RTooltip.Content>
      </RTooltip.Portal>
    </RTooltip.Root>
  );
}

export function Modal({
  open, onOpenChange, title, description, children, footer, wide = false,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="fixed inset-0 z-40 bg-black/60 animate-fade-in" />
        <RDialog.Content
          className={cx(
            "fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto",
            "rounded-lg border border-border-strong bg-surface shadow-2xl animate-fade-in",
            wide ? "max-w-2xl" : "max-w-lg",
          )}
        >
          <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
            <div>
              <RDialog.Title className="text-[17px] font-semibold">{title}</RDialog.Title>
              {description && <RDialog.Description className="mt-1 text-[14px] text-muted">{description}</RDialog.Description>}
            </div>
            <RDialog.Close asChild>
              <Button variant="ghost" size="sm" aria-label="Close dialog" icon={<X aria-hidden className="size-4" />} />
            </RDialog.Close>
          </div>
          <div className="px-5 py-4">{children}</div>
          {footer && <div className="flex justify-end gap-2 border-t border-border px-5 py-3">{footer}</div>}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  );
}

export function SectionTitle({ children, aside, id }: { children: ReactNode; aside?: ReactNode; id?: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <h2 id={id} className="text-[15px] font-semibold">{children}</h2>
      {aside}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="min-w-0">
      <dt className="eyebrow">{label}</dt>
      <dd className="mt-1 truncate text-[22px] font-semibold tabular-nums" title={typeof value === "string" ? value : undefined}>{value}</dd>
      {hint && <dd className="text-[13px] text-subtle">{hint}</dd>}
    </div>
  );
}
