import { useCallback, useEffect, useRef, useState } from 'react'
import type { AttemptTraceView, AttemptView, ExecutionDetail, ExecutionSummary } from '../../../api/v1/client'
import { problemMessage, type ArenaV1Client } from '../study-design-preflight/types'
import type { ExecutionActivity, ExecutionControlInput, ExecutionRemoteState } from './types'

interface UseExecutionControlOptions extends ExecutionControlInput {
  client: ArenaV1Client
  projectId?: string
  onExecutionSelected?: (executionId: string) => void
}

function stateFor(error: unknown): ExecutionRemoteState {
  const problem = problemMessage(error)
  return problem.kind === 'offline' ? 'offline' : problem.kind === 'permission' ? 'permission' : 'error'
}

function messageFor(error: unknown): string {
  return problemMessage(error).message
}

function isExecutionTerminal(event: ExecutionActivity['event'], executionId: string): boolean {
  return event.event === 'terminal'
    && event.data.execution_id === executionId
    && typeof event.data.status === 'string'
    && /^(completed|failed|cancelled)$/.test(event.data.status)
}

export function useExecutionControl({ client, projectId, frozenExperimentId, preflightReport, requestedExecutionId = null, onExecutionSelected }: UseExecutionControlOptions) {
  const [state, setState] = useState<ExecutionRemoteState>('loading')
  const [message, setMessage] = useState('')
  const [executions, setExecutions] = useState<ExecutionSummary[]>([])
  const [nextOffset, setNextOffset] = useState<number | null>(null)
  const [selected, setSelected] = useState<ExecutionDetail | null>(null)
  const [events, setEvents] = useState<ExecutionActivity[]>([])
  const [attempt, setAttempt] = useState<AttemptView | null>(null)
  const [trace, setTrace] = useState<AttemptTraceView | null>(null)
  const [busy, setBusy] = useState(false)
  const selectedId = useRef<string | null>(null)
  const fixtureRequests = useRef(new Map<string, { key: string; executionId?: string; terminal?: boolean }>())
  const loadGeneration = useRef(0)
  const routeIdentity = useRef('')

  const captureCurrent = useCallback(() => {
    const generation = loadGeneration.current
    return () => generation === loadGeneration.current
  }, [])

  const observeFixtureExecution = useCallback((detail: ExecutionDetail) => {
    const request = fixtureRequests.current.get(JSON.stringify([projectId, frozenExperimentId]))
    if (request?.executionId === detail.execution_id && /^(completed|failed|cancelled)$/.test(detail.status)) {
      request.terminal = true
    }
  }, [projectId, frozenExperimentId])

  const refreshSelected = useCallback(async (executionId: string, isCurrent: () => boolean) => {
    const detail = await client.executions.get(executionId, { projectId })
    if (!isCurrent()) return null
    observeFixtureExecution(detail)
    selectedId.current = executionId
    setSelected(detail)
    return detail
  }, [client, projectId, observeFixtureExecution])

  const load = useCallback(async (executionId = requestedExecutionId ?? (
    routeIdentity.current === JSON.stringify([projectId, frozenExperimentId, requestedExecutionId]) ? selectedId.current : null
  )) => {
    const generation = ++loadGeneration.current
    const isCurrent = () => generation === loadGeneration.current
    const identity = JSON.stringify([projectId, frozenExperimentId, requestedExecutionId])
    if (routeIdentity.current !== identity) {
      routeIdentity.current = identity
      selectedId.current = executionId ?? null
      setSelected(null); setEvents([]); setAttempt(null); setTrace(null)
    }
    setBusy(false)
    if (!frozenExperimentId) {
      if (isCurrent()) { setExecutions([]); setNextOffset(null); setSelected(null); setState('empty') }
      return
    }
    setState('loading')
    setMessage('')
    try {
      const response = await client.executions.list({ experimentId: frozenExperimentId }, { projectId })
      if (!isCurrent()) return
      const summaries = response.executions
      if (executionId) {
        const detail = await client.executions.get(executionId, { projectId })
        if (!isCurrent()) return
        if (detail.experiment_id !== frozenExperimentId) {
          setExecutions(summaries); setNextOffset(response.pagination.next_offset); setSelected(null)
          setState('error'); setMessage('The URL-selected execution belongs to a different experiment. No execution was selected.')
          return
        }
        selectedId.current = executionId
        observeFixtureExecution(detail)
        setExecutions(summaries.some((item) => item.execution_id === executionId) ? summaries : [detail, ...summaries])
        setNextOffset(response.pagination.next_offset)
        setSelected(detail)
        setState('ready')
        return generation
      }
      if (summaries.length === 0) {
        setExecutions([]); setNextOffset(null); setSelected(null); setState('empty'); return
      }
      setExecutions(summaries)
      setNextOffset(response.pagination.next_offset)
      const current = summaries.find((item) => item.execution_id === selectedId.current) ?? summaries[0]
      const detail = await refreshSelected(current.execution_id, isCurrent)
      if (!detail || !isCurrent()) return
      setState('ready')
      return generation
    } catch (error) {
      if (isCurrent()) { setState(stateFor(error)); setMessage(messageFor(error)) }
    }
  }, [client, frozenExperimentId, projectId, refreshSelected, requestedExecutionId, observeFixtureExecution])

  useEffect(() => {
    const generation = loadGeneration
    void load()
    return () => { ++generation.current }
  }, [load])

  const loadMore = useCallback(async () => {
    if (!frozenExperimentId || nextOffset === null) return
    const isCurrent = captureCurrent()
    try {
      const response = await client.executions.list({ experimentId: frozenExperimentId, offset: nextOffset }, { projectId })
      if (!isCurrent()) return
      setExecutions((current) => {
        const known = new Set(current.map((item) => item.execution_id))
        return [...current, ...response.executions.filter((item) => !known.has(item.execution_id))]
      })
      setNextOffset(response.pagination.next_offset)
    } catch (error) { if (isCurrent()) setMessage(messageFor(error)) }
  }, [captureCurrent, client, frozenExperimentId, nextOffset, projectId])

  const choose = useCallback(async (executionId: string) => {
    ++loadGeneration.current
    const isCurrent = captureCurrent()
    selectedId.current = executionId
    setSelected(null); setState('loading'); setBusy(false)
    setAttempt(null); setTrace(null); setEvents([])
    try {
      const detail = await refreshSelected(executionId, isCurrent)
      if (!detail || !isCurrent()) return
      setState('ready')
      onExecutionSelected?.(executionId)
    } catch (error) { if (isCurrent()) { setState(stateFor(error)); setMessage(messageFor(error)) } }
  }, [captureCurrent, onExecutionSelected, refreshSelected])

  useEffect(() => {
    if (!selected?.execution_id || state !== 'ready') return
    const controller = new AbortController()
    let active = true
    const isCurrent = captureCurrent()
    void (async () => {
      try {
        for await (const event of client.executions.events(selected.execution_id, { projectId, signal: controller.signal })) {
          if (!active || !isCurrent()) return
          setEvents((current) => [...current, { event, receivedAt: new Date().toISOString() }])
          if (isExecutionTerminal(event, selected.execution_id)) {
            const refreshed = await refreshSelected(selected.execution_id, () => active && isCurrent() && selectedId.current === selected.execution_id)
            if (refreshed && /completed|failed|cancelled/i.test(refreshed.status)) return
          }
        }
      } catch (error) {
        if (!controller.signal.aborted && active && isCurrent()) { setState(stateFor(error)); setMessage(`Live observation interrupted: ${messageFor(error)}`) }
      }
    })()
    return () => { active = false; controller.abort() }
  }, [captureCurrent, client, projectId, refreshSelected, selected?.execution_id, state])

  const create = useCallback(async (provenance: Parameters<ArenaV1Client['executions']['create']>[1], idempotencyKey: string) => {
    if (!frozenExperimentId || preflightReport?.verdict !== 'PASS') return false
    const isCurrent = captureCurrent()
    setBusy(true); setMessage('Submitting a durable dispatch request…')
    try {
      const created = await client.executions.create(frozenExperimentId, provenance, { projectId, idempotencyKey })
      const loadedGeneration = isCurrent() ? await load(created.execution_id) : undefined
      if (loadedGeneration !== loadGeneration.current) return false
      setMessage(`Durable work was enqueued as ${created.execution_id}. This API request did not start provider execution.`)
      onExecutionSelected?.(created.execution_id)
      return true
    } catch (error) {
      if (isCurrent()) setMessage(messageFor(error)); return false
    } finally { if (isCurrent()) setBusy(false) }
  }, [captureCurrent, client, frozenExperimentId, load, onExecutionSelected, preflightReport?.verdict, projectId])

  const createOfflineDemo = useCallback(async () => {
    if (!frozenExperimentId || preflightReport?.verdict !== 'PASS') return false
    const isCurrent = captureCurrent()
    const scope = JSON.stringify([projectId, frozenExperimentId])
    let request = fixtureRequests.current.get(scope)
    if (!request || request.terminal) {
      request = { key: globalThis.crypto?.randomUUID?.() ?? `offline-demo-${Date.now()}-${Math.random().toString(16).slice(2)}` }
      fixtureRequests.current.set(scope, request)
    }
    setBusy(true); setMessage('Starting the bounded bundled fixture execution…')
    try {
      const created = await client.offlineDemo.execute(frozenExperimentId, { projectId, idempotencyKey: request.key })
      request.executionId = created.execution_id
      const loadedGeneration = isCurrent() ? await load(created.execution_id) : undefined
      if (loadedGeneration !== loadGeneration.current) return false
      setMessage(`Bundled synthetic fixture execution was scheduled as ${created.execution_id}. No provider was invoked.`)
      onExecutionSelected?.(created.execution_id)
      return true
    } catch (error) {
      if (isCurrent()) setMessage(messageFor(error)); return false
    } finally { if (isCurrent()) setBusy(false) }
  }, [captureCurrent, client, frozenExperimentId, load, onExecutionSelected, preflightReport?.verdict, projectId])

  const cancel = useCallback(async () => {
    if (!selected) return
    const isCurrent = captureCurrent()
    setBusy(true)
    try { await client.executions.cancel(selected.execution_id, { projectId }); if (isCurrent() && await load(selected.execution_id) === loadGeneration.current) setMessage('Cancellation was requested for durable jobs. A request does not imply a provider has stopped.') }
    catch (error) { if (isCurrent()) setMessage(messageFor(error)) }
    finally { if (isCurrent()) setBusy(false) }
  }, [captureCurrent, client, load, projectId, selected])

  const resume = useCallback(async () => {
    if (!selected) return
    const isCurrent = captureCurrent()
    setBusy(true)
    try { await client.executions.resume(selected.execution_id, { projectId }); if (isCurrent() && await load(selected.execution_id) === loadGeneration.current) setMessage('Resume request accepted by the durable execution service.') }
    catch (error) { if (isCurrent()) setMessage(problemMessage(error).kind === 'hold' ? `Resume HOLD: ${messageFor(error)}` : messageFor(error)) }
    finally { if (isCurrent()) setBusy(false) }
  }, [captureCurrent, client, load, projectId, selected])

  const inspectAttempt = useCallback(async (attemptId: string) => {
    const isCurrent = captureCurrent()
    try { const detail = await client.attempts.get(attemptId, { projectId }); if (isCurrent()) { setAttempt(detail); setTrace(null) } }
    catch (error) { if (isCurrent()) setMessage(messageFor(error)) }
  }, [captureCurrent, client, projectId])

  const inspectTrace = useCallback(async (attemptId: string) => {
    const isCurrent = captureCurrent()
    try { const detail = await client.attempts.trace(attemptId, { projectId }); if (isCurrent()) setTrace(detail) }
    catch (error) { if (isCurrent()) setMessage(messageFor(error)) }
  }, [captureCurrent, client, projectId])

  return { state, message, executions, nextOffset, selected, events, attempt, trace, busy, load, loadMore, choose, create, createOfflineDemo, cancel, resume, inspectAttempt, inspectTrace }
}
