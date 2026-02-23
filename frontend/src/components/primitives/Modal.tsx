import { useEffect, useId, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

interface ModalProps {
  isOpen: boolean
  title: string
  onClose: () => void
  children: ReactNode
  className?: string
  overlayClassName?: string
  contentClassName?: string
  hideHeader?: boolean
  hideCloseButton?: boolean
  closeLabel?: string
  closeOnBackdrop?: boolean
}

const FOCUSABLE_SELECTOR =
  'button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])'

export function Modal({
  isOpen,
  title,
  onClose,
  children,
  className = '',
  overlayClassName = '',
  contentClassName = '',
  hideHeader = false,
  hideCloseButton = false,
  closeLabel,
  closeOnBackdrop = true,
}: ModalProps) {
  const modalRef = useRef<HTMLDivElement>(null)
  const prevFocusRef = useRef<HTMLElement | null>(null)
  const titleId = useId()

  useEffect(() => {
    if (!isOpen) return
    prevFocusRef.current = document.activeElement as HTMLElement | null

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const appRoot = document.getElementById('root')
    const previousAriaHidden = appRoot?.getAttribute('aria-hidden') ?? null
    appRoot?.setAttribute('aria-hidden', 'true')

    const first = modalRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)
    first?.focus()

    return () => {
      document.body.style.overflow = previousOverflow
      if (appRoot) {
        if (previousAriaHidden === null) {
          appRoot.removeAttribute('aria-hidden')
        } else {
          appRoot.setAttribute('aria-hidden', previousAriaHidden)
        }
      }
      prevFocusRef.current?.focus()
    }
  }, [isOpen])

  if (!isOpen) return null

  function handleOverlayClick(e: React.MouseEvent<HTMLDivElement>) {
    if (closeOnBackdrop && e.target === e.currentTarget) onClose()
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === 'Escape') {
      e.stopPropagation()
      onClose()
      return
    }
    if (e.key !== 'Tab') return

    const focusables = modalRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
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

  return createPortal(
    <div
      className={[
        'fixed inset-0 z-[60] flex items-center justify-center bg-black/70 motion-fade-in',
        overlayClassName,
      ].join(' ')}
      onClick={handleOverlayClick}
      onKeyDown={handleKeyDown}
    >
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={[
          'motion-slide-up flex w-full max-w-2xl flex-col rounded-lg border border-border bg-bg-secondary',
          className,
        ].join(' ')}
      >
        {!hideHeader && (
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <h2 id={titleId} className="text-sm font-mono text-text-primary">
              {title}
            </h2>
            {!hideCloseButton && (
              <button
                type="button"
                onClick={onClose}
                aria-label={closeLabel ?? `Close ${title}`}
                className="ui-control rounded border border-border px-2 py-1 text-xs text-text-secondary hover:border-accent-info hover:text-accent-info"
              >
                Close
              </button>
            )}
          </div>
        )}
        {hideHeader && <span id={titleId} className="sr-only">{title}</span>}
        <div className={['min-h-0', contentClassName].join(' ')}>{children}</div>
      </div>
    </div>,
    document.body,
  )
}
