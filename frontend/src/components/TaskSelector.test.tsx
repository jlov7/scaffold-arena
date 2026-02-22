import { render, screen } from '@testing-library/react'

import { TaskSelector } from './TaskSelector'

describe('TaskSelector', () => {
  test('infers provider label when provider metadata is missing', () => {
    render(
      <TaskSelector
        tasks={[
          {
            id: 'extraction',
            name: 'Extraction',
            subtitle: 'Extract fields',
            type: 'EXTRACTION',
          },
        ]}
        models={[
          {
            id: 'claude-sonnet-4-6',
            label: 'Claude Sonnet 4.6',
            provider: undefined as unknown as string,
            input_usd_per_mtok: 3,
            output_usd_per_mtok: 15,
          },
        ]}
        isRunning={false}
        selectedTaskId="extraction"
        selectedModelId="claude-sonnet-4-6"
        estimatedCostUsd={0.21}
        onSelectTask={() => {}}
        onSelectModel={() => {}}
        onRun={() => {}}
        onCancel={() => {}}
      />,
    )

    const option = screen.getByRole('option', {
      name: '[anthropic] Claude Sonnet 4.6 ($3/$15)',
    })
    expect(option).toBeInTheDocument()
  })
})
