import { Modal } from './primitives/Modal'
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
    const boldMatch = remaining.match(/^\*\*(.+?)\*\*/)
    if (boldMatch) {
      parts.push(<strong key={key++} className="font-bold text-text-primary">{boldMatch[1]}</strong>)
      remaining = remaining.slice(boldMatch[0].length)
      continue
    }

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

    const italicMatch = remaining.match(/^\*(.+?)\*/)
    if (italicMatch) {
      parts.push(<em key={key++}>{italicMatch[1]}</em>)
      remaining = remaining.slice(italicMatch[0].length)
      continue
    }

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
        <div key={i} className="mb-3 mt-4 border-b border-border pb-1 text-lg font-bold text-text-primary first:mt-0">
          {renderInline(line.slice(2))}
        </div>,
      )
    } else if (line.startsWith('## ')) {
      result.push(
        <div key={i} className="mb-2 mt-4 text-base font-semibold text-text-primary">
          {renderInline(line.slice(3))}
        </div>,
      )
    } else if (line.startsWith('### ')) {
      result.push(
        <div key={i} className="mb-1 mt-3 text-sm font-semibold text-text-secondary">
          {renderInline(line.slice(4))}
        </div>,
      )
    } else if (line.startsWith('---')) {
      result.push(<div key={i} className="my-3 border-t border-border" />)
    } else if (line.trim() === '') {
      result.push(<div key={i} className="h-2" />)
    } else if (/^(\d+)\.\s/.test(line)) {
      const match = line.match(/^(\d+)\.\s(.*)/)!
      result.push(
        <div key={i} className="flex gap-2 pl-4 text-sm leading-relaxed text-text-secondary">
          <span className="shrink-0 tabular-nums text-text-muted">{match[1]}.</span>
          <span>{renderInline(match[2])}</span>
        </div>,
      )
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      result.push(
        <div key={i} className="flex gap-2 pl-4 text-sm leading-relaxed text-text-secondary">
          <span className="shrink-0 text-text-muted">&bull;</span>
          <span>{renderInline(line.slice(2))}</span>
        </div>,
      )
    } else {
      result.push(
        <div key={i} className="text-sm leading-relaxed text-text-secondary">
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
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Audit report"
      className="h-[88vh] max-w-3xl font-mono shadow-2xl"
      contentClassName="flex min-h-0 flex-1 flex-col"
    >
      <div className="flex-1 overflow-y-auto px-6 py-5">
        {isLoading && (
          <div className="rounded border border-border/60 bg-bg-primary p-3 text-xs text-text-secondary">
            Generating report and preparing downloads...
          </div>
        )}

        {!isLoading && !markdown && (
          <div className="rounded border border-border/60 bg-bg-primary p-3 text-xs text-text-secondary">
            No report is available yet. Run export from the Results workspace to generate one.
          </div>
        )}

        {!isLoading && markdown && (
          <div className="text-sm">{renderMarkdown(markdown)}</div>
        )}
      </div>

      <div className="shrink-0 border-t border-border px-5 py-4">
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="ui-control rounded border border-border px-3 py-1.5 text-xs text-text-secondary hover:border-accent-info hover:text-accent-info"
          >
            Close
          </button>
          {markdown && (
            <>
              <button
                type="button"
                onClick={() => {
                  void copyMarkdown(markdown)
                }}
                className="ui-control rounded border border-border bg-bg-tertiary px-4 py-2 text-xs font-bold tracking-wide text-text-primary hover:bg-border/60"
              >
                Copy
              </button>
              <button
                type="button"
                onClick={() => downloadMarkdown(markdown)}
                className="ui-control rounded border border-border bg-bg-tertiary px-4 py-2 text-xs font-bold tracking-wide text-text-primary hover:bg-border/60"
              >
                Download .md
              </button>
            </>
          )}
          {markdown && pdfBase64 && (
            <button
              type="button"
              onClick={() => downloadPdf(pdfBase64)}
              className="ui-control rounded border border-accent-info bg-accent-info px-4 py-2 text-xs font-bold tracking-wide text-bg-primary hover:opacity-90"
            >
              Download PDF
            </button>
          )}
        </div>
      </div>
    </Modal>
  )
}
