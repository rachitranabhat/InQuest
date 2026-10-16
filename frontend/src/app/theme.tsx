import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Theme = "dark" | "light";
export const THEME_KEY = "prism.theme";

/** Dark is the default; a saved choice wins. index.html applies the saved value before first paint. */
export function readTheme(): Theme {
  try {
    return localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

function apply(t: Theme) {
  const el = document.documentElement;
  el.dataset.theme = t;
  document.querySelector('meta[name="color-scheme"]')?.setAttribute("content", t);
}

const Ctx = createContext<{ theme: Theme; setTheme: (t: Theme) => void }>({ theme: "dark", setTheme: () => {} });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(readTheme);
  useEffect(() => {
    apply(theme);
    try { localStorage.setItem(THEME_KEY, theme); } catch { /* storage unavailable: theme lasts for this page */ }
  }, [theme]);
  // apply before the state update so children that read CSS variables on re-render (the graph) see the new values
  const setTheme = useCallback((t: Theme) => { apply(t); setThemeState(t); }, []);
  const value = useMemo(() => ({ theme, setTheme }), [theme, setTheme]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);
