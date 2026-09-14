## Summary
- What changed and why

## Validation
- [ ] `./scripts/verify-all.sh`
- [ ] `cd frontend && npx -y pnpm@10 test:e2e`
- [ ] `cd frontend && npx -y pnpm@10 test:a11y`
- [ ] `cd frontend && npx -y pnpm@10 verify:visual` for UI changes
- [ ] `impeccable detect --json frontend/src` for frontend/design-system changes
- [ ] Trace-audit output reviewed if run/evaluation/report behavior changed

## Risk
- User-facing risk:
- Rollback strategy:

## Screenshots / Evidence
- Include before/after screenshots, visual artifacts, trace-audit report links, or command output as appropriate
