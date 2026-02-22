const args = process.argv.slice(2).filter((arg) => arg !== '--')
const arg = args[0]

if (!arg || arg === '--help' || arg === '-h') {
  console.log('Usage: pnpm smoke:prod -- <base_url>')
  console.log('Example: pnpm smoke:prod -- https://scaffold-arena.example')
  process.exit(0)
}

const base = arg.replace(/\/$/, '')

async function check(url, label) {
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error(`${label} failed: ${res.status} ${res.statusText}`)
  }
  return res
}

try {
  await check(`${base}/`, 'Homepage')
  await check(`${base}/api/health`, 'API health')
  await check(`${base}/api/meta`, 'API meta')
  console.log('Production smoke checks passed.')
} catch (error) {
  console.error('Production smoke checks failed.')
  console.error(error instanceof Error ? error.message : String(error))
  process.exit(1)
}
