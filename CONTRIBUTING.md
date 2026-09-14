# Contributing to Scaffold Arena

Thank you for your interest in contributing. Scaffold Arena is an evidence-bound research instrument, so changes must preserve both software correctness and the stated claim boundary.

## Development setup

1. Fork and clone the repository.
2. Follow the [Getting Started](docs/getting-started.md) guide.
3. Create a focused feature branch from `main`.
4. Do not configure provider credentials merely to install, validate, or run the synthetic fixture.

## Project structure

```text
scaffold-arena/
├── backend/          # Python, FastAPI, protocol, workers, evaluation, evidence
├── frontend/         # React and TypeScript Workbench
├── specs/            # Generated and stable protocol schemas
├── study_packs/      # Declarative studies and repository fixtures
├── release/          # Authoritative software release state
├── scripts/          # Verification and operational tooling
└── docs/             # Product, architecture, research, and operations
```

See [Architecture](docs/architecture.md) for the system boundaries.

## Development workflow

### Running in development

```bash
cd backend
uv sync --frozen --extra dev --extra research
uv run uvicorn main:app --reload --port 8000
```

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

### Authoritative verification

Run the complete repository gate before requesting review:

```bash
./scripts/verify-all.sh
```

For a clean-checkout proof:

```bash
./scripts/verify-clean-clone.sh
```

Release-bearing changes must also pass:

```bash
python scripts/verify-release-metadata.py --root .
```

External-service tests that cannot run must remain explicit skips; they must not be converted into passes.

### Code style

**Python**

- Use type hints for public and boundary-facing functions.
- Keep protocol, adapter, persistence, evaluation, and evidence models strict and fail-closed.
- Prefer small modules with explicit dependency direction.
- Do not translate missing evidence to zero, false, success, or an inferred value.

**TypeScript**

- Preserve strict TypeScript.
- Use existing Workbench design-system and API boundaries.
- Keep durable IDs in the URL where the protocol-v1 Workbench requires recovery.
- Streaming UI must remain bounded and reconnectable.

## Making changes

### Protocol and StudyPack changes

- Preserve protocol `1.0` compatibility unless the change deliberately introduces a new protocol version.
- Regenerate schemas from the strict Pydantic authority rather than editing generated schemas by hand.
- Uploaded StudyPacks remain declarative and cannot import or execute code.
- Frozen identity, migration behavior, and claim ceilings require tests.

### Adapters and harness integrations

- Adapters must be installed and allowlisted as trusted code.
- Capabilities, isolation, cancellation, cleanup, usage, artifacts, and trace semantics must be explicit.
- Unsupported controls produce a typed failure or limitation; they are never silently approximated.
- Add or extend conformance tests for malformed output, timeouts, cancellation, secret handling, and partial evidence.

### Evaluation and analysis changes

- Deterministic evaluation remains at least 70% of every task-family score.
- Severe state, permission, evidence, and integrity failures cannot be averaged away.
- The state oracle remains authoritative over agent narration.
- Agent-side verification is a treatment mechanism, not the independent evaluator.
- Statistical outputs must preserve exclusions, missingness, adequacy, multiplicity, and descriptive-versus-confirmatory status.

### Security-sensitive changes

Authentication, project scoping, workers, adapters, archives, artifacts, exports, retention, redaction, release workflows, and dependency changes are security-sensitive. Update the threat model or security documentation when the trust boundary changes.

### Frontend changes

- Use the Workbench design tokens and durable resource APIs.
- Do not reconstruct absent evidence in browser state.
- Status must never rely on color alone.
- Empty, loading, blocked, and error states require a truthful next action.
- Run accessibility, visual, performance, and end-to-end gates.

## Commit messages

Use Conventional Commits in imperative mood:

```text
feat: add adapter certification receipt
fix: preserve unknown cost through cancellation
security: reject cross-project artifact binding
docs: define release withdrawal procedure
```

Explain why the change exists, not only what changed. Keep one logical concern per commit.

## Pull requests

1. Create a focused branch.
2. Add a failing regression or contract test before the implementation when behavior changes.
3. Keep commits reviewable and avoid unrelated refactoring.
4. Run the complete verification gate.
5. Fill in the pull-request template, including evidence, security, compatibility, and rollback considerations.
6. Open against `main`; do not push directly to protected branches.

### Pull-request checklist

- [ ] The exact failure or missing contract is reproduced by a test.
- [ ] Backend, frontend, packaging, accessibility, visual, performance, and container gates pass as applicable.
- [ ] Protocol/schema compatibility is preserved or a migration is documented.
- [ ] Evidence classes and claim ceilings remain truthful.
- [ ] No credential, secret, private source, restricted artifact, or customer data is committed.
- [ ] New storage, API, adapter, or worker paths enforce project scope at their atomic boundary.
- [ ] Documentation, changelog, and threat model are updated when applicable.
- [ ] The diff contains no placeholders, silent approximations, or simulated public evidence.

## Release changes

A normal feature pull request must not create or overwrite a GitHub release.

A release-preparation pull request updates the authoritative metadata, citation date, changelog heading and links, and all package versions together. After it is merged, a maintainer creates an annotated `v<version>` tag at the exact merge commit. Only `.github/workflows/release.yml` may publish release artifacts.

The workflow builds packages and an OCI image, generates an SPDX SBOM, checksums the release set, creates keyless Sigstore signatures, creates GitHub attestations, and creates the GitHub release only after every prior gate succeeds. See [Release verification and recovery](docs/ops/release-verification.md).

Do not:

- attach hand-built assets to a release;
- reuse or move an existing release tag;
- replace assets under the same version;
- describe a workflow artifact as a public release;
- describe an artifact signature as research validation.

## Maintainers and ownership

Maintainer responsibilities and the current independence limitation are documented in [MAINTAINERS.md](MAINTAINERS.md). `.github/CODEOWNERS` declares intended review ownership but does not prove that GitHub branch rules are enabled.

## Architecture decisions

Significant changes should include or update an ADR. Key invariants include:

- provider execution never starts implicitly;
- the API process does not own attempt execution;
- protocol-v1 streams are GET-only and cursor-recoverable;
- deterministic evaluation remains at least 70%;
- missing cost or usage is `UNKNOWN`, never zero;
- frozen inputs and derived evidence remain content-addressed;
- team-mode access is project-scoped and fail-closed;
- fixture, live, human-calibrated, cross-model, and independent evidence remain separately attributable.

## Reporting issues

Include:

- exact revision or released version;
- reproduction steps;
- expected and observed behavior;
- relevant redacted logs or request IDs;
- Python, Node, database, and storage profile;
- whether external services were available;
- whether the issue affects evidence or claim eligibility.

Potential vulnerabilities follow [SECURITY.md](SECURITY.md), not public issues.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
