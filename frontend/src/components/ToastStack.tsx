import { useEffect } from 'react'

export interface ToastItem {
  id: number
  type: 'success' | 'error' | 'info'
  message: string
}

interface ToastStackProps {
  toasts: ToastItem[]
  onDismiss: (id: number) => void
}

const TOAST_STYLE: Record<ToastItem['type'], string> = {
  success: 'border-accent-winner/40 bg-accent-winner/10 text-accent-winner',
  error: 'border-accent-loser/40 bg-accent-loser/10 text-accent-loser',
  info: 'border-accent-info/40 bg-accent-info/10 text-accent-info',
}

export default function ToastStack({ toasts, onDismiss }: ToastStackProps) {
  useEffect(() => {
    const timers = toasts.map((toast) =>
      window.setTimeout(() => onDismiss(toast.id), 5000),
    )
    return () => {
      for (const timer of timers) window.clearTimeout(timer)
    }
  }, [toasts, onDismiss])

  if (toasts.length === 0) return null

  return (
    <div className="fixed top-4 right-4 z-[70] flex w-[320px] max-w-[90vw] flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={[
            'motion-slide-up flex items-start gap-2 rounded border px-3 py-2 text-xs font-mono shadow-lg backdrop-blur-sm',
            TOAST_STYLE[toast.type],
          ].join(' ')}
          role={toast.type === 'error' ? 'alert' : 'status'}
          aria-live={toast.type === 'error' ? 'assertive' : 'polite'}
        >
          <span className="flex-1">{toast.message}</span>
          <button
            type="button"
            onClick={() => onDismiss(toast.id)}
            aria-label="Dismiss notification"
            className="shrink-0 opacity-60 hover:opacity-100 transition-opacity leading-none"
          >
            &times;
          </button>
        </div>
      ))}
    </div>
  )
}
