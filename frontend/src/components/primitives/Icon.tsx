interface IconProps {
  name: 'play' | 'stop' | 'history' | 'leaderboard' | 'settings' | 'share' | 'download'
  className?: string
  title?: string
}

export function Icon({ name, className = 'h-3 w-3', title }: IconProps) {
  switch (name) {
    case 'play':
      return (
        <svg viewBox="0 0 16 16" className={className} aria-hidden={title ? undefined : true} role={title ? 'img' : undefined}>
          {title && <title>{title}</title>}
          <path fill="currentColor" d="M4 2.6 13 8l-9 5.4z" />
        </svg>
      )
    case 'stop':
      return (
        <svg viewBox="0 0 16 16" className={className} aria-hidden={title ? undefined : true} role={title ? 'img' : undefined}>
          {title && <title>{title}</title>}
          <rect x="3" y="3" width="10" height="10" fill="currentColor" />
        </svg>
      )
    case 'history':
      return (
        <svg viewBox="0 0 16 16" className={className} aria-hidden={title ? undefined : true} role={title ? 'img' : undefined}>
          {title && <title>{title}</title>}
          <path fill="currentColor" d="M8 2a6 6 0 1 1-5.66 4H1l2.5-2.5L6 6H4a4 4 0 1 0 4-4z" />
        </svg>
      )
    case 'leaderboard':
      return (
        <svg viewBox="0 0 16 16" className={className} aria-hidden={title ? undefined : true} role={title ? 'img' : undefined}>
          {title && <title>{title}</title>}
          <path fill="currentColor" d="M2 13h3V7H2zm4 0h3V3H6zm4 0h3V9h-3z" />
        </svg>
      )
    case 'settings':
      return (
        <svg viewBox="0 0 16 16" className={className} aria-hidden={title ? undefined : true} role={title ? 'img' : undefined}>
          {title && <title>{title}</title>}
          <path fill="currentColor" d="M9.5 1 10 3l1.6.6L13 2.4l1.1 1.1-1.2 1.4L13.5 6 16 6.5v1L13.5 8l-.6 1.6 1.2 1.4-1.1 1.1-1.4-1.2L10 13l-.5 2h-1L8 13l-1.6-.6L5 13.6l-1.1-1.1 1.2-1.4L4.5 8 2 7.5v-1L4.5 6l.6-1.6L3.9 3l1.1-1.1 1.4 1.2L8 3l.5-2zM8 6.2A1.8 1.8 0 1 0 8 9.8 1.8 1.8 0 0 0 8 6.2" />
        </svg>
      )
    case 'share':
      return (
        <svg viewBox="0 0 16 16" className={className} aria-hidden={title ? undefined : true} role={title ? 'img' : undefined}>
          {title && <title>{title}</title>}
          <path fill="currentColor" d="M11 1h4v4h-1.5V3.6l-4.2 4.2-1-1 4.2-4.2H11zM3 4h5v1.5H4.5v6h6V8H12v5H3z" />
        </svg>
      )
    case 'download':
      return (
        <svg viewBox="0 0 16 16" className={className} aria-hidden={title ? undefined : true} role={title ? 'img' : undefined}>
          {title && <title>{title}</title>}
          <path fill="currentColor" d="M7.2 2h1.6v6l2.2-2.2 1.1 1.1L8 11 3.9 6.9 5 5.8 7.2 8zM3 12h10v2H3z" />
        </svg>
      )
  }
}
