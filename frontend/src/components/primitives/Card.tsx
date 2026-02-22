import type { HTMLAttributes, ReactNode } from 'react'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  title?: string
  children: ReactNode
}

export function Card({ title, children, className = '', ...props }: CardProps) {
  return (
    <section
      {...props}
      className={[
        'rounded-lg border border-border bg-bg-secondary p-4 shadow-[var(--elevation-1)]',
        className,
      ].join(' ')}
    >
      {title && (
        <div className="mb-2 text-[10px] uppercase tracking-widest text-text-secondary">
          {title}
        </div>
      )}
      {children}
    </section>
  )
}
