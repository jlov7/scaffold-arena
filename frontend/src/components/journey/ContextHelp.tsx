interface ContextHelpProps {
  title: string
  body: string
  successCriteria?: string
}

export function ContextHelp({ title, body, successCriteria }: ContextHelpProps) {
  return (
    <aside
      className="rounded-lg border border-border/70 bg-bg-secondary p-4"
      aria-live="polite"
      aria-label="Context guidance"
    >
      <div className="text-[10px] font-mono uppercase tracking-widest text-text-secondary">
        Context guidance
      </div>
      <h2 className="mt-2 text-sm font-mono text-text-primary">{title}</h2>
      <p className="mt-1 max-w-[80ch] text-xs leading-relaxed text-text-secondary">
        {body}
      </p>
      {successCriteria && (
        <p className="mt-2 rounded border border-border/50 bg-bg-primary px-2 py-1 text-[11px] text-text-muted">
          Done when: {successCriteria}
        </p>
      )}
    </aside>
  )
}
