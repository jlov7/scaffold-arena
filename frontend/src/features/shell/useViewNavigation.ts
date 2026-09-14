import { useCallback, useEffect, useState } from 'react'

import {
  appPathForView,
  appViewFromPath,
  type AppView,
} from '../../app/viewState'

const VIEW_STORAGE_KEY = 'scaffold_arena_last_view'

export function useViewNavigation() {
  const [activeView, setActiveView] = useState<AppView>(() => {
    let pathname = window.location.pathname
    const search = window.location.search

    if (pathname === '/') {
      const nextPath = `${appPathForView('arena')}${search}`
      window.history.replaceState({}, '', nextPath)
      pathname = appPathForView('arena')
    }

    try {
      const stored = localStorage.getItem(VIEW_STORAGE_KEY)
      if (stored) {
        const restored = appViewFromPath(stored)
        const params = new URLSearchParams(search)
        if (restored !== 'arena' && !params.get('run_id')) {
          const nextPath = `${appPathForView(restored)}${search}`
          window.history.replaceState({}, '', nextPath)
          pathname = appPathForView(restored)
        }
      }
    } catch {
      // storage unavailable
    }

    return appViewFromPath(pathname)
  })

  useEffect(() => {
    const onPopState = () => {
      setActiveView(appViewFromPath(window.location.pathname))
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const navigateToView = useCallback((view: AppView) => {
    setActiveView(view)
    const nextPath = `${appPathForView(view)}${window.location.search}`
    window.history.pushState({}, '', nextPath)
  }, [])

  useEffect(() => {
    try {
      localStorage.setItem(VIEW_STORAGE_KEY, appPathForView(activeView))
    } catch {
      // storage unavailable
    }
  }, [activeView])

  return {
    activeView,
    setActiveView,
    navigateToView,
  }
}
