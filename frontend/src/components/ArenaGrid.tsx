import ArenaPanel from './ArenaPanel'
import type { PanelState } from '../types'

interface ArenaGridProps {
  panels: PanelState[]
}

export default function ArenaGrid({ panels }: ArenaGridProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 items-stretch">
      {panels.map((panel) => (
        <ArenaPanel key={panel.scaffoldId} panel={panel} />
      ))}
    </div>
  )
}
