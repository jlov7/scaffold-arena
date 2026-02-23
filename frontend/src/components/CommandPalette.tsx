import { useMemo, useState } from 'react'
import { Modal } from './primitives/Modal'

export interface CommandPaletteItem {
  id: string
  label: string
  hint?: string
  run: () => void
}

interface CommandPaletteProps {
  isOpen: boolean
  onClose: () => void
  commands: CommandPaletteItem[]
}

export default function CommandPalette({
  isOpen,
  onClose,
  commands,
}: CommandPaletteProps) {
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return commands
    return commands.filter((command) => command.label.toLowerCase().includes(q))
  }, [commands, query])

  return (
    <Modal
      isOpen={isOpen}
      onClose={() => {
        setQuery('')
        onClose()
      }}
      title="Command palette"
      className="max-w-xl font-mono"
      contentClassName="p-4"
    >
      <label className="block">
        <span className="sr-only">Search commands</span>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search commands..."
          autoFocus
          className="w-full rounded border border-border bg-bg-primary px-3 py-2 text-xs text-text-primary placeholder:text-text-muted"
        />
      </label>

      <div className="mt-3 max-h-72 overflow-y-auto rounded border border-border bg-bg-primary">
        {filtered.length === 0 && (
          <div className="px-3 py-2 text-xs text-text-secondary">
            No commands matched. Try a different search term.
          </div>
        )}
        {filtered.map((command) => (
          <button
            key={command.id}
            type="button"
            onClick={() => {
              command.run()
              setQuery('')
              onClose()
            }}
            className="flex w-full items-center justify-between border-b border-border px-3 py-2 text-left text-xs text-text-secondary hover:bg-bg-tertiary hover:text-accent-info last:border-b-0"
          >
            <span>{command.label}</span>
            {command.hint && (
              <kbd className="rounded border border-border px-1.5 py-0.5 text-[10px] text-text-muted">
                {command.hint}
              </kbd>
            )}
          </button>
        ))}
      </div>
    </Modal>
  )
}
