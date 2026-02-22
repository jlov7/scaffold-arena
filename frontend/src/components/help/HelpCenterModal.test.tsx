import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import HelpCenterModal from './HelpCenterModal'

describe('HelpCenterModal', () => {
  test('shows offline troubleshooting guidance', () => {
    render(
      <HelpCenterModal
        isOpen
        isOnline={false}
        connectionState="idle"
        hasApiToken
        profile="evaluator"
        taskId="extraction"
        errorMessage={null}
        onClose={() => {}}
        onOpenTour={() => {}}
        onOpenShortcuts={() => {}}
        onOpenSettings={() => {}}
        onRetry={() => {}}
        onRun={() => {}}
      />,
    )

    expect(screen.getByRole('dialog', { name: /help center/i })).toBeInTheDocument()
    expect(screen.getByText(/You appear to be offline/i)).toBeInTheDocument()
    expect(screen.getByText(/Extraction recovery playbook/i)).toBeInTheDocument()
  })

  test('routes quick actions and closes on escape', () => {
    const onClose = vi.fn()
    const onOpenTour = vi.fn()
    const onOpenShortcuts = vi.fn()
    const onOpenSettings = vi.fn()
    const onRetry = vi.fn()
    const onRun = vi.fn()

    render(
      <HelpCenterModal
        isOpen
        isOnline
        connectionState="connected"
        hasApiToken
        profile="evaluator"
        taskId="research"
        errorMessage={null}
        onClose={onClose}
        onOpenTour={onOpenTour}
        onOpenShortcuts={onOpenShortcuts}
        onOpenSettings={onOpenSettings}
        onRetry={onRetry}
        onRun={onRun}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /^Open guided tour$/i }))
    expect(onOpenTour).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledTimes(1)

    fireEvent.keyDown(screen.getByRole('dialog', { name: /help center/i }), {
      key: 'Escape',
    })
    expect(onClose).toHaveBeenCalledTimes(2)

    fireEvent.click(screen.getByRole('button', { name: /show shortcuts/i }))
    expect(onOpenShortcuts).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: /open settings/i }))
    expect(onOpenSettings).toHaveBeenCalledTimes(1)
    expect(onRetry).toHaveBeenCalledTimes(0)
    expect(onRun).toHaveBeenCalledTimes(0)
  })

  test('runs playbook primary action for auth blockers', () => {
    const onClose = vi.fn()
    const onOpenSettings = vi.fn()

    render(
      <HelpCenterModal
        isOpen
        isOnline
        connectionState="connected"
        hasApiToken={false}
        profile="evaluator"
        taskId="risk"
        errorMessage={null}
        onClose={onClose}
        onOpenTour={() => {}}
        onOpenShortcuts={() => {}}
        onOpenSettings={onOpenSettings}
        onRetry={() => {}}
        onRun={() => {}}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Open settings now/i }))
    expect(onOpenSettings).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  test('shows role path and triggers recommended role action', () => {
    const onClose = vi.fn()
    const onOpenTour = vi.fn()

    render(
      <HelpCenterModal
        isOpen
        isOnline
        connectionState="connected"
        hasApiToken
        profile="executive"
        taskId="extraction"
        errorMessage={null}
        onClose={onClose}
        onOpenTour={onOpenTour}
        onOpenShortcuts={() => {}}
        onOpenSettings={() => {}}
        onRetry={() => {}}
        onRun={() => {}}
      />,
    )

    expect(screen.getByText(/Role path: Executive/i)).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole('button', { name: /Recommended: Open guided tour now/i }),
    )
    expect(onOpenTour).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
