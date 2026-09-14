import type { ButtonHTMLAttributes, ReactNode } from 'react'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  tone?: 'primary' | 'secondary' | 'danger' | 'ghost'
  children: ReactNode
}

export function Button({ tone = 'secondary', className = '', children, ...props }: ButtonProps) {
  const toneClass =
    tone === 'primary'
      ? 'lab-button-primary'
      : tone === 'danger'
        ? 'border-accent-loser bg-accent-loser/12 text-accent-loser hover:bg-accent-loser/18'
        : tone === 'ghost'
          ? 'border-transparent bg-transparent text-text-secondary hover:border-border hover:text-text-primary'
          : 'lab-button-secondary'

  return (
    <button
      {...props}
      className={[
        'ui-control inline-flex min-h-9 items-center justify-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-40',
        toneClass,
        className,
      ].join(' ')}
    >
      {children}
    </button>
  )
}
