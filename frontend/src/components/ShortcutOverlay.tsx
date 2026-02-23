import { Modal } from './primitives/Modal'

interface ShortcutOverlayProps {
  isOpen: boolean
  onClose: () => void
}

export default function ShortcutOverlay({
  isOpen,
  onClose,
}: ShortcutOverlayProps) {
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Keyboard shortcuts"
      closeLabel="Close keyboard shortcuts"
      className="max-w-md font-mono"
      contentClassName="p-5"
    >
        <div className="flex items-center justify-between">
          <div className="text-xs uppercase tracking-widest text-text-secondary">
            Keyboard Shortcuts
          </div>
        </div>
        <div className="mt-4 space-y-2 text-xs text-text-primary">
          <div className="flex items-center justify-between">
            <span>Run Arena</span>
            <kbd className="rounded border border-border px-2 py-0.5">Cmd/Ctrl + Enter</kbd>
          </div>
          <div className="flex items-center justify-between">
            <span>Open command palette</span>
            <kbd className="rounded border border-border px-2 py-0.5">Cmd/Ctrl + K</kbd>
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
    </Modal>
  )
}
