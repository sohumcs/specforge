import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

/** What a recruiter does: one click, explore a sample, trace a node. */
test('"Try it instantly" opens a verified sample in under 10 seconds', async ({ page }) => {
  const started = Date.now()
  await page.goto('/')
  await page.getByRole('button', { name: /Open in demo/ }).first().click()
  await expect(page).toHaveURL(/\/app\/b\//)
  await expect(page.getByText(/^\d+ nodes · \d+ links$/)).toBeVisible()
  await expect(page.getByLabel(/Quality score \d+, open quality panel/)).toBeVisible()
  expect(Date.now() - started).toBeLessThan(10_000)
  await expect(page.getByText('demo', { exact: true })).toBeVisible() // demo badge in the header
})

test('select a node to see its trace chain and similar nodes', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Try it instantly' }).click()
  await expect(page.getByRole('heading', { name: 'Sandbox' })).toBeVisible()
  await page.getByRole('link', { name: /Food delivery marketplace/ }).click()
  await page.getByRole('tab', { name: 'Outline' }).click()
  await page.getByRole('region', { name: /Stories/ }).getByRole('button').first().click()
  const panel = page.getByRole('complementary', { name: /Story US-\d+ details/ })
  await expect(panel.getByText('Comes from')).toBeVisible()
  await expect(panel.getByRole('button', { name: /REQ-\d+/ }).first()).toBeVisible()
  await expect(panel.getByText('Semantically similar')).toBeVisible()
})

test('blueprint workspace has no serious accessibility violations', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: /Open in demo/ }).first().click()
  await expect(page).toHaveURL(/\/app\/b\//)
  await expect(page.getByText(/^\d+ nodes · \d+ links$/)).toBeVisible()
  for (const tab of ['Quality', 'Delivery', 'Outline']) {
    await page.getByRole('tab', { name: new RegExp(tab) }).click()
    await expect(page.getByRole('tabpanel')).not.toBeEmpty()
    await expect(page.getByRole('tabpanel').locator('.animate-pulse')).toHaveCount(0) // skeletons gone
    const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).exclude('.react-flow').analyze()
    const serious = result.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious.map((v) => `${tab}: ${v.id} (${v.nodes.length})`)).toEqual([])
  }
})
