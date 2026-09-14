import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('app architecture boundaries', () => {
  it('keeps protocol-v1 routing and legacy loading in separate route chunks', () => {
    const appPath = resolve(process.cwd(), 'src/App.tsx')
    const appCode = readFileSync(appPath, 'utf8')
    const mainPath = resolve(process.cwd(), 'src/main.tsx')
    const mainCode = readFileSync(mainPath, 'utf8')

    expect(mainCode).toContain("import('./workbench-v1/WorkbenchV1App')")
    expect(mainCode).toContain("const LegacyApp = lazy(() => import('./App'))")
    expect(mainCode).toContain("pathname === '/' || pathname.startsWith('/workbench/')")
    expect(appCode).not.toContain('WorkbenchV1App')
    expect(appCode).toContain('export default function LegacyApp()')
  })

  it('routes history and leaderboard through workspace containers', () => {
    const appPath = resolve(process.cwd(), 'src/App.tsx')
    const appCode = readFileSync(appPath, 'utf8')

    expect(appCode).toContain('HistoryWorkspace')
    expect(appCode).toContain('LeaderboardWorkspace')
    expect(appCode).toContain("from './features/workspaces/HistoryWorkspace'")
    expect(appCode).toContain("from './features/workspaces/LeaderboardWorkspace'")
  })

  it('centralizes next-action resolution in journey module', () => {
    const appPath = resolve(process.cwd(), 'src/App.tsx')
    const appCode = readFileSync(appPath, 'utf8')

    expect(appCode).toContain('resolveNextActionKey')
    expect(appCode).toContain('buildNextActionCopy')
    expect(appCode).not.toContain("type NextActionKey =")
  })

  it('delegates report, comparison, autopsy, and history orchestration to feature hooks', () => {
    const appPath = resolve(process.cwd(), 'src/App.tsx')
    const appCode = readFileSync(appPath, 'utf8')

    expect(appCode).toContain("from './features/comparison/useComparison'")
    expect(appCode).toContain("from './features/autopsy/useAutopsy'")
    expect(appCode).toContain("from './features/history/useRunHistory'")
    expect(appCode).toContain("from './features/reporting/useReportExports'")
    expect(appCode).not.toContain('createComparison,')
    expect(appCode).not.toContain('generateReport,')
    expect(appCode).not.toContain('fetchRunDetails,')
  })
})
