import { describe, expect, it } from 'vitest'

import { normalizeWebVitalMetric } from './perf/webVitals'

describe('normalizeWebVitalMetric', () => {
  it('normalizes numeric metric payload', () => {
    const metric = normalizeWebVitalMetric({
      name: 'LCP',
      value: 1234.56,
      id: 'abc',
      rating: 'good',
    })

    expect(metric).toEqual({
      metric_name: 'LCP',
      value: 1234.56,
      metric_id: 'abc',
      rating: 'good',
    })
  })
})
