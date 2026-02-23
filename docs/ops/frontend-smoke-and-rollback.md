# Frontend Smoke, Domain, and Rollback Playbook

This runbook covers production hardening checks, custom-domain cutover, smoke validation, and rollback.

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
4. CORS allowlist includes deployed frontend URL(s):
   - `CORS_ORIGINS=https://scaffold-arena.vercel.app,http://localhost:5173`
5. Scheduled uptime monitoring is enabled (`.github/workflows/uptime.yml`) and repo notifications are on.

## Custom Domain Cutover (Vercel Frontend)

Use this once you have your domain name ready.

1. Add domain in Vercel project:
   - `vercel domains add <your-domain>`
2. In your DNS provider, add the records shown by Vercel (typically `A`/`CNAME`).
3. Verify domain in Vercel:
   - `vercel domains inspect <your-domain>`
4. Set frontend production env var to point to Railway backend:
   - `VITE_API_BASE_URL=https://scaffold-arena-production.up.railway.app/api`
5. Update Railway allowlist + app metadata:
   - `CORS_ORIGINS=https://<your-domain>,https://scaffold-arena.vercel.app,http://localhost:5173`
   - `OPENROUTER_SITE_URL=https://<your-domain>`
6. Redeploy both services:
   - `railway up --detach`
   - `vercel --prod --yes`

## Smoke Procedure

1. Deploy to target environment.
2. Run scripted smoke:
   - `cd frontend && pnpm smoke:prod -- https://scaffold-arena.vercel.app`
3. Manually verify:
   - Arena run creation and completion
   - History load and deep link refresh
   - Leaderboard render
   - Settings controls (theme, notifications, telemetry)
4. Confirm backend API:
   - `curl https://scaffold-arena-production.up.railway.app/api/health`
   - `curl https://scaffold-arena-production.up.railway.app/api/meta`

## Ongoing Monitoring

1. GitHub scheduled monitor runs every 30 minutes (`Production Uptime Monitor`).
2. On failure, it opens or updates a single incident issue:
   - title: `[Uptime] Production health checks failing`
3. Review issue updates and action run links for root-cause evidence.

## Rollback Triggers

- Critical run flow fails
- API unavailable or deep-link routes return non-200
- Major accessibility regression
- JS/CSS budget breach in production build
- Elevated client error rate after release

## Rollback Steps

1. Roll frontend back to previous Vercel production deployment.
2. Roll backend back to previous healthy Railway deployment.
3. Confirm rollback with smoke script and API checks.
4. Keep uptime incident issue open with owner + ETA until green.
