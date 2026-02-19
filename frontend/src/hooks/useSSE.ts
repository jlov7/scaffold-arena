import { useEffect, useRef, useCallback } from 'react'

type SSEHandler = (eventName: string, data: unknown) => void

export function useSSE(
  url: string | null,
  onEvent: SSEHandler,
  onError?: (err: Event) => void,
) {
  const sourceRef = useRef<EventSource | null>(null)
  const handlerRef = useRef(onEvent)
  handlerRef.current = onEvent

  const close = useCallback(() => {
    if (sourceRef.current) {
      sourceRef.current.close()
      sourceRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!url) return

    const es = new EventSource(url)
    sourceRef.current = es

    const eventTypes = [
      'run_started',
      'scaffold_started',
      'scaffold_phase',
      'scaffold_delta',
      'scaffold_completed',
      'scaffold_failed',
      'evaluation_completed',
      'run_complete',
      'heartbeat',
      'comparison_started',
      'case_started',
      'case_delta',
      'case_completed',
      'case_evaluation_completed',
      'comparison_complete',
    ]

    for (const type of eventTypes) {
      es.addEventListener(type, (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data)
          handlerRef.current(type, data)
        } catch {
          // Skip malformed events
        }
      })
    }

    es.onerror = (e) => {
      onError?.(e)
      // EventSource auto-reconnects; close on terminal events
    }

    return () => {
      es.close()
      sourceRef.current = null
    }
  }, [url, onError])

  return { close }
}
