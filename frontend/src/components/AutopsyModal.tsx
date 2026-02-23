import { useState } from 'react'

import type { AutopsyResult } from '../types'
import { Modal } from './primitives/Modal'

interface AutopsyModalProps {
  isOpen: boolean
  onClose: () => void
  autopsy: AutopsyResult | null
  isLoading: boolean
  onApplyPatch: (patch: Record<string, unknown>) => Promise<void> | void
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
  const hasPatch = autopsy?.patch && Object.keys(autopsy.patch).length > 0
  const [isApplyingPatch, setIsApplyingPatch] = useState(false)

  async function handleApplyPatch(): Promise<void> {
    if (!autopsy?.patch || isApplyingPatch) return
    setIsApplyingPatch(true)
    try {
      await onApplyPatch(autopsy.patch)
    } finally {
      setIsApplyingPatch(false)
    }
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`Autopsy: ${scaffoldName}`}
      closeLabel="Close autopsy modal"
      className="max-h-[85vh] max-w-2xl font-mono shadow-2xl"
      contentClassName="flex min-h-0 flex-1 flex-col"
    >
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {isLoading && (
          <div className="rounded border border-border/60 bg-bg-primary p-3 text-xs text-text-secondary">
            Analyzing failures and generating patch suggestions...
          </div>
        )}

        {!isLoading && !autopsy && (
          <div className="rounded border border-border/60 bg-bg-primary p-3 text-xs text-text-secondary">
            No autopsy data is available for this scaffold yet. Rerun analysis from Results and try again.
          </div>
        )}

        {!isLoading && autopsy && (
          <div className="space-y-5">
            {autopsy.summary && (
              <div>
                <div className="mb-1 text-xs tracking-widest text-text-secondary/60">SUMMARY</div>
                <div className="text-sm leading-relaxed text-text-primary">{autopsy.summary}</div>
              </div>
            )}

            {autopsy.failures.length > 0 ? (
              <div>
                <div className="mb-2 text-xs tracking-widest text-text-secondary/60">FAILURES</div>
                <div className="space-y-3">
                  {autopsy.failures.map((failure, index) => (
                    <div
                      key={`${failure.type}-${index}`}
                      className="rounded border border-border/50 bg-bg-primary/40 p-3"
                    >
                      <div className="mb-1 flex items-center gap-2">
                        <span
                          className={[
                            'w-5 shrink-0 text-xs font-bold',
                            severityStyle(failure.severity),
                          ].join(' ')}
                        >
                          [{severityIcon(failure.severity)}]
                        </span>
                        <span className="text-xs font-semibold text-text-primary">{failure.type}</span>
                        <span
                          className={[
                            'ml-auto text-xs uppercase tracking-wide',
                            severityStyle(failure.severity),
                          ].join(' ')}
                        >
                          {failure.severity}
                        </span>
                      </div>
                      {failure.description && (
                        <div className="mb-1 pl-7 text-xs text-text-secondary">{failure.description}</div>
                      )}
                      {failure.evidence && (
                        <div className="pl-7 text-xs text-text-secondary">
                          <span className="text-text-secondary/60">Evidence: </span>
                          <span>{failure.evidence}</span>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="rounded border border-border/60 bg-bg-primary p-3 text-xs text-text-secondary">
                No concrete failures were extracted. Validate prompt and scoring context, then rerun autopsy.
              </div>
            )}

            {hasPatch && (
              <div>
                <div className="mb-2 text-xs tracking-widest text-text-secondary/60">SUGGESTED PATCH</div>
                <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded border border-border/50 bg-bg-primary p-3 text-xs leading-relaxed text-text-secondary">
                  {JSON.stringify(autopsy.patch, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>

      {!isLoading && autopsy && (
        <div className="shrink-0 border-t border-border px-5 py-4">
          <div className="flex flex-wrap items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="ui-control rounded border border-border px-3 py-1.5 text-xs text-text-secondary hover:border-accent-info hover:text-accent-info"
            >
              Close
            </button>
            <button
              type="button"
              onClick={() => {
                void handleApplyPatch()
              }}
              disabled={!hasPatch || isApplyingPatch}
              className="ui-control rounded border border-accent-winner bg-accent-winner px-4 py-1.5 text-xs font-bold tracking-wide text-bg-primary hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {isApplyingPatch ? 'Applying patch...' : 'Apply patch and rerun'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}
