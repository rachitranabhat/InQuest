import { Moon, Sun } from "lucide-react";
import { useTheme } from "../../app/theme";
import { cx } from "../../lib/cx";
import { Tip } from "../ui/Primitives";

/** Compact sliding switch: sun (light) on the left, moon (dark) on the right. Checked = dark theme. */
export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const dark = theme === "dark";
  return (
    <Tip content={dark ? "Switch to light theme" : "Switch to dark theme"}>
      <button type="button" role="switch" aria-checked={dark} aria-label="Dark theme"
        onClick={() => setTheme(dark ? "light" : "dark")}
        className="relative inline-flex h-7 w-[3.25rem] shrink-0 items-center rounded-full border border-border-strong bg-elevated transition-colors duration-200 hover:border-accent motion-reduce:transition-none">
        <Sun aria-hidden className={cx("absolute left-1.5 size-3.5 transition-colors", dark ? "text-subtle" : "text-warning")} />
        <Moon aria-hidden className={cx("absolute right-1.5 size-3.5 transition-colors", dark ? "text-analysis" : "text-subtle")} />
        <span aria-hidden className={cx(
          "absolute top-[2px] flex size-[22px] items-center justify-center rounded-full border border-border-strong bg-surface shadow-sm",
          "transition-transform duration-200 ease-out motion-reduce:transition-none",
          dark ? "translate-x-[25px]" : "translate-x-[2px]",
        )}>
          {dark ? <Moon className="size-3.5 text-analysis" /> : <Sun className="size-3.5 text-warning" />}
        </span>
      </button>
    </Tip>
  );
}
