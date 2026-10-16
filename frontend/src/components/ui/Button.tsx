import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { cx } from "../../lib/cx";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "warning";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-accent text-accent-ink border-accent hover:brightness-110 glow-accent-soft active:brightness-95",
  secondary: "bg-elevated text-text border-border-strong hover:border-muted hover:bg-hover active:bg-elevated",
  ghost: "bg-transparent text-muted border-transparent hover:text-text hover:bg-hover active:bg-elevated",
  danger:
    "bg-transparent text-critical border-critical/70 hover:bg-critical/10 hover:border-critical active:bg-critical/15",
  warning:
    "bg-transparent text-warning border-warning/70 hover:bg-warning/10 hover:border-warning active:bg-warning/15",
};
const SIZES: Record<Size, string> = { sm: "h-8 px-2.5 text-[13px] gap-1.5", md: "h-9 px-3.5 text-[14px] gap-2" };

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading = false, icon, className, children, disabled, type = "button", ...rest },
  ref,
) {
  const isDisabled = disabled || loading;
  return (
    <button
      ref={ref}
      type={type}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      className={cx(
        "inline-flex select-none items-center justify-center whitespace-nowrap rounded-md border font-medium",
        "transition-[filter,background-color,border-color,box-shadow,color] duration-150",
        "active:translate-y-px disabled:cursor-not-allowed disabled:opacity-55 disabled:active:translate-y-0",
        "disabled:hover:shadow-none disabled:hover:brightness-100",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 aria-hidden className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
});
