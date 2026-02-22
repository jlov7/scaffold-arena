import { memo } from 'react'
import ArenaPanel from './ArenaPanel'
import ErrorBoundary from './ErrorBoundary'
import type { PanelState } from '../types'

interface ArenaGridProps {
  panels: PanelState[]
}

function ArenaGridComponent({ panels }: ArenaGridProps) {
  return (
    <div className="grid grid-cols-1 gap-4 items-stretch md:grid-cols-2 xl:grid-cols-2">
      {panels.map((panel) => (
        <ErrorBoundary key={panel.scaffoldId} panelLabel={panel.scaffoldName}>
          <ArenaPanel panel={panel} />
        </ErrorBoundary>
      ))}
    </div>
  )
}

const ArenaGrid = memo(
  ArenaGridComponent,
  (prev, next) => prev.panels === next.panels,
)

export default ArenaGrid
