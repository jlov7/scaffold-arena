import { describe, expect, it } from 'vitest'

import { resolveTeamProject } from './teamProject'

const team = (memberships: Array<{ project_id: string; role: 'admin' | 'operator' | 'reviewer' | 'viewer' }>) => ({ authenticated: true, mode: 'team' as const, memberships })

describe('team project selection', () => {
  it('does not invent project context for zero memberships', () => {
    expect(resolveTeamProject(team([]), undefined)).toEqual({ kind: 'choose', memberships: [] })
  })

  it('recovers exactly one membership without a chooser', () => {
    expect(resolveTeamProject(team([{ project_id: 'only-project', role: 'operator' }]), undefined)).toEqual({ kind: 'auto', projectId: 'only-project' })
  })

  it('requires explicit selection for multiple memberships and preserves an URL project', () => {
    const memberships = [{ project_id: 'alpha', role: 'viewer' as const }, { project_id: 'beta', role: 'admin' as const }]
    expect(resolveTeamProject(team(memberships), undefined)).toEqual({ kind: 'choose', memberships })
    expect(resolveTeamProject(team(memberships), 'beta')).toEqual({ kind: 'ready' })
    expect(resolveTeamProject(team(memberships), 'revoked-project')).toEqual({ kind: 'choose', memberships })
  })
})
