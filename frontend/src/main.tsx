import { StrictMode, Suspense, lazy, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/fonts.css'
import './styles/theme.css'

const Constellation = lazy(() => import('./components/Constellation'))
const WorkbenchV1App = lazy(() =>
  import('./workbench-v1/WorkbenchV1App').then(({ WorkbenchV1App }) => ({
    default: WorkbenchV1App,
  })),
)
const LegacyApp = lazy(() => import('./App'))

export function AppRoute() {
  const [pathname, setPathname] = useState(() => window.location.pathname)

  useEffect(() => {
    const sync = () => setPathname(window.location.pathname)
    window.addEventListener('popstate', sync)
    return () => window.removeEventListener('popstate', sync)
  }, [])

  if (pathname === '/constellation') return <Constellation />
  if (pathname === '/' || pathname.startsWith('/workbench/')) {
    return <WorkbenchV1App />
  }
  return <LegacyApp />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Suspense fallback={null}>
      <AppRoute />
    </Suspense>
  </StrictMode>,
)
