import { useEffect, useRef, useState, useMemo } from 'react'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface SimNode {
  id: string
  x: number
  y: number
  vx: number
  vy: number
  r: number
  label: string
}

interface SimEdge {
  source: number
  target: number
}

interface ConstellationDebugState {
  dpr: number
  canvas: { w: number; h: number }
  css: { w: number; h: number }
  nodes: Array<{ id: string; x: number; y: number; r: number }>
  overlaps: Array<{ a: string; b: string; distance: number; minDistance: number }>
  clipped: Array<{ id: string; reason: string }>
  seed: number
  ticks: number
  settled: boolean
}

declare global {
  interface Window {
    __READY?: boolean
    __constellationDebug?: () => ConstellationDebugState
  }
}

declare const __GIT_SHA__: string

/* ------------------------------------------------------------------ */
/*  Seeded PRNG — mulberry32                                           */
/* ------------------------------------------------------------------ */

function mulberry32(seed: number): () => number {
  let s = seed | 0
  return () => {
    s = (s + 0x6d2b79f5) | 0
    let t = Math.imul(s ^ (s >>> 15), 1 | s)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/* ------------------------------------------------------------------ */
/*  Graph generation                                                   */
/* ------------------------------------------------------------------ */

const NODE_LABELS = [
  'Planner',
  'Executor',
  'Critic',
  'Memory',
  'Router',
  'Retriever',
  'Summarizer',
  'Validator',
]

function generateGraph(
  rng: () => number,
  width: number,
  height: number,
): { nodes: SimNode[]; edges: SimEdge[] } {
  const pad = 80
  const nodes: SimNode[] = NODE_LABELS.map((label, i) => ({
    id: `node-${i}`,
    x: pad + rng() * (width - 2 * pad),
    y: pad + rng() * (height - 2 * pad),
    vx: 0,
    vy: 0,
    r: 20 + rng() * 15,
    label,
  }))

  const edgeSet = new Set<string>()
  const edges: SimEdge[] = []
  for (let i = 0; i < nodes.length; i++) {
    const count = 1 + Math.floor(rng() * 2)
    for (let e = 0; e < count; e++) {
      const j = Math.floor(rng() * nodes.length)
      if (j !== i) {
        const lo = Math.min(i, j)
        const hi = Math.max(i, j)
        const key = `${lo}-${hi}`
        if (!edgeSet.has(key)) {
          edgeSet.add(key)
          edges.push({ source: lo, target: hi })
        }
      }
    }
  }

  return { nodes, edges }
}

/* ------------------------------------------------------------------ */
/*  Force simulation                                                   */
/* ------------------------------------------------------------------ */

const REPULSION = 8000
const SPRING_K = 0.005
const SPRING_REST = 120
const CENTER_GRAVITY = 0.01
const DAMPING = 0.9
const SETTLE_THRESHOLD = 0.1

function simTick(
  nodes: SimNode[],
  edges: SimEdge[],
  cx: number,
  cy: number,
): void {
  // Coulomb repulsion between all pairs
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const dx = nodes[j].x - nodes[i].x
      const dy = nodes[j].y - nodes[i].y
      const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
      const force = REPULSION / (dist * dist)
      const fx = (dx / dist) * force
      const fy = (dy / dist) * force
      nodes[i].vx -= fx
      nodes[i].vy -= fy
      nodes[j].vx += fx
      nodes[j].vy += fy
    }
  }

  // Spring attraction along edges
  for (const edge of edges) {
    const a = nodes[edge.source]
    const b = nodes[edge.target]
    const dx = b.x - a.x
    const dy = b.y - a.y
    const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
    const displacement = dist - SPRING_REST
    const force = SPRING_K * displacement
    const fx = (dx / dist) * force
    const fy = (dy / dist) * force
    a.vx += fx
    a.vy += fy
    b.vx -= fx
    b.vy -= fy
  }

  // Center gravity
  for (const node of nodes) {
    node.vx += (cx - node.x) * CENTER_GRAVITY
    node.vy += (cy - node.y) * CENTER_GRAVITY
  }

  // Integrate velocity + apply damping
  for (const node of nodes) {
    node.vx *= DAMPING
    node.vy *= DAMPING
    node.x += node.vx
    node.y += node.vy
  }
}

function kineticEnergy(nodes: SimNode[]): number {
  let energy = 0
  for (const n of nodes) {
    energy += n.vx * n.vx + n.vy * n.vy
  }
  return energy
}

/* ------------------------------------------------------------------ */
/*  Debug state                                                        */
/* ------------------------------------------------------------------ */

function computeDebugState(
  nodes: SimNode[],
  canvasEl: HTMLCanvasElement,
  seed: number,
  tickCount: number,
  settled: boolean,
): ConstellationDebugState {
  const dpr = window.devicePixelRatio || 1
  const rect = canvasEl.getBoundingClientRect()

  const overlaps: ConstellationDebugState['overlaps'] = []
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const dx = nodes[j].x - nodes[i].x
      const dy = nodes[j].y - nodes[i].y
      const distance = Math.sqrt(dx * dx + dy * dy)
      const minDistance = nodes[i].r + nodes[j].r
      if (distance < minDistance) {
        overlaps.push({
          a: nodes[i].id,
          b: nodes[j].id,
          distance: Math.round(distance * 100) / 100,
          minDistance: Math.round(minDistance * 100) / 100,
        })
      }
    }
  }

  const clipped: ConstellationDebugState['clipped'] = []
  for (const node of nodes) {
    if (node.x - node.r < 0) clipped.push({ id: node.id, reason: 'left' })
    if (node.y - node.r < 0) clipped.push({ id: node.id, reason: 'top' })
    if (node.x + node.r > rect.width) clipped.push({ id: node.id, reason: 'right' })
    if (node.y + node.r > rect.height) clipped.push({ id: node.id, reason: 'bottom' })
  }

  return {
    dpr,
    canvas: { w: canvasEl.width, h: canvasEl.height },
    css: { w: rect.width, h: rect.height },
    nodes: nodes.map((n) => ({
      id: n.id,
      x: Math.round(n.x * 100) / 100,
      y: Math.round(n.y * 100) / 100,
      r: Math.round(n.r * 100) / 100,
    })),
    overlaps,
    clipped,
    seed,
    ticks: tickCount,
    settled,
  }
}

/* ------------------------------------------------------------------ */
/*  Canvas rendering                                                   */
/* ------------------------------------------------------------------ */

function draw(
  ctx: CanvasRenderingContext2D,
  nodes: SimNode[],
  edges: SimEdge[],
  showDebug: boolean,
  width: number,
  height: number,
): void {
  ctx.clearRect(0, 0, width, height)
  ctx.fillStyle = '#0a0a0f'
  ctx.fillRect(0, 0, width, height)

  // Edges
  ctx.strokeStyle = '#2a2a3e'
  ctx.lineWidth = 1.5
  for (const edge of edges) {
    const a = nodes[edge.source]
    const b = nodes[edge.target]
    ctx.beginPath()
    ctx.moveTo(a.x, a.y)
    ctx.lineTo(b.x, b.y)
    ctx.stroke()
  }

  // Nodes
  for (const node of nodes) {
    ctx.beginPath()
    ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2)
    ctx.fillStyle = '#1a1a2e'
    ctx.fill()
    ctx.strokeStyle = '#10b981'
    ctx.lineWidth = 2
    ctx.stroke()

    // Label
    ctx.fillStyle = '#e8e8f0'
    ctx.font = '11px "JetBrains Mono", ui-monospace, monospace'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(node.label, node.x, node.y)

    // Debug: bounding box + anchor
    if (showDebug) {
      ctx.strokeStyle = 'rgba(245, 158, 11, 0.5)'
      ctx.lineWidth = 1
      ctx.setLineDash([3, 3])
      ctx.strokeRect(node.x - node.r, node.y - node.r, node.r * 2, node.r * 2)
      ctx.setLineDash([])

      ctx.fillStyle = '#ef4444'
      ctx.beginPath()
      ctx.arc(node.x, node.y, 2, 0, Math.PI * 2)
      ctx.fill()
    }
  }
}

/* ------------------------------------------------------------------ */
/*  Query param parsing                                                */
/* ------------------------------------------------------------------ */

function parseTestParams(): {
  seed: number
  isStatic: boolean
  maxTicks: number
  showDebug: boolean
} {
  const params = new URLSearchParams(window.location.search)
  return {
    seed: parseInt(params.get('seed') ?? '0', 10) || Date.now(),
    isStatic: params.get('static') === '1',
    maxTicks: parseInt(params.get('ticks') ?? '300', 10),
    showDebug: params.get('debug') === '1',
  }
}

/* ------------------------------------------------------------------ */
/*  React component                                                    */
/* ------------------------------------------------------------------ */

export default function Constellation() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [watermark, setWatermark] = useState('')
  const testParams = useMemo(parseTestParams, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const { seed, isStatic, maxTicks, showDebug } = testParams
    const rng = mulberry32(seed)
    const dpr = window.devicePixelRatio || 1

    // Size canvas to viewport, accounting for DPR
    const rect = canvas.getBoundingClientRect()
    canvas.width = Math.round(rect.width * dpr)
    canvas.height = Math.round(rect.height * dpr)

    const ctx = canvas.getContext('2d')!
    ctx.scale(dpr, dpr)

    const { nodes, edges } = generateGraph(rng, rect.width, rect.height)
    const cx = rect.width / 2
    const cy = rect.height / 2

    const finalize = (tickCount: number, settled: boolean) => {
      draw(ctx, nodes, edges, showDebug, rect.width, rect.height)
      const debugState = computeDebugState(nodes, canvas, seed, tickCount, settled)
      window.__constellationDebug = () => debugState
      window.__READY = true

      const sha = typeof __GIT_SHA__ !== 'undefined' ? __GIT_SHA__ : 'dev'
      setWatermark(
        `SHA:${sha} | ${Math.round(rect.width)}x${Math.round(rect.height)} | DPR:${dpr} | seed:${seed} | ticks:${tickCount}`,
      )
    }

    if (isStatic) {
      // Synchronous: run all ticks immediately, render once
      let tickCount = 0
      let settled = false
      for (let t = 0; t < maxTicks; t++) {
        simTick(nodes, edges, cx, cy)
        tickCount++
        if (kineticEnergy(nodes) < SETTLE_THRESHOLD) {
          settled = true
          break
        }
      }
      if (!settled) settled = true // ran all ticks — treat as settled
      finalize(tickCount, settled)
    } else {
      // Animated: requestAnimationFrame loop
      let tickCount = 0
      let raf: number
      const animate = () => {
        simTick(nodes, edges, cx, cy)
        tickCount++
        const energy = kineticEnergy(nodes)
        if (energy < SETTLE_THRESHOLD || tickCount >= maxTicks) {
          finalize(tickCount, true)
          return
        }
        draw(ctx, nodes, edges, showDebug, rect.width, rect.height)
        raf = requestAnimationFrame(animate)
      }
      raf = requestAnimationFrame(animate)
      return () => cancelAnimationFrame(raf)
    }
  }, [testParams])

  return (
    <div
      id="constellation-root"
      style={{
        position: 'fixed',
        inset: 0,
        background: '#0a0a0f',
        overflow: 'hidden',
      }}
    >
      <canvas
        id="constellation"
        ref={canvasRef}
        style={{ width: '100%', height: '100%', display: 'block' }}
      />
      {testParams.showDebug && watermark && (
        <div
          id="constellation-watermark"
          data-testid="watermark"
          style={{
            position: 'absolute',
            bottom: 8,
            left: 8,
            fontFamily: '"JetBrains Mono", ui-monospace, monospace',
            fontSize: '10px',
            color: 'rgba(232, 232, 240, 0.5)',
            background: 'rgba(10, 10, 15, 0.8)',
            padding: '4px 8px',
            borderRadius: '4px',
            pointerEvents: 'none',
            zIndex: 10,
          }}
        >
          {watermark}
        </div>
      )}
    </div>
  )
}
