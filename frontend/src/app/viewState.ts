export const APP_VIEWS = [
  'arena',
  'results',
  'history',
  'leaderboard',
  'settings',
] as const

export type AppView = (typeof APP_VIEWS)[number]

const VIEW_SET = new Set<string>(APP_VIEWS)

export function appViewFromPath(pathname: string): AppView {
  const normalized = pathname.trim().replace(/\/+/g, '/')
  if (normalized === '' || normalized === '/') return 'arena'
  const first = normalized.replace(/^\//, '').split('/')[0]
  if (VIEW_SET.has(first)) return first as AppView
  return 'arena'
}

export function appPathForView(view: AppView): string {
  return view === 'arena' ? '/arena' : `/${view}`
}

export function appViewLabel(view: AppView): string {
  switch (view) {
    case 'arena':
      return 'Arena'
    case 'results':
      return 'Results'
    case 'history':
      return 'History'
    case 'leaderboard':
      return 'Leaderboard'
    case 'settings':
      return 'Settings'
  }
}
