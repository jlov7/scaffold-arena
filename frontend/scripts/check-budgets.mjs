import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const distDir = fileURLToPath(new URL('../dist', import.meta.url))
const assetsDir = join(distDir, 'assets')

const files = readdirSync(assetsDir)
const jsFiles = files.filter((name) => name.endsWith('.js'))
const cssFiles = files.filter((name) => name.endsWith('.css'))
const htmlPath = join(distDir, 'index.html')

const limits = {
  jsBytes: 372_000,
  cssBytes: 52_000,
  htmlBytes: 5_000,
}

let jsTotal = 0
for (const file of jsFiles) {
  jsTotal += statSync(join(assetsDir, file)).size
}

let cssTotal = 0
for (const file of cssFiles) {
  cssTotal += statSync(join(assetsDir, file)).size
}

const htmlBytes = Buffer.byteLength(readFileSync(htmlPath, 'utf8'), 'utf8')

const violations = []
if (jsTotal > limits.jsBytes) {
  violations.push(`JS budget exceeded: ${jsTotal} > ${limits.jsBytes}`)
}
if (cssTotal > limits.cssBytes) {
  violations.push(`CSS budget exceeded: ${cssTotal} > ${limits.cssBytes}`)
}
if (htmlBytes > limits.htmlBytes) {
  violations.push(`HTML budget exceeded: ${htmlBytes} > ${limits.htmlBytes}`)
}

if (violations.length > 0) {
  console.error('Performance budget check failed:')
  for (const violation of violations) {
    console.error(`- ${violation}`)
  }
  process.exit(1)
}

console.log('Performance budget check passed.')
console.log(`- JS: ${jsTotal}/${limits.jsBytes}`)
console.log(`- CSS: ${cssTotal}/${limits.cssBytes}`)
console.log(`- HTML: ${htmlBytes}/${limits.htmlBytes}`)
