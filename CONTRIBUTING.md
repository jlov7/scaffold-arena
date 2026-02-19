# Contributing to Scaffold Arena

Thank you for your interest in contributing. This guide will help you get started.

## Development Setup

1. Fork and clone the repository
2. Follow the [Getting Started](docs/getting-started.md) guide for installation
3. Create a feature branch from `main`

## Project Structure

```
scaffold-arena/
├── backend/          # Python / FastAPI
│   ├── scaffolds/    # Scaffold implementations
│   ├── tasks/        # Task definitions
│   ├── evaluation/   # Scoring system
│   └── ...
├── frontend/         # React / TypeScript
│   └── src/
│       ├── components/
│       ├── hooks/
│       └── ...
└── docs/             # Documentation
```

See [Architecture](docs/architecture.md) for detailed system design.

## Development Workflow

### Running in Development

```bash
# Backend (auto-reloads on changes)
cd backend && uv run uvicorn main:app --reload --port 8000

# Frontend (HMR via Vite)
cd frontend && pnpm dev
```

### Code Style

**Python:**
- Format with `ruff format`
- Lint with `ruff check`
- Type hints required for function signatures

**TypeScript:**
- Format with Prettier (via ESLint)
- Strict TypeScript (`strict: true`)
- Prefer named exports

### Testing

```bash
# Backend tests
cd backend && uv run pytest

# Frontend type check
cd frontend && pnpm tsc --noEmit
```

## Making Changes

### Adding a New Scaffold

1. Create `backend/scaffolds/your_scaffold.py`
2. Extend `BaseScaffold` and implement the `run()` async generator
3. Register in `main.py`'s startup handler
4. See [Scaffold Architectures](docs/scaffolds.md) for the interface contract

### Adding a New Task

1. Create `backend/tasks/your_task.py`
2. Extend `BaseTask` with input text, schema, and gold standard
3. Add weight table entry in `evaluation/harness.py`
4. Add deterministic metric functions in `evaluation/deterministic.py`
5. Register in `main.py`'s startup handler

### Modifying the Evaluation System

- Deterministic metrics must carry **>=70% weight** for every task type
- All weights must be published in `evaluation/harness.py`
- New metrics need corresponding functions in `evaluation/deterministic.py`

### Frontend Changes

- Components live in `frontend/src/components/`
- Use the existing design tokens from `styles/theme.css`
- Streaming components must use ref-based buffering (never setState per token)

## Commit Messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add chain-of-thought scaffold
fix: handle empty JSON in extraction task
docs: update evaluation methodology section
refactor: simplify fan-in queue implementation
```

- Use imperative mood ("add" not "added")
- Explain **why**, not just what
- One logical change per commit

## Pull Requests

1. Create a feature branch: `git checkout -b feat/your-feature`
2. Make your changes with clear, focused commits
3. Ensure all tests pass and types check
4. Open a PR against `main`
5. Fill in the PR template

### PR Checklist

- [ ] Tests pass (`uv run pytest` + `pnpm tsc --noEmit`)
- [ ] Code is formatted (`ruff format` + Prettier)
- [ ] New scaffolds/tasks are registered in `main.py`
- [ ] Evaluation weights sum to 1.0 and deterministic >= 0.70
- [ ] Documentation updated if applicable
- [ ] No secrets or API keys committed

## Architecture Decisions

Before making significant architectural changes, please open an issue to discuss the approach. Key invariants to preserve:

- **SSE is GET-only** — the frontend uses `EventSource`
- **Deterministic eval >= 70%** — no reducing deterministic weights below this
- **Fan-in queue pattern** — all scaffolds share one event queue per run
- **Single source of truth for pricing** — `config/models.py` only
- **Cancellation-safe scaffolds** — check `cancelled_check` between API calls

## Reporting Issues

When reporting bugs, please include:
- Steps to reproduce
- Expected vs. actual behavior
- Backend terminal output (if applicable)
- Browser console errors (if applicable)
- Python/Node versions

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
