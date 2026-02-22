import type { SelectHTMLAttributes } from 'react'

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={[
        'ui-control w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs text-text-primary',
        props.className ?? '',
      ].join(' ')}
    />
  )
}
