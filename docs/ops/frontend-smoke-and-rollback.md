# Frontend Smoke and Rollback Playbook

## Smoke Procedure
1. Deploy to target environment.
2. Run `pnpm smoke:prod -- <base_url>`.
3. Manually verify:
   - Arena run creation and completion
   - History load
   - Leaderboard render
   - Settings controls (theme, notifications, telemetry)

## Rollback Triggers
- Critical run flow fails
- Major accessibility regression
- JS/CSS budget breach in production build
- Elevated client error rate after release

## Rollback Steps
1. Revert to last known good deployment tag.
2. Confirm rollback with smoke script.
3. Disable risky flags if needed.
4. Open incident record with root-cause owner and ETA.
