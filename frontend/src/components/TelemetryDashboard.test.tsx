import { render, screen } from '@testing-library/react'

import TelemetryDashboard from './TelemetryDashboard'

describe('TelemetryDashboard', () => {
  test('renders onboarding and recovery metrics', () => {
    render(
      <TelemetryDashboard
        events={[
          { name: 'onboarding_step_completed', payload: {}, ts_ms: 1 },
          { name: 'onboarding_step_completed', payload: {}, ts_ms: 2 },
          { name: 'onboarding_help_opened', payload: {}, ts_ms: 3 },
          { name: 'onboarding_primary_action', payload: {}, ts_ms: 4 },
          { name: 'onboarding_blocker_detected', payload: {}, ts_ms: 5 },
          {
            name: 'onboarding_blocker_resolved',
            payload: { duration_ms: 12000 },
            ts_ms: 6,
          },
          { name: 'fallback_mode_enabled', payload: {}, ts_ms: 7 },
          {
            name: 'route_timing',
            payload: { from_view: 'arena', to_view: 'results', dwell_ms: 4200 },
            ts_ms: 8,
          },
          {
            name: 'persona_selected',
            payload: { profile: 'operator', experience_mode: 'advanced' },
            ts_ms: 9,
          },
          {
            name: 'activation_completed',
            payload: { profile: 'operator' },
            ts_ms: 10,
          },
          {
            name: 'ux_feedback_submitted',
            payload: { sentiment: 'helpful' },
            ts_ms: 11,
          },
        ]}
      />,
    )

    expect(screen.getByText('Onboarding Funnel')).toBeInTheDocument()
    expect(screen.getByText('Onboarding steps completed')).toBeInTheDocument()
    expect(screen.getByText('Help opened')).toBeInTheDocument()
    expect(screen.getByText('Primary actions used')).toBeInTheDocument()
    expect(screen.getByText('Failure Recovery')).toBeInTheDocument()
    expect(screen.getByText('Recovery success rate')).toBeInTheDocument()
    expect(screen.getByText('100%')).toBeInTheDocument()
    expect(screen.getByText('Fallback mode activations')).toBeInTheDocument()
    expect(screen.getByText('Route Timing')).toBeInTheDocument()
    expect(screen.getByText('Route transitions')).toBeInTheDocument()
    expect(screen.getByText('Role Segments')).toBeInTheDocument()
    expect(screen.getByText('Activation completions')).toBeInTheDocument()
    expect(screen.getByText('Feedback submissions')).toBeInTheDocument()
  })
})
