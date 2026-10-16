import { ChevronDown } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { cx } from "../../lib/cx";

/** Button + region pair (WAI-ARIA disclosure). Content stays out of the DOM until opened. */
export function Disclosure({
  label, icon, children, defaultOpen = false, className, buttonClassName, regionClassName, onOpenChange, count,
}: {
  label: ReactNode;
  icon?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
  buttonClassName?: string;
  regionClassName?: string;
  onOpenChange?: (open: boolean) => void;
  count?: number;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div className={className}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => { setOpen((o) => !o); onOpenChange?.(!open); }}
        className={cx(
          "inline-flex items-center gap-1.5 rounded-md text-[13.5px] font-medium text-accent transition-colors duration-150 hover:text-text",
          buttonClassName,
        )}
      >
        {icon}
        <span>{label}</span>
        {count !== undefined && <span className="mono text-[12.5px] text-subtle">({count})</span>}
        <ChevronDown aria-hidden className={cx("size-4 transition-transform duration-150 motion-reduce:transition-none", open && "rotate-180")} />
      </button>
      <div id={id} role="region" aria-label={typeof label === "string" ? label : undefined} hidden={!open} className={regionClassName}>
        {open && children}
      </div>
    </div>
  );
}
