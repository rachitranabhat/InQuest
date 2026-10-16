import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// V2 Data & Methodology page: database-backed dataset summary for any reviewer; labels + evaluation for seniors only.

async function prep(page: Page) {
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
}
async function choose(page: Page, rid: string) {
  await page.locator("#reviewer-select").selectOption(rid);
  await expect.poll(() => page.evaluate(() => JSON.parse(sessionStorage.getItem("prism.session") ?? "null")?.reviewer?.reviewer_id)).toBe(rid);
}
async function axe(page: Page, label: string) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  expect(r.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${label}: ${v.id} ${v.nodes[0]?.target}`)).toEqual([]);
}

test("data & methodology: counts from the database; technical view only for seniors", async ({ page }) => {
  await prep(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await choose(page, "REV-03");
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Data & Methodology" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Data & Methodology" })).toBeVisible();
  const api = await (await page.request.get("/api/methodology", { headers: { "X-Reviewer-Session": await page.evaluate(() => JSON.parse(sessionStorage.getItem("prism.session")!).token) } })).json();
  const ds = page.getByRole("region", { name: "Dataset" });
  await expect(ds).toContainText(api.dataset_version);
  await expect(ds.getByText(String(api.counts.retailers), { exact: true })).toBeVisible();           // stable count (others grow with Scenario Lab runs)
  await expect(ds).toContainText("Transactions");
  await expect(page.getByRole("region", { name: "Scenario categories" }).getByRole("row")).toHaveCount(api.scenario_categories.length + 1);
  await expect(page.getByRole("heading", { name: /Technical view/ })).toHaveCount(0);
  await axe(page, "methodology (analyst)");

  await choose(page, "REV-02");
  await expect(page.getByRole("heading", { name: /Technical view/ })).toBeVisible();
  await expect(page.getByRole("region", { name: "Detection metrics" })).toContainText("This database (development");
  await page.getByLabel("Planted pattern").selectOption("1");
  const rows = page.getByRole("region", { name: "Scenario labels table" }).getByRole("row");
  await expect(rows.nth(1)).toContainText("Yes");
  await expect(page.getByRole("region", { name: "Scenario labels table" })).not.toContainText(/\bNo\b/);
  await axe(page, "methodology (senior)");
});
