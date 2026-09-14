import { afterEach, describe, expect, it, vi } from 'vitest'

import { assignVariant } from './experiments/assign'

describe('assignVariant', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('returns stored variant when available', () => {
    const storage = new Map<string, string>()
    storage.set('scaffold_arena_exp_tour_entry', 'cta_only')
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value)
      },
    })

    const variant = assignVariant('tour_entry', ['auto_open', 'cta_only'])
    expect(variant).toBe('cta_only')
  })

  it('assigns and persists a variant when missing', () => {
    const storage = new Map<string, string>()
    vi.spyOn(Math, 'random').mockReturnValue(0.99)
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value)
      },
    })

    const variant = assignVariant('post_run_rail_order', [
      'compare_first',
      'export_first',
    ])
    expect(variant).toBe('export_first')
    expect(storage.get('scaffold_arena_exp_post_run_rail_order')).toBe('export_first')
  })

  it('supports persona path experiment assignments', () => {
    const storage = new Map<string, string>()
    vi.spyOn(Math, 'random').mockReturnValue(0.75)
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value)
      },
    })

    const variant = assignVariant('persona_path', [
      'evaluator_default',
      'operator_default',
    ])
    expect(variant).toBe('operator_default')
    expect(storage.get('scaffold_arena_exp_persona_path')).toBe(
      'operator_default',
    )
  })
})
