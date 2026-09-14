import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import StreamingText from './StreamingText'

describe('StreamingText', () => {
  it('renders safely when text is undefined', () => {
    render(<StreamingText text={undefined} isStreaming={false} />)

    const output = screen.getByText('', { selector: 'pre' })
    expect(output).toBeInTheDocument()
  })

  it('shows cursor while streaming', () => {
    const { container } = render(<StreamingText text={null} isStreaming />)

    expect(container.querySelector('span.animate-pulse')).toBeInTheDocument()
  })

  it('windows long output by default and allows full expansion', async () => {
    const longText = `prefix-${'A'.repeat(15_000)}-suffix`
    const { container } = render(<StreamingText text={longText} isStreaming={false} />)

    expect(screen.getByRole('button', { name: /show full output/i })).toBeInTheDocument()
    const pre = container.querySelector('pre')
    expect(pre?.textContent).toContain('suffix')
    expect(pre?.textContent).not.toContain('prefix-')

    fireEvent.click(screen.getByRole('button', { name: /show full output/i }))
    await waitFor(() => {
      expect(pre?.textContent).toContain('prefix-')
    })
  })
})
