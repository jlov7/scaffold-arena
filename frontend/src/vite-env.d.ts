/// <reference types="vite/client" />

declare const __APP_VERSION__: string
declare const __GIT_SHA__: string

interface Window {
  __arenaTelemetryEvents?: Array<{
    name: string
    ts_ms: number
    payload: Record<string, unknown>
  }>
  __READY?: boolean
  __constellationDebug?: () => {
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
}
