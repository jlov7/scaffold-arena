import type { Metric } from 'web-vitals'

import { trackEvent } from '../telemetry/tracker'

export function normalizeWebVitalMetric(metric: Pick<Metric, 'name' | 'value' | 'id' | 'rating'>): Record<string, unknown> {
  return {
    metric_name: metric.name,
    value: Number(metric.value),
    metric_id: metric.id,
    rating: metric.rating,
  }
}

export async function initWebVitals(): Promise<void> {
  const { onCLS, onINP, onLCP, onFCP, onTTFB } = await import('web-vitals')
  const report = (metric: Metric) => {
    trackEvent('web_vital', normalizeWebVitalMetric(metric))
  }
  onCLS(report)
  onINP(report)
  onLCP(report)
  onFCP(report)
  onTTFB(report)
}
