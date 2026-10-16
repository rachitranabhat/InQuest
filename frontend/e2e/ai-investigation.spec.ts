import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

// AI Investigation tab. Simulated runs hit the real backend (runs execute in the background and are saved in
// the V2 database). The "live", "partial", "failed" and "running" states use MOCKED API responses (page.route)
// because the sandbox has no OpenAI access; they test labelling and state handling only.

async function prep(page: Page) {
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.locator("#reviewer-select").selectOption("REV-01");
  await expect.poll(() => page.evaluate(() => JSON.parse(sessionStorage.getItem("prism.session") ?? "null")?.reviewer?.reviewer_id)).toBe("REV-01");
}
async function openTab(page: Page, caseId: string) {
  await page.goto(`/cases/${caseId}`, { waitUntil: "domcontentloaded" });
  await page.getByRole("tab", { name: "AI Investigation" }).click();
}
const lead = (page: Page) => page.getByRole("region", { name: /Lead investigator/ });
function countPosts(page: Page, caseId: string) {
  const n = { v: 0 };
  page.on("request", (r) => { if (r.method() === "POST" && r.url().endsWith(`/api/cases/${caseId}/investigations`)) n.v++; });
  return n;
}

test("simulated investigation: concise lead, citations, history, persistence, status unchanged", async ({ page }) => {
  await prep(page);
  const caseId = "CASE-18007";
  const before = await (await page.request.get(`/api/cases/${caseId}`)).json();
  const posts = countPosts(page, caseId);
  await openTab(page, caseId);
  await page.getByRole("button", { name: /Run AI Investigation|Run again/ }).click();
  await expect(lead(page)).toBeVisible({ timeout: 30_000 });
  expect(posts.v).toBe(1);
  await expect(page.getByTestId("run-label")).toHaveText("Simulated analysis");
  await expect(lead(page).getByTestId("lead-assessment")).toHaveText(/Suspicion supported|Concern reduced|Inconclusive|Insufficient evidence/);
  const summary = (await lead(page).getByTestId("lead-summary").textContent())!.trim();
  expect(summary.length).toBeGreaterThan(10);
  expect(summary.match(/[.!?](\s|$)/g)?.length ?? 1).toBeLessThanOrEqual(1);   // one sentence
  await expect(lead(page)).toContainText("Next step");
  for (const t of ["Points toward suspicion", "Possible ordinary explanations", "Missing information"]) await expect(lead(page)).toContainText(t);
  for (const sel of ["Points toward suspicion", "Possible ordinary explanations"]) {
    const n = await lead(page).locator("h4", { hasText: sel }).locator("xpath=..").locator("[data-finding]").count();
    expect(n).toBeLessThanOrEqual(3);
  }
  // details are collapsed until expanded
  await expect(page.getByRole("region", { name: "Suspicion agent" })).toHaveCount(0);
  await page.getByRole("button", { name: /Agent details/ }).click();
  for (const name of ["Suspicion agent", "Alternative explanation agent"]) {
    await expect(page.getByRole("region", { name }).getByTestId("stage-badge")).toHaveText("Simulated");
    await expect(page.getByRole("region", { name }).locator("[data-finding]").first()).toBeVisible();
  }
  // a citation opens exactly that record in the evidence drawer
  const chip = lead(page).getByRole("button", { name: /^Open evidence EV-\d{6}/ }).first();
  const ev = (await chip.textContent())!.trim();
  await chip.click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByText(ev).first()).toBeVisible();
  await drawer.getByRole("button", { name: "Back to where this evidence was opened" }).click();
  await expect(drawer).toBeHidden();
  const res = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id} ${v.nodes[0]?.target}`)).toEqual([]);

  // tab navigation does not restart or lose the run
  await page.getByRole("tab", { name: "Evidence" }).click();
  await page.getByRole("tab", { name: "AI Investigation" }).click();
  await expect(lead(page)).toBeVisible();
  expect(posts.v).toBe(1);
  const firstId = (await page.locator("main").getByText(/INV-[\w-]+/).first().textContent())!.match(/INV-[\w-]+/)![0];

  // a refresh restores it from the database, without a new run
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("tab", { name: "AI Investigation" }).click();
  await expect(lead(page)).toBeVisible();
  expect(posts.v).toBe(1);

  // an explicit rerun adds history; the earlier run is still selectable and unchanged
  await page.getByRole("button", { name: "Run again" }).click();
  expect(posts.v).toBe(2);
  const picker = page.getByRole("combobox", { name: "Investigation run" });
  await expect.poll(async () => picker.locator("option").count(), { timeout: 30_000 }).toBeGreaterThanOrEqual(2);
  await expect(lead(page)).toBeVisible({ timeout: 30_000 });
  await picker.selectOption(firstId);
  await expect(page.locator("main")).toContainText(firstId);
  await expect(lead(page).getByTestId("lead-summary")).toHaveText(summary);

  const after = await (await page.request.get(`/api/cases/${caseId}`)).json();
  expect([after.status, after.updated_at_utc]).toEqual([before.status, before.updated_at_utc]);
});

test("running state survives tab switches without a new run (MOCKED running record)", async ({ page }) => {
  await prep(page);
  const caseId = "CASE-18007";
  const posts = countPosts(page, caseId);
  const run = { investigation_id: "INV-MOCK-RUN", case_id: caseId, requested_mode: "llm", mode: null, status: "running",
    assessment: null, requested_by: "REV-01", started_at_utc: "2026-10-15T12:00:00Z", finished_at_utc: null, error: null };
  await page.route(`**/api/cases/${caseId}/investigations`, (r: Route) =>
    r.request().method() === "GET" ? r.fulfill({ contentType: "application/json", body: JSON.stringify([run]) }) : r.continue());
  await openTab(page, caseId);
  await expect(page.getByRole("status").filter({ hasText: "Investigation running" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run again" })).toBeDisabled();
  await page.getByRole("tab", { name: "Summary" }).click();
  await page.getByRole("tab", { name: "AI Investigation" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Investigation running" })).toBeVisible();
  expect(posts.v).toBe(0);
});

test("labels: live AI, partial fallback and failed runs are distinguished (MOCKED API responses)", async ({ page }) => {
  await prep(page);
  const caseId = "CASE-18007";
  const h = { "X-Reviewer-Session": await page.evaluate(() => JSON.parse(sessionStorage.getItem("prism.session")!).token) };
  const started = await (await page.request.post(`/api/cases/${caseId}/investigations`, { headers: h, data: { mode: "deterministic" } })).json();
  let base: any;
  await expect.poll(async () => {
    base = await (await page.request.get(`/api/investigations/${started.investigation_id}`, { headers: h })).json();
    return base.status;
  }, { timeout: 30_000 }).toBe("completed");
  const live = { ...base, investigation_id: "INV-MOCK-LIVE", requested_mode: "llm", mode: "llm", model: "gpt-4o-mini",
    agents: { suspicion: { ...base.agents.suspicion, mode: "llm", stage_status: "live" }, alternative: { ...base.agents.alternative, mode: "llm", stage_status: "live_repaired" } },
    lead: { ...base.lead, mode: "llm", stage_status: "live" } };
  const partial = { ...live, investigation_id: "INV-MOCK-PART", mode: "llm_partial_fallback",
    agents: { ...live.agents, alternative: { ...base.agents.alternative, mode: "deterministic", stage_status: "fallback", fallback_reason: "schema error (test)" } } };
  const sum = (r: any, status = "completed", error: string | null = null) => ({ investigation_id: r.investigation_id, case_id: caseId,
    requested_mode: "llm", mode: r.mode, status, assessment: r.lead?.assessment ?? null, requested_by: "REV-01",
    started_at_utc: "2026-10-15T12:00:00Z", finished_at_utc: "2026-10-15T12:01:00Z", error });
  let history: unknown[] = [sum(live)];
  await page.route(`**/api/cases/${caseId}/investigations`, (r: Route) => r.fulfill({ contentType: "application/json", body: JSON.stringify(history) }));
  await page.route("**/api/investigations/INV-MOCK-*", (r: Route) =>
    r.fulfill({ contentType: "application/json", body: JSON.stringify(r.request().url().endsWith("LIVE") ? live : partial) }));

  await openTab(page, caseId);
  await expect(page.getByTestId("run-label")).toHaveText("Live AI");
  await page.getByRole("button", { name: /Agent details/ }).click();
  await expect(page.getByRole("region", { name: "Alternative explanation agent" }).getByTestId("stage-badge")).toHaveText("Live AI · schema repaired once");

  history = [sum(partial), sum(live)];
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.evaluate((c) => sessionStorage.removeItem(`prism.investigation.${c}`), caseId);
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("tab", { name: "AI Investigation" }).click();
  await expect(page.getByTestId("run-label")).toHaveText("Partial fallback");
  await page.getByRole("button", { name: /Agent details/ }).click();
  await expect(page.getByRole("region", { name: "Suspicion agent" }).getByTestId("stage-badge")).toHaveText("Live AI");
  await expect(page.getByRole("region", { name: "Alternative explanation agent" }).getByTestId("stage-badge")).toHaveText("Fell back to simulated");
  await expect(page.getByRole("region", { name: "Alternative explanation agent" })).toContainText("schema error (test)");

  history = [{ ...sum({ investigation_id: "INV-MOCK-FAIL", mode: null }, "failed", "Interrupted: the server restarted before this run finished.") }, sum(partial), sum(live)];
  await page.evaluate((c) => sessionStorage.removeItem(`prism.investigation.${c}`), caseId);
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("tab", { name: "AI Investigation" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Failed investigation" })).toContainText("Interrupted");
  await expect(page.getByRole("combobox", { name: "Investigation run" }).locator("option")).toHaveCount(3);
});
