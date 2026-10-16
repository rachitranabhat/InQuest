import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// Final investigation decision: a regular reviewer's "substantiated" is a recommendation that a senior confirms.

async function prep(page: Page) {
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
}
async function choose(page: Page, rid: string) {
  await page.locator("#reviewer-select").selectOption(rid);
  await expect.poll(() => page.evaluate(() => JSON.parse(sessionStorage.getItem("prism.session") ?? "null")?.reviewer?.reviewer_id)).toBe(rid);
}
const token = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("prism.session") ?? "null")?.token as string);

test("substantiated: recommendation by a reviewer, confirmation by a senior, full history", async ({ page }) => {
  await prep(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await choose(page, "REV-01");
  const h = { "X-Reviewer-Session": await token(page) };
  const scenarios = await (await page.request.get("/api/scenarios")).json();
  const run = await (await page.request.post(`/api/scenarios/${scenarios[0].key}/run`, { headers: h })).json();
  const caseId = run.case_id as string;
  await page.request.post(`/api/cases/${caseId}/reports`, { headers: h, data: { mode: "deterministic" } });
  await page.request.post(`/api/cases/${caseId}/actions`, { headers: h, data: { action: "start_review", idempotency_key: `e2e-${Date.now()}` } });

  await page.goto(`/cases/${caseId}`, { waitUntil: "domcontentloaded" });
  await page.getByRole("tab", { name: "Review", exact: true }).click();
  const decision = page.getByRole("region", { name: "Investigation decision" });
  await expect(decision.getByText("No investigation decision recorded yet.")).toBeVisible();
  // AML wording never claims proven money laundering
  await decision.getByLabel("Type of concern").selectOption("aml");
  await expect(decision.getByRole("radio", { name: /not proof of money laundering/ })).toBeVisible();
  await decision.getByLabel("Type of concern").selectOption("fraud");
  const sub = decision.getByRole("radio", { name: /Suspected Fraud Substantiated/ });
  await sub.check();
  await expect(decision.getByText("Recorded as a recommendation; a senior investigator confirms.")).toBeVisible();
  await decision.getByLabel(/Justification/).fill("Forty-two linked purchases in one hour at one retailer; cited records match the alert.");
  await decision.getByRole("button", { name: "Choose evidence" }).click();
  const boxes = decision.getByRole("list", { name: "Evidence to cite" }).getByRole("checkbox");
  await boxes.nth(0).check();
  await boxes.nth(1).check();
  await decision.getByRole("button", { name: "Review and submit" }).click();
  const confirm = page.getByRole("dialog", { name: "Confirm investigation decision" });
  await expect(confirm).toContainText("Stays Under Review until a senior investigator confirms");
  await expect(confirm).toContainText("2 items cited");
  await expect(confirm).toContainText("not a legal determination of guilt");
  await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze().then((r) =>
    expect(r.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]));
  await confirm.getByRole("button", { name: "Record recommendation" }).click();
  const current = decision.getByLabel("Current decision");
  await expect(current).toContainText("Awaiting senior confirmation");
  await expect(current.getByRole("button", { name: "Confirm finding" })).toHaveCount(0);     // not for regular reviewers
  await expect(page.getByText("Under Review").first()).toBeVisible();

  // the API refuses a regular reviewer's confirmation, whatever the page shows
  const hist = await (await page.request.get(`/api/cases/${caseId}/dispositions`)).json();
  const did = hist.current.disposition_id;
  const denied = await page.request.post(`/api/cases/${caseId}/dispositions/${did}/review`,
    { headers: h, data: { decision: "confirm", notes: "Trying to self-approve.", idempotency_key: `e2e-x-${Date.now()}` } });
  expect(denied.status()).toBe(403);

  // senior confirms
  await choose(page, "REV-02");
  await current.getByRole("button", { name: "Confirm finding" }).click();
  const rv = page.getByRole("dialog", { name: "Confirm substantiated finding" });
  await rv.getByLabel("Your notes (required)").fill("Checked the two cited records against the timeline.");
  await rv.getByRole("button", { name: "Confirm finding" }).click();
  await expect(current).toContainText("Confirmed by senior investigator");
  await expect(page.getByText("Closed — Suspicion Substantiated").first()).toBeVisible();
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("tab", { name: "Review", exact: true }).click();
  const history = page.getByRole("list", { name: "Decision history, newest first" });
  await expect(history.getByRole("listitem")).toHaveCount(2);
  await expect(history.getByRole("listitem").first()).toContainText("Senior confirmation");
  await expect(history.getByRole("listitem").last()).toContainText("Avery Chen");
  const audit = await (await page.request.get(`/api/cases/${caseId}/audit`)).json();
  expect(audit.map((a: { action: string }) => a.action).slice(-2)).toEqual(["record_disposition", "confirm_disposition"]);
});
