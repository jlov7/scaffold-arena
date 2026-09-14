import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

import { fixturePack, mockWorkbenchV1 } from '../support/workbenchV1Mock'

test('Workbench v1 default and primary recovery routes have no serious or critical WCAG 2.2 axe violations', async ({ page }) => {
  await mockWorkbenchV1(page)
  for (const route of [
    '/',
    `/workbench/design?study_pack_id=${fixturePack.study_pack_id}&study_pack_version=${fixturePack.version}`,
    '/workbench/studies',
    '/workbench/execute?experiment_id=fixture-created-experiment',
    '/workbench/analyze?experiment_id=fixture-created-experiment&execution_id=fixture-execution',
    '/workbench/evidence?execution_id=fixture-execution',
    '/workbench/xray',
    '/workbench/observatory',
    '/workbench/counterfactual',
    '/workbench/forge',
    '/workbench/trace-lab?execution_id=fixture-execution',
    '/workbench/settings',
  ]) {
    await page.goto(route)
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag22aa']).analyze()
    const blocking = results.violations.filter((violation) => ['critical', 'serious'].includes(violation.impact ?? ''))
    expect(blocking, `${route}: ${JSON.stringify(blocking, null, 2)}`).toEqual([])
  }
})
