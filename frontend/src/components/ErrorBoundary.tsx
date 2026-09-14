import { Component, type ErrorInfo, type ReactNode } from 'react'

interface ErrorBoundaryProps {
  children: ReactNode
  panelLabel?: string
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

export default class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = {
    hasError: false,
    error: null,
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    if (import.meta.env.DEV) {
      console.error('Panel render error', error, errorInfo)
    }
  }

  render(): ReactNode {
    if (!this.state.hasError) {
      return this.props.children
    }

    return (
      <div className="flex min-h-[420px] flex-col justify-between rounded-lg border border-accent-loser/40 bg-bg-secondary p-4 font-mono">
        <div>
          <div className="text-xs font-bold uppercase tracking-wider text-accent-loser">
            Panel Error
          </div>
          <div className="mt-2 text-sm text-text-secondary">
            {this.props.panelLabel ?? 'This panel'} failed to render.
          </div>
          {import.meta.env.DEV && this.state.error && (
            <pre className="mt-3 overflow-auto rounded bg-bg-primary p-2 text-xs text-accent-loser/90">
              {this.state.error.message}
            </pre>
          )}
        </div>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="mt-4 self-start rounded border border-border px-3 py-1 text-xs text-text-primary hover:border-accent-info"
        >
          Reload
        </button>
      </div>
    )
  }
}
