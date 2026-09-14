import type { ArenaSession } from '../api/v1/client'

export type TeamProjectDecision =
  | { kind: 'not_team' | 'ready' }
  | { kind: 'auto'; projectId: string }
  | { kind: 'choose'; memberships: NonNullable<ArenaSession['memberships']> }

export function resolveTeamProject(session: ArenaSession | null, projectId: string | undefined): TeamProjectDecision {
  if (session?.mode !== 'team') return { kind: 'not_team' }
  const memberships = session.memberships ?? []
  if (projectId && memberships.some((membership) => membership.project_id === projectId)) return { kind: 'ready' }
  if (projectId) return { kind: 'choose', memberships }
  if (memberships.length === 1) return { kind: 'auto', projectId: memberships[0].project_id }
  return { kind: 'choose', memberships }
}
