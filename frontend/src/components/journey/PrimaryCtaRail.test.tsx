import { render, screen } from '@testing-library/react'

import { PrimaryCtaRail } from './PrimaryCtaRail'

function renderRail(orderVariant: 'compare_first' | 'export_first') {
  render(
    <PrimaryCtaRail
      stage="review"
      canRun
      hasResults
      orderVariant={orderVariant}
      onRun={() => {}}
      onCompare={() => {}}
      onExport={() => {}}
      onShare={() => {}}
    />,
  )
}

describe('PrimaryCtaRail', () => {
  test('renders compare before export for compare_first variant', () => {
    renderRail('compare_first')
    const buttons = screen.getAllByRole('button')
    const labels = buttons.map((button) => button.textContent?.trim())
    expect(labels).toContain('Run proof comparison')
    expect(labels).toContain('Export report')
    expect(labels.indexOf('Run proof comparison')).toBeLessThan(
      labels.indexOf('Export report'),
    )
  })

  test('renders export before compare for export_first variant', () => {
    renderRail('export_first')
    const buttons = screen.getAllByRole('button')
    const labels = buttons.map((button) => button.textContent?.trim())
    expect(labels).toContain('Run proof comparison')
    expect(labels).toContain('Export report')
    expect(labels.indexOf('Export report')).toBeLessThan(
      labels.indexOf('Run proof comparison'),
    )
  })

  test('shows focused review action in guided mode after results exist', () => {
    render(
      <PrimaryCtaRail
        stage="review"
        canRun
        hasResults
        showSecondary={false}
        onOpenResults={() => {}}
        onRun={() => {}}
        onCompare={() => {}}
        onExport={() => {}}
        onShare={() => {}}
      />,
    )

    expect(
      screen.getByRole('button', { name: 'Review results' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Run proof comparison' }),
    ).not.toBeInTheDocument()
  })
})
