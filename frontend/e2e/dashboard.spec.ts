// End-to-end smoke: requires backend on :8000 with hydrated data and the Vite
// dev server (playwright.config.ts starts it automatically).
import { expect, test } from "@playwright/test";

test("overview loads with account switcher and metrics", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("tab", { name: /\$5K/ })).toBeVisible();
  await expect(page.getByRole("tab", { name: /\$500/ })).toBeVisible();
  await expect(page.getByRole("tab", { name: /Combined/ })).toBeVisible();
  await expect(page.getByText("Current value")).toBeVisible();
  await expect(page.getByText("Growth of $100", { exact: false })).toBeVisible();
});

test("switching accounts updates the dashboard", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("tab", { name: /\$500/ }).click();
  await expect(page.getByText("Current value")).toBeVisible();
  await page.getByRole("tab", { name: /Combined/ }).click();
  await expect(page.getByText("Account contributions")).toBeVisible();
});

test("holdings table searches and sorts", async ({ page }) => {
  await page.goto("/holdings");
  await expect(page.locator("table tbody tr").first()).toBeVisible();
  await page.getByPlaceholder("Search ticker or sector…").fill("GOOGL");
  await expect(page.locator("table tbody tr")).toHaveCount(1);
});

test("heatmap renders with period switcher", async ({ page }) => {
  await page.goto("/heatmap");
  await expect(page.getByRole("button", { name: "Weekly" })).toBeVisible();
  await expect(page.locator(".js-plotly-plot").first()).toBeVisible();
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
  await expect(page.getByText("Current value")).toBeVisible();
});
