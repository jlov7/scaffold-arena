interface SkeletonProps {
  className?: string
}

export function Skeleton({ className = '' }: SkeletonProps) {
  return (
    <div
      aria-hidden="true"
      className={['skeleton-shimmer rounded-sm', className].join(' ')}
    />
  )
}
