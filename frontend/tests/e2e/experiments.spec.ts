import { expect, test } from '@playwright/test'

import { mockLeaderboard, mockMeta, mockRunDetails, mockRunHistory } from '../support/mockApi'

test.beforeEach(async ({ page }) => {
  await mockMeta(page)
  await mockRunHistory(page)
  await mockLeaderboard(page)
  await mockRunDetails(page)
})

test('tour_entry auto_open variant opens guided tour on first load', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.removeItem('scaffold_arena_tour_seen')
    window.localStorage.setItem('scaffold_arena_exp_tour_entry', 'auto_open')
  })

  await page.goto('/arena')

  await expect(page.getByRole('dialog', { name: 'Guided Tour' })).toBeVisible()
})

test('tour_entry cta_only variant does not auto-open guided tour', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.removeItem('scaffold_arena_tour_seen')
    window.localStorage.setItem('scaffold_arena_exp_tour_entry', 'cta_only')
  })

  await page.goto('/arena')

  await expect(page.getByRole('dialog', { name: 'Guided Tour' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Take the tour' })).toBeVisible()
})
