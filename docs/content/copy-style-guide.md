# Copy Style Guide and Templates

Use this guide for all user-facing text across Scaffold Arena.

## Voice and Tone Matrix

| Context | Tone | Rule | Example |
| --- | --- | --- | --- |
| Neutral instruction | Clear, direct | State action and expected outcome | `Choose a task to define quality criteria.` |
| Success | Confident, concise | Confirm outcome and next action | `Run completed. Review score, cost, and time.` |
| Warning | Cautionary, actionable | Explain risk and safe alternative | `Force rerun may increase spend. Continue?` |
| Blocker/error | Calm, procedural | Reason + recovery + fallback in one block | `Session token missing. Open Settings, add token, then retry. If blocked, use safe fallback mode.` |

## Reusable Templates

### CTA labels

- Format: `Verb + outcome`
- Examples:
  - `Run arena`
  - `Export report`
  - `Open settings now`
  - `Run proof comparison`

### Helper text

- Format: `Why` + `required input` + `expected outcome`
- Template:
  - `Pick <input> so the system can <outcome>.`

### Blocker copy

- Format: `Reason` + `Recovery action` + `Fallback option`
- Template:
  - `<reason>. <action now>. If this continues, <fallback>.`

### Empty state copy

- Format: `Purpose` + `next action` + optional learn link
- Template:
  - `No <entity> yet. <primary action>. Learn how in Help Center.`

## Banned Patterns

- Avoid vague words: `thing`, `stuff`, `just`, `simply`, `obviously`.
- Avoid internal jargon in first-touch flows.
- Never ship blockers without an immediate recovery action.

## QA Checklist

1. CTA starts with a verb.
2. Blocker copy includes recovery.
3. Empty states include next action.
4. String is understandable without prior domain context.
