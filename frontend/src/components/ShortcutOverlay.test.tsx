import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ShortcutOverlay from './ShortcutOverlay'

describe('ShortcutOverlay accessibility', () => {
  it('renders as dialog and closes on Escape', () => {
    const onClose = vi.fn()
    render(<ShortcutOverlay isOpen onClose={onClose} />)

    const dialog = screen.getByRole('dialog', { name: /keyboard shortcuts/i })
    expect(dialog).toBeInTheDocument()

    fireEvent.keyDown(dialog, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
