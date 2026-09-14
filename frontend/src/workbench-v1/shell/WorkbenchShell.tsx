import {
  FlaskConical,
  Menu,
  PanelRightOpen,
} from 'lucide-react'
import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react'

import { GuidedLabControl, StatusIndicator, WorkbenchButton } from '../design-system'
import { LAB_WORKBENCH_NAVIGATION, MOBILE_GUIDED_AREAS, MOBILE_LAB_AREAS, primaryDecisionForArea, WORKBENCH_NAVIGATION } from './navigation'
import type { WorkbenchArea, WorkbenchNavigationItem, WorkbenchShellProps } from './types'

function NavigationButton({ item, active, onNavigate }: { item: WorkbenchNavigationItem; active: boolean; onNavigate: (area: WorkbenchArea) => void }) {
  const Icon = item.icon
  return <button type="button" className="sa-nav-button" data-active={active} aria-label={item.label} aria-current={active ? 'page' : undefined} onClick={() => onNavigate(item.id)}><Icon aria-hidden="true" size={17} /><span className="sa-nav-label">{item.label}</span></button>
}

function EvidenceDrawer({ isOpen, onClose, children }: { isOpen: boolean; onClose: () => void; children: ReactNode }) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLElement>(null)

  useEffect(() => {
    if (isOpen) closeRef.current?.focus()
  }, [isOpen])

  if (!isOpen) return null

  const trapFocus = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') { event.preventDefault(); onClose(); return }
    if (event.key !== 'Tab') return
    const focusable = panelRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), [href], input, select, textarea, summary, [tabindex]:not([tabindex="-1"])')
    if (!focusable?.length) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }

  return <div className="sa-mobile-drawer" data-open="true" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <aside ref={panelRef} className="sa-mobile-drawer-panel" role="dialog" aria-modal="true" aria-label="Evidence and specification" onKeyDown={trapFocus}>
      <header className="sa-mobile-drawer-head"><h2>Evidence &amp; specification</h2><WorkbenchButton ref={closeRef} type="button" onClick={onClose}>Close</WorkbenchButton></header>
      {children}
    </aside>
  </div>
}

export function WorkbenchShell({ activeArea, onNavigate, mode, onModeChange, children, evidence, title = 'Scaffold Arena', version = '1.0', studyLabel = 'No study selected', specTitle = 'Frozen spec', specLabel = 'No frozen specification', statuses = [], stageTitle }: WorkbenchShellProps) {
  const [isEvidenceOpen, setEvidenceOpen] = useState(false)
  const [isMoreOpen, setMoreOpen] = useState(false)
  const shellRef = useRef<HTMLDivElement>(null)
  const evidenceTriggerRef = useRef<HTMLButtonElement | null>(null)
  const moreButtonRef = useRef<HTMLButtonElement>(null)
  const navigation = mode === 'guided' ? WORKBENCH_NAVIGATION : LAB_WORKBENCH_NAVIGATION
  const mobileAreas = mode === 'guided' ? MOBILE_GUIDED_AREAS : MOBILE_LAB_AREAS
  const activeNavigationArea = mode === 'guided' ? primaryDecisionForArea(activeArea) : activeArea
  const activeItem = navigation.find((item) => item.id === activeNavigationArea) ?? navigation[0]
  const remainingItems = navigation.filter((item) => !mobileAreas.includes(item.id as never))

  useEffect(() => {
    const shell = shellRef.current
    if (!isEvidenceOpen || !shell) return
    const previousOverflow = document.body.style.overflow
    shell.setAttribute('inert', '')
    document.body.style.overflow = 'hidden'
    return () => {
      shell.removeAttribute('inert')
      document.body.style.overflow = previousOverflow
    }
  }, [isEvidenceOpen])

  const closeEvidence = () => {
    setEvidenceOpen(false)
    window.requestAnimationFrame(() => evidenceTriggerRef.current?.focus())
  }
  const openEvidence = (event: MouseEvent<HTMLButtonElement>) => {
    evidenceTriggerRef.current = event.currentTarget
    setEvidenceOpen(true)
  }
  const navigate = (area: WorkbenchArea) => { setMoreOpen(false); onNavigate(area) }

  return <div className="sa-workbench">
    <a className="sa-skip-link" href="#workbench-main">Skip to workspace</a>
    <div ref={shellRef} className="sa-shell">
      <header className="sa-command-bar" aria-label="Workbench command and status bar">
        <div className="sa-brand"><FlaskConical className="sa-brand-mark" aria-hidden="true" size={22} />{title}<span className="sa-version">{version}</span></div>
        <div className="sa-command-cell"><div className="sa-command-label">Selected study</div><div className="sa-command-value">{studyLabel}</div></div>
        <div className="sa-command-cell"><div className="sa-command-label">{specTitle}</div><div className="sa-command-value">{specLabel}</div></div>
        {statuses.slice(0, 2).map((status) => <div className="sa-command-status" key={status.label}><span>{status.label}</span><StatusIndicator tone={status.tone ?? 'info'}>{status.value}</StatusIndicator></div>)}
        <button className="sa-icon-button" type="button" aria-label="Open evidence inspector" onClick={openEvidence}><PanelRightOpen aria-hidden="true" size={18} /></button>
      </header>

      <header className="sa-mobile-bar" aria-label="Mobile workbench commands"><div className="sa-mobile-brand"><FlaskConical className="sa-brand-mark" aria-hidden="true" size={22} /><span>{title}</span><span className="sa-version">{version}</span></div>{statuses.slice(-1).map((status) => <StatusIndicator key={status.label} tone={status.tone ?? 'info'}>{status.value}</StatusIndicator>)}<button className="sa-icon-button" type="button" aria-label="Open evidence and specification" onClick={openEvidence}><PanelRightOpen aria-hidden="true" size={18} /></button></header>

      <aside className="sa-rail"><nav className="sa-primary-nav" aria-label="Workbench areas">{navigation.map((item) => <NavigationButton key={item.id} item={item} active={item.id === activeNavigationArea} onNavigate={navigate} />)}</nav></aside>

      <main id="workbench-main" className="sa-stage" tabIndex={-1}>
        <header className="sa-stage-header"><div><div className="sa-region-label">Operate / {activeItem.label}</div><h1 className="sa-stage-heading">{stageTitle ?? activeItem.label}</h1></div><GuidedLabControl value={mode} onChange={onModeChange} /></header>
        {children}
      </main>

      <aside className="sa-inspector" aria-label="Evidence inspector"><header className="sa-inspector-heading"><span>Evidence</span><span>Specification</span></header><div className="sa-inspector-content">{evidence}</div></aside>

      <nav className="sa-mobile-nav" aria-label="Mobile workbench areas">
        {mobileAreas.map((id) => { const item = navigation.find((candidate) => candidate.id === id)!; return <NavigationButton key={id} item={item} active={id === activeNavigationArea} onNavigate={navigate} /> })}
        <div onKeyDown={(event) => { if (event.key === 'Escape' && isMoreOpen) { event.preventDefault(); setMoreOpen(false); moreButtonRef.current?.focus() } }}><button ref={moreButtonRef} type="button" className="sa-nav-button" data-active={remainingItems.some((item) => item.id === activeNavigationArea)} aria-expanded={isMoreOpen} aria-controls="workbench-more-menu" onClick={() => setMoreOpen((open) => !open)}><Menu aria-hidden="true" size={17} /><span>More</span></button>{isMoreOpen && <div id="workbench-more-menu" className="sa-mobile-menu">{remainingItems.map((item) => <NavigationButton key={item.id} item={item} active={item.id === activeNavigationArea} onNavigate={navigate} />)}<button type="button" className="sa-nav-button" onClick={(event) => { setMoreOpen(false); openEvidence(event) }}><PanelRightOpen aria-hidden="true" size={17} /><span>Evidence &amp; specification</span></button></div>}</div>
      </nav>
    </div>
    <EvidenceDrawer isOpen={isEvidenceOpen} onClose={closeEvidence}>{evidence}</EvidenceDrawer>
  </div>
}
