import { useRef, useEffect } from 'react'

interface StreamingTextProps {
  text: string
  isStreaming: boolean
}

export default function StreamingText({ text, isStreaming }: StreamingTextProps) {
  const containerRef = useRef<HTMLPreElement>(null)
  const prevLenRef = useRef(0)

  // Update textContent directly to avoid React re-renders on the DOM text node
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.textContent = text
      // Auto-scroll to bottom during streaming
      if (isStreaming) {
        containerRef.current.scrollTop = containerRef.current.scrollHeight
      }
    }
    prevLenRef.current = text.length
  }, [text, isStreaming])

  return (
    <div className="relative">
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
