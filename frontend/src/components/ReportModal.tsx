import { useEffect, useRef } from 'react'

import { emitAppToast } from '../utils/toast'

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
  emitAppToast({ type: 'success', message: 'Markdown exported' })
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
  emitAppToast({ type: 'success', message: 'PDF exported' })
}

async function copyMarkdown(markdown: string): Promise<void> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(markdown)
    } else {
      const el = document.createElement('textarea')
      el.value = markdown
      document.body.appendChild(el)
      el.select()
      document.execCommand('copy')
      document.body.removeChild(el)
    }
    emitAppToast({ type: 'success', message: 'Copied to clipboard' })
  } catch {
    emitAppToast({ type: 'error', message: 'Copy failed' })
  }
}

function renderInline(text: string): React.ReactNode {
  const parts: React.ReactNode[] = []
  let remaining = text
  let key = 0

  while (remaining.length > 0) {
    // Bold: **text**
    const boldMatch = remaining.match(/^\*\*(.+?)\*\*/)
    if (boldMatch) {
      parts.push(<strong key={key++} className="font-bold text-text-primary">{boldMatch[1]}</strong>)
      remaining = remaining.slice(boldMatch[0].length)
      continue
    }

    // Inline code: `code`
    const codeMatch = remaining.match(/^`([^`]+)`/)
    if (codeMatch) {
      parts.push(
        <code key={key++} className="rounded bg-bg-tertiary px-1 py-0.5 text-[0.85em] text-accent-info">
          {codeMatch[1]}
        </code>,
      )
      remaining = remaining.slice(codeMatch[0].length)
      continue
    }

    // Italic: *text*
    const italicMatch = remaining.match(/^\*(.+?)\*/)
    if (italicMatch) {
      parts.push(<em key={key++}>{italicMatch[1]}</em>)
      remaining = remaining.slice(italicMatch[0].length)
      continue
    }

    // Link: [text](url)
    const linkMatch = remaining.match(/^\[([^\]]+)\]\(([^)]+)\)/)
    if (linkMatch) {
      parts.push(
        <a key={key++} href={linkMatch[2]} target="_blank" rel="noopener noreferrer" className="text-accent-info underline decoration-dotted hover:decoration-solid">
          {linkMatch[1]}
        </a>,
      )
      remaining = remaining.slice(linkMatch[0].length)
      continue
    }

    // Plain text — consume until next special character
    const nextSpecial = remaining.slice(1).search(/[*`[]/)
    if (nextSpecial === -1) {
      parts.push(remaining)
      break
    }
    parts.push(remaining.slice(0, nextSpecial + 1))
    remaining = remaining.slice(nextSpecial + 1)
  }

  return parts.length === 1 ? parts[0] : parts
}

function renderMarkdown(raw: string): React.ReactNode {
  const lines = raw.split('\n')
  const result: React.ReactNode[] = []
  let inCodeBlock = false
  let codeLines: string[] = []
  let codeLang = ''

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]

    // Code fence toggle
    if (line.startsWith('```')) {
      if (!inCodeBlock) {
        inCodeBlock = true
        codeLang = line.slice(3).trim()
        codeLines = []
      } else {
        result.push(
          <pre key={i} className="my-2 overflow-x-auto rounded border border-border bg-bg-primary p-3 text-xs leading-relaxed">
            {codeLang && <div className="mb-1 text-[10px] uppercase tracking-wider text-text-muted">{codeLang}</div>}
            <code className="text-text-primary">{codeLines.join('\n')}</code>
          </pre>,
        )
        inCodeBlock = false
      }
      continue
    }

    if (inCodeBlock) {
      codeLines.push(line)
      continue
    }

    if (line.startsWith('# ')) {
      result.push(
        <div key={i} className="text-lg font-bold text-text-primary mb-3 mt-4 first:mt-0 border-b border-border pb-1">
          {renderInline(line.slice(2))}
        </div>,
      )
    } else if (line.startsWith('## ')) {
      result.push(
        <div key={i} className="text-base font-semibold text-text-primary mb-2 mt-4">
          {renderInline(line.slice(3))}
        </div>,
      )
    } else if (line.startsWith('### ')) {
      result.push(
        <div key={i} className="text-sm font-semibold text-text-secondary mb-1 mt-3">
          {renderInline(line.slice(4))}
        </div>,
      )
    } else if (line.startsWith('---')) {
      result.push(<div key={i} className="border-t border-border my-3" />)
    } else if (line.trim() === '') {
      result.push(<div key={i} className="h-2" />)
    } else if (/^(\d+)\.\s/.test(line)) {
      const match = line.match(/^(\d+)\.\s(.*)/)!
      result.push(
        <div key={i} className="text-sm text-text-secondary leading-relaxed pl-4 flex gap-2">
          <span className="shrink-0 text-text-muted tabular-nums">{match[1]}.</span>
          <span>{renderInline(match[2])}</span>
        </div>,
      )
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      result.push(
        <div key={i} className="text-sm text-text-secondary leading-relaxed pl-4 flex gap-2">
          <span className="shrink-0 text-text-muted">&bull;</span>
          <span>{renderInline(line.slice(2))}</span>
        </div>,
      )
    } else {
      result.push(
        <div key={i} className="text-sm text-text-secondary leading-relaxed">
          {renderInline(line)}
        </div>,
      )
    }
  }

  return result
}

export default function ReportModal({
  isOpen,
  onClose,
  markdown,
  pdfBase64,
  isLoading,
}: ReportModalProps) {
  const modalRef = useRef<HTMLDivElement>(null)
  const prevFocusRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!isOpen) return
    prevFocusRef.current = document.activeElement as HTMLElement | null
    const first = modalRef.current?.querySelector<HTMLElement>(
      'button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])',
    )
    first?.focus()

    return () => {
      prevFocusRef.current?.focus()
    }
  }, [isOpen])

  if (!isOpen) return null

  function handleOverlayClick(e: React.MouseEvent<HTMLDivElement>) {
    if (e.target === e.currentTarget) onClose()
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === 'Escape') {
      e.stopPropagation()
      onClose()
      return
    }
    if (e.key !== 'Tab') return

    const focusables = modalRef.current?.querySelectorAll<HTMLElement>(
      'button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])',
    )
    if (!focusables || focusables.length === 0) return

    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    const active = document.activeElement

    if (e.shiftKey && active === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && active === last) {
      e.preventDefault()
      first.focus()
    }
  }

  return (
    <div
      className="motion-fade-in fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={handleOverlayClick}
    >
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="report-modal-title"
        className="motion-slide-up bg-bg-secondary border border-border rounded-lg w-full max-w-3xl h-[88vh] flex flex-col shadow-2xl font-mono"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border shrink-0">
          <span id="report-modal-title" className="text-xs tracking-widest font-bold text-text-primary">AUDIT REPORT</span>
          <button
            type="button"
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
              type="button"
              onClick={() => void copyMarkdown(markdown)}
              className="ui-control text-xs font-bold text-text-primary bg-bg-tertiary hover:bg-border/60 active:bg-border transition-colors border border-border rounded px-4 py-2 tracking-wide"
            >
              Copy
            </button>
            <button
              type="button"
              onClick={() => downloadMarkdown(markdown)}
              className="ui-control text-xs font-bold text-text-primary bg-bg-tertiary hover:bg-border/60 active:bg-border transition-colors border border-border rounded px-4 py-2 tracking-wide"
            >
              Download .md
            </button>
            {pdfBase64 && (
              <button
                type="button"
                onClick={() => downloadPdf(pdfBase64)}
                className="ui-control text-xs font-bold text-bg-primary bg-accent-info hover:bg-accent-info/80 active:bg-accent-info/70 transition-colors rounded px-4 py-2 tracking-wide"
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
