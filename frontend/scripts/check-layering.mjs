import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const violations = []

function listFiles(rootDir) {
  const out = []
  for (const entry of readdirSync(rootDir, { withFileTypes: true })) {
    const full = join(rootDir, entry.name)
    if (entry.isDirectory()) {
      out.push(...listFiles(full))
      continue
    }
    if (entry.isFile() && (full.endsWith('.ts') || full.endsWith('.tsx'))) {
      out.push(full)
    }
  }
  return out
}

function importsFrom(filePath) {
  const src = readFileSync(filePath, 'utf8')
  const matches = src.matchAll(/from\s+['"]([^'"]+)['"]/g)
  return Array.from(matches, (m) => m[1])
}

for (const file of listFiles('src/components/primitives')) {
  const imports = importsFrom(file)
  for (const imp of imports) {
    if (imp.includes('/features/') || imp.includes('/App')) {
      violations.push(`${file} imports disallowed higher layer: ${imp}`)
    }
  }
}

for (const file of listFiles('src/features')) {
  const imports = importsFrom(file)
  for (const imp of imports) {
    if (imp.includes('/App')) {
      violations.push(`${file} imports App shell directly: ${imp}`)
    }
  }
}

if (violations.length > 0) {
  console.error('Layering check failed:')
  for (const line of violations) {
    console.error(`- ${line}`)
  }
  process.exit(1)
}

console.log('Layering check passed.')
