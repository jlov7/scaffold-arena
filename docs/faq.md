# FAQ

## Is Scaffold Arena a model leaderboard?

No. It is designed to hold the model and experimental conditions fixed while varying harness mechanisms.

## Is it a general agent runtime?

No. It is an experimental controller, evaluator, analysis workbench, and evidence packager. Harnesses connect through adapters.

## Can I run it without provider credentials?

Yes. The bundled synthetic StudyPack and fixture adapter run offline. Fixture output is always labelled and cannot support provider-performance claims.

## Can I import arbitrary code in a StudyPack?

No. Uploaded packs are declarative. Executable adapters and graders require a separately installed trusted package.

## Why is a result marked HOLD?

HOLD means the available evidence cannot support the requested action or claim. Common causes include capability mismatch, incomplete traces, unknown usage, failed factor manipulation, inadequate sample size, absent human calibration, or missing external reproduction.

## What do receipts prove?

They prove custody and integrity of the named artifacts and bindings. They do not prove outcome correctness, evaluator independence, or deployment security.

## Is team mode a hosted SaaS control plane?

No. It is a self-hosted, single-organisation profile with PostgreSQL, S3-compatible artifacts, OIDC sessions, and project roles.

## What evidence ships today?

Protocol and fixture evidence. There is no published live-provider comparison, completed human calibration, or independent reproduction. See [evidence status](evidence-status.md).

## Where do I start?

- [Getting started](getting-started.md)
- [User guide](user-guide.md)
- [Technical explainer](explainers/technical.md)
