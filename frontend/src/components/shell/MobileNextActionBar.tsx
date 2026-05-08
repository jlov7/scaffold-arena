interface MobileNextActionBarProps {
  ctaLabel: string
  disabled: boolean
  onClick: () => void
}

export function MobileNextActionBar({
  ctaLabel,
  disabled,
  onClick,
}: MobileNextActionBarProps) {
  return (
    <div className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-bg-secondary/95 px-3 py-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] backdrop-blur sm:hidden">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className="w-full rounded border border-accent-info bg-accent-info/10 py-3 text-xs font-mono font-semibold text-accent-info hover:bg-accent-info hover:text-bg-primary disabled:cursor-not-allowed disabled:opacity-40"
      >
        {ctaLabel}
      </button>
    </div>
  )
}
