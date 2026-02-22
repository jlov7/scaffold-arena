import { fireEvent, render, screen } from '@testing-library/react'

import {
  ExperienceModeCard,
  type ExperienceMode,
  type UserProfile,
} from './ExperienceModeCard'

describe('ExperienceModeCard', () => {
  test('lets user switch mode and role', () => {
    let mode: ExperienceMode = 'guided'
    let profile: UserProfile = 'evaluator'

    render(
      <ExperienceModeCard
        mode={mode}
        profile={profile}
        onModeChange={(next) => {
          mode = next
        }}
        onProfileChange={(next) => {
          profile = next
        }}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Advanced' }))
    fireEvent.click(screen.getByRole('button', { name: 'Executive' }))

    expect(mode).toBe('advanced')
    expect(profile).toBe('executive')
  })
})
