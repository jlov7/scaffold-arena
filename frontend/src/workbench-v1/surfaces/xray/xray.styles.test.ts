import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('X-Ray responsive and motion guardrails', () => {
  const css = readFileSync(resolve(process.cwd(), 'src/workbench-v1/surfaces/xray/xray.css'), 'utf8')

  it('provides a narrow-screen layout and disables surface motion for reduced-motion users', () => {
    expect(css).toContain('@media (max-width: 720px)')
    expect(css).toContain('@media (prefers-reduced-motion: reduce)')
    expect(css).toContain('animation: none !important')
  })
})
