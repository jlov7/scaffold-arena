# First-Click IA Results

Date: 2026-02-20  
Suite: `frontend/tests/e2e/first-click.spec.ts`

## Tasks

1. Reach Settings from shell navigation.
2. Reach History from shell navigation.
3. Reach Leaderboard from shell navigation.
4. Reach Results from shell navigation.
5. Verify progressive-nav first-click behavior at `320px`.

## Outcome

- Desktop first-click success: **4/4**.
- Mobile first-click success (`320px`): **2/2** (primary direct, secondary via `More`).
- Aggregate: **100% first-click success for covered IA tasks**.

## Notes

- Progressive disclosure is intentional for narrow screens:
  - `Arena` + `Results` stay directly visible.
  - Secondary destinations are one tap behind `More`.
- This validates IA discoverability for top-shell destinations in both desktop and constrained mobile contexts.
