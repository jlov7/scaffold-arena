import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, test } from 'vitest'

type ColorMap = Record<string, string>

function parseBlockColors(block: string): ColorMap {
  const matches = block.matchAll(
    /--color-([a-z-]+):\s*((?:#[0-9a-fA-F]{6})|(?:oklch\([^)]+\)))/g,
  )
  const colors: ColorMap = {}
  for (const match of matches) {
    colors[match[1]] = match[2].toLowerCase()
  }
  return colors
}

function parseThemeColors(css: string): { dark: ColorMap; light: ColorMap } {
  const darkMatch = css.match(/@theme\s*{([\s\S]*?)}/)
  const lightMatch = css.match(/:root\[data-theme='light']\s*{([\s\S]*?)}/)
  if (!darkMatch || !lightMatch) {
    throw new Error('Unable to parse color token blocks from theme.css')
  }
  return {
    dark: parseBlockColors(darkMatch[1]),
    light: parseBlockColors(lightMatch[1]),
  }
}

function channelToLinear(channel: number): number {
  const normalized = channel / 255
  return normalized <= 0.03928
    ? normalized / 12.92
    : ((normalized + 0.055) / 1.055) ** 2.4
}

interface LinearRgb {
  r: number
  g: number
  b: number
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value))
}

function hexToLinearRgb(hex: string): LinearRgb {
  const numeric = Number.parseInt(hex.replace('#', ''), 16)
  return {
    r: channelToLinear((numeric >> 16) & 255),
    g: channelToLinear((numeric >> 8) & 255),
    b: channelToLinear(numeric & 255),
  }
}

function oklchToLinearRgb(color: string): LinearRgb {
  const match = color.match(/oklch\(([\d.]+)%\s+([\d.]+)\s+([\d.]+)\)/)
  if (!match) throw new Error(`Unable to parse OKLCH color: ${color}`)

  const L = Number(match[1]) / 100
  const C = Number(match[2])
  const hRad = (Number(match[3]) * Math.PI) / 180
  const a = C * Math.cos(hRad)
  const b = C * Math.sin(hRad)

  const lPrime = L + 0.3963377774 * a + 0.2158037573 * b
  const mPrime = L - 0.1055613458 * a - 0.0638541728 * b
  const sPrime = L - 0.0894841775 * a - 1.291485548 * b

  const l = lPrime ** 3
  const m = mPrime ** 3
  const s = sPrime ** 3

  return {
    r: clamp01(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    g: clamp01(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    b: clamp01(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  }
}

function colorToLinearRgb(color: string): LinearRgb {
  if (color.startsWith('#')) return hexToLinearRgb(color)
  if (color.startsWith('oklch(')) return oklchToLinearRgb(color)
  throw new Error(`Unsupported color token: ${color}`)
}

function luminance(color: string): number {
  const { r, g, b } = colorToLinearRgb(color)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrastRatio(foregroundHex: string, backgroundHex: string): number {
  const fg = luminance(foregroundHex)
  const bg = luminance(backgroundHex)
  const brighter = Math.max(fg, bg)
  const darker = Math.min(fg, bg)
  return (brighter + 0.05) / (darker + 0.05)
}

describe('theme color contrast', () => {
  const css = readFileSync(resolve(process.cwd(), 'src/styles/theme.css'), 'utf8')
  const { dark, light } = parseThemeColors(css)
  const checks = [
    { fg: 'text-primary', bg: 'bg-primary' },
    { fg: 'text-secondary', bg: 'bg-primary' },
    { fg: 'text-muted', bg: 'bg-secondary' },
    { fg: 'accent-info', bg: 'bg-primary' },
    { fg: 'accent-winner', bg: 'bg-primary' },
    { fg: 'accent-loser', bg: 'bg-primary' },
    { fg: 'accent-warning', bg: 'bg-primary' },
  ] as const

  for (const pair of checks) {
    test(`dark theme ${pair.fg} on ${pair.bg} is AA compliant`, () => {
      expect(contrastRatio(dark[pair.fg], dark[pair.bg])).toBeGreaterThanOrEqual(4.5)
    })

    test(`light theme ${pair.fg} on ${pair.bg} is AA compliant`, () => {
      expect(contrastRatio(light[pair.fg], light[pair.bg])).toBeGreaterThanOrEqual(4.5)
    })
  }
})
