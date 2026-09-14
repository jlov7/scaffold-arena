import type { ButtonHTMLAttributes, ReactNode } from 'react'

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string
  children: ReactNode
}

export function IconButton({
  label,
  children,
  className = '',
  ...props
}: IconButtonProps) {
  return (
    <button
      {...props}
      type={props.type ?? 'button'}
      aria-label={label}
      title={props.title ?? label}
      className={[
        'ui-control inline-flex h-11 w-11 items-center justify-center rounded-md border border-border bg-bg-primary text-text-secondary hover:border-border-hover hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-40 sm:h-9 sm:w-9',
        className,
      ].join(' ')}
    >
      {children}
    </button>
  )
}
