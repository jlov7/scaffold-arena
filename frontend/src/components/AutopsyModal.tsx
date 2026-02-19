import type { AutopsyResult } from '../types'

interface AutopsyModalProps {
  isOpen: boolean
  onClose: () => void
  autopsy: AutopsyResult | null
  isLoading: boolean
  onApplyPatch: (patch: Record<string, unknown>) => void
  scaffoldName: string
}

function severityStyle(severity: string): string {
  switch (severity.toLowerCase()) {
    case 'critical':
      return 'text-accent-loser'
    case 'high':
      return 'text-accent-warning'
    default:
      return 'text-text-secondary'
  }
}

function severityIcon(severity: string): string {
  switch (severity.toLowerCase()) {
    case 'critical':
      return '!!'
    case 'high':
      return '!'
    default:
      return '~'
  }
}

export default function AutopsyModal({
  isOpen,
  onClose,
  autopsy,
  isLoading,
  onApplyPatch,
  scaffoldName,
}: AutopsyModalProps) {
  if (!isOpen) return null

  const hasPatch = autopsy?.patch && Object.keys(autopsy.patch).length > 0

  function handleOverlayClick(e: React.MouseEvent<HTMLDivElement>) {
    if (e.target === e.currentTarget) onClose()
  }

  function handleApply() {
    if (autopsy?.patch) onApplyPatch(autopsy.patch)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={handleOverlayClick}
    >
      <div
        className="bg-bg-secondary border border-border rounded-lg w-full max-w-2xl max-h-[85vh] flex flex-col font-mono shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-accent-loser text-xs tracking-widest font-bold">AUTOPSY</span>
            <span className="text-border">|</span>
            <span className="text-text-primary text-sm">{scaffoldName}</span>
          </div>
          <button
            onClick={onClose}
            className="text-text-secondary hover:text-text-primary transition-colors text-lg leading-none w-6 h-6 flex items-center justify-center rounded hover:bg-border/50"
            aria-label="Close"
          >
            X
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {isLoading && (
            <div className="text-text-secondary text-xs animate-pulse">Analyzing failures...</div>
          )}

          {!isLoading && !autopsy && (
            <div className="text-text-secondary text-xs opacity-40">No autopsy data available.</div>
          )}

          {!isLoading && autopsy && (
            <>
              {/* Summary */}
              {autopsy.summary && (
                <div>
                  <div className="text-xs text-text-secondary/60 tracking-widest mb-1">SUMMARY</div>
                  <div className="text-sm text-text-primary leading-relaxed">{autopsy.summary}</div>
                </div>
              )}

              {/* Failures */}
              {autopsy.failures.length > 0 && (
                <div>
                  <div className="text-xs text-text-secondary/60 tracking-widest mb-2">FAILURES</div>
                  <div className="space-y-3">
                    {autopsy.failures.map((f, i) => (
                      <div key={i} className="border border-border/50 rounded p-3 bg-bg-primary/40">
                        <div className="flex items-center gap-2 mb-1">
                          <span
                            className={[
                              'text-xs font-bold w-5 shrink-0',
                              severityStyle(f.severity),
                            ].join(' ')}
                          >
                            [{severityIcon(f.severity)}]
                          </span>
                          <span className="text-text-primary text-xs font-semibold">{f.type}</span>
                          <span
                            className={[
                              'ml-auto text-xs uppercase tracking-wide',
                              severityStyle(f.severity),
                            ].join(' ')}
                          >
                            {f.severity}
                          </span>
                        </div>
                        {f.description && (
                          <div className="text-xs text-text-secondary mb-1 pl-7">{f.description}</div>
                        )}
                        {f.evidence && (
                          <div className="pl-7">
                            <span className="text-xs text-text-secondary/50">Evidence: </span>
                            <span className="text-xs text-text-secondary">{f.evidence}</span>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Patch */}
              {hasPatch && (
                <div>
                  <div className="text-xs text-text-secondary/60 tracking-widest mb-2">SUGGESTED PATCH</div>
                  <pre className="bg-bg-primary border border-border/50 rounded p-3 text-xs text-text-secondary overflow-x-auto whitespace-pre-wrap break-words leading-relaxed">
                    {JSON.stringify(autopsy.patch, null, 2)}
                  </pre>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        {!isLoading && autopsy && hasPatch && (
          <div className="px-5 py-4 border-t border-border shrink-0 flex justify-end">
            <button
              onClick={handleApply}
              className="text-xs font-bold text-bg-primary bg-accent-winner hover:bg-accent-winner/80 active:bg-accent-winner/70 transition-colors rounded px-4 py-2 tracking-wide"
            >
              Apply Patch &amp; Rerun
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
