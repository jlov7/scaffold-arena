import { StrictMode, Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/geist/index.css'
import '@fontsource-variable/geist-mono/index.css'
import './styles/theme.css'
import App from './App'
import { initWebVitals } from './perf/webVitals'

const Constellation = lazy(() => import('./components/Constellation'))
const isConstellationRoute = window.location.pathname === '/constellation'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {isConstellationRoute ? (
      <Suspense fallback={null}>
        <Constellation />
      </Suspense>
    ) : (
      <App />
    )}
  </StrictMode>,
)

void initWebVitals()
