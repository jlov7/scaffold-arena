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
        'lab-panel p-4',
        className,
      ].join(' ')}
    >
      {title && (
        <div className="lab-label mb-2">
          {title}
        </div>
      )}
      {children}
    </section>
  )
}
