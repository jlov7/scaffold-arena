import { useEffect, useRef, useCallback } from 'react'

type SSEHandler = (eventName: string, data: unknown) => void
interface SSEOptions {
  onError?: (err: Event) => void
  onRetrying?: (attempt: number) => void
  onFailed?: () => void
  onConnected?: () => void
  maxRetries?: number
}

export function useSSE(
  url: string | null,
  onEvent: SSEHandler,
  options?: SSEOptions,
) {
  const sourceRef = useRef<EventSource | null>(null)
  const handlerRef = useRef(onEvent)
  const optionsRef = useRef(options)

  useEffect(() => {
    handlerRef.current = onEvent
  }, [onEvent])

  useEffect(() => {
    optionsRef.current = options
  }, [options])

  const close = useCallback(() => {
    if (sourceRef.current) {
      sourceRef.current.close()
      sourceRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!url) return

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

    let cancelled = false
    let reconnectTimer: number | null = null
    let retryCount = 0
    const maxRetries = optionsRef.current?.maxRetries ?? 5

    const connect = () => {
      if (cancelled) return

      const es = new EventSource(url)
      sourceRef.current = es

      es.onopen = () => {
        retryCount = 0
        optionsRef.current?.onConnected?.()
      }

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
        optionsRef.current?.onError?.(e)
        es.close()
        sourceRef.current = null

        if (cancelled) return

        retryCount += 1
        if (retryCount > maxRetries) {
          optionsRef.current?.onFailed?.()
          return
        }

        optionsRef.current?.onRetrying?.(retryCount)
        const backoffMs = Math.min(500 * 2 ** (retryCount - 1), 8000)
        reconnectTimer = window.setTimeout(connect, backoffMs)
      }
    }

    connect()

    return () => {
      cancelled = true
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer)
      }
      if (sourceRef.current) {
        sourceRef.current.close()
      }
      sourceRef.current = null
    }
  }, [url])

  return { close }
}
