import { BarChart3, BookOpen, Database, FlaskConical, GitCompareArrows, History, Inbox, Menu, PanelLeftClose, PanelLeftOpen, ShieldAlert, ShieldCheck, Sparkles, UserRound, X } from "lucide-react";
import { useEffect, useState, type ReactElement } from "react";
import { matchPath, NavLink, Outlet, useLocation } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { useApp } from "../../app/AppContext";
import { api } from "../../lib/api";
import { cx } from "../../lib/cx";
import { Tip } from "../ui/Primitives";
import { useToast } from "../ui/Toast";
import { GuideDock } from "../../features/workspace/GuidePanel";
import { ThemeToggle } from "./ThemeToggle";

const NAV = [
  { to: "/", label: "Queue", icon: Inbox, end: true },
  { to: "/compare", label: "Compare", icon: GitCompareArrows },
  { to: "/scenarios", label: "Scenario Lab", icon: FlaskConical },
  { to: "/reports", label: "Reports & history", icon: History },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/methodology", label: "Data & Methodology", icon: BookOpen },
];
// Shown only to the Senior investigator role. Hiding the links is convenience only: the API refuses other roles.
const SENIOR_NAV = [
  { to: "/restricted", label: "Restricted Records", icon: ShieldCheck, end: false },
  { to: "/data", label: "Data Management", icon: Database, end: false },
];

function LogoMark() {
  return (
    <svg aria-hidden viewBox="0 0 32 32" className="size-7 shrink-0">
      <rect width="32" height="32" rx="7" fill="#19283D" />
      <path d="M16 5 27 25H5Z" fill="none" stroke="#60CFFF" strokeWidth="2.4" strokeLinejoin="round" />
      <path d="M16 5v20" stroke="#9FA9FF" strokeWidth="1.6" />
    </svg>
  );
}

function Logo({ name }: { name: string }) {
  return (
    <span className="flex items-center gap-2.5">
      <svg aria-hidden viewBox="0 0 32 32" className="size-7">
        <rect width="32" height="32" rx="7" fill="#19283D" />
        <path d="M16 5 27 25H5Z" fill="none" stroke="#60CFFF" strokeWidth="2.4" strokeLinejoin="round" />
        <path d="M16 5v20" stroke="#9FA9FF" strokeWidth="1.6" />
      </svg>
      <span className="hidden text-[17px] font-semibold tracking-tight min-[480px]:inline">{name}</span>
    </span>
  );
}

function SessionPicker() {
  const { session, signIn, signOut, config } = useApp();
  const [code, setCode] = useState("");
  const needCode = !!config?.access_code_required && !session;
  const toast = useToast();
  const { data: reviewers } = useQuery({ queryKey: ["reviewers"], queryFn: api.reviewers, staleTime: Infinity });
  return (
    <div className="flex items-center gap-2">
      <UserRound aria-hidden className="hidden size-4 text-subtle sm:block" />
      {needCode && (
        <>
          <label htmlFor="access-code" className="sr-only">Demo access code</label>
          <input id="access-code" type="password" autoComplete="off" placeholder="Access code" value={code}
            onChange={(e) => setCode(e.target.value)} className="field h-8 w-[7.5rem] py-0 text-[13px]" />
        </>
      )}
      <label htmlFor="reviewer-select" className="sr-only">Simulated reviewer session</label>
      <select
        id="reviewer-select"
        className="field h-8 w-[6.75rem] min-w-0 py-0 pr-6 text-[13px] sm:w-auto sm:pr-8"
        value={session?.reviewer.reviewer_id ?? ""}
        onChange={async (e) => {
          const v = e.target.value;
          if (!v) return signOut();
          try {
            await signIn(v, code || undefined);
            setCode("");
            toast.push({ tone: "success", title: "Simulated session started", body: "Demo session — not real authentication." });
          } catch (err) {
            toast.push({ tone: "error", title: "Could not start session", body: (err as Error).message });
          }
        }}
      >
        <option value="">Choose reviewer…</option>
        {(reviewers ?? []).map((r) => (
          <option key={r.reviewer_id} value={r.reviewer_id}>
            {r.display_name} · {r.role}
          </option>
        ))}
      </select>
      <Tip content="Simulated reviewer session. It identifies who recorded an action; it is not authentication.">
        <span tabIndex={0} className="hidden rounded border border-warning/50 px-1.5 py-0.5 text-[11.5px] font-medium text-warning sm:inline">
          Simulated
        </span>
      </Tip>
    </div>
  );
}

function AiModeSwitch() {
  const { config, aiMode, setAiMode } = useApp();
  const llmOk = !!config?.llm_available;
  return (
    <div role="radiogroup" aria-label="AI writing mode" className="flex rounded-md border border-border-strong p-0.5 text-[13px]">
      {(["deterministic", "llm"] as const).map((m) => {
        const disabled = m === "llm" && !llmOk;
        const checked = aiMode === m;
        const btn = (
          <button
            key={m}
            role="radio"
            aria-checked={checked}
            aria-disabled={disabled || undefined}
            onClick={() => !disabled && setAiMode(m)}
            className={cx(
              "flex h-7 items-center gap-1.5 rounded px-2 font-medium sm:px-2.5 transition-colors duration-150",
              checked ? "bg-elevated text-text" : "text-muted hover:text-text",
              disabled && "cursor-not-allowed opacity-55 hover:text-muted",
            )}
          >
            {m === "llm" && <Sparkles aria-hidden className="hidden size-3.5 text-analysis sm:block" />}
            {m === "deterministic" ? "Demo" : "LLM"}
          </button>
        );
        return disabled ? (
          <Tip key={m} content="LLM mode needs OPENAI_API_KEY in the server's .env file.">{btn}</Tip>
        ) : (
          btn
        );
      })}
    </div>
  );
}

const RAIL_KEY = "prism.sidebarCollapsed";

/** Tooltip with the page name, only when the sidebar is collapsed to icons. */
function RailTip({ on, label, children }: { on: boolean; label: string; children: ReactElement }) {
  return on ? <Tip content={label}>{children}</Tip> : children;
}

export function AppShell() {
  const { config, configError, isSenior } = useApp();
  const [navOpen, setNavOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => setNavOpen(false), [loc.pathname]);
  // Desktop sidebar: expanded (icons + labels) or collapsed (icons only). Remembered across pages and reloads.
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem(RAIL_KEY) === "1"; } catch { return false; } });
  useEffect(() => { try { localStorage.setItem(RAIL_KEY, collapsed ? "1" : "0"); } catch { /* storage unavailable */ } }, [collapsed]);
  const slim = collapsed && !navOpen; // the small-screen overlay always shows labels
  const name = config?.branding.product_name ?? "INQUEST";
  return (
    <div className="flex min-h-dvh flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[70] focus:rounded-md focus:bg-accent focus:px-3 focus:py-2 focus:text-accent-ink">
        Skip to main content
      </a>
      <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b sm:gap-3 border-border bg-bg/95 px-3 backdrop-blur sm:px-4">
        <button className="rounded-md p-2 text-muted hover:bg-hover hover:text-text lg:hidden" aria-label={navOpen ? "Close navigation" : "Open navigation"}
          aria-expanded={navOpen} aria-controls="primary-nav" onClick={() => setNavOpen((o) => !o)}>
          {navOpen ? <X aria-hidden className="size-5" /> : <Menu aria-hidden className="size-5" />}
        </button>
        <NavLink to="/" className="text-text no-underline hover:no-underline lg:hidden" aria-label={`${name} home`}>
          <Logo name={name} />
        </NavLink>
        <div className="ml-auto flex min-w-0 items-center gap-1.5 sm:gap-3">
          <AiModeSwitch />
          <SessionPicker />
          <ThemeToggle />
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <nav
          id="primary-nav"
          aria-label="Primary"
          className={cx(
            "z-20 flex w-60 shrink-0 flex-col overflow-hidden border-r border-border bg-bg pb-4 pt-3",
            "fixed inset-y-14 left-0 transition-[transform,width] duration-200 ease-out motion-reduce:transition-none",
            "lg:static lg:visible lg:translate-x-0",
            slim ? "px-2 lg:w-[3.75rem]" : "px-3",
            navOpen ? "translate-x-0" : "invisible -translate-x-full",
          )}
        >
          <div className={cx("mb-3 hidden items-center lg:flex", slim ? "flex-col gap-2" : "gap-2")}>
            <NavLink to="/" aria-label={`${name} home`} className="min-w-0 text-text no-underline hover:no-underline">
              {slim ? <span className="block"><LogoMark /></span> : (
                <span className="flex min-w-0 flex-col">
                  <span className="flex items-center gap-2"><LogoMark /><span className="text-[16.5px] font-semibold tracking-tight">{name}</span></span>
                </span>
              )}
            </NavLink>
            <Tip content={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
              <button type="button" onClick={() => setCollapsed((v) => !v)} aria-controls="primary-nav" aria-expanded={!collapsed}
                aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                className={cx("rounded-md p-1.5 text-subtle transition-colors duration-150 hover:bg-hover hover:text-text", !slim && "ml-auto")}>
                {collapsed ? <PanelLeftOpen aria-hidden className="size-[18px]" /> : <PanelLeftClose aria-hidden className="size-[18px]" />}
              </button>
            </Tip>
          </div>
          {!slim && config?.branding.tagline && (
            <p className="-mt-1.5 mb-3 hidden px-0.5 text-[12px] leading-snug text-subtle lg:block">{config.branding.tagline}</p>
          )}
          <ul className="space-y-0.5">
            {(isSenior ? [...NAV, ...SENIOR_NAV] : NAV).map(({ to, label, icon: Icon, end }) => (
              <li key={to}>
                <RailTip on={slim} label={label}>
                <NavLink
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    cx(
                      "relative flex items-center gap-2.5 rounded-md py-2 text-[14px] font-medium no-underline transition-colors duration-150 hover:no-underline",
                      slim ? "justify-center px-3 lg:px-0" : "px-3",
                      isActive ? cx("bg-elevated text-text before:absolute before:inset-y-1.5 before:w-[3px] before:rounded-r before:bg-accent", slim ? "before:-left-2" : "before:-left-3")
                        : "text-muted hover:bg-hover hover:text-text",
                    )
                  }
                >
                  <Icon aria-hidden className="size-[18px] shrink-0" />
                  <span className={cx("truncate", slim && "lg:sr-only")}>{label}</span>
                </NavLink>
                </RailTip>
              </li>
            ))}
          </ul>
          {slim ? (
            <Tip content={config?.branding.disclaimer ?? "Synthetic data only."}>
              <span tabIndex={0} role="img" aria-label={`Synthetic data. ${config?.branding.disclaimer ?? ""}`}
                className="mx-auto mt-auto hidden rounded-md p-2 text-warning lg:block"><ShieldAlert aria-hidden className="size-4" /></span>
            </Tip>
          ) : (
            <div className="mt-auto rounded-lg border border-border p-3 text-[12px] leading-relaxed text-subtle">
              <p className="flex items-center gap-1.5 font-medium text-warning">
                <ShieldAlert aria-hidden className="size-4" /> Synthetic data
              </p>
              <p className="mt-1">{config?.branding.disclaimer ?? "Synthetic data only."}</p>
            </div>
          )}
        </nav>
        <main id="main" tabIndex={-1} className="min-w-0 flex-1 outline-none">
          {configError ? (
            <div role="alert" className="m-6 rounded-lg border border-critical/60 bg-critical/5 p-4 text-[14px]">
              <p className="font-medium">Cannot reach the INQUEST API</p>
              <p className="mt-1 text-muted">{configError.message} Start it with <code className="mono">python scripts/dev.py</code>.</p>
            </div>
          ) : (
            <Outlet />
          )}
        </main>
        {/* the case workspace has its own case-scoped copilot */}
        {!matchPath("/cases/:caseId", loc.pathname) && <GuideDock />}
      </div>
    </div>
  );
}
