import type { ReactNode } from 'react'

interface DrawerProps {
  isOpen: boolean
  title: string
  children: ReactNode
  onClose: () => void
}

export function Drawer({ isOpen, title, children, onClose }: DrawerProps) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-[55] bg-bg-primary/72 sm:hidden">
      <button
        type="button"
        className="absolute inset-0 cursor-default"
        aria-label="Close drawer"
        onClick={onClose}
      />
      <aside className="motion-slide-up absolute inset-x-0 bottom-0 max-h-[82dvh] overflow-y-auto rounded-t-lg border border-border bg-bg-secondary p-4 shadow-[var(--lab-shadow)]">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-text-primary">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="ui-control rounded-md border border-border px-3 py-1.5 text-sm text-text-secondary"
          >
            Close
          </button>
        </div>
        {children}
      </aside>
    </div>
  )
}
