import { render, screen } from '@testing-library/react'

import LiveRegion from './LiveRegion'

describe('LiveRegion', () => {
  test('renders polite status announcements by default', () => {
    render(<LiveRegion message="Run complete. Winner ready." />)
    const status = screen.getByRole('status')
    expect(status).toHaveAttribute('aria-live', 'polite')
    expect(status).toHaveTextContent('Run complete. Winner ready.')
  })

  test('renders assertive alert announcements when requested', () => {
    render(
      <LiveRegion
        message="Connection failed. Retry required."
        priority="assertive"
      />,
    )
    const alert = screen.getByRole('alert')
    expect(alert).toHaveAttribute('aria-live', 'assertive')
    expect(alert).toHaveTextContent('Connection failed. Retry required.')
  })
})
