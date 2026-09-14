# Getting started

Scaffold Arena can run entirely with synthetic fixtures. Provider credentials are optional and no provider call starts during installation, startup, StudyPack validation, or preflight.

## Prerequisites

- Python 3.11+
- Node.js 20+
- `uv`
- `pnpm` 10

## Install

```bash
git clone https://github.com/jlov7/scaffold-arena.git
cd scaffold-arena

cd backend
uv sync --frozen --extra dev --extra research

cd ../frontend
npx -y pnpm@10 install --frozen-lockfile
```

## Run the verified provider-free browser demo

Terminal 1 runs the literal-loopback API and enables only the bounded bundled fixture:

```bash
# Terminal 1, from the repository root
cd backend
uv run arena serve --host 127.0.0.1 --port 8000 --enable-offline-demo
```

Terminal 2 serves the Workbench. The Vite proxy is required for a fresh clone:

```bash
# Terminal 2, from the repository root
cd frontend
VITE_API_PROXY_TARGET=http://127.0.0.1:8000 npx -y pnpm@10 dev --host 127.0.0.1
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Import `offline-demo-v1`, create and freeze an experiment, run preflight, then use **Run bundled offline demo** after a `PASS`. The run produces durable synthetic fixture records and invokes no provider.

## Run the separate CLI fixture and provenance example

```bash
# From the repository root
cd backend
demo_dir="$(mktemp -d /tmp/scaffold-arena-demo.XXXXXX)"
uv run arena demo --path "$demo_dir"
```

This command is a separate local provenance workflow. It validates the bundled fixture and writes a descriptive decision card. It does not start the Workbench. The directory must be fresh and empty; the command refuses a non-empty output location.

The browser fixture is unavailable in default server mode and direct-ASGI/container launches. The literal-loopback launcher above does not trust forwarded headers, accepts direct loopback requests only, runs at most one bundled fixture execution at a time, and never enables provider execution.

## Verify the offline demonstration

```bash
# From the repository root
cd backend
uv run pytest tests/study_packs_v1/test_offline_demo_v1.py \
  tests/integration_v1/test_offline_demo_fixture_chain.py -q
```

The test imports, freezes, executes, evaluates, analyzes, and derives evidence for the 16-arm, 80-attempt synthetic fixture study. It is protocol evidence, not a provider benchmark.

## Capture provenance for a StudyPack

```bash
# From the repository root
cd backend
provenance_root="$(mktemp -d /tmp/scaffold-arena-provenance.XXXXXX)"
uv run arena provenance capture \
  --root .. \
  --study-pack ../study_packs/offline-demo-v1/study-pack.json \
  --output "$provenance_root/provenance.json"
```

The capture binds the observed Git revision and dirty state, lockfiles, installed package versions, runtime identity, prompts, context declarations, tools, preregistration, and evidence-source hashes. It is local custody metadata, not a signed build or deployment attestation. Existing output files are never overwritten.

## Configure a live provider

Copy `backend/.env.example` to `backend/.env` and set only the provider variables you intend to use. Run preflight before execution. Missing provider usage or pricing remains `UNKNOWN`; it is never represented as zero cost.

Live adapters remain subject to their declared capability, isolation, and evidence ceilings. See [adapter certification](adapters/certification.md) and [evidence status](evidence-status.md).

## Team profile

The team profile requires PostgreSQL, an S3-compatible artifact store, OIDC server sessions, and project-scoped RBAC. It fails closed when those prerequisites are incomplete. Follow [the deployment runbook](ops/team-deployment.md); repository configuration is not deployment assurance.

## Full verification

```bash
./scripts/verify-all.sh
```

See [the documentation index](README.md) for protocol, API, evaluation, evidence, security, and operations references.
