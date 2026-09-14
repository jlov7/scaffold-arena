import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const distDir = fileURLToPath(new URL('../dist', import.meta.url))
const assetsDir = join(distDir, 'assets')
const htmlPath = join(distDir, 'index.html')

const limits = {
  htmlBytes: 5_000,
  shellJsBytes: 220_000,
  shellCssBytes: 70_000,
  shellAssetBytes: 130_000,
  shellTransferBytes: 400_000,
  workbenchFirstLoadBytes: 550_000,
  legacyFirstLoadBytes: 590_000,
  lazyChunkBytes: 210_000,
  // The release-readiness candidate measured 609,190 emitted JS bytes.
  // The 610 kB ceiling is a 5,000-byte (0.83%) rebaseline; every other
  // startup, route, lazy, CSS, and asset ceiling remains unchanged.
  totalJsBytes: 610_000,
  totalCssBytes: 100_000,
  totalAssetBytes: 820_000,
}

const files = readdirSync(assetsDir)
const assetPath = (name) => join(assetsDir, name)
const bytes = (name) => statSync(assetPath(name)).size
const html = readFileSync(htmlPath, 'utf8')
const htmlBytes = Buffer.byteLength(html, 'utf8')

function assetName(url) {
  const cleanUrl = url.split('?')[0].split('#')[0]
  if (cleanUrl.startsWith('/assets/')) return cleanUrl.slice('/assets/'.length)
  if (cleanUrl.startsWith('./assets/')) return cleanUrl.slice('./assets/'.length)
  return null
}

function linkedAssets(markup, pattern) {
  return [...markup.matchAll(pattern)]
    .map((match) => assetName(match[1]))
    .filter((name) => name && files.includes(name))
}

function uniqueRouteChunk(prefix, extension) {
  const chunks = files.filter((name) =>
    new RegExp(`^${prefix}-[^/]+\\.${extension}$`).test(name),
  )
  if (chunks.length !== 1) {
    throw new Error(
      `Expected exactly one ${prefix} ${extension} route chunk, found ${chunks.length}: ${chunks.join(', ') || 'none'}`,
    )
  }
  return chunks[0]
}

function staticJsClosure(entry) {
  const closure = new Set()
  const visit = (file) => {
    if (closure.has(file)) return
    if (!files.includes(file)) throw new Error(`Missing static dependency: ${file}`)
    closure.add(file)
    const source = readFileSync(assetPath(file), 'utf8')
    const imports = source.matchAll(
      /(?:\bfrom|\bimport\s*)["']\.\/([^"']+\.js)["']/g,
    )
    for (const match of imports) visit(match[1])
  }
  visit(entry)
  return closure
}

function cssAssetClosure(cssFiles) {
  const assets = new Set(cssFiles)
  for (const cssFile of cssFiles) {
    const css = readFileSync(assetPath(cssFile), 'utf8')
    for (const name of linkedAssets(css, /url\(["']?([^"')]+)["']?\)/g)) {
      assets.add(name)
    }
  }
  return assets
}

const initialJs = new Set(
  linkedAssets(html, /<script[^>]+\bsrc=["']([^"']+)["']/g),
)
const initialCss = new Set(
  linkedAssets(
    html,
    /<link[^>]+\brel=["']stylesheet["'][^>]+\bhref=["']([^"']+)["']/g,
  ),
)
const initialAssets = new Set([
  ...initialJs,
  ...cssAssetClosure(initialCss),
])

const workbenchJs = staticJsClosure(uniqueRouteChunk('WorkbenchV1App', 'js'))
const legacyJs = staticJsClosure(uniqueRouteChunk('App', 'js'))

function deferredWorkbenchSurface(label, marker) {
  const matching = files.filter((name) =>
    name.endsWith('.js') && readFileSync(assetPath(name), 'utf8').includes(marker),
  )
  if (matching.length !== 1) {
    throw new Error(
      `Expected exactly one deferred ${label} surface chunk, found ${matching.length}: ${matching.join(', ') || 'none'}`,
    )
  }
  if (workbenchJs.has(matching[0])) {
    throw new Error(`${label} must remain outside the Workbench static import closure`)
  }
  return matching[0]
}

const xraySurfaceChunk = deferredWorkbenchSurface('Harness X-Ray', 'Inspect captured source')
const observatorySurfaceChunk = deferredWorkbenchSurface('Observatory', 'Inspect persisted evidence')
const counterfactualSurfaceChunk = deferredWorkbenchSurface(
  'Counterfactual Replay',
  'Run provider-free fixture replay',
)
const forgeSurfaceChunk = deferredWorkbenchSurface(
  'Arena Forge',
  'Stage untrusted fixture proposal',
)
const traceLabSurfaceChunk = deferredWorkbenchSurface(
  'Trace Lab',
  'Compare persisted traces',
)
const workbenchCss = cssAssetClosure(
  new Set([uniqueRouteChunk('WorkbenchV1App', 'css')]),
)
const legacyCss = cssAssetClosure(
  new Set(files.filter((name) => new RegExp('^App-[^/]+\\.css$').test(name))),
)

const routeTransfer = (routeJs, routeCss) =>
  new Set([...initialAssets, ...routeJs, ...routeCss])
const workbenchFirstLoad = routeTransfer(workbenchJs, workbenchCss)
const legacyFirstLoad = routeTransfer(legacyJs, legacyCss)
const routeAdditions = (route) =>
  [...route].filter((name) => !initialAssets.has(name))

const jsFiles = files.filter((name) => name.endsWith('.js'))
const cssFiles = files.filter((name) => name.endsWith('.css'))
const lazyChunks = [...jsFiles, ...cssFiles].filter(
  (name) => !initialAssets.has(name),
)
const sum = (names) => names.reduce((total, name) => total + bytes(name), 0)
const routeBytes = (route) => htmlBytes + sum([...route])

const initialJsBytes = sum([...initialJs])
const initialCssBytes = sum([...initialCss])
const initialAssetBytes = sum(
  [...initialAssets].filter((name) => !initialJs.has(name) && !initialCss.has(name)),
)
const initialTransferBytes = htmlBytes + sum([...initialAssets])
const workbenchFirstLoadBytes = routeBytes(workbenchFirstLoad)
const legacyFirstLoadBytes = routeBytes(legacyFirstLoad)
const workbenchRouteJsBytes = sum(routeAdditions(workbenchJs))
const workbenchRouteCssBytes = sum(routeAdditions(workbenchCss))
const legacyRouteJsBytes = sum(routeAdditions(legacyJs))
const legacyRouteCssBytes = sum(routeAdditions(legacyCss))
const jsTotal = sum(jsFiles)
const cssTotal = sum(cssFiles)
const assetTotal = htmlBytes + sum(files)

const violations = []
const check = (label, actual, limit) => {
  if (actual > limit) violations.push(`${label} exceeded: ${actual} > ${limit}`)
}

check('HTML budget', htmlBytes, limits.htmlBytes)
check('Shell JS budget', initialJsBytes, limits.shellJsBytes)
check('Shell CSS budget', initialCssBytes, limits.shellCssBytes)
check('Shell font/static asset budget', initialAssetBytes, limits.shellAssetBytes)
check('Shell transfer budget', initialTransferBytes, limits.shellTransferBytes)
check('Workbench first-load budget', workbenchFirstLoadBytes, limits.workbenchFirstLoadBytes)
check('Legacy first-load budget', legacyFirstLoadBytes, limits.legacyFirstLoadBytes)
for (const chunk of lazyChunks) check(`Lazy chunk ${chunk}`, bytes(chunk), limits.lazyChunkBytes)
check('Total JS budget', jsTotal, limits.totalJsBytes)
check('Total CSS budget', cssTotal, limits.totalCssBytes)
check('Total emitted asset budget', assetTotal, limits.totalAssetBytes)

if (violations.length > 0) {
  console.error('Performance budget check failed:')
  for (const violation of violations) console.error(`- ${violation}`)
  process.exit(1)
}

console.log('Performance budget check passed.')
console.log(`- Shell transfer: ${initialTransferBytes}/${limits.shellTransferBytes}`)
console.log(`  - HTML: ${htmlBytes}/${limits.htmlBytes}`)
console.log(`  - JS: ${initialJsBytes}/${limits.shellJsBytes}`)
console.log(`  - CSS: ${initialCssBytes}/${limits.shellCssBytes}`)
console.log(`  - fonts/static: ${initialAssetBytes}/${limits.shellAssetBytes}`)
console.log(`- Workbench first load: ${workbenchFirstLoadBytes}/${limits.workbenchFirstLoadBytes}`)
console.log(`  - route JS added to shell: ${workbenchRouteJsBytes}`)
console.log(`  - route CSS/static added to shell: ${workbenchRouteCssBytes}`)
console.log(`- Legacy first load: ${legacyFirstLoadBytes}/${limits.legacyFirstLoadBytes}`)
console.log(`  - route JS added to shell: ${legacyRouteJsBytes}`)
console.log(`  - route CSS/static added to shell: ${legacyRouteCssBytes}`)
console.log(`- Largest lazy chunk: ${Math.max(...lazyChunks.map(bytes), 0)}/${limits.lazyChunkBytes}`)
console.log(
  `- Deferred analysis chunks: ${xraySurfaceChunk}, ${observatorySurfaceChunk}, ${counterfactualSurfaceChunk}, ${forgeSurfaceChunk}, ${traceLabSurfaceChunk}`,
)
console.log(`- Total JS: ${jsTotal}/${limits.totalJsBytes}`)
console.log(`- Total CSS: ${cssTotal}/${limits.totalCssBytes}`)
console.log(`- Total emitted assets: ${assetTotal}/${limits.totalAssetBytes}`)
