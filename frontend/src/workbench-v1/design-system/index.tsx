import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Info,
  WifiOff,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import { forwardRef, type ButtonHTMLAttributes, type ReactNode, type TableHTMLAttributes } from 'react'

import './workbench.css'

export type StatusTone = 'ready' | 'info' | 'warning' | 'failure' | 'offline'

const statusIcons: Record<StatusTone, LucideIcon> = {
  ready: CheckCircle2,
  info: Info,
  warning: AlertTriangle,
  failure: XCircle,
  offline: WifiOff,
}

export function StatusIndicator({ tone, children }: { tone: StatusTone; children: ReactNode }) {
  const Icon = statusIcons[tone]
  return <span className="sa-status" data-tone={tone}><Icon aria-hidden="true" size={14} />{children}</span>
}

export const WorkbenchButton = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { tone?: 'primary' | 'secondary' | 'danger' }>(
  ({ tone = 'secondary', ...props }, ref) => <button ref={ref} {...props} className={`sa-button ${props.className ?? ''}`} data-tone={tone} />,
)
WorkbenchButton.displayName = 'WorkbenchButton'

export function WorkbenchPanel({ title, action, tone, children }: { title?: ReactNode; action?: ReactNode; tone?: 'default' | 'inset' | 'critical'; children: ReactNode }) {
  return <section className="sa-panel" data-tone={tone === 'default' ? undefined : tone}>
    {title && <header className="sa-panel-header"><h2 className="sa-panel-title">{title}</h2>{action}</header>}
    <div className="sa-panel-body">{children}</div>
  </section>
}

export function GuidedLabControl({ value, onChange }: { value: 'guided' | 'lab'; onChange: (value: 'guided' | 'lab') => void }) {
  return <div className="sa-segmented" aria-label="Workbench presentation">
    <button type="button" aria-pressed={value === 'guided'} onClick={() => onChange('guided')}>Guided</button>
    <button type="button" aria-pressed={value === 'lab'} onClick={() => onChange('lab')}>Lab</button>
  </div>
}

export function SevereFailureBanner({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <section className="sa-severe-banner" role="alert"><CircleAlert aria-hidden="true" size={20} /><div><strong>{title}</strong><p>{children}</p></div>{action}</section>
}

export function DisclosureRow({ title, children, open = false }: { title: ReactNode; children: ReactNode; open?: boolean }) {
  return <details className="sa-disclosure" open={open}><summary>{title}<ChevronDown aria-hidden="true" size={16} /></summary><div className="sa-disclosure-content">{children}</div></details>
}

export function WorkbenchTable(props: TableHTMLAttributes<HTMLTableElement>) {
  return <div className="sa-table-wrap" tabIndex={0} role="region" aria-label="Scrollable data table"><table {...props} className={`sa-data-table ${props.className ?? ''}`} /></div>
}

export function WorkbenchState({ kind, title, children, action }: { kind: 'loading' | 'empty' | 'error' | 'offline'; title: string; children: ReactNode; action?: ReactNode }) {
  const tone: StatusTone = kind === 'error' ? 'failure' : kind === 'offline' ? 'offline' : kind === 'loading' ? 'info' : 'warning'
  return <section className="sa-state" aria-live={kind === 'loading' ? 'polite' : undefined}><StatusIndicator tone={tone}>{kind}</StatusIndicator><h3>{title}</h3><p>{children}</p>{action}</section>
}
