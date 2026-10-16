import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// Senior-only pages (role-based demo), dashboard copilot scope, and the light/dark theme.

const errors: string[] = [];
async function prep(page: Page) {
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  page.on("console", (m) => { if (m.type() === "error" && !/fonts\./.test(m.location().url) && !/status of 403/.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
}
async function axe(page: Page, label: string) {
  const res = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  const serious = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${label}: ${v.id} (${v.nodes.length}) ${v.help} — ${v.nodes[0]?.target}`)).toEqual([]);
}
async function choose(page: Page, rid: string) {
  await page.locator("#reviewer-select").selectOption(rid);
  await expect.poll(() => page.evaluate(() => JSON.parse(sessionStorage.getItem("prism.session") ?? "null")?.reviewer?.reviewer_id)).toBe(rid);
}
const token = (page: Page) => page.evaluate(() => JSON.parse(sessionStorage.getItem("prism.session") ?? "null")?.token as string);

test("regular reviewers cannot see or fetch restricted records", async ({ page }) => {
  await prep(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await choose(page, "REV-01");
  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(nav.getByRole("link", { name: "Queue" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Restricted Records" })).toHaveCount(0);
  await expect(nav.getByRole("link", { name: "Data Management" })).toHaveCount(0);
  await page.goto("/restricted", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("alert")).toContainText("does not have senior investigator access");
  // the server refuses the same requests directly, whatever the page shows
  const h = { "X-Reviewer-Session": await token(page) };
  for (const url of ["/api/restricted/records", "/api/restricted/access-log", "/api/admin/summary", "/api/admin/tables/players"]) {
    expect((await page.request.get(url, { headers: h })).status(), url).toBe(403);
  }
  const r = await page.request.post("/api/restricted/players/PLY-00001/reveal", { headers: h, data: { reason: "Trying to read identity details" } });
  expect(r.status()).toBe(403);
  expect(await r.text()).not.toContain("@example.invalid");
  expect(errors).toEqual([]);
});

test("senior access needs a reason and is recorded in the access log", async ({ page }) => {
  await prep(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await choose(page, "REV-02");
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Restricted Records" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Restricted Records" })).toBeVisible();
  await expect(page.getByText("Role-based demo, not production authorization.")).toBeVisible();
  const table = page.getByRole("table").first();
  await expect(table).not.toContainText("@example.invalid");               // nothing identifying before a reveal
  await axe(page, "restricted records");

  const row = table.getByRole("row").filter({ has: page.getByRole("link", { name: /^CASE-\d{5}$/ }) }).first();
  const pid = (await row.getByRole("cell").first().textContent())!.trim();
  await row.getByRole("button", { name: `Reveal identity for ${pid}` }).click();
  const dlg = page.getByRole("dialog", { name: `Reveal identity for ${pid}` });
  const go = dlg.getByRole("button", { name: "Reveal and record access" });
  await expect(go).toBeDisabled();
  await dlg.getByLabel("Reason for access (required)").fill("too short");
  await expect(go).toBeDisabled();
  const reason = `E2E check of account holder ${Date.now()}`;
  await dlg.getByLabel("Reason for access (required)").fill(reason);
  await go.click();
  await expect(dlg).toBeHidden();
  await expect(row).toContainText("@example.invalid");
  await expect(row).toContainText("Fictional");
  const log = page.getByRole("region", { name: "Identity access log" });
  await expect(log.getByRole("row").filter({ hasText: reason })).toContainText(pid);
  await expect(log.getByRole("row").filter({ hasText: reason })).toContainText("Jordan Patel");
  await expect(log).not.toContainText("@example.invalid");
  // switching to a regular reviewer drops revealed details from the page
  await choose(page, "REV-03");
  await expect(page.getByText("@example.invalid")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("data management shows counts and whitelisted, read-only browsing", async ({ page }) => {
  await prep(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await choose(page, "REV-02");
  await page.goto("/data", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { level: 1, name: "Data Management" })).toBeVisible();
  for (const l of ["Players", "Transactions", "Retailers", "Cases", "Alerts", "Audit records"]) await expect(page.getByText(l, { exact: true }).first()).toBeVisible();
  await page.getByRole("tab", { name: "Players" }).click();
  await expect(page.getByRole("columnheader", { name: "player id" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: /name|email|phone/ })).toHaveCount(0);
  await page.getByRole("tab", { name: "Transactions" }).click();
  await page.getByLabel(/Search IDs/).fill("TXN-00000");
  await expect(page.getByRole("table")).toContainText("TXN-00000");
  await axe(page, "data management");
  expect(errors).toEqual([]);
});

test("dashboard copilot explains INQUEST and has no case access", async ({ page }) => {
  await prep(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Open INQUEST Copilot" }).click();
  const dock = page.getByRole("dialog", { name: /Dashboard help/ });
  await expect(dock.getByRole("group", { name: "Suggested questions" }).getByRole("button")).toHaveCount(4); // 3 + "N more"
  await dock.getByRole("button", { name: "What does the prototype score mean?" }).click();
  await expect(dock.getByRole("article").last()).toContainText("not a probability of fraud");
  await dock.getByLabel("Ask a question about INQUEST").fill("Why was CASE-18001 flagged?");
  await dock.getByRole("button", { name: "Send question" }).click();
  const a = dock.getByRole("article").last();
  await expect(a).toContainText("no access to case records");
  await expect(a.getByText(/EV-\d+|TXN-\d+|\$\d/)).toHaveCount(0);           // no evidence, records or amounts
  await a.getByRole("link", { name: "Open CASE-18001" }).click();
  await expect(page).toHaveURL(/\/cases\/CASE-18001$/);
  // inside the case the case-scoped, cited copilot replaces the dashboard help
  await expect(page.getByRole("dialog", { name: /Dashboard help/ })).toHaveCount(0);
  await page.getByRole("button", { name: /INQUEST Copilot/ }).first().click();
  await expect(page.getByRole("dialog", { name: /INQUEST Copilot — CASE-18001/ })).toBeVisible();
  expect(errors).toEqual([]);
});

test("theme toggle switches, persists across reloads and both themes pass contrast checks", async ({ page }) => {
  await prep(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "dark");                 // default
  const sw = page.getByRole("switch", { name: "Dark theme" });
  await expect(sw).toHaveAttribute("aria-checked", "true");
  const bg = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const darkBg = await bg();
  await sw.focus();
  await page.keyboard.press("Space");
  await expect(html).toHaveAttribute("data-theme", "light");
  await expect(sw).toHaveAttribute("aria-checked", "false");
  expect(await bg()).not.toBe(darkBg);
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).filter)).toBe("none");   // not an invert filter
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(html).toHaveAttribute("data-theme", "light");
  await expect(page.getByRole("link", { name: /^Open CASE-\d{5}$/ }).first()).toBeVisible();
  await axe(page, "queue (light)");
  await page.goto("/cases/CASE-18003", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("tab", { name: "Summary" })).toBeVisible();
  await axe(page, "summary (light)");
  await page.getByRole("tab", { name: "Evidence" }).click();
  await expect(page.getByRole("tab", { name: "Transactions" }).first()).toBeVisible();
  await axe(page, "evidence (light)");
  await page.getByRole("tab", { name: "Historical Comparison" }).click();
  await axe(page, "history (light)");
  await page.getByRole("tab", { name: "Review" }).click();
  await axe(page, "review (light)");
  await page.getByRole("button", { name: "Open INQUEST Copilot" }).click();
  await expect(page.getByRole("dialog", { name: /INQUEST Copilot — CASE-18003/ })).toBeVisible();
  await axe(page, "case copilot (light)");
  await page.getByRole("button", { name: "Minimize INQUEST Copilot" }).click();
  await page.goto("/analytics", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await axe(page, "analytics (light)");
  await page.getByRole("button", { name: "Open INQUEST Copilot" }).click();
  await expect(page.getByRole("dialog", { name: /Dashboard help/ })).toBeVisible();
  await axe(page, "dashboard copilot (light)");
  await page.getByRole("button", { name: "Minimize INQUEST Copilot" }).click();
  await choose(page, "REV-02");
  await page.goto("/restricted", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("table").first()).toBeVisible();
  await axe(page, "restricted (light)");
  await page.goto("/data", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("table").first()).toBeVisible();
  await axe(page, "data management (light)");
  // and back to dark, which also persists
  await page.getByRole("switch", { name: "Dark theme" }).click();
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(html).toHaveAttribute("data-theme", "dark");
  await page.goto("/cases/CASE-18003", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("tab", { name: "Summary" })).toBeVisible();
  await axe(page, "summary (dark)");
  expect(errors).toEqual([]);
});
