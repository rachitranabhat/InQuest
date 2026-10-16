import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, storedSession, storeSession } from "../lib/api";
import { setDisplayTimezone } from "../lib/format";
import type { AiMode, AppConfig, Session } from "../types/api";

interface AppState {
  config: AppConfig | undefined;
  configError: Error | null;
  session: Session | null;
  signIn: (reviewerId: string, accessCode?: string) => Promise<void>;
  signOut: () => void;
  aiMode: AiMode;
  setAiMode: (m: AiMode) => void;
  /** Senior investigator / admin role in the simulated session. UI only — the server enforces it on every request. */
  isSenior: boolean;
}

const Ctx = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const { data: config, error } = useQuery({ queryKey: ["config"], queryFn: api.config, staleTime: 60_000 });
  const [session, setSession] = useState<Session | null>(() => storedSession());
  const [aiMode, setAiModeState] = useState<AiMode>(() => {
    try {
      return (localStorage.getItem("prism.aiMode") as AiMode) || "deterministic";
    } catch {
      return "deterministic";
    }
  });

  useEffect(() => {
    if (config) {
      setDisplayTimezone(config.branding.display_timezone);
      document.title = `${config.branding.product_name} · ${config.branding.tagline}`;
      if (!config.llm_available && aiMode === "llm") setAiModeState("deterministic");
    }
  }, [config, aiMode]);

  const signIn = useCallback(async (reviewerId: string, accessCode?: string) => {
    const s = await api.startSession(reviewerId, accessCode);
    storeSession(s);
    setSession(s);
    qc.removeQueries({ queryKey: ["restricted"] });
    qc.removeQueries({ queryKey: ["admin"] });
    qc.invalidateQueries();
  }, [qc]);

  const signOut = useCallback(() => {
    storeSession(null);
    setSession(null);
    qc.removeQueries({ queryKey: ["restricted"] });
    qc.removeQueries({ queryKey: ["admin"] });
  }, [qc]);

  const setAiMode = useCallback((m: AiMode) => {
    setAiModeState(m);
    try {
      localStorage.setItem("prism.aiMode", m);
    } catch {
      /* ignore */
    }
  }, []);

  const isSenior = !!session && (config?.senior_roles ?? ["Senior investigator", "Admin"]).includes(session.reviewer.role);
  const value = useMemo(
    () => ({ config, configError: (error as Error) ?? null, session, signIn, signOut, aiMode, setAiMode, isSenior }),
    [config, error, session, signIn, signOut, aiMode, setAiMode, isSenior],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** For leaf components that can render without the app shell (e.g. in isolation tests). */
export function useAppOptional(): AppState | null {
  return useContext(Ctx);
}

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp outside AppProvider");
  return v;
}
