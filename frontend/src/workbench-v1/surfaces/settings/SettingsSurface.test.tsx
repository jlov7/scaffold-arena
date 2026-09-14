import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { SettingsSurface } from './SettingsSurface'

describe('SettingsSurface', () => {
  it('renders the archival-only retention ceiling without claiming deletion', async () => {
    const client = {
      auth: { session: vi.fn().mockResolvedValue({ authenticated: true, mode: 'team', user: { subject: 'admin' }, memberships: [] }) },
      settings: { get: vi.fn().mockResolvedValue({ deployment_profile: 'team', storage: { kind: 'postgresql', configured: true, team_ready: true }, authentication: { mode: 'oidc_server_session', configured: true }, adapters: { configured: true, provider_started: false }, budget: { max_cost_per_run_usd: 1, daily_budget_usd: 2 }, retention: { status: 'PASS_ARCHIVAL_ONLY', reason: 'Recovery-bound archival only.' }, secrets: { exposed: false, source: 'environment' } }) },
    } as unknown as Parameters<typeof SettingsSurface>[0]['client']
    render(<SettingsSurface client={client} projectId="project-one" />)
    expect(await screen.findByText(/PASS_ARCHIVAL_ONLY/)).toBeInTheDocument()
    expect(screen.getByText(/does not claim project deletion or artifact-byte reclamation/i)).toBeInTheDocument()
  })

  it('keeps Guided identity context decision-level rather than exposing durable identities', async () => {
    const client = {
      auth: { session: vi.fn().mockResolvedValue({ authenticated: true, mode: 'team', user: { subject: 'member-opaque-id' }, memberships: [{ project_id: 'project-opaque-id', role: 'viewer' }] }) },
      settings: { get: vi.fn().mockResolvedValue({ deployment_profile: 'team', storage: { kind: 'postgresql', configured: true, team_ready: true }, authentication: { mode: 'oidc_server_session', configured: true }, adapters: { configured: true, provider_started: false }, budget: { max_cost_per_run_usd: 1, daily_budget_usd: 2 }, retention: { status: 'PASS_ARCHIVAL_ONLY', reason: 'Recovery-bound archival only.' }, secrets: { exposed: false, source: 'environment' } }) },
    } as unknown as Parameters<typeof SettingsSurface>[0]['client']
    render(<SettingsSurface client={client} projectId="project-opaque-id" mode="guided" />)
    await waitFor(() => expect(screen.getByText(/Project context:/)).toHaveTextContent('Selected authorized project'))
    expect(screen.getByText(/Authenticated subject:/)).toHaveTextContent('Authenticated team member')
    expect(screen.getByText(/Authorized project 1/)).toBeInTheDocument()
    expect(screen.queryByText('project-opaque-id')).not.toBeInTheDocument()
    expect(screen.queryByText('member-opaque-id')).not.toBeInTheDocument()
  })
})
