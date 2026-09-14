import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { globSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'

const sourceFiles = globSync('src/**/*.{ts,tsx}', { cwd: process.cwd() })
const forbiddenBuildToken = ['VITE', 'API', 'TOKEN'].join('_')

test('frontend source has no build-time API token support', () => {
  const source = sourceFiles
    .map((file) => readFileSync(join(process.cwd(), file), 'utf8'))
    .join('\n')

  assert.equal(source.includes(forbiddenBuildToken), false)
})

test('built frontend does not contain a build-time API token marker', () => {
  const dist = join(process.cwd(), 'dist')
  if (!existsSync(dist)) return
  const built = globSync('**/*.*', { cwd: dist })
    .map((file) => readFileSync(join(dist, file), 'utf8'))
    .join('\n')

  assert.equal(built.includes(forbiddenBuildToken), false)
})
