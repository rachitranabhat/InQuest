import { LockKeyhole } from "lucide-react";
import type { ReactNode } from "react";
import { useApp } from "../../app/AppContext";

/**
 * Route guard for senior-only pages. This only avoids showing an empty page: the server checks the
 * session's role on every restricted request and answers 401/403 regardless of what the browser shows.
 */
export function SeniorGate({ children, title }: { children: ReactNode; title: string }) {
  const { session, isSenior } = useApp();
  if (isSenior) return <>{children}</>;
  return (
    <div className="mx-auto max-w-xl p-6">
      <div role="alert" className="panel p-5">
        <p className="flex items-center gap-2 text-[16px] font-semibold"><LockKeyhole aria-hidden className="size-5 text-warning" /> {title}</p>
        <p className="mt-2 text-[14px] text-muted">
          {session
            ? `${session.reviewer.display_name} (${session.reviewer.role}) does not have senior investigator access.`
            : "Choose a reviewer first."}{" "}
          This page is available to the Senior investigator role in the simulated session.
        </p>
        <p className="mt-2 text-[12.5px] text-subtle">Roles come from a simulated reviewer session, not real sign-in.</p>
      </div>
    </div>
  );
}

export function DemoAuthNotice() {
  return (
    <p role="note" className="rounded-md border border-warning/50 bg-warning/5 px-3 py-2 text-[13px] text-muted">
      <span className="font-medium text-warning">Role-based demo, not production authorization. </span>
      The server checks the reviewer role on every request, but the reviewer session itself is simulated: anyone using this
      demo can choose any reviewer. All records are synthetic and identity details are fictional.
    </p>
  );
}
