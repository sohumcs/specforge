import { readFile } from 'node:fs/promises'

import { expect, test, type Page } from '@playwright/test'

/**
 * The whole product, as a new user:
 * register → create project → generate from a brief (live progress) → verified
 * score → fix an issue with AI → edit a requirement → see the impact →
 * regenerate affected → move a story on the board → export MD + PDF.
 */
test.describe.configure({ mode: 'serial' })

const BRIEF =
  'A volunteer shift planner for a city food bank. Coordinators publish weekly shifts, volunteers sign up and swap shifts, ' +
  'and the system sends reminders. Coordinators track attendance and export hours for volunteer certificates.'

let page: Page

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage()
})

test.afterAll(async () => {
  await page.close()
})

test('register and create a project', async () => {
  const email = `e2e-${Date.now()}@example.com`
  await page.goto('/register')
  await page.getByLabel('Name').fill('E2E Tester')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel(/Password/).fill('e2e-password-123')
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page).toHaveURL(/\/app$/)
  await page.getByRole('button', { name: 'New project' }).click()
  await page.getByLabel('Name', { exact: true }).fill('Food bank')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Food bank' })).toBeVisible()
})

test('generate a blueprint with live progress', async () => {
  await page.getByLabel('Title').fill('Volunteer shift planner')
  await page.getByLabel('Project brief').fill(BRIEF)
  // Progress streams over SSE. With the offline provider a run can finish in
  // about a second, too fast to reliably catch the step text, so assert the
  // stream itself was opened (and answered) instead.
  const stream = page.waitForResponse((r) => /\/api\/v1\/jobs\/[^/]+\/events$/.test(r.url()))
  await page.getByRole('button', { name: 'Generate blueprint' }).click()
  const sse = await stream
  expect(sse.status()).toBe(200)
  expect(sse.headers()['content-type']).toContain('text/event-stream')
  // …then we land on the graph.
  await expect(page).toHaveURL(/\/app\/b\/[0-9a-f-]+/, { timeout: 150_000 })
  await expect(page.getByRole('application', { name: 'Blueprint graph' }).or(page.getByLabel('Blueprint graph'))).toBeVisible()
  await expect(page.getByText(/^\d+ nodes · \d+ links$/)).toBeVisible()
  await expect(page.getByLabel(/Quality score \d+, open quality panel/)).toBeVisible()
})

test('quality panel shows the score and fixes an issue', async () => {
  await page.getByRole('tab', { name: /Quality/ }).click()
  await expect(page.getByRole('tabpanel').getByLabel(/Quality score \d+ out of 100/)).toBeVisible()
  await expect(page.getByRole('meter', { name: 'Traceability score' })).toBeVisible()
  const fix = page.getByRole('button', { name: 'Fix with AI' }).first()
  if (await fix.count()) {
    await fix.click()
    await expect(page.getByText(/^Fixed [A-Z]{2,3}-\d{3}/)).toBeVisible({ timeout: 90_000 })
  } else {
    await expect(page.getByText(/passes every check/)).toBeVisible()
  }
})

test('edit a requirement, see the impact, regenerate affected', async () => {
  await page.getByRole('tab', { name: 'Outline' }).click()
  await page.getByRole('region', { name: /Requirements/ }).getByRole('button').first().click()
  const panel = page.getByRole('complementary', { name: /Requirement REQ-\d+ details/ })
  await expect(panel).toBeVisible()
  await expect(panel.getByText('Trace chain')).toBeVisible()
  await panel.getByRole('button', { name: 'Edit' }).click()
  const title = panel.getByLabel('Title')
  await title.fill(`${await title.inputValue()} with SMS reminders`)
  await panel.getByRole('button', { name: 'Save & show impact' }).click()
  await expect(panel.getByText(/downstream item.* marked stale/)).toBeVisible()
  const banner = page.getByText(/item.* may be out of date after your edit/)
  await expect(banner).toBeVisible()
  await page.getByRole('button', { name: 'Regenerate affected' }).click()
  await expect(banner).toBeHidden({ timeout: 120_000 })
})

test('move a story on the delivery board', async () => {
  await page.getByRole('tab', { name: 'Delivery' }).click()
  const select = page.getByLabel(/^Status of US-\d+/).first()
  // The select is labelled by its wrapping <label> ('Status of US-001').
  const key = (await select.evaluate((el) => el.closest('label')?.querySelector('span')?.textContent ?? '')).replace('Status of ', '').trim()
  expect(key).toMatch(/^US-\d+$/)
  await select.selectOption('done')
  await expect(page.getByRole('region', { name: 'Done column' }).getByText(key, { exact: true })).toBeVisible()
  await expect(page.getByRole('progressbar', { name: 'stories done' })).not.toHaveAttribute('aria-valuenow', '0')
})

test('export Markdown and PDF', async () => {
  await page.getByRole('tab', { name: 'Brief & export' }).click()
  const [md] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: /Markdown/ }).click()])
  expect(md.suggestedFilename()).toBe('volunteer-shift-planner.md')
  const text = await readFile((await md.path())!, 'utf8')
  expect(text).toContain('## Requirements')
  expect(text).toContain('## REST API')
  const [pdf] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: /PDF/ }).click()])
  expect(pdf.suggestedFilename()).toBe('volunteer-shift-planner.pdf')
  expect((await readFile((await pdf.path())!)).subarray(0, 4).toString()).toBe('%PDF')
})
