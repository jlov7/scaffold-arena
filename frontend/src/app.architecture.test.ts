import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('app architecture boundaries', () => {
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
})
