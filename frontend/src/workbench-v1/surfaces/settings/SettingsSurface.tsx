import { useCallback, useEffect, useState } from 'react'

import { ApiProblem, createArenaV1, type ArenaSession, type DeploymentReadiness } from '../../../api/v1/client'
import { SevereFailureBanner, StatusIndicator, WorkbenchButton, WorkbenchPanel, WorkbenchState } from '../../design-system'

import './settings.css'

type Client = ReturnType<typeof createArenaV1>

export function SettingsSurface({ client, projectId, mode = 'lab', onProjectSelect }: { client: Client; projectId?: string; mode?: 'guided' | 'lab'; onProjectSelect?: (projectId: string) => void }) {
  const [session, setSession] = useState<ArenaSession | null>(null)
  const [readiness, setReadiness] = useState<DeploymentReadiness | null>(null)
  const [message, setMessage] = useState('')
  const [state, setState] = useState<'loading' | 'ready' | 'offline' | 'permission' | 'error'>('loading')

  const load = useCallback(async () => {
    setState('loading')
    try {
      const [currentSession, currentReadiness] = await Promise.all([client.auth.session({ projectId }), client.settings.get({ projectId })])
      setSession(currentSession); setReadiness(currentReadiness); setState('ready'); setMessage('')
    } catch (error) {
      if (error instanceof ApiProblem && (error.status === 401 || error.status === 403)) setState('permission')
      else if (error instanceof ApiProblem && error.status < 500) setState('error')
      else setState('offline')
      setMessage(error instanceof Error ? error.message : 'Settings readiness could not be recovered.')
    }
  }, [client, projectId])
  useEffect(() => {
    const timer = window.setTimeout(() => { void load() }, 0)
    return () => window.clearTimeout(timer)
  }, [load])

  if (state === 'loading') return <WorkbenchState kind="loading" title="Recovering deployment readiness">Reading the authoritative deployment, session, adapter, budget, and retention state.</WorkbenchState>
  if (state === 'offline') return <WorkbenchState kind="offline" title="Settings readiness unavailable" action={<WorkbenchButton onClick={() => void load()}>Retry</WorkbenchButton>}>{message}</WorkbenchState>
  if (state === 'permission') return <SevereFailureBanner title="Session or project access required" action={<WorkbenchButton onClick={() => void load()}>Retry session</WorkbenchButton>}>{message || 'Select an authorized project or sign in through the configured team identity provider.'}</SevereFailureBanner>
  if (state === 'error' || !readiness || !session) return <WorkbenchState kind="error" title="Could not recover settings" action={<WorkbenchButton onClick={() => void load()}>Retry</WorkbenchButton>}>{message}</WorkbenchState>

  return <section className="sa-journey" aria-labelledby="settings-heading">
    <WorkbenchPanel title={<span id="settings-heading">Deployment and authority</span>} action={<StatusIndicator tone={readiness.deployment_profile === 'team' ? 'info' : 'warning'}>{readiness.deployment_profile}</StatusIndicator>}>
      <p className="sa-journey-copy">This is protocol-v1 readiness only. It reports configured state and explicit HOLDs; it does not claim deployment assurance, provider execution, benchmark outcomes, or retention completion.</p>
      <dl className="sa-settings-grid"><div><dt>Session</dt><dd>{session.authenticated ? `${session.mode} session` : 'Unauthenticated'}</dd></div><div><dt>Storage</dt><dd>{readiness.storage.kind} · {readiness.storage.configured ? 'configured' : 'not configured'}</dd></div><div><dt>Authentication</dt><dd>{readiness.authentication.mode} · {readiness.authentication.configured ? 'configured' : 'not configured'}</dd></div><div><dt>Adapters</dt><dd>{readiness.adapters.configured ? 'configured' : 'not configured'} · provider started: {String(readiness.adapters.provider_started)}</dd></div><div><dt>Run budget</dt><dd>${readiness.budget.max_cost_per_run_usd.toFixed(2)}</dd></div><div><dt>Daily budget</dt><dd>${readiness.budget.daily_budget_usd.toFixed(2)}</dd></div></dl>
    </WorkbenchPanel>
    {readiness.retention.status === 'HOLD' ? <SevereFailureBanner title="Retention and deletion HOLD">{readiness.retention.reason}</SevereFailureBanner> : <WorkbenchPanel title="Retention and deletion"><p className="sa-journey-copy">{readiness.retention.status}: {readiness.retention.reason}</p><p className="sa-journey-copy">Retention plans are project-scoped, confirmation-bound, and admin-only. This surface does not claim project deletion or artifact-byte reclamation.</p></WorkbenchPanel>}
    <WorkbenchPanel title="Identity and project scope"><p className="sa-journey-copy">Project context: {mode === 'lab' ? <code>{projectId ?? session.project_id ?? 'Not selected'}</code> : projectId || session.project_id ? 'Selected authorized project' : 'Not selected'}</p>{session.mode === 'team' ? <><p className="sa-journey-copy">Authenticated subject: {mode === 'lab' ? <code>{session.user?.subject ?? 'Unknown'}</code> : session.user ? 'Authenticated team member' : 'Unknown'}</p><ul className="sa-journey-list">{session.memberships?.length ? session.memberships.map((membership, index) => <li key={membership.project_id}>{mode === 'lab' ? <code>{membership.project_id}</code> : `Authorized project ${index + 1}`} — {membership.role}{onProjectSelect && <WorkbenchButton disabled={membership.project_id === projectId} onClick={() => onProjectSelect(membership.project_id)}>Use project</WorkbenchButton>}</li>) : <li>No project memberships were returned.</li>}</ul></> : <p className="sa-journey-copy">Personal mode has no login flow and retains the stated local authority ceiling: {session.authority_ceiling ?? 'Unknown'}.</p>}</WorkbenchPanel>
    <WorkbenchPanel title="Secret boundary"><p className="sa-journey-copy">Secret exposure: {String(readiness.secrets.exposed)}. Source policy: {readiness.secrets.source}. This UI does not collect, display, cache, or transmit provider credentials.</p></WorkbenchPanel>
  </section>
}
