import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// Core investigator workflow against a running backend (synthetic data, demo mode).
// Uses a scenario-lab case so repeated runs never depend on a curated case's state.

const consoleErrors: string[] = [];

async function prep(page: Page) {
  // fonts are optional; never let a blocked CDN stall the run
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    if (/fonts\.(googleapis|gstatic)\.com/.test(m.location().url)) return; // aborted on purpose above
    consoleErrors.push(`${m.text()} @ ${m.location().url}`);
  });
  page.on("pageerror", (e) => consoleErrors.push(String(e)));
}

async function axe(page: Page, label: string) {
  const res = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  const serious = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${label}: ${v.id} (${v.nodes.length}) ${v.help}`)).toEqual([]);
}

async function noOverflow(page: Page) {
  const { overflow, wide } = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    wide: [...document.querySelectorAll("body *")]
      .filter((el) => el.getBoundingClientRect().right > window.innerWidth + 1 && el.getBoundingClientRect().width > 0)
      .slice(0, 5).map((el) => `${el.tagName}.${String(el.className).slice(0, 60)}`),
  }));
  expect(overflow, `wider than the viewport: ${wide.join(" | ")}`).toBeLessThanOrEqual(1);
}

test("core investigation workflow", async ({ page, request }) => {
  await prep(page);

  // 1. Queue: metrics, quick filters and the case table
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { level: 1, name: "Investigation queue" })).toBeVisible();
  await expect(page.getByRole("link", { name: /^Open CASE-\d{5}$/ }).first()).toBeVisible();
  for (const h of ["Case ID", "Alert type", "Priority", "Score band", "Evidence", "Status", "Last updated", "Reviewer"]) {
    await expect(page.getByRole("columnheader", { name: h, exact: true })).toBeVisible();
  }
  await axe(page, "queue");

  // 2. Search and a quick filter narrow the queue via the API
  await page.getByLabel(/search/i).first().fill("CASE-18003");
  await page.getByLabel(/search/i).first().press("Enter");
  await expect(page.getByRole("link", { name: "Open CASE-18003" })).toBeVisible();
  await page.getByRole("button", { name: /^Clear/ }).click();
  const partial = page.getByRole("group", { name: "Evidence filter" }).getByRole("button", { name: "Partial" });
  await partial.click();
  await expect(partial).toHaveAttribute("aria-pressed", "true");
  await expect(page).toHaveURL(/completeness=Partial/);
  await page.getByRole("button", { name: /^Clear/ }).click();

  // 3. Choose a clearly simulated reviewer session
  await page.locator("#reviewer-select").selectOption({ index: 1 });
  await expect(page.getByText(/simulated/i).first()).toBeVisible();

  // 4. Scenario lab creates a fresh case and opens the workspace
  await page.getByRole("link", { name: /scenario/i }).first().click();
  await page.getByRole("button", { name: "Run scenario" }).first().click();
  await expect(page).toHaveURL(/\/cases\/CASE-\d{5}$/);
  const caseId = page.url().split("/").pop() as string;
  await expect(page.getByRole("heading", { name: caseId })).toBeVisible();
  // Summary first: four plain questions, never a verdict
  await expect(page.getByRole("tablist", { name: "Case views" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Summary", exact: true })).toHaveAttribute("aria-selected", "true"); // default tab
  expect(await page.getByRole("tablist", { name: "Case views" }).getByRole("tab").allInnerTexts())
    .toEqual(["Summary", "AI Investigation", "Evidence", "Historical Comparison", "Review"]);
  for (const q of ["What happened?", "Why was the case flagged?", "What are the main unusual activities?", "What should be checked next?"]) {
    await expect(page.getByRole("heading", { name: q })).toBeVisible();
  }
  await expect(page.getByRole("tabpanel")).not.toContainText(/\b(is guilty|committed fraud|money laundering occurred)\b/i);
  await page.getByRole("tab", { name: "Evidence", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Findings", exact: true })).toBeVisible();          // left: flagged activities
  await expect(page.getByRole("heading", { name: "Evidence Explorer" })).toBeVisible();             // right: supporting evidence
  await expect(page.getByRole("tablist", { name: "Evidence views" }).getByRole("tab", { name: /Relationships|Saved|Bookmarks/ })).toHaveCount(0);
  await expect(page.getByRole("link", { name: /Relationship/ })).toHaveCount(0);
  await page.getByRole("tab", { name: "Review", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Review workflow" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Investigation decision" })).toBeVisible();

  // 5. Generate an evidence-linked report from the decision card (demo mode, no API key)
  await page.getByRole("button", { name: "Generate report" }).first().click();
  await expect(page.getByRole("button", { name: "Export PDF" })).toBeVisible({ timeout: 30_000 });

  // 6. All 11 sections are present (most collapsed) with verification status
  for (const h of ["Case overview", "Why the alert was raised", "What happened", "Key findings", "Supporting records",
    "Compared with previous activity", "Retailers, accounts and other players", "Other possible explanations",
    "Missing or conflicting information", "Suggested next checks", "Review status"]) {
    await expect(page.getByRole("heading", { name: new RegExp(`^${h}`) })).toBeVisible();
  }
  await expect(page.getByText(/statements checked against the evidence/).first()).toBeVisible();

  // 7. Clicking a citation opens the evidence drawer for that record
  const chip = page.getByRole("button", { name: /^Open evidence EV-\d{6}/ }).first();
  const chipName = (await chip.getAttribute("aria-label")) ?? "";
  const evId = chipName.match(/EV-\d{6}/)?.[0] as string;
  await chip.click();
  const drawer = page.getByRole("dialog");
  await expect(drawer).toBeVisible();
  await expect(drawer.getByText(evId).first()).toBeVisible();
  await axe(page, "workspace+drawer");

  // 8. "Back" closes the drawer and returns focus to the citation
  await drawer.getByRole("button", { name: "Back to where this evidence was opened" }).click();
  await expect(drawer).toBeHidden();
  await expect(page.locator(":focus")).toHaveAttribute("aria-label", chipName);

  // 9. Floating copilot: opens from the launcher, answers with citations, minimises back to the icon
  const launcher = page.getByRole("button", { name: "Open INQUEST Copilot" });
  await launcher.click();
  const chat = page.getByRole("dialog", { name: new RegExp(`INQUEST Copilot — ${caseId}`) });
  await expect(chat).toBeVisible();
  await expect(chat.getByLabel("Ask a question about this case")).toBeFocused();
  await expect(chat.getByRole("group", { name: "Suggested questions" }).getByRole("button", { name: /\?$/ })).toHaveCount(3);
  await chat.getByLabel("Ask a question about this case").fill("Which retailers were involved?");
  await chat.getByRole("button", { name: "Send question" }).click();
  const answer = chat.getByRole("article", { name: "Copilot answer" }).last();
  await expect(answer).toBeVisible({ timeout: 30_000 });
  const cite = answer.getByRole("button", { name: /^Open evidence EV-\d{6}/ }).first();
  await cite.click();                                                   // cited evidence still opens
  await expect(page.getByRole("dialog").filter({ hasText: /EV-\d{6}/ }).last()).toBeVisible();
  await page.keyboard.press("Escape");
  await axe(page, "copilot open");
  await chat.getByRole("button", { name: "Minimize copilot" }).click();
  await expect(chat).toBeHidden();
  await expect(page.getByRole("button", { name: "Open INQUEST Copilot" })).toBeFocused();
  // reopening keeps the conversation
  await page.getByRole("button", { name: "Open INQUEST Copilot" }).click();
  await expect(chat.getByRole("article", { name: "Copilot answer" })).toHaveCount(1);
  await chat.getByRole("button", { name: "Minimize copilot" }).click();

  // 10. Start review
  await page.getByRole("button", { name: "Start review" }).click();
  await page.getByRole("dialog").getByRole("button", { name: /^Confirm/ }).click();
  await expect(page.getByText("Under Review").first()).toBeVisible();

  // 11. Investigation decision: justification and evidence are required before the confirmation step
  const decision = page.getByRole("region", { name: "Investigation decision" });
  await decision.getByRole("radio", { name: /Escalate for Further Investigation/ }).check();
  await decision.getByLabel(/Justification/).fill("short");
  await decision.getByRole("button", { name: "Review and submit" }).click();
  await expect(decision.getByText(/At least \d+ characters/)).toBeVisible();
  await expect(decision.getByText("Cite at least one evidence item.")).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Confirm investigation decision" })).toHaveCount(0);

  // 12. Escalate with a justification and cited evidence, confirmed in a summary; status persists after reload
  await decision.getByLabel(/Justification/).fill("Checked timeline and retailer spread; referring for a second-level review.");
  await decision.getByRole("button", { name: "Choose evidence" }).click();
  await decision.getByRole("list", { name: "Evidence to cite" }).getByRole("checkbox").first().check();
  await decision.getByRole("button", { name: "Review and submit" }).click();
  const confirm = page.getByRole("dialog", { name: "Confirm investigation decision" });
  await expect(confirm).toContainText("Under Review → Escalated");
  await confirm.getByRole("button", { name: "Record decision" }).click();
  await expect(decision.getByLabel("Current decision")).toContainText("Escalate for Further Investigation");
  await expect(page.getByText("Escalated").first()).toBeVisible();
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByText("Escalated").first()).toBeVisible();

  // 13. The audit trail records the decision with report version + evidence hash; report is locked
  const audit = await (await request.get(`/api/cases/${caseId}/audit`)).json();
  const esc = audit.find((a: { action: string }) => a.action === "record_disposition");
  expect(esc?.report_version).toBeGreaterThan(0);
  expect(esc?.evidence_hash).toMatch(/^[0-9a-f]{64}$/);
  const dsp = await (await request.get(`/api/cases/${caseId}/dispositions`)).json();
  expect(dsp.current.disposition).toBe("escalate");
  expect(dsp.current.evidence_ids.length).toBe(1);
  const rep = await (await request.get(`/api/reports/${esc.report_id}`)).json();
  expect(rep.status).toBe("locked");
  const menu = page.getByRole("button", { name: "Open navigation" });
  if (await menu.isVisible()) await menu.click(); // the workspace keeps the menu behind the toggle below 1536px
  await page.getByRole("link", { name: /reports/i }).first().click();
  await expect(page.getByRole("link", { name: caseId }).first()).toBeVisible();

  // 14. PDF export from the saved version
  const pdf = await request.get(`/api/reports/${esc.report_id}/pdf`);
  expect(pdf.ok()).toBeTruthy();
  expect((await pdf.body()).subarray(0, 4).toString()).toBe("%PDF");

  expect(consoleErrors).toEqual([]);
});

test("workspace is usable at phone width", async ({ page }) => {
  await prep(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/cases/CASE-18003", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("tablist", { name: "Case views" })).toBeVisible();
  await noOverflow(page);
  await page.getByRole("tab", { name: "Evidence" }).click();
  await expect(page.getByRole("region", { name: "Evidence Explorer" })).toBeVisible();
  await noOverflow(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("link", { name: /^Open CASE-\d{5}$/ }).first()).toBeVisible();
  await noOverflow(page);
});

test("relationship explorer renders real relationships", async ({ page }) => {
  await prep(page);
  await page.goto("/cases/CASE-18005/graph", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: /Relationship explorer/ })).toBeVisible();
  await expect(page.locator("canvas").first()).toBeVisible();
  await axe(page, "explorer");
});

test("findings: three levels, view evidence, citations, zero baseline", async ({ page, request }) => {
  await prep(page);
  // CASE-18009: overnight share 0% before vs. 74.2% recently (observed zero, not missing data)
  const session = await (await request.post("/api/session", { data: { reviewer_id: "REV-03" } })).json();
  await request.post("/api/cases/CASE-18009/reports", { data: { mode: "deterministic" }, headers: { "X-Reviewer-Session": session.token } });
  await page.goto("/cases/CASE-18009", { waitUntil: "domcontentloaded" });
  const allFindings = () => page.getByRole("tab", { name: "Evidence", exact: true }).click();
  await allFindings();

  // Level 1: short and understood without expanding anything
  const card = page.getByRole("article", { name: "Unusual transaction timing" });
  await expect(card).toBeVisible({ timeout: 20_000 });
  await expect(card.getByText("Most recent linked purchases happened overnight")).toBeVisible();
  await expect(card.getByText("0% → 74.2%")).toBeVisible();
  await expect(card.getByText("Increase: 74.2 percentage points")).toBeVisible();
  await expect(card).not.toContainText(/∞|Infinity|NaN|—/);
  await expect(card.getByText("Why it may matter")).toHaveCount(0);

  // "View evidence" jumps to the Evidence Explorer, filtered and highlighted
  await card.getByRole("button", { name: "View evidence for Unusual transaction timing" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Evidence for Unusual transaction timing" })).toBeVisible();
  await expect(page.getByRole("tab", { name: /^Transactions/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("tr[data-highlighted='true']").first()).toBeVisible();

  // one click from a record to the original record, then back without losing place
  const rec = page.getByRole("button", { name: /^Open record TXN-/ }).first();
  const recName = (await rec.getAttribute("aria-label")) as string;
  await rec.click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByText(/TXN-\d+/).first()).toBeVisible();
  await expect(drawer.getByText("Data sources")).toBeVisible();
  await drawer.getByRole("button", { name: "Back to where this evidence was opened" }).click();
  await expect(drawer).toBeHidden();
  await expect(page.locator(":focus")).toHaveAttribute("aria-label", recName);

  // Level 2 via keyboard (the finding stays on the left while its evidence shows on the right)
  const details = card.getByRole("button", { name: "Details", exact: true });
  await details.focus();
  await page.keyboard.press("Enter");
  await expect(details).toHaveAttribute("aria-expanded", "true");
  await expect(card.getByText("Keep in mind")).toBeVisible();                 // limitations stay
  await expect(card.getByText("Why it may matter")).toHaveCount(0);          // no repeat of the card's numbers
  await expect(card.getByText(/not proof of wrongdoing/)).toHaveCount(0);    // one reminder at the top of the tab
  await expect(page.getByText("Flagged patterns require review; they do not establish wrongdoing.")).toBeVisible();

  // Level 3: exact metric names, periods, ramp, evidence version
  await card.getByRole("button", { name: "Technical details" }).click();
  await expect(card.getByText("Timing anomaly", { exact: true })).toBeVisible();
  await expect(card.getByText("night_share_pct", { exact: true })).toBeVisible();
  await expect(card.getByRole("table", { name: "How the points were calculated" })).toBeVisible();
  await expect(card.getByText(/^SNP-\d{6}$/)).toBeVisible();
  await expect(card.getByText("2026-09-15 – 2026-10-07", { exact: true })).toBeVisible();

  // the numbers on screen are the stored evidence values
  const api = await (await request.get("/api/cases/CASE-18009/findings")).json();
  const timing = api.findings.find((f: { key: string }) => f.key === "timing");
  expect(timing.verification.status).toBe("verified");
  expect(timing.comparison.rows.map((r: { value: number }) => r.value)).toEqual([0, 74.2]);
  await axe(page, "findings expanded");

  // a case with indicators inside the normal range: they are listed compactly behind a disclosure
  await page.goto("/cases/CASE-18003", { waitUntil: "domcontentloaded" });
  await allFindings();
  const also = page.getByRole("button", { name: /Also checked: within the normal range/ });
  await expect(also).toHaveAttribute("aria-expanded", "false", { timeout: 20_000 });
  await also.click();
  await expect(page.getByRole("article", { name: "Unusual transaction timing" })).toBeVisible();
  await noOverflow(page);
  expect(consoleErrors).toEqual([]);
});

test("history, completeness, bookmarks, notes and checklist", async ({ page, request }) => {
  await prep(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.locator("#reviewer-select").selectOption("REV-02");
  await page.goto("/cases/CASE-18009", { waitUntil: "domcontentloaded" });

  // Historical comparison: previous / recent / difference / change, unavailable rows explained
  await page.getByRole("tab", { name: "Historical Comparison", exact: true }).click();
  const hist = page.getByRole("table", { name: /Previous and recent activity/ });
  await expect(hist.getByRole("rowheader", { name: /Transactions per day/ })).toBeVisible();
  await expect(hist.getByRole("rowheader", { name: /Overnight share/ })).toBeVisible();
  await expect(hist.getByRole("row", { name: /Overnight share/ })).toContainText("+74.2 pp");
  await expect(hist.getByText("unavailable:")).toBeVisible();
  await expect(hist).not.toContainText(/∞|Infinity|NaN/);
  const h = await (await request.get("/api/cases/CASE-18009/history")).json();
  expect(h.rows.find((r: { key: string }) => r.key === "per_day").current).toBe(4.43);
  // comparison charts render (per day vs previous average, hour of day previous vs recent)
  await expect(page.getByText(/Hour of day/)).toBeVisible();
  await expect(page.locator("figure[aria-labelledby=hours-cap] .recharts-bar-rectangle").first()).toBeAttached();
  await expect(page.locator("figure[aria-labelledby=days-cap] .recharts-bar-rectangle").first()).toBeAttached();
  await axe(page, "history");

  // Evidence completeness card (Review)
  await page.getByRole("tab", { name: "Review", exact: true }).click();
  const cov = page.getByRole("list", { name: "Data coverage" });
  await expect(cov.getByText("Timestamps")).toBeVisible();
  await expect(cov.getByText("Customer identity & intent")).toBeVisible();

  // Bookmarks are hidden from the case workflow (backend untouched)
  await page.getByRole("tab", { name: "Evidence", exact: true }).click();
  await page.getByRole("tab", { name: /^Transactions/ }).click();
  await expect(page.getByRole("button", { name: /^Bookmark / })).toHaveCount(0);
  // selecting a record on the right opens its source record and highlights it
  const rec = page.getByRole("button", { name: /^Open record TXN-/ }).first();
  await rec.click();
  await expect(page.getByRole("dialog").getByText(/TXN-\d+/).first()).toBeVisible();
  await expect(page.locator("tr[aria-current], tr[data-highlighted='true']").first()).toBeAttached();
  await page.keyboard.press("Escape");

  // Checklist: steps tick themselves (history was opened) and can be ticked by hand
  await page.getByRole("tab", { name: "Review", exact: true }).click();
  await page.getByRole("button", { name: /Investigation checklist/ }).click();
  await expect(page.getByRole("checkbox", { name: "Compare historical context" })).toBeChecked();
  const ask = page.getByRole("checkbox", { name: "Ask follow-up questions" });
  await ask.check();
  await expect(ask).toBeChecked();
  expect(consoleErrors).toEqual([]);
});

test("compare two cases", async ({ page }) => {
  await prep(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("checkbox", { name: "Select CASE-18009 to compare" }).check();
  await page.getByRole("checkbox", { name: "Select CASE-18003 to compare" }).check();
  await page.getByRole("button", { name: "Compare cases" }).click();
  await expect(page).toHaveURL(/\/compare\?a=CASE-18009&b=CASE-18003/);
  for (const s of ["Overview", "Indicators", "Activity patterns", "Evidence completeness", "Retailers & entities", "Timelines"]) {
    await expect(page.getByRole("region", { name: s })).toBeVisible({ timeout: 20_000 });
  }
  await expect(page.getByRole("region", { name: "Indicators" }).getByText("0% → 74.2%")).toBeVisible();
  await axe(page, "compare");
  await noOverflow(page);
  expect(consoleErrors).toEqual([]);
});

test("sidebar collapses to icons, keeps the active page, and remembers the choice", async ({ page }) => {
  await prep(page);
  await page.goto("/cases/CASE-18003", { waitUntil: "domcontentloaded" });
  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(nav.getByText("INQUEST", { exact: true })).toBeVisible();              // branding when expanded
  const wide = (await nav.boundingBox())!.width;
  const mainBefore = (await page.locator("#main").boundingBox())!.width;
  const toggle = nav.getByRole("button", { name: "Collapse sidebar" });
  await toggle.focus();
  await page.keyboard.press("Enter");                                               // keyboard operable
  const expand = nav.getByRole("button", { name: "Expand sidebar" });
  await expect(expand).toHaveAttribute("aria-expanded", "false");
  await expect.poll(async () => (await nav.boundingBox())!.width).toBeLessThan(70);
  expect(wide).toBeGreaterThan(200);
  await expect.poll(async () => (await page.locator("#main").boundingBox())!.width).toBeGreaterThan(mainBefore + 150);
  const queue = nav.getByRole("link", { name: "Queue" });                           // still named for screen readers
  await queue.focus();
  await expect(page.getByRole("tooltip", { name: "Queue" })).toBeVisible();         // tooltip on focus
  await axe(page, "sidebar collapsed");
  await nav.getByRole("link", { name: "Scenario Lab" }).click();
  await expect(page).toHaveURL(/\/scenarios$/);
  await expect(nav.getByRole("button", { name: "Expand sidebar" })).toBeVisible();   // persists across navigation
  await expect(nav.getByRole("link", { name: "Scenario Lab" })).toHaveAttribute("aria-current", "page");
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(nav.getByRole("button", { name: "Expand sidebar" })).toBeVisible();   // and across reloads
  await nav.getByRole("button", { name: "Expand sidebar" }).click();
  await expect.poll(async () => (await nav.boundingBox())!.width).toBeGreaterThan(200);
  await noOverflow(page);
});

test("copilot conversations stay with their own case", async ({ page }) => {
  await prep(page);
  await page.goto("/cases/CASE-18006", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Open INQUEST Copilot" }).click();
  const chatA = page.getByRole("dialog", { name: /INQUEST Copilot — CASE-18006/ });
  await chatA.getByLabel("Ask a question about this case").fill("What is missing from the records?");
  await chatA.getByRole("button", { name: "Send question" }).click();
  await expect(chatA.getByRole("article", { name: "Copilot answer" }).last()).toBeVisible({ timeout: 30_000 });
  const draft = "unsent draft for 18006";
  await chatA.getByLabel("Ask a question about this case").fill(draft);
  await chatA.getByRole("button", { name: "Minimize copilot" }).click();
  await page.getByRole("button", { name: "Open INQUEST Copilot" }).click();
  await expect(chatA.getByLabel("Ask a question about this case")).toHaveValue(draft); // minimise keeps the draft

  // another case: its own heading, none of CASE-18006's messages or draft
  await page.goto("/cases/CASE-18008", { waitUntil: "domcontentloaded" });
  const chatB = page.getByRole("dialog", { name: /INQUEST Copilot — CASE-18008/ });
  await expect(chatB).toBeVisible();                                                // open state remembered
  await expect(chatB.getByLabel("Ask a question about this case")).toHaveValue("");
  await expect(chatB).not.toContainText("What is missing from the records?");
  const apiB = await (await page.request.get("/api/cases/CASE-18008/chat")).json();
  await expect(chatB.getByRole("article", { name: "Copilot answer" })).toHaveCount(apiB.filter((m: { role: string }) => m.role !== "user").length);
  expect(consoleErrors).toEqual([]);
});

test("scenario lab lists the backend scenarios and runs one", async ({ page, request }) => {
  await prep(page);
  await page.goto("/scenarios", { waitUntil: "domcontentloaded" });
  const list = await (await request.get("/api/scenarios")).json();
  await expect(page.getByRole("button", { name: "Run scenario" })).toHaveCount(list.length);
  expect(consoleErrors).toEqual([]);
});
