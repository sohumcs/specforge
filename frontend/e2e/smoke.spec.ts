import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

test.describe('public pages', () => {
  test('landing explains the product and lists the samples', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toContainText('blueprint')
    await expect(page.getByRole('button', { name: 'Try it instantly' })).toBeVisible()
    await expect(page.getByRole('button', { name: /Open in demo/ })).toHaveCount(4)
    await expect(page.getByRole('link', { name: /Sohum on LinkedIn/ })).toHaveAttribute('href', /linkedin\.com\/in\/sohumcs/)
  })

  test('landing has no serious accessibility violations', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('button', { name: /Open in demo/ }).first()).toBeVisible()
    const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
    const serious = result.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious.map((v) => `${v.id}: ${v.nodes.length} nodes`)).toEqual([])
  })

  test('status page reports a healthy stack', async ({ page }) => {
    await page.goto('/status')
    await expect(page.getByText('PostgreSQL + pgvector', { exact: true })).toBeVisible()
    await expect(page.getByText(/All systems operational|Degraded/)).toBeVisible()
    await expect(page.getByText(/ML models (loaded|loading)/)).toBeVisible({ timeout: 60_000 })
  })

  test('API docs and probes are reachable through the proxy', async ({ request }) => {
    expect((await request.get('/health')).ok()).toBeTruthy()
    expect((await request.get('/ready')).ok()).toBeTruthy()
    const spec = await (await request.get('/openapi.json')).json()
    expect(spec.paths['/api/v1/blueprints/{blueprint_id}/generate']).toBeTruthy()
    expect((await request.get('/metrics')).status()).toBe(404) // not public
  })
})
