import { useRef, useEffect, useMemo, useState } from 'react'

interface StreamingTextProps {
  text?: string | null
  isStreaming: boolean
}

export default function StreamingText({ text, isStreaming }: StreamingTextProps) {
  const containerRef = useRef<HTMLPreElement>(null)
  const [showFullText, setShowFullText] = useState(false)
  const safeText = text ?? ''
  const MAX_WINDOW_CHARS = 14_000

  const renderText = useMemo(() => {
    if (showFullText || safeText.length <= MAX_WINDOW_CHARS) return safeText
    return safeText.slice(-MAX_WINDOW_CHARS)
  }, [safeText, showFullText])

  const isWindowed = !showFullText && safeText.length > MAX_WINDOW_CHARS

  // Update textContent directly to avoid React re-renders on the DOM text node
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.textContent = renderText
      // Auto-scroll to bottom during streaming
      if (isStreaming) {
        containerRef.current.scrollTop = containerRef.current.scrollHeight
      }
    }
  }, [renderText, isStreaming])

  return (
    <div className="relative">
      {isWindowed && (
        <div className="mb-2 flex items-center justify-between rounded border border-border/60 bg-bg-secondary px-2 py-1 text-[10px] font-mono text-text-muted">
          <span>Showing latest {MAX_WINDOW_CHARS.toLocaleString()} chars for performance.</span>
          <button
            type="button"
            onClick={() => setShowFullText(true)}
            className="rounded border border-border px-2 py-0.5 text-[10px] text-text-secondary hover:border-accent-info hover:text-accent-info"
          >
            Show full output
          </button>
        </div>
      )}
      <pre
        ref={containerRef}
        className="font-mono text-xs leading-relaxed text-text-primary whitespace-pre-wrap break-words overflow-y-auto max-h-80 p-3 bg-bg-primary rounded"
      />
      {isStreaming && (
        <span className="inline-block w-1.5 h-4 bg-accent-info animate-pulse ml-0.5 align-text-bottom" />
      )}
    </div>
  )
}
