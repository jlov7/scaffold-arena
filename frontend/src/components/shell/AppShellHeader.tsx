import { COPY } from '../../content/copy'
import {
  APP_VIEWS,
  appViewLabel,
  type AppView,
} from '../../app/viewState'

interface AppShellHeaderProps {
  activeView: AppView
  stageLabel: string
  theme: 'dark' | 'light'
  onOpenHelp: () => void
  onExplainScreen: () => void
  onOpenTour: () => void
  onOpenCommandPalette: () => void
  onToggleTheme: () => void
  onNavigate: (view: AppView) => void
}

const VIEW_HINTS: Record<AppView, string> = {
  arena: 'Run and monitor benchmarks.',
  results: 'Review winners, costs, and diagnostics.',
  history: 'Re-open previous runs quickly.',
  leaderboard: 'Compare aggregate scaffold performance.',
  settings: 'Configure keys, preferences, and safeguards.',
}

export function AppShellHeader({
  activeView,
  stageLabel,
  theme,
  onOpenHelp,
  onExplainScreen,
  onOpenTour,
  onOpenCommandPalette,
  onToggleTheme,
  onNavigate,
}: AppShellHeaderProps) {
  const mobilePrimaryViews: AppView[] = ['arena', 'results']
  const mobileSecondaryViews = APP_VIEWS.filter(
    (view) => !mobilePrimaryViews.includes(view),
  )

  return (
    <header className="border-b border-border" role="banner">
      <div className="px-4 py-2.5 sm:px-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="font-mono text-lg font-bold tracking-tight text-text-primary sm:text-xl">
              {COPY.app.title}
            </h1>
            <p className="mt-1 text-sm text-text-secondary sm:text-[0.95rem]">
              {COPY.app.subtitle}
            </p>
          </div>
          <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-1">
            <span className="hidden rounded border border-accent-info/40 bg-accent-info/10 px-2 py-1 text-xs font-mono text-accent-info sm:inline-block">
              {stageLabel}
            </span>
            <button
              type="button"
              onClick={onOpenHelp}
              className="ui-control rounded border border-transparent min-h-11 px-2.5 py-2 text-sm font-mono text-text-secondary hover:border-border hover:text-accent-info sm:min-h-0 sm:px-2.5 sm:py-1.5 sm:text-xs"
            >
              Help
            </button>
            <button
              type="button"
              onClick={onExplainScreen}
              className="ui-control hidden rounded border border-transparent min-h-11 px-2.5 py-2 text-sm font-mono text-text-secondary hover:border-border hover:text-accent-info sm:inline-block sm:min-h-0 sm:px-2.5 sm:py-1.5 sm:text-xs"
            >
              Explain this screen
            </button>
            <button
              type="button"
              onClick={onOpenTour}
              className="ui-control rounded border border-transparent min-h-11 px-2.5 py-2 text-sm font-mono text-text-secondary hover:border-border hover:text-accent-info sm:min-h-0 sm:px-2.5 sm:py-1.5 sm:text-xs"
            >
              {COPY.actions.takeTour}
            </button>
            <button
              type="button"
              onClick={onOpenCommandPalette}
              className="ui-control rounded border border-transparent min-h-11 px-2.5 py-2 text-sm font-mono text-text-secondary hover:border-border hover:text-accent-info sm:min-h-0 sm:px-2.5 sm:py-1.5 sm:text-xs"
              aria-label="Open command palette"
            >
              Cmd/Ctrl+K
            </button>
            <button
              type="button"
              onClick={onToggleTheme}
              className="ui-control rounded border border-transparent min-h-11 min-w-11 px-3 py-2 text-sm font-mono text-text-secondary hover:border-border hover:text-accent-info sm:min-h-0 sm:min-w-0 sm:px-2.5 sm:py-1.5 sm:text-xs"
              aria-label={theme === 'dark' ? 'Light theme' : 'Dark theme'}
            >
              {theme === 'dark' ? '\u2600' : '\u263E'}
            </button>
          </div>
        </div>
        <div className="mt-2 flex items-center justify-between gap-3">
          <nav aria-label="Primary" className="flex items-center gap-1 overflow-x-auto">
            <div className="contents max-[360px]:hidden">
              {APP_VIEWS.map((view) => (
                <button
                  key={view}
                  id={view === 'settings' ? 'tour-settings-link' : undefined}
                  type="button"
                  onClick={() => onNavigate(view)}
                  title={VIEW_HINTS[view]}
                  aria-current={activeView === view ? 'page' : undefined}
                  aria-label={`Open ${appViewLabel(view)} view`}
                  className={[
                    'ui-control rounded border min-h-11 px-2.5 py-2 text-sm font-mono transition-colors sm:min-h-0 sm:px-2.5 sm:py-1.5 sm:text-xs',
                    activeView === view
                      ? 'border-accent-info bg-accent-info/10 text-accent-info'
                      : 'border-transparent text-text-secondary hover:border-border hover:text-accent-info',
                  ].join(' ')}
                >
                  {appViewLabel(view)}
                </button>
              ))}
            </div>
            <div className="hidden w-full items-center gap-1 max-[360px]:flex">
              {mobilePrimaryViews.map((view) => (
                <button
                  key={view}
                  type="button"
                  onClick={() => onNavigate(view)}
                  title={VIEW_HINTS[view]}
                  aria-current={activeView === view ? 'page' : undefined}
                  aria-label={`Open ${appViewLabel(view)} view`}
                  className={[
                    'ui-control rounded border min-h-11 px-2.5 py-2 text-sm font-mono transition-colors sm:min-h-0 sm:px-2.5 sm:py-1.5 sm:text-xs',
                    activeView === view
                      ? 'border-accent-info bg-accent-info/10 text-accent-info'
                      : 'border-transparent text-text-secondary hover:border-border hover:text-accent-info',
                  ].join(' ')}
                >
                  {appViewLabel(view)}
                </button>
              ))}
              <details className="relative">
                <summary className="list-none rounded border border-transparent min-h-11 px-2.5 py-2 text-xs font-mono text-text-secondary hover:border-border hover:text-accent-info cursor-pointer sm:min-h-0 sm:px-2.5 sm:py-1 sm:text-[11px]">
                  More
                </summary>
                <div className="absolute right-0 z-20 mt-1 w-40 rounded border border-border bg-bg-secondary p-1.5 shadow-lg">
                  {mobileSecondaryViews.map((view) => (
                    <button
                      key={view}
                      id={view === 'settings' ? 'tour-settings-link' : undefined}
                      type="button"
                      onClick={() => onNavigate(view)}
                      title={VIEW_HINTS[view]}
                      aria-current={activeView === view ? 'page' : undefined}
                      aria-label={`Open ${appViewLabel(view)} view`}
                      className={[
                        'ui-control mb-0.5 block w-full rounded min-h-11 px-3 py-2 text-left text-sm font-mono sm:min-h-0 sm:px-2.5 sm:py-1.5 sm:text-xs',
                        activeView === view
                          ? 'bg-accent-info/10 text-accent-info'
                          : 'text-text-secondary hover:text-accent-info hover:bg-bg-tertiary',
                      ].join(' ')}
                    >
                      {appViewLabel(view)}
                    </button>
                  ))}
                </div>
              </details>
            </div>
          </nav>
          <div className="hidden text-xs font-mono text-text-muted min-[380px]:block">
            {COPY.app.breadcrumbHome} / {appViewLabel(activeView)}
          </div>
        </div>
      </div>
    </header>
  )
}
