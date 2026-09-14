import { useEffect, useMemo, useRef, useState } from 'react'
import type { ExperimentDetail } from '../../../api/v1/client'
import { DisclosureRow, SevereFailureBanner, StatusIndicator, WorkbenchButton, WorkbenchPanel, WorkbenchState, WorkbenchTable } from '../../design-system'
import { asArray, designExpansion, expectedAttempts, FIXTURE_LABEL, fixturePack, isRecord, problemMessage, stringValue, type ArenaV1Client, type CanonicalExperiment, type CanonicalStudyPack, type PackSelection } from '../../journeys/study-design-preflight/types'
import '../../journeys/study-design-preflight/journey.css'

export interface DesignSurfaceProps {
  client: ArenaV1Client
  packSelection: PackSelection | null
  experimentId: string | null
  mode: 'guided' | 'lab'
  onExperimentSelected: (experimentId: string) => void
  onNavigateToStudies?: () => void
  projectId?: string
}

type RemoteState = 'idle' | 'loading' | 'offline' | 'permission' | 'error'

function uniqueExperimentId(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+/, '').slice(0, 128)
}

function cloneTemplate(template: CanonicalExperiment, experimentId: string, predecessorId: string | null = null): CanonicalExperiment {
  const clone = JSON.parse(JSON.stringify(template)) as CanonicalExperiment
  clone.experiment_id = experimentId
  clone.frozen = false
  clone.freeze_hash = null
  clone.frozen_at = null
  clone.study_pack_hash = null
  clone.owner_approval = 'approved'
  if (predecessorId) clone.predecessor_experiment_id = predecessorId
  return clone
}

function combinations(factors: readonly Record<string, unknown>[]): Array<Record<string, unknown>> {
  return factors.reduce<Array<Record<string, unknown>>>((rows, factor) => {
    const factorId = stringValue(factor.factor_id, 'factor')
    const levels = Array.isArray(factor.levels) ? factor.levels : []
    return rows.flatMap((row) => levels.map((level) => ({ ...row, [factorId]: level })))
  }, [{}])
}

function JsonList({ values }: { values: readonly Record<string, unknown>[] }) {
  if (values.length === 0) return <p className="sa-journey-note">None declared.</p>
  return <ul className="sa-journey-list">{values.map((value, index) => <li key={`${stringValue(value.scenario_id, stringValue(value.harness_id, String(index)))}-${index}`}><strong>{stringValue(value.title, stringValue(value.scenario_id, stringValue(value.harness_id, 'Declared item')))}</strong>{typeof value.description === 'string' && <> — {value.description}</>}</li>)}</ul>
}

export function DesignSurface({ client, packSelection, experimentId, mode, onExperimentSelected, onNavigateToStudies, projectId }: DesignSurfaceProps) {
  const [state, setState] = useState<RemoteState>('idle')
  const [message, setMessage] = useState('')
  const [pack, setPack] = useState<CanonicalStudyPack | null>(null)
  const [loadedExperiment, setLoadedExperiment] = useState<ExperimentDetail | null>(null)
  const [templateIndex, setTemplateIndex] = useState(0)
  const [newId, setNewId] = useState('')
  const [approved, setApproved] = useState(false)
  const [labDraft, setLabDraft] = useState('')
  const [validationErrors, setValidationErrors] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const errorSummary = useRef<HTMLDivElement>(null)
  const packId = packSelection?.studyPackId
  const packVersion = packSelection?.version

  useEffect(() => {
    if (!packId || !packVersion) { setPack(null); setLoadedExperiment(null); setState('idle'); return }
    let active = true
    setState('loading')
    setMessage('')
    void client.studyPacks.get(packId, packVersion, { projectId }).then((response) => {
      if (!active) return
      const canonical = response.canonical_study_pack as CanonicalStudyPack
      setPack(canonical)
      const template = (canonical.experiments[0] ?? null) as CanonicalExperiment | null
      setNewId(template ? `${template.experiment_id}-v2` : '')
      setLabDraft(template ? JSON.stringify(cloneTemplate(template, `${template.experiment_id}-v2`), null, 2) : '')
      setState('idle')
    }).catch((error: unknown) => {
      if (!active) return
      const problem = problemMessage(error)
      setState(problem.kind === 'offline' ? 'offline' : problem.kind === 'permission' ? 'permission' : 'error')
      setMessage(problem.message)
    })
    return () => { active = false }
  }, [client, packId, packVersion, projectId])

  useEffect(() => {
    if (!experimentId) { setLoadedExperiment(null); return }
    let active = true
    void client.experiments.get(experimentId, { projectId }).then((response) => { if (active) setLoadedExperiment(response) }).catch((error: unknown) => {
      if (active) setMessage(problemMessage(error).message)
    })
    return () => { active = false }
  }, [client, experimentId, projectId])

  const templates = useMemo(() => pack ? pack.experiments.map((value) => value as CanonicalExperiment) : [], [pack])
  const template = templates[templateIndex] ?? null
  const selectedDefinition = loadedExperiment?.definition ?? template ?? null
  const frozen = loadedExperiment?.immutable_identity.frozen === true
  const creationSource = frozen && loadedExperiment ? loadedExperiment.definition as CanonicalExperiment : template
  const factors = asArray(selectedDefinition?.factors)
  const matrix = combinations(factors)
  const expansion = selectedDefinition ? designExpansion(selectedDefinition) : 0
  const attempts = selectedDefinition ? expectedAttempts(selectedDefinition) : 0

  const create = async (candidate: CanonicalExperiment) => {
    setValidationErrors([])
    setBusy(true)
    try {
      const response = await client.experiments.create(candidate, { projectId })
      const createdId = typeof response.experiment_id === 'string' ? response.experiment_id : candidate.experiment_id
      setMessage(mode === 'lab' ? `Created unfrozen experiment ${createdId}. Freeze is the next separate action.` : 'Created an unfrozen comparison design. Freezing it is the next separate action.')
      onExperimentSelected(createdId)
    } catch (error) {
      const problem = problemMessage(error)
      setMessage(problem.message)
      setValidationErrors([problem.kind === 'hold' ? `HOLD: ${problem.message}` : problem.message])
      requestAnimationFrame(() => errorSummary.current?.focus())
    } finally { setBusy(false) }
  }

  const createGuided = () => {
    if (!creationSource) return
    const experimentIdValue = uniqueExperimentId(newId)
    const errors: string[] = []
    if (!/^[a-z][a-z0-9_-]{1,127}$/.test(experimentIdValue)) errors.push('Experiment ID must start with a lowercase letter and use only lowercase letters, numbers, underscores, or hyphens.')
    if (!approved) errors.push('Owner approval must be explicitly confirmed before creating an ExperimentSpec.')
    if (errors.length) { setValidationErrors(errors); requestAnimationFrame(() => errorSummary.current?.focus()); return }
    void create(cloneTemplate(creationSource, experimentIdValue, frozen ? loadedExperiment?.experiment_id ?? null : null))
  }

  const createLab = () => {
    try {
      const parsed: unknown = JSON.parse(labDraft)
      if (!isRecord(parsed)) throw new Error('The canonical draft must be a JSON object.')
      const required = ['experiment_id', 'study_pack_id', 'scenario_ids', 'harness_ids', 'deterministic_weight']
      const errors = required.filter((key) => !(key in parsed)).map((key) => `Missing required ExperimentSpec field: ${key}.`)
      if (parsed.frozen === true) errors.push('A new Lab draft must be unfrozen. Use versioning for a frozen experiment.')
      if (frozen && parsed.predecessor_experiment_id !== loadedExperiment?.experiment_id) errors.push(`Versioned draft must link predecessor_experiment_id to ${loadedExperiment?.experiment_id}.`)
      if (errors.length) { setValidationErrors(errors); requestAnimationFrame(() => errorSummary.current?.focus()); return }
      void create(parsed as CanonicalExperiment)
    } catch (error) {
      setValidationErrors([error instanceof Error ? `Malformed JSON: ${error.message}` : 'Malformed JSON draft.'])
      requestAnimationFrame(() => errorSummary.current?.focus())
    }
  }

  const beginVersion = () => {
    if (!loadedExperiment) return
    const base = loadedExperiment.definition as CanonicalExperiment
    const id = `${loadedExperiment.experiment_id}-v2`
    const version = cloneTemplate(base, id, loadedExperiment.experiment_id)
    setNewId(id)
    setApproved(false)
    setLabDraft(JSON.stringify(version, null, 2))
    setMessage(mode === 'lab' ? `Version draft prepared with predecessor ${loadedExperiment.experiment_id}; the frozen specification remains unchanged.` : 'A version draft is ready. The frozen specification remains unchanged.')
  }

  if (!packSelection) return <WorkbenchState kind="empty" title="Select a StudyPack first" action={onNavigateToStudies && <WorkbenchButton onClick={onNavigateToStudies}>Go to Studies</WorkbenchButton>}>Choose a durable StudyPack and version in Studies. Design cannot recover a pack from browser-only state.</WorkbenchState>
  if (state === 'loading') return <WorkbenchState kind="loading" title="Loading canonical StudyPack">Recovering {packSelection.studyPackId} {packSelection.version} from the registry.</WorkbenchState>
  if (state === 'offline') return <WorkbenchState kind="offline" title="Canonical StudyPack unavailable" action={onNavigateToStudies && <WorkbenchButton onClick={onNavigateToStudies}>Choose another StudyPack</WorkbenchButton>}>Reconnect to the registry and reselect this exact pack version. {message}</WorkbenchState>
  if (state === 'permission') return <SevereFailureBanner title="Project context required">{message || 'Select a project with access to this StudyPack.'}</SevereFailureBanner>
  if (state === 'error' || !pack) return <WorkbenchState kind="error" title="Could not recover StudyPack" action={onNavigateToStudies && <WorkbenchButton onClick={onNavigateToStudies}>Return to Studies</WorkbenchButton>}>{message || 'Return to Studies and select a durable version.'}</WorkbenchState>

  return <section className="sa-journey" aria-labelledby="design-heading">
    {fixturePack(pack) && <p className="sa-journey-fixture">{FIXTURE_LABEL}</p>}
    {frozen && <SevereFailureBanner title="Frozen specification is immutable" action={<WorkbenchButton onClick={beginVersion}>Create version draft</WorkbenchButton>}>The persisted frozen identity cannot be edited. A new experiment ID with a predecessor link is required.</SevereFailureBanner>}
    <WorkbenchPanel title={<span id="design-heading">{pack.title}</span>} action={<StatusIndicator tone="info">{mode === 'lab' ? `${pack.study_pack_id} · ${pack.version}` : 'Study selected'}</StatusIndicator>}>
      <div className="sa-journey-grid">
        <div><h3 className="sa-panel-title">Scenarios</h3><JsonList values={asArray(pack.scenarios)} /></div>
        <div><h3 className="sa-panel-title">Harnesses</h3><JsonList values={asArray(pack.harnesses)} /></div>
      </div>
      <DisclosureRow title="Claim limitations"><ul className="sa-journey-list">{[...pack.allowed_claims, ...pack.limitations].map((text, index) => <li key={index}>{text}</li>)}</ul></DisclosureRow>
    </WorkbenchPanel>

    <WorkbenchPanel title="Experiment templates">
      {templates.length === 0 ? <WorkbenchState kind="empty" title="No included experiment templates">This canonical StudyPack does not declare a reusable template.</WorkbenchState> : <div className="sa-journey-form">
        <label className="sa-journey-field">Template
          <select value={templateIndex} onChange={(event) => { const index = Number(event.target.value); setTemplateIndex(index); const choice = templates[index]; if (choice) { setNewId(`${choice.experiment_id}-v2`); setLabDraft(JSON.stringify(cloneTemplate(choice, `${choice.experiment_id}-v2`), null, 2)) } }}>
            {templates.map((item, index) => <option key={item.experiment_id} value={index}>{mode === 'lab' ? item.experiment_id : `Template ${index + 1}`}</option>)}
          </select>
        </label>
        <p className="sa-journey-copy">{expansion} treatment arms · {attempts} expected attempts, derived from declared factor levels, scenarios, harnesses, endpoints, and repetitions.</p>
        {mode === 'guided' ? <>
          <label className="sa-journey-check"><input type="checkbox" checked={approved} onChange={(event) => setApproved(event.target.checked)} /> I have explicit owner approval to create this new, unfrozen ExperimentSpec.</label>
          <p className="sa-journey-note">A sensible version identity is prepared from the selected template. Lab exposes the canonical identifier and complete object.</p><div className="sa-journey-actions"><WorkbenchButton onClick={createGuided} disabled={busy || frozen && !loadedExperiment}>Create unfrozen experiment</WorkbenchButton></div>
        </> : <>
          <label className="sa-journey-field">Canonical ExperimentSpec JSON<textarea value={labDraft} onChange={(event) => setLabDraft(event.target.value)} spellCheck={false} aria-describedby="lab-draft-help" /></label>
          <p id="lab-draft-help" className="sa-journey-note">Lab submits this complete canonical draft through the same create endpoint as Guided. Frozen identities cannot be edited.</p>
          <div className="sa-journey-actions"><WorkbenchButton onClick={createLab} disabled={busy}>Create unfrozen experiment</WorkbenchButton></div>
        </>}
      </div>}
      {validationErrors.length > 0 && <div ref={errorSummary} className="sa-journey-summary" role="alert" tabIndex={-1}><strong>Resolve before creating the experiment</strong><ul>{validationErrors.map((error, index) => <li key={index}>{error}</li>)}</ul></div>}
      {message && <p className="sa-journey-status" role="status">{message}</p>}
    </WorkbenchPanel>

    {selectedDefinition && <>
      <WorkbenchPanel title="P / V / R / M factor configuration">
        <div className="sa-table-wrap"><WorkbenchTable><thead><tr><th scope="col">Factor</th><th scope="col">Levels</th><th scope="col">Control / manipulation check</th><th scope="col">Capabilities</th></tr></thead><tbody>{factors.map((factor) => <tr key={stringValue(factor.factor_id)}><td><strong>{stringValue(factor.factor_id)}</strong><br />{stringValue(factor.description, '')}</td><td>{(Array.isArray(factor.levels) ? factor.levels : []).map((level) => String(level)).join(', ')}</td><td>{asArray(factor.manipulation_checks).map((check) => stringValue(check.oracle)).join(', ') || 'Not declared'}</td><td>{asArray(factor.capability_requirements).map((need) => stringValue(need.capability)).join(', ') || 'None declared'}</td></tr>)}</tbody></WorkbenchTable></div>
      </WorkbenchPanel>
      <WorkbenchPanel title={`Treatment matrix (${matrix.length} declared arms)`}><div className="sa-journey-matrix">{matrix.map((arm, index) => <div className="sa-journey-cell" key={index}><strong>Arm {index + 1}</strong>{Object.entries(arm).map(([key, value]) => <div key={key}>{key}: {String(value)}</div>)}</div>)}</div></WorkbenchPanel>
      <WorkbenchPanel title="Controls and endpoint pins"><div className="sa-journey-grid"><div><h3 className="sa-panel-title">Scenarios and controls</h3><JsonList values={asArray(pack.scenarios)} /></div><div><h3 className="sa-panel-title">Endpoints</h3><JsonList values={asArray(selectedDefinition.model_endpoints)} /></div></div></WorkbenchPanel>
    </>}
  </section>
}
