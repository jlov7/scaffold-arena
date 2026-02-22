import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ToastStack from './ToastStack'

describe('ToastStack accessibility', () => {
  it('uses assertive live region for errors', () => {
    render(
      <ToastStack
        toasts={[{ id: 1, type: 'error', message: 'Something failed' }]}
        onDismiss={vi.fn()}
      />,
    )

    const toast = screen.getByRole('alert')
    expect(toast).toHaveAttribute('aria-live', 'assertive')
  })

  it('uses polite live region for non-errors', () => {
    render(
      <ToastStack
        toasts={[{ id: 1, type: 'success', message: 'Saved' }]}
        onDismiss={vi.fn()}
      />,
    )

    const toast = screen.getByRole('status')
    expect(toast).toHaveAttribute('aria-live', 'polite')
  })
})
