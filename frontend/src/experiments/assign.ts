const EXPERIMENT_STORAGE_PREFIX = 'scaffold_arena_exp_'

export type ExperimentId =
  | 'tour_entry'
  | 'post_run_rail_order'
  | 'persona_path'

export function assignVariant<TVariant extends string>(
  experiment: ExperimentId,
  variants: readonly TVariant[],
): TVariant {
  if (variants.length === 0) {
    throw new Error('assignVariant requires at least one variant')
  }

  const storageKey = `${EXPERIMENT_STORAGE_PREFIX}${experiment}`
  try {
    const stored = localStorage.getItem(storageKey)
    if (stored && variants.includes(stored as TVariant)) {
      return stored as TVariant
    }
  } catch {
    // storage unavailable
  }

  const bucket = Math.floor(Math.random() * variants.length)
  const assigned = variants[bucket] ?? variants[0]

  try {
    localStorage.setItem(storageKey, assigned)
  } catch {
    // storage unavailable
  }

  return assigned
}
