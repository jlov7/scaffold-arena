interface LiveRegionProps {
  message: string | null
  priority?: 'polite' | 'assertive'
}

export default function LiveRegion({
  message,
  priority = 'polite',
}: LiveRegionProps) {
  if (!message) return null

  return (
    <div
      className="sr-only"
      role={priority === 'assertive' ? 'alert' : 'status'}
      aria-live={priority}
      aria-atomic="true"
    >
      {message}
    </div>
  )
}
