import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, test } from 'vitest'

type ColorMap = Record<string, string>

function parseBlockColors(block: string): ColorMap {
  const matches = block.matchAll(/--color-([a-z-]+):\s*(#[0-9a-fA-F]{6})/g)
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

function luminance(hex: string): number {
  const numeric = Number.parseInt(hex.replace('#', ''), 16)
  const r = (numeric >> 16) & 255
  const g = (numeric >> 8) & 255
  const b = numeric & 255
  return (
    0.2126 * channelToLinear(r) +
    0.7152 * channelToLinear(g) +
    0.0722 * channelToLinear(b)
  )
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
