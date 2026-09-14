# Frontend smoke and rollback playbook

This runbook describes generic production smoke and rollback checks. It does not identify a current deployment or authorize a deployment.

## Production Hardening Checklist

1. Frontend security headers enforced at edge (`frontend/vercel.json`):
   - `Strict-Transport-Security`
   - `X-Content-Type-Options`
   - `X-Frame-Options`
   - `Referrer-Policy`
   - `Permissions-Policy`
   - `X-Permitted-Cross-Domain-Policies`
2. Frontend deep-link routing works for SPA routes (for example `/history` returns 200).
3. Backend security headers and HSTS are enabled in production (`backend/main.py` middleware).
4. CORS allowlist includes the approved frontend origin and local development origin where required.
5. The selected backend platform has a health check for `/api/health`.

## Domain and origin change

Before a domain or origin change, the deployment operator should:

1. add and verify the domain with the chosen hosting and DNS providers;
2. set the frontend API base URL to the approved backend URL;
3. update the backend CORS allowlist and any provider metadata to the approved public origin;
4. deploy the frontend and backend through the approved release process; and
5. record the immutable revision and deployment receipts.

## Smoke Procedure

1. Deploy to target environment.
2. Run the repository's scripted production smoke with the approved frontend URL, backend API URL, and full Git revision.
   - Omit `--expected-sha` only when revision parity is unavailable; the smoke still checks the public frontend and API build receipts.
   - `build_time` is deployment-build metadata. It is reproducible only when the build supplies `SOURCE_DATE_EPOCH`; it does not establish release-artifact reproducibility by itself.
3. Manually verify:
   - Arena run creation and completion
   - History load and deep link refresh
   - Leaderboard render
   - Settings controls (theme, notifications, telemetry)
4. Confirm the deployment's documented health and build-metadata endpoints.

## Ongoing Monitoring

1. Configure the selected backend platform to health-check `/api/health`.
2. Run the repository's production smoke after a deployment.
3. Use scheduled uptime checks only when the deployment owner has approved their cost, access, and notification policy.

## Rollback Triggers

- Critical run flow fails
- API unavailable or deep-link routes return non-200
- Major accessibility regression
- JS/CSS budget breach in production build
- Elevated client error rate after release

## Rollback Steps

1. Roll the frontend back to the previous known-good deployment.
2. Roll the backend back to the corresponding known-good deployment.
3. Confirm rollback with smoke script and API checks.
4. Record the incident, responsible operator, and next review time until the smoke checks pass.
