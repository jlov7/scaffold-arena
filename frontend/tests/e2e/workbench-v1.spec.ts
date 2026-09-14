import { expect, test } from '@playwright/test'

import { fixturePack, mockWorkbenchV1, personalSession } from '../support/workbenchV1Mock'

test.beforeEach(async ({ page }) => {
  await mockWorkbenchV1(page)
})

test('personal offline fixture import, design, freeze, and preflight HOLD keep execution blocked', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('h1.sa-stage-heading')).toHaveText('Compare')
  await page.getByRole('button', { name: 'Choose a study' }).click()
  await expect(page.locator('h1.sa-stage-heading')).toHaveText('Study Canvas')
  await expect(page.getByText('Synthetic fixture — not benchmark evidence.')).toBeVisible()
  await page.getByRole('button', { name: 'Select' }).click()
  await expect(page).toHaveURL(/\/workbench\/design.*study_pack_id=offline-demo-v1/)
  await page.getByLabel('I have explicit owner approval to create this new, unfrozen ExperimentSpec.').check()
  await page.getByRole('button', { name: 'Create unfrozen experiment' }).click()
  await expect(page).toHaveURL(/\/workbench\/preflight.*fixture-created-experiment/)
  await expect(page.getByText('Synthetic fixture — not benchmark evidence.')).toBeVisible()
  await page.getByRole('button', { name: 'Freeze experiment' }).click()
  await expect(page.getByRole('button', { name: 'Preflight experiment' })).toBeEnabled()
  await page.getByRole('button', { name: 'Preflight experiment' }).click()
  await expect(page.getByText('Execution remains unavailable')).toBeVisible()
  await expect(page.getByText('No provider request has been emitted.')).toBeVisible()
  await page.getByRole('button', { name: 'Lab', exact: true }).click()
  await page.getByRole('button', { name: 'Run Cockpit' }).click()
  await expect(page.getByText('Execution is blocked')).toBeVisible()
  await expect(page.getByText('Execution HOLD', { exact: true })).toBeVisible()
})

test('team chooser, project switch, and browser history preserve durable URL state', async ({ page }) => {
  await mockWorkbenchV1(page, { session: { ...personalSession, mode: 'team', memberships: [{ project_id: 'project-a', role: 'owner' }, { project_id: 'project-b', role: 'viewer' }] } })
  await page.goto('/workbench/settings')
  await expect(page.getByText('Choose a project')).toBeVisible()
  await page.getByRole('button', { name: 'Use project' }).first().click()
  await expect(page).toHaveURL(/project_id=project-a/)
  await page.getByRole('button', { name: 'Use project' }).last().click()
  await expect(page).toHaveURL(/project_id=project-b/)
  await page.goBack()
  await expect(page).toHaveURL(/project_id=project-a/)
  await page.goForward()
  await expect(page).toHaveURL(/project_id=project-b/)
})

test('recovery states are explicit for analysis, trace, review, evidence, and settings', async ({ page }) => {
  await mockWorkbenchV1(page, { unavailable: true })
  for (const [route, title] of [
    ['/workbench/analyze?experiment_id=fixture-created-experiment&execution_id=fixture-execution', 'Analysis recovery unavailable'],
    ['/workbench/trace-lab?execution_id=fixture-execution', 'Trace Lab unavailable'],
    ['/workbench/review', 'Review recovery unavailable'],
    ['/workbench/evidence', 'Evidence recovery unavailable'],
    ['/workbench/settings', 'Settings readiness unavailable'],
  ]) {
    await page.goto(route)
    await expect(page.getByText(title)).toBeVisible()
  }
})

test('keyboard navigation, evidence drawer focus trap and restore, reduced motion, and non-colour status survive mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await expect(page.getByRole('link', { name: 'Skip to workspace' })).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to workspace' })).toBeFocused()
  await page.getByRole('button', { name: 'Open evidence and specification' }).focus()
  await page.keyboard.press('Enter')
  const drawer = page.getByRole('dialog', { name: 'Evidence and specification' })
  await expect(drawer).toBeVisible()
  await expect(drawer.getByRole('button', { name: 'Close' })).toBeFocused()
  await drawer.getByRole('button', { name: 'Close' }).press('Shift+Tab')
  await expect(drawer.getByText('Evidence limitation')).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(drawer.getByRole('button', { name: 'Close' })).toBeFocused()
  await expect(drawer).toHaveCSS('transition-duration', '0.01s')
  await page.keyboard.press('Escape')
  await expect(drawer).toBeHidden()
  await expect(page.getByRole('button', { name: 'Open evidence and specification' })).toBeFocused()
  await expect(
    page.getByLabel('Mobile workbench commands').getByText('Revision unverified'),
  ).toBeVisible()
})

test('evidence drawer is visible at desktop width and restores focus after Escape', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  const opener = page.getByRole('button', { name: 'Open evidence inspector' })
  await opener.focus()
  await page.keyboard.press('Enter')
  const drawer = page.getByRole('dialog', { name: 'Evidence and specification' })
  await expect(drawer).toBeVisible()
  await expect(drawer.getByRole('button', { name: 'Close' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(drawer).toBeHidden()
  await expect(opener).toBeFocused()
})

test('desktop, tablet, and mobile v1 routes render without horizontal overflow', async ({ page }) => {
  for (const viewport of [{ width: 1440, height: 900 }, { width: 768, height: 1024 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    await page.goto(`/workbench/design?study_pack_id=${fixturePack.study_pack_id}&study_pack_version=${fixturePack.version}`)
    await page.getByRole('button', { name: 'Lab', exact: true }).click()
    await expect(page.locator('h1.sa-stage-heading')).toHaveText('Design')
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(2)
  }
})

test('X-Ray and Observatory preserve their evidence boundary on a reduced-motion mobile viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  for (const [route, heading, boundary] of [
    ['/workbench/xray', 'Harness X-Ray', /never executes source, starts a provider, or contacts a network endpoint/i],
    ['/workbench/observatory', 'Context, Memory, Loop, and Graph Observatory', /does not execute a graph, replay an attempt, or reconstruct missing evidence/i],
  ]) {
    await page.goto(route)
    await expect(page.getByRole('region', { name: heading })).toBeVisible()
    await expect(page.getByText(boundary)).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(2)
  }
})

test('Counterfactual Replay stays provider-free, keyboard-operable, and narrow-screen safe', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/workbench/counterfactual')
  await expect(page.getByText('$0.00 consumed')).toBeVisible()
  const replay = page.getByRole('button', { name: 'Run provider-free fixture replay' })
  await replay.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'Effect and uncertainty' })).toBeVisible()
  await page.getByRole('button', { name: 'Run Harness CI check' }).click()
  await expect(page.getByRole('heading', { name: 'Policy checks' })).toBeVisible()
  await expect(page.getByRole('status')).toContainText(/not posted a comment/i)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(2)
})

test('Arena Forge keeps its untrusted, digest-only controls keyboard-operable on reduced-motion mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/workbench/forge')
  await expect(page.getByText(/cannot inspect sealed holdouts/i)).toBeVisible()
  const stage = page.getByRole('button', { name: 'Stage untrusted fixture proposal' })
  await stage.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByText('Untrusted proposal record')).toBeVisible()
  await page.getByRole('button', { name: 'Simulate next best experiment' }).click()
  await expect(page.getByRole('table', { name: 'Ranked constrained experiment designs' })).toBeVisible()
  await page.getByRole('button', { name: 'Check process-safety controls' }).click()
  await expect(page.getByRole('table', { name: 'Process-safety checks' })).toBeVisible()
  await expect(page.getByRole('status')).toContainText(/PASS: process-safety control record retained/i)
  expect(await stage.evaluate((element) => Number.parseFloat(getComputedStyle(element).transitionDuration))).toBeLessThanOrEqual(0.001)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(2)
})
