import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Button } from './primitives/Button'
import StateCallout from './StateCallout'
import { ProgressStepper } from './journey/ProgressStepper'

describe('story-driven component coverage', () => {
  it('renders button tone stories', () => {
    const stories = [
      { tone: 'primary' as const, label: 'Run arena' },
      { tone: 'secondary' as const, label: 'Open settings' },
      { tone: 'danger' as const, label: 'Cancel run' },
    ]

    stories.forEach((story) => {
      const view = render(<Button tone={story.tone}>{story.label}</Button>)
      expect(screen.getByRole('button', { name: story.label })).toBeInTheDocument()
      view.unmount()
    })
  })

  it('renders state callout stories for each state family', () => {
    const stories = [
      { kind: 'loading' as const, title: 'Loading run' },
      { kind: 'empty' as const, title: 'No results yet' },
      { kind: 'partial' as const, title: 'Partial output captured' },
      { kind: 'error' as const, title: 'Request failed' },
      { kind: 'blocked' as const, title: 'Blocked by configuration' },
      { kind: 'success' as const, title: 'Run complete' },
    ]

    stories.forEach((story) => {
      const view = render(
        <StateCallout
          kind={story.kind}
          title={story.title}
          description="Story coverage snapshot."
        />,
      )
      expect(screen.getByText(story.title)).toBeInTheDocument()
      view.unmount()
    })
  })

  it('renders progress-stepper stories for setup and review stages', () => {
    const stories = [
      {
        label: 'setup',
        steps: [
          { id: 'setup' as const, label: 'Choose task and model', status: 'current' as const },
          { id: 'run' as const, label: 'Run arena', status: 'upcoming' as const },
          { id: 'review' as const, label: 'Review scoreboard', status: 'upcoming' as const },
          { id: 'iterate' as const, label: 'Compare, autopsy, export', status: 'upcoming' as const },
        ],
      },
      {
        label: 'review',
        steps: [
          { id: 'setup' as const, label: 'Choose task and model', status: 'complete' as const },
          { id: 'run' as const, label: 'Run arena', status: 'complete' as const },
          { id: 'review' as const, label: 'Review scoreboard', status: 'current' as const },
          { id: 'iterate' as const, label: 'Compare, autopsy, export', status: 'upcoming' as const },
        ],
      },
    ]

    stories.forEach((story) => {
      const view = render(<ProgressStepper steps={story.steps} />)
      expect(screen.getAllByText(/Step/i).length).toBeGreaterThan(0)
      view.unmount()
    })
  })
})
