interface ReportModalProps {
  isOpen: boolean
  onClose: () => void
  markdown: string | null
  pdfBase64: string | null
  isLoading: boolean
}

function downloadMarkdown(markdown: string) {
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'audit-report.md'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function downloadPdf(pdfBase64: string) {
  const binary = atob(pdfBase64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  const blob = new Blob([bytes], { type: 'application/pdf' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'audit-report.pdf'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function renderMarkdown(raw: string): React.ReactNode {
  const lines = raw.split('\n')
  return lines.map((line, i) => {
    if (line.startsWith('# ')) {
      return (
        <div key={i} className="text-lg font-bold text-text-primary mb-3 mt-4 first:mt-0 border-b border-border pb-1">
          {line.slice(2)}
        </div>
      )
    }
    if (line.startsWith('## ')) {
      return (
        <div key={i} className="text-base font-semibold text-text-primary mb-2 mt-4">
          {line.slice(3)}
        </div>
      )
    }
    if (line.startsWith('### ')) {
      return (
        <div key={i} className="text-sm font-semibold text-text-secondary mb-1 mt-3">
          {line.slice(4)}
        </div>
      )
    }
    if (line.startsWith('---')) {
      return <div key={i} className="border-t border-border my-3" />
    }
    if (line.trim() === '') {
      return <div key={i} className="h-2" />
    }
    return (
      <div key={i} className="text-sm text-text-secondary leading-relaxed">
        {line}
      </div>
    )
  })
}

export default function ReportModal({
  isOpen,
  onClose,
  markdown,
  pdfBase64,
  isLoading,
}: ReportModalProps) {
  if (!isOpen) return null

  function handleOverlayClick(e: React.MouseEvent<HTMLDivElement>) {
    if (e.target === e.currentTarget) onClose()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={handleOverlayClick}
    >
      <div
        className="bg-bg-secondary border border-border rounded-lg w-full max-w-3xl h-[88vh] flex flex-col shadow-2xl font-mono"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border shrink-0">
          <span className="text-xs tracking-widest font-bold text-text-primary">AUDIT REPORT</span>
          <button
            onClick={onClose}
            className="text-text-secondary hover:text-text-primary transition-colors text-lg leading-none w-6 h-6 flex items-center justify-center rounded hover:bg-border/50"
            aria-label="Close"
          >
            X
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {isLoading && (
            <div className="text-text-secondary text-xs animate-pulse">Generating report...</div>
          )}

          {!isLoading && !markdown && (
            <div className="text-text-secondary text-xs opacity-40">No report available.</div>
          )}

          {!isLoading && markdown && (
            <div className="text-sm">{renderMarkdown(markdown)}</div>
          )}
        </div>

        {/* Footer */}
        {!isLoading && markdown && (
          <div className="px-5 py-4 border-t border-border shrink-0 flex items-center gap-3 justify-end">
            <button
              onClick={() => downloadMarkdown(markdown)}
              className="text-xs font-bold text-text-primary bg-bg-tertiary hover:bg-border/60 active:bg-border transition-colors border border-border rounded px-4 py-2 tracking-wide"
            >
              Download .md
            </button>
            {pdfBase64 && (
              <button
                onClick={() => downloadPdf(pdfBase64)}
                className="text-xs font-bold text-bg-primary bg-accent-info hover:bg-accent-info/80 active:bg-accent-info/70 transition-colors rounded px-4 py-2 tracking-wide"
              >
                Download PDF
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
