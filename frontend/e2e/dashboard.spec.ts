// End-to-end smoke: requires a backend with hydrated sleeves and the Vite dev
// server (playwright.config.ts starts it automatically).
import { expect, test } from "@playwright/test";

test("portfolio overview shows benchmarks and all four sleeves", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Portfolio value")).toBeVisible();
  await expect(page.getByText("Excess vs SPY")).toBeVisible();
  await expect(page.getByText("Statistics: Portfolio vs. SPY vs. QQQ")).toBeVisible();
  for (const n of [1, 2, 3, 4]) {
    await expect(page.locator(`main a[href="/sleeves/${n}"]`)).toBeVisible();
  }
});

test("a sleeve card opens the sleeve and its tabs work", async ({ page }) => {
  await page.goto("/");
  await page.locator('main a[href="/sleeves/1"]').click();
  await expect(page.getByRole("heading", { name: "Sleeve 1" })).toBeVisible();
  await expect(page.getByText("Current holdings")).toBeVisible();
  await page.getByRole("link", { name: "Stocks", exact: true }).click();
  await expect(page.getByText("Where the return came from").first()).toBeVisible();
  await page.getByRole("link", { name: "History", exact: true }).last().click();
  await expect(page.getByText("Open positions")).toBeVisible();
  await expect(page.getByRole("button", { name: "Record trade" })).toBeVisible();
});

test("sleeve risk switches between purchase and latest-year windows", async ({ page }) => {
  await page.goto("/sleeves/1/risk");
  await expect(page.getByText("ending the day before", { exact: false })).toBeVisible();
  await expect(page.getByText("Correlation matrix")).toBeVisible();
  await page.getByRole("button", { name: "Latest year" }).click();
  await expect(page.getByText("ending the day before", { exact: false })).toBeHidden();
});

test("an empty sleeve offers the funding form", async ({ page }) => {
  await page.goto("/sleeves/4");
  await expect(page.getByRole("button", { name: "Fund Sleeve 4" })).toBeDisabled();
  await expect(page.getByLabel("Ticker 1")).toBeVisible();
});

test("heatmaps cover holdings and the S&P 500, switching together", async ({ page }) => {
  await page.goto("/heatmap");
  await expect(page.getByText("All holdings by period")).toBeVisible();
  await expect(page.getByText("S&P 500 (SPY)")).toBeVisible();
  await expect(page.locator(".js-plotly-plot").nth(1)).toBeVisible();
  await page.getByRole("group", { name: "Heatmap period" }).getByRole("button", { name: "Year", exact: true }).click();
  await expect(page.getByText(/companies, year, as of/)).toBeVisible();
});

test("holdings table searches", async ({ page }) => {
  await page.goto("/holdings");
  await expect(page.locator("table tbody tr").first()).toBeVisible();
  await page.getByPlaceholder("Search ticker or sector…").fill("GOOGL");
  await expect(page.locator("table tbody tr")).toHaveCount(1);
});

test("transactions export link and table render", async ({ page }) => {
  await page.goto("/transactions");
  await expect(page.locator("table tbody tr").first()).toBeVisible();
  await expect(page.getByText("⤓ Export CSV")).toBeVisible();
});

test("mobile layout shows menu and content", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByLabel("Menu")).toBeVisible();
  await expect(page.getByText("Portfolio value")).toBeVisible();
});
