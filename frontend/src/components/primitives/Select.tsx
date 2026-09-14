import type { SelectHTMLAttributes } from 'react'

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={[
        'ui-control w-full rounded-md border border-border bg-bg-primary px-3 py-2 text-sm text-text-primary',
        props.className ?? '',
      ].join(' ')}
    />
  )
}
