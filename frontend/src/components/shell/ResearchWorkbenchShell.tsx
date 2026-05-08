import {
  Activity,
  BarChart3,
  Command,
  Database,
  FileText,
  HelpCircle,
  History,
  Map,
  Moon,
  PanelRightOpen,
  Settings,
  Sun,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'

import {
  APP_VIEWS,
  appViewLabel,
  type AppView,
} from '../../app/viewState'
import { COPY } from '../../content/copy'
import { Button } from '../primitives/Button'
import { Drawer } from '../primitives/Drawer'
import { IconButton } from '../primitives/IconButton'
import { StatusBadge } from '../primitives/StatusBadge'

interface ResearchWorkbenchShellProps {
  activeView: AppView
  stageLabel: string
  theme: 'dark' | 'light'
  isRunning: boolean
  isOnline: boolean
  hasApiToken: boolean
  runId: string | null
  nextActionTitle: string
  nextActionBody: string
  nextActionCta: string
  nextActionDisabled?: boolean
  children: ReactNode
  inspector: ReactNode
  onOpenHelp: () => void
  onExplainScreen: () => void
  onOpenTour: () => void
  onOpenCommandPalette: () => void
  onToggleTheme: () => void
  onNavigate: (view: AppView) => void
  onRunNextAction: () => void
}

const VIEW_ICON: Record<AppView, typeof Activity> = {
  arena: Activity,
  results: FileText,
  history: History,
  leaderboard: BarChart3,
  settings: Settings,
}

const VIEW_HINTS: Record<AppView, string> = {
  arena: 'Run and monitor experiments.',
  results: 'Review winners, costs, and diagnostics.',
  history: 'Re-open previous runs quickly.',
  leaderboard: 'Compare aggregate scaffold performance.',
  settings: 'Configure keys, preferences, and safeguards.',
}

const COMPACT_MOBILE_SECONDARY_VIEWS = new Set<AppView>([
  'history',
  'leaderboard',
  'settings',
])

export function ResearchWorkbenchShell({
  activeView,
  stageLabel,
  theme,
  isRunning,
  isOnline,
  hasApiToken,
  runId,
  nextActionTitle,
  nextActionBody,
  nextActionCta,
  nextActionDisabled = false,
  children,
  inspector,
  onOpenHelp,
  onExplainScreen,
  onOpenTour,
  onOpenCommandPalette,
  onToggleTheme,
  onNavigate,
  onRunNextAction,
}: ResearchWorkbenchShellProps) {
  const [isInspectorOpen, setInspectorOpen] = useState(false)

  const nextActionPanel = (
    <section className="lab-panel p-4">
      <div className="lab-label">Next action</div>
      <h2 className="mt-2 text-base font-semibold text-text-primary">
        {nextActionTitle}
      </h2>
      <p className="lab-copy mt-2 text-sm">{nextActionBody}</p>
      <Button
        type="button"
        tone="primary"
        className="mt-4 w-full"
        onClick={onRunNextAction}
        disabled={nextActionDisabled}
      >
        {nextActionCta}
      </Button>
    </section>
  )

  return (
    <div className="lab-shell">
      <header className="lab-command" role="banner">
        <div className="flex min-h-16 items-center gap-3 px-3 sm:px-4">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <div className="hidden h-10 w-10 shrink-0 items-center justify-center rounded-md border border-border bg-bg-primary sm:flex">
              <Database className="h-5 w-5 text-accent-winner" strokeWidth={1.8} />
            </div>
            <div className="min-w-[8.25rem] sm:min-w-[13rem]">
              <h1 className="truncate text-base font-semibold tracking-[-0.01em] text-text-primary sm:text-lg">
                {COPY.app.title}
              </h1>
              <p className="hidden truncate text-sm text-text-secondary sm:block">
                {COPY.app.subtitle}
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onOpenCommandPalette}
            aria-label="Open command palette"
            className="ui-control hidden min-w-[16rem] items-center gap-2 rounded-md border border-border bg-bg-primary px-3 py-2 text-left text-sm text-text-muted hover:border-border-hover hover:text-text-secondary md:flex"
          >
            <Command className="h-4 w-4" strokeWidth={1.8} />
            <span className="flex-1">Command or search</span>
            <kbd className="font-mono text-[10px] uppercase tracking-[0.12em] text-text-muted">
              Cmd K
            </kbd>
          </button>

          <div className="hidden items-center gap-2 lg:flex">
            <StatusBadge tone={isRunning ? 'info' : 'neutral'}>
              {isRunning ? 'Running' : stageLabel}
            </StatusBadge>
            <StatusBadge tone={isOnline ? 'success' : 'warning'}>
              {isOnline ? 'Online' : 'Offline'}
            </StatusBadge>
            <StatusBadge tone={hasApiToken ? 'success' : 'warning'}>
              {hasApiToken ? 'Key ready' : 'Server key'}
            </StatusBadge>
          </div>

          <div className="flex items-center gap-1">
            <div className="hidden sm:block md:hidden">
              <IconButton label="Open command palette" onClick={onOpenCommandPalette}>
                <Command className="h-4 w-4" strokeWidth={1.8} />
              </IconButton>
            </div>
            <div className="hidden sm:block xl:hidden">
              <IconButton
                label="Open inspector"
                onClick={() => setInspectorOpen(true)}
              >
                <PanelRightOpen className="h-4 w-4" strokeWidth={1.8} />
              </IconButton>
            </div>
            <IconButton label="Help" title="Help" onClick={onOpenHelp}>
              <HelpCircle className="h-4 w-4" strokeWidth={1.8} />
            </IconButton>
            <IconButton label={COPY.actions.takeTour} onClick={onOpenTour}>
              <Map className="h-4 w-4" strokeWidth={1.8} />
            </IconButton>
            <div className="hidden lg:block">
              <Button type="button" tone="ghost" onClick={onExplainScreen}>
                Explain this screen
              </Button>
            </div>
            <IconButton
              label={theme === 'dark' ? 'Light theme' : 'Dark theme'}
              onClick={onToggleTheme}
            >
              {theme === 'dark' ? (
                <Sun className="h-4 w-4" strokeWidth={1.8} />
              ) : (
                <Moon className="h-4 w-4" strokeWidth={1.8} />
              )}
            </IconButton>
          </div>
        </div>
      </header>

      <nav className="lab-rail" aria-label="Primary">
        <div className="flex h-full flex-col items-center gap-2 px-2 py-4">
          {APP_VIEWS.map((view) => {
            const Icon = VIEW_ICON[view]
            const active = activeView === view
            return (
              <button
                key={view}
                id={view === 'settings' ? 'tour-settings-link' : undefined}
                type="button"
                onClick={() => onNavigate(view)}
                title={VIEW_HINTS[view]}
                aria-current={active ? 'page' : undefined}
                aria-label={`Open ${appViewLabel(view)} view`}
                className={[
                  'ui-control flex h-12 w-12 items-center justify-center rounded-md border transition-colors',
                  active
                    ? 'border-accent-info bg-accent-info/12 text-accent-info'
                    : 'border-transparent text-text-muted hover:border-border hover:text-text-primary',
                ].join(' ')}
              >
                <Icon className="h-5 w-5" strokeWidth={1.8} />
              </button>
            )
          })}
          <div className="mt-auto">
            <IconButton label="Open inspector" onClick={() => setInspectorOpen(true)}>
              <PanelRightOpen className="h-4 w-4" strokeWidth={1.8} />
            </IconButton>
          </div>
        </div>
      </nav>

      <main
        id="main-content"
        role="main"
        tabIndex={-1}
        className="lab-stage min-h-0 overflow-x-hidden px-4 py-5 sm:px-6 lg:px-8"
      >
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="lab-label">{COPY.app.breadcrumbHome} / {appViewLabel(activeView)}</div>
            <h2 className="mt-2 text-2xl font-semibold tracking-[-0.02em] text-text-primary">
              {appViewLabel(activeView)}
            </h2>
          </div>
          {runId && (
            <div className="font-mono text-xs text-text-muted">
              Run {runId}
            </div>
          )}
        </div>
        {children}
      </main>

      <aside className="lab-inspector overflow-y-auto p-4" aria-label="Evidence inspector">
        {nextActionPanel}
        <div className="mt-4 space-y-4">{inspector}</div>
      </aside>

      <div
        className="fixed inset-x-0 bottom-[4.35rem] z-40 px-3 pb-2 sm:hidden"
        aria-label="Mobile next action"
      >
        <Button
          type="button"
          tone="primary"
          className="w-full shadow-[var(--lab-shadow)]"
          onClick={onRunNextAction}
          disabled={nextActionDisabled}
        >
          {nextActionCta}
        </Button>
      </div>

      <nav
        className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-bg-secondary px-2 py-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] sm:hidden"
        aria-label="Mobile primary"
      >
        <div className="grid grid-cols-5 gap-1 max-[360px]:grid-cols-3">
          {APP_VIEWS.map((view) => {
            const Icon = VIEW_ICON[view]
            const active = activeView === view
            return (
              <button
                key={view}
                type="button"
                onClick={() => onNavigate(view)}
                aria-current={active ? 'page' : undefined}
                aria-label={`Open ${appViewLabel(view)} view`}
                className={[
                  'ui-control flex min-h-12 flex-col items-center justify-center gap-1 rounded-md border px-1 text-[10px]',
                  COMPACT_MOBILE_SECONDARY_VIEWS.has(view) ? 'max-[360px]:hidden' : '',
                  active
                    ? 'border-accent-info bg-accent-info/12 text-accent-info'
                    : 'border-transparent text-text-muted',
                ].join(' ')}
              >
                <Icon className="h-4 w-4" strokeWidth={1.8} />
                <span className="max-w-full truncate">{appViewLabel(view)}</span>
              </button>
            )
          })}
          <details className="relative hidden max-[360px]:block">
            <summary className="ui-control flex min-h-12 cursor-pointer list-none flex-col items-center justify-center gap-1 rounded-md border border-transparent px-1 text-[10px] text-text-muted">
              <PanelRightOpen className="h-4 w-4" strokeWidth={1.8} />
              <span>More</span>
            </summary>
            <div className="absolute bottom-full right-0 mb-2 w-48 rounded-md border border-border bg-bg-secondary p-2 shadow-[var(--lab-shadow)]">
              {APP_VIEWS.filter((view) => COMPACT_MOBILE_SECONDARY_VIEWS.has(view)).map((view) => {
                const Icon = VIEW_ICON[view]
                const active = activeView === view
                return (
                  <button
                    key={view}
                    type="button"
                    onClick={() => onNavigate(view)}
                    aria-current={active ? 'page' : undefined}
                    aria-label={`Open ${appViewLabel(view)} view`}
                    className={[
                      'ui-control flex min-h-11 w-full items-center gap-2 rounded-md border px-2 text-left text-xs',
                      active
                        ? 'border-accent-info bg-accent-info/12 text-accent-info'
                        : 'border-transparent text-text-secondary',
                    ].join(' ')}
                  >
                    <Icon className="h-4 w-4" strokeWidth={1.8} />
                    <span>{appViewLabel(view)}</span>
                  </button>
                )
              })}
              <button
                type="button"
                onClick={() => setInspectorOpen(true)}
                className="ui-control flex min-h-11 w-full items-center gap-2 rounded-md border border-transparent px-2 text-left text-xs text-text-secondary"
              >
                <PanelRightOpen className="h-4 w-4" strokeWidth={1.8} />
                <span>Inspector</span>
              </button>
            </div>
          </details>
        </div>
      </nav>

      <Drawer
        isOpen={isInspectorOpen}
        title="Evidence inspector"
        onClose={() => setInspectorOpen(false)}
      >
        <div className="space-y-4">
          {nextActionPanel}
          {inspector}
        </div>
      </Drawer>
    </div>
  )
}
