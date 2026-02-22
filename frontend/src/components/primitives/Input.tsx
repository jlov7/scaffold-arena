import type { InputHTMLAttributes } from 'react'

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={[
        'ui-control w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs text-text-primary',
        props.className ?? '',
      ].join(' ')}
    />
  )
}
