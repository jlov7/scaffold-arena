export interface SegmentedControlOption<TValue extends string> {
  value: TValue
  label: string
  disabled?: boolean
}

interface SegmentedControlProps<TValue extends string> {
  label: string
  value: TValue
  options: SegmentedControlOption<TValue>[]
  onChange: (value: TValue) => void
  className?: string
}

export function SegmentedControl<TValue extends string>({
  label,
  value,
  options,
  onChange,
  className = '',
}: SegmentedControlProps<TValue>) {
  return (
    <div
      className={['inline-flex rounded-md border border-border bg-bg-primary p-1', className].join(' ')}
      role="group"
      aria-label={label}
    >
      {options.map((option) => {
        const selected = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            disabled={option.disabled}
            aria-pressed={selected}
            onClick={() => onChange(option.value)}
            className={[
              'ui-control rounded-sm px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-40',
              selected
                ? 'bg-accent-info/14 text-accent-info'
                : 'text-text-secondary hover:text-text-primary',
            ].join(' ')}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
