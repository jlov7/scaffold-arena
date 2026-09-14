import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { SevereFailureBanner, StatusIndicator, WorkbenchButton, WorkbenchPanel, WorkbenchState, WorkbenchTable } from '../../design-system'
import { FIXTURE_LABEL, type ArenaV1Client, type PackSelection, problemMessage } from '../../journeys/study-design-preflight/types'
import '../../journeys/study-design-preflight/journey.css'

export interface StudiesSurfaceProps {
  client: ArenaV1Client
  mode?: 'guided' | 'lab'
  selection: PackSelection | null
  onSelect: (selection: PackSelection) => void
  projectId?: string
}

type LoadState = 'loading' | 'ready' | 'empty' | 'offline' | 'permission' | 'error'

function contentType(file: File): string {
  return file.name.toLowerCase().endsWith('.zip') ? 'application/zip' : 'application/json'
}

export function StudiesSurface({ client, mode = 'lab', selection, onSelect, projectId }: StudiesSurfaceProps) {
  const [packs, setPacks] = useState<Awaited<ReturnType<ArenaV1Client['studyPacks']['list']>>['study_packs']>([])
  const [state, setState] = useState<LoadState>('loading')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const inputId = useId()
  const fileRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    setState('loading')
    setMessage('')
    try {
      const response = await client.studyPacks.list({ projectId })
      setPacks(response.study_packs)
      setState(response.study_packs.length === 0 ? 'empty' : 'ready')
    } catch (error) {
      const problem = problemMessage(error)
      setState(problem.kind === 'offline' ? 'offline' : problem.kind === 'permission' ? 'permission' : 'error')
      setMessage(problem.message)
    }
  }, [client, projectId])

  useEffect(() => { void load() }, [load])

  const importPack = async (file: File) => {
    setBusy(true)
    setMessage('Validating the selected file against the registry contract…')
    try {
      const type = contentType(file)
      const validation = await client.studyPacks.validate(file, type, { projectId })
      if (validation.valid !== true) {
        setMessage(typeof validation.message === 'string' ? validation.message : 'The selected file did not pass registry validation.')
        setState('error')
        return
      }
      const imported = await client.studyPacks.import(file, type, { projectId })
      const studyPackId = typeof imported.study_pack_id === 'string' ? imported.study_pack_id : undefined
      const version = typeof imported.version === 'string' ? imported.version : undefined
      await load()
      if (studyPackId && version) onSelect({ studyPackId, version })
      setMessage('The registry accepted the selected StudyPack.')
    } catch (error) {
      const problem = problemMessage(error)
      setState(problem.kind === 'offline' ? 'offline' : problem.kind === 'permission' ? 'permission' : 'error')
      setMessage(problem.kind === 'hold' ? `Import HOLD: ${problem.message}` : problem.message)
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const startBundledDemo = async () => {
    setBusy(true)
    setMessage('Importing the bundled synthetic fixture into the durable registry…')
    try {
      const imported = await client.offlineDemo.start({ projectId })
      await load()
      onSelect({ studyPackId: imported.study_pack_id, version: imported.version })
      setMessage('Bundled synthetic fixture imported. Create, approve, freeze, and preflight the comparison before running it.')
    } catch (error) {
      const problem = problemMessage(error)
      setState(problem.kind === 'offline' ? 'offline' : problem.kind === 'permission' ? 'permission' : 'error')
      setMessage(problem.kind === 'hold' ? `Demo import HOLD: ${problem.message}` : problem.message)
    } finally {
      setBusy(false)
    }
  }

  const exportPack = async (pack: PackSelection) => {
    setBusy(true)
    setMessage('Preparing the registry-owned export…')
    try {
      const result = await client.exports.studyPack(pack.studyPackId, pack.version, { projectId })
      const url = URL.createObjectURL(result.blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = result.filename ?? `${pack.studyPackId}-${pack.version}.zip`
      anchor.click()
      URL.revokeObjectURL(url)
      setMessage('Export downloaded from the registry endpoint.')
    } catch (error) {
      setMessage(problemMessage(error).message)
    } finally {
      setBusy(false)
    }
  }

  if (state === 'loading') return <WorkbenchState kind="loading" title="Loading durable StudyPacks">Reading the project registry.</WorkbenchState>
  if (state === 'offline') return <WorkbenchState kind="offline" title="Study registry unavailable" action={<WorkbenchButton onClick={() => void load()}>Retry registry</WorkbenchButton>}>{message || 'Reconnect to the registry, then retry.'}</WorkbenchState>
  if (state === 'permission') return <SevereFailureBanner title="Project context required" action={<WorkbenchButton onClick={() => void load()}>Retry with project context</WorkbenchButton>}>{message || 'Choose a project with StudyPack access.'}</SevereFailureBanner>
  if (state === 'error' && packs.length === 0) return <WorkbenchState kind="error" title="Could not load StudyPacks" action={<WorkbenchButton onClick={() => void load()}>Retry registry</WorkbenchButton>}>{message}</WorkbenchState>

  return <section className="sa-journey" aria-labelledby="studies-heading">
    <WorkbenchPanel title={<span id="studies-heading">Study Canvas</span>} action={<StatusIndicator tone="info">Durable registry</StatusIndicator>}>
      <div className="sa-journey-form">
        {mode === 'guided' ? <p className="sa-journey-copy">Available studies are discovered from the durable registry automatically. Importing a canonical file or browsing its internal path is available in Lab.</p> : <><p className="sa-journey-copy">Import a protocol-v1 JSON or ZIP archive. Files are validated first, then sent to the immutable registry.</p><label className="sa-journey-field" htmlFor={inputId}>StudyPack file
          <input ref={fileRef} id={inputId} type="file" accept="application/json,.json,application/zip,.zip" disabled={busy} onChange={(event) => {
            const file = event.currentTarget.files?.[0]
            if (file) void importPack(file)
          }} />
        </label><div className="sa-journey-actions"><WorkbenchButton onClick={() => fileRef.current?.click()} disabled={busy}>Validate and import</WorkbenchButton><WorkbenchButton tone="secondary" onClick={() => fileRef.current?.click()} disabled={busy}>Choose bundled demo file</WorkbenchButton></div><div className="sa-journey-callout"><p><strong>Bundled demo file requires local selection.</strong> Select <code>study_packs/offline-demo-v1/study-pack.json</code> from this checkout. Runbook: <code>study_packs/offline-demo-v1/README.md</code>. No static asset route is available in this build.</p></div></>}
        <p className="sa-journey-fixture">{FIXTURE_LABEL}</p>
        {message && <p className="sa-journey-status" data-tone={state === 'error' ? 'error' : undefined} role="status">{message}</p>}
      </div>
    </WorkbenchPanel>

    {state === 'empty' ? <WorkbenchState kind="empty" title="No durable StudyPacks" action={mode === 'lab' ? <WorkbenchButton onClick={() => fileRef.current?.click()}>Select a StudyPack file</WorkbenchButton> : <WorkbenchButton tone="primary" disabled={busy} onClick={() => void startBundledDemo()}>Import bundled demo</WorkbenchButton>}>{mode === 'lab' ? 'Import a protocol-v1 JSON or ZIP archive to begin.' : 'Import the bundled synthetic fixture to try the complete local protocol journey. It is not benchmark evidence and does not run a provider.'}</WorkbenchState> :
      <WorkbenchPanel title="Available StudyPacks">
        <div className="sa-table-wrap"><WorkbenchTable>
          <thead><tr><th scope="col">StudyPack</th><th scope="col">Version</th><th scope="col">Authority</th><th scope="col">Action</th></tr></thead>
          <tbody>{packs.map((pack) => {
            const selected = selection?.studyPackId === pack.study_pack_id && selection.version === pack.version
            return <tr key={`${pack.study_pack_id}:${pack.version}`} aria-selected={selected}>
              <td><strong>{pack.title}</strong>{mode === 'lab' && <><br /><span className="sa-journey-compact">{pack.study_pack_id}</span></>}</td>
              <td>{pack.version}</td><td>{pack.authority_ceiling}</td>
              <td><div className="sa-journey-actions"><WorkbenchButton tone={selected ? 'primary' : 'secondary'} onClick={() => onSelect({ studyPackId: pack.study_pack_id, version: pack.version })}>{selected ? 'Selected' : 'Select'}</WorkbenchButton><WorkbenchButton tone="secondary" onClick={() => void exportPack({ studyPackId: pack.study_pack_id, version: pack.version })} disabled={busy}>Export</WorkbenchButton></div></td>
            </tr>
          })}</tbody>
        </WorkbenchTable></div>
      </WorkbenchPanel>}
    {state === 'error' && packs.length > 0 && <SevereFailureBanner title="Latest registry action failed" action={<WorkbenchButton onClick={() => void load()}>Reload registry</WorkbenchButton>}>{message}</SevereFailureBanner>}
  </section>
}
