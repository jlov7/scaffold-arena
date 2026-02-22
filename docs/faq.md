# FAQ

## Is this production-ready SaaS?
Not yet. It is engineered to a high standard for benchmark rigor and internal dissemination, with many production-grade practices already in place.

## What is the core value proposition?
Scaffold Arena demonstrates that orchestration quality often has a larger outcome impact than model upgrades alone.

## What does "deterministic-first evaluation" mean?
Each task assigns at least 70% of score weight to deterministic, reproducible metrics.

## Are the research sources real?
No. The benchmark uses synthetic sources and labels them explicitly in UI/reporting.

## Can I add my own tasks?
Yes. Custom task creation is supported, including optional JSON schema constraints.

## How do beginners avoid getting stuck?
Use the in-app sequence:
- Checklist panel for exact next step
- Immediate guidance card when blocked
- Help Center (`Help` button, `H`, or `F1`) for task-aware recovery playbooks
- Guided tour + shortcuts for orientation

## How do I verify quality quickly?
Run:
- Frontend: `pnpm lint && pnpm test && pnpm build`
- Backend: `uv run pytest -q`

## Where should I start reading?
- Product story: [`../README.md`](../README.md)
- Docs portal: [`README.md`](README.md)
- Technical deep dive: [`explainers/technical.md`](explainers/technical.md)
