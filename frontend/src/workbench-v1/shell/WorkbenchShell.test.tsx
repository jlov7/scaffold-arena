import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { SevereFailureBanner, StatusIndicator, WorkbenchButton } from '../design-system'
import { WorkbenchShell } from './WorkbenchShell'
import type { WorkbenchArea, WorkbenchMode } from './types'

function ShellHarness({ onNavigate = vi.fn() }: { onNavigate?: (area: WorkbenchArea) => void }) {
  const [area, setArea] = useState<WorkbenchArea>('studies')
  const [mode, setMode] = useState<WorkbenchMode>('guided')
  return <WorkbenchShell
    activeArea={area}
    onNavigate={(next) => { setArea(next); onNavigate(next) }}
    mode={mode}
    onModeChange={setMode}
    studyLabel="Genome conformance fixture"
    specLabel="spec_v1.0.0"
    statuses={[{ label: 'Adapters', value: '3 / 3', tone: 'ready' }, { label: 'Workers', value: '24 / 24', tone: 'ready' }]}
    evidence={<section><h2>Evidence record</h2><p>Custody and integrity only.</p><WorkbenchButton>Inspect artifact</WorkbenchButton><details><summary>Evidence limitation</summary><p>Unknown values remain unknown.</p></details></section>}
  ><p>One shared content slot.</p></WorkbenchShell>
}

describe('WorkbenchShell', () => {
  it('selects a decision job through stable Guided navigation', () => {
    const onNavigate = vi.fn()
    render(<ShellHarness onNavigate={onNavigate} />)

    fireEvent.click(screen.getAllByRole('button', { name: 'Improve' })[0])

    expect(onNavigate).toHaveBeenCalledWith('improve')
    expect(screen.getAllByRole('button', { name: 'Improve' })[0]).toHaveAttribute('aria-current', 'page')
  })

  it('switches Guided and Lab over the same stage slot', () => {
    render(<ShellHarness />)

    fireEvent.click(screen.getByRole('button', { name: 'Lab' }))

    expect(screen.getByRole('button', { name: 'Lab' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getAllByRole('button', { name: 'Design' }).length).toBeGreaterThan(0)
    expect(screen.getByText('One shared content slot.')).toBeInTheDocument()
  })

  it('exposes the semantic workbench landmarks', () => {
    render(<ShellHarness />)

    expect(screen.getByRole('banner', { name: /command and status/i })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Workbench areas' })).toBeInTheDocument()
    expect(screen.getByRole('main')).toBeInTheDocument()
    expect(screen.getByRole('complementary', { name: 'Evidence inspector' })).toBeInTheDocument()
  })

  it('opens the evidence drawer, traps initial focus, and restores focus after Escape', async () => {
    render(<ShellHarness />)
    const opener = screen.getByRole('button', { name: 'Open evidence and specification' })

    fireEvent.click(opener)
    const dialog = screen.getByRole('dialog', { name: 'Evidence and specification' })
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
    expect(document.querySelector('.sa-shell')).toHaveAttribute('inert')
    expect(document.body).toHaveStyle({ overflow: 'hidden' })

    const close = screen.getByRole('button', { name: 'Close' })
    const limitation = dialog.querySelector('summary')!
    fireEvent.keyDown(close, { key: 'Tab', shiftKey: true })
    expect(limitation).toHaveFocus()
    fireEvent.keyDown(limitation, { key: 'Tab' })
    expect(close).toHaveFocus()

    fireEvent.keyDown(dialog, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'Evidence and specification' })).not.toBeInTheDocument()
    await waitFor(() => expect(opener).toHaveFocus())
    expect(document.querySelector('.sa-shell')).not.toHaveAttribute('inert')
  })

  it('closes the mobile More menu with Escape', () => {
    render(<ShellHarness />)
    const more = screen.getByRole('button', { name: 'More' })

    fireEvent.click(more)
    expect(more).toHaveAttribute('aria-expanded', 'true')
    const menu = document.getElementById('workbench-more-menu')
    expect(menu).toBeInTheDocument()
    fireEvent.keyDown(menu!, { key: 'Escape' })

    expect(more).toHaveAttribute('aria-expanded', 'false')
    expect(more).toHaveFocus()
  })
})

describe('design-system status and failure primitives', () => {
  it('pairs every status color with readable text and an icon', () => {
    render(<StatusIndicator tone="failure">Preflight incomplete</StatusIndicator>)
    expect(screen.getByText('Preflight incomplete')).toBeInTheDocument()
    expect(screen.getByText('Preflight incomplete').querySelector('svg')).toBeInTheDocument()
  })

  it('keeps the severe-failure next action available', () => {
    const resolve = vi.fn()
    render(<SevereFailureBanner title="Severe failures (2)" action={<WorkbenchButton onClick={resolve}>Resolve failures</WorkbenchButton>}>Execution remains blocked until failures are resolved.</SevereFailureBanner>)

    fireEvent.click(screen.getByRole('button', { name: 'Resolve failures' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Execution remains blocked')
    expect(resolve).toHaveBeenCalledOnce()
  })
})
