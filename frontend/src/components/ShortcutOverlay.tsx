import { useEffect, useRef } from 'react'

interface ShortcutOverlayProps {
  isOpen: boolean
  onClose: () => void
}

export default function ShortcutOverlay({
  isOpen,
  onClose,
}: ShortcutOverlayProps) {
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
      className="fixed inset-0 z-60 flex items-center justify-center bg-black/70"
      onClick={onClose}
    >
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcut-overlay-title"
        tabIndex={-1}
        className="w-full max-w-md rounded-lg border border-border bg-bg-secondary p-5 font-mono"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <div className="flex items-center justify-between">
          <div id="shortcut-overlay-title" className="text-xs uppercase tracking-widest text-text-secondary">
            Keyboard Shortcuts
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-border px-2 py-0.5 text-[11px] text-text-secondary hover:border-accent-info hover:text-accent-info"
          >
            Close
          </button>
        </div>
        <div className="mt-4 space-y-2 text-xs text-text-primary">
          <div className="flex items-center justify-between">
            <span>Run Arena</span>
            <kbd className="rounded border border-border px-2 py-0.5">Cmd/Ctrl + Enter</kbd>
          </div>
          <div className="flex items-center justify-between">
            <span>Close modals/overlay</span>
            <kbd className="rounded border border-border px-2 py-0.5">Escape</kbd>
          </div>
          <div className="flex items-center justify-between">
            <span>Show shortcuts</span>
            <kbd className="rounded border border-border px-2 py-0.5">?</kbd>
          </div>
          <div className="flex items-center justify-between">
            <span>Open help center</span>
            <kbd className="rounded border border-border px-2 py-0.5">H / F1</kbd>
          </div>
        </div>
      </div>
    </div>
  )
}
