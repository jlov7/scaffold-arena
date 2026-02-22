import type { ButtonHTMLAttributes, ReactNode } from 'react'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  tone?: 'primary' | 'secondary' | 'danger'
  children: ReactNode
}

export function Button({ tone = 'secondary', className = '', children, ...props }: ButtonProps) {
  const toneClass =
    tone === 'primary'
      ? 'border-accent-info bg-accent-info text-bg-primary hover:opacity-90'
      : tone === 'danger'
        ? 'border-accent-loser bg-accent-loser text-white hover:opacity-90'
        : 'border-border bg-bg-primary text-text-secondary hover:border-accent-info hover:text-accent-info'

  return (
    <button
      {...props}
      className={[
        'ui-control rounded border px-3 py-1.5 text-xs font-mono disabled:cursor-not-allowed disabled:opacity-40',
        toneClass,
        className,
      ].join(' ')}
    >
      {children}
    </button>
  )
}
