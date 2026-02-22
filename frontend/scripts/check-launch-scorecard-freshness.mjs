import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

const frontendDir = resolve(import.meta.dirname, '..')
const repoDir = resolve(frontendDir, '..')
const scorecardPath = join(repoDir, 'docs', 'reviews', 'frontend-panel-scorecard.md')

const MAX_AGE_DAYS = Number(process.env.SCORECARD_MAX_AGE_DAYS ?? '14')

const raw = readFileSync(scorecardPath, 'utf8')
const dateMatch = raw.match(/Date:\s*(\d{4}-\d{2}-\d{2})/)

if (!dateMatch) {
  console.error(`Launch scorecard freshness check failed: missing Date field in ${scorecardPath}`)
  process.exit(1)
}

const scorecardDate = new Date(`${dateMatch[1]}T00:00:00Z`)
const now = new Date()
const ageMs = now.getTime() - scorecardDate.getTime()
const ageDays = Math.floor(ageMs / (1000 * 60 * 60 * 24))

if (ageDays > MAX_AGE_DAYS) {
  console.error(
    `Launch scorecard freshness check failed: ${dateMatch[1]} is ${ageDays} days old (max ${MAX_AGE_DAYS}).`,
  )
  process.exit(1)
}

console.log(
  `Launch scorecard freshness check passed: ${dateMatch[1]} (${ageDays} days old, max ${MAX_AGE_DAYS}).`,
)
