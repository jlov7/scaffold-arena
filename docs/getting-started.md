# Getting Started

> From zero to your first arena run in under 5 minutes.

Need the full docs index? See [`docs/README.md`](README.md).

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11+ | [python.org](https://python.org) |
| Node.js | 18+ | [fnm](https://github.com/Schniz/fnm) or [nvm](https://github.com/nvm-sh/nvm) |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| pnpm | latest | `npm install -g pnpm` |
| Provider API key (at least one) | — | [Anthropic](https://console.anthropic.com/), [OpenAI](https://platform.openai.com/), [Gemini](https://aistudio.google.com/), or [OpenRouter](https://openrouter.ai/) |

## Installation

### 1. Clone the Repository

```bash
git clone <repo-url>
cd scaffold-arena
```

### 2. Set Up the Backend

```bash
cd backend
cp .env.example .env
```

Open `.env` and add at least one provider API key:

```env
ANTHROPIC_API_KEY=sk-ant-...your-key-here...
OPENAI_API_KEY=sk-proj-...your-key-here...
GEMINI_API_KEY=...your-key-here...
OPENROUTER_API_KEY=sk-or-v1-...your-key-here...
```

Install Python dependencies:

```bash
uv sync
```

### 3. Set Up the Frontend

```bash
cd ../frontend
pnpm install
```

That's it. No build step needed for development.

## Running the Application

You'll need two terminal windows:

**Terminal 1 — Backend:**

```bash
cd backend
uv run uvicorn main:app --reload --port 8000
```

You should see:

```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Started reloader process
```

**Terminal 2 — Frontend:**

```bash
cd frontend
pnpm dev
```

You should see:

```
  VITE v7.x.x  ready in <N> ms

  ➜  Local:   http://localhost:5173/
```

### 3. Open the Arena

Navigate to **http://localhost:5173** in your browser.

You'll see the Scaffold Arena interface with:
- An **Onboarding lane** for role and guided-first setup
- A **Configure lane** for task/model selection and run launch
- A **Live run lane** and **Results workspace** for execution and analysis

## Your First Arena Run

### Step 1: Pick a Role (Onboarding Lane)

Choose the role that matches your immediate objective:
- Evaluator (fast benchmark)
- Operator (reliability and guardrails)
- Analyst (evidence and diagnostics)
- Executive (decision-first summary)

Then move to Configure lane.

### Step 2: Select a Task (Configure Lane)

Click any task card. **Structured Extraction** is a good starting point — it's the fastest and most visual.

### Step 3: Select a Model (Configure Lane)

The default model is Claude Sonnet 4.6. You can switch to Claude Haiku 4.5, OpenAI GPT-4.1 mini, Gemini 2.5 Flash, or OpenRouter models when those provider keys are configured.

### Step 4: Click "Run Arena"

Start the run from Configure lane.

Before launch, the app runs a **preflight check** (task/model/scaffolds/options/budget/provider readiness). If any check fails, you get a concrete blocker message and remediation.

Then open Live run lane to monitor execution.

Four panels appear, each running a different scaffold architecture on your selected task. You'll see:

- **Live streaming text** as each scaffold generates output
- **Phase indicators** showing what each scaffold is doing (planning, executing, verifying, etc.)
- **Real-time metrics** (tokens, cost, time) as each scaffold completes

### Step 5: Review Results Summary

Once all scaffolds finish, open **Results Summary lane**. The Score Dashboard shows ranked results with:
- Total score (0–100)
- Hover any score to see the metric breakdown
- The winner gets highlighted

### Step 6: Run Proof Comparison (Diagnostics Lane)

Open **Diagnostics lane**, then click "Run Proof Comparison" to prove that the winning scaffold on a cheap model beats an expensive model running bare. This is the key insight.

### Step 7: Diagnose Failures (Optional)

Click "Autopsy" on any losing scaffold to see exactly why it scored lower. The autopsy provides:
- Classified failure types with evidence
- Machine-applicable patches
- One-click "Apply Patch & Rerun" to verify the fix

### Step 8: Export Report (Optional)

Click "Export Report" to generate a comprehensive Markdown report documenting the full arena results. Download as `.md` or `.pdf`.

For sharing complete evidence in one file, use **Export Bundle** in Results. It downloads a zip containing run payload + diagnostics timeline + report markdown.

### Fast Navigation (Optional)

Open the command palette with `Cmd/Ctrl+K` to jump between workspaces or trigger actions quickly.

## Configuration

### Environment Variables

All configuration is via environment variables in `backend/.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | `""` | Required only for Claude models |
| `OPENAI_API_KEY` | `""` | Required only for OpenAI models |
| `GEMINI_API_KEY` | `""` | Required only for Gemini models |
| `OPENROUTER_API_KEY` | `""` | Required only for OpenRouter models |
| `GEMINI_OPENAI_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai/` | Gemini OpenAI-compatible endpoint |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter base URL |
| `OPENROUTER_SITE_URL` | `""` | Optional OpenRouter attribution header (`HTTP-Referer`) |
| `OPENROUTER_APP_NAME` | `Scaffold Arena` | Optional OpenRouter attribution header (`X-Title`) |
| `APP_ENV` | `dev` | Environment mode |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed CORS origins (comma-separated) |
| `DEFAULT_MAIN_MODEL_ID` | `claude-sonnet-4-6` | Default model for arena runs |
| `DEFAULT_CHEAP_MODEL_ID` | `claude-haiku-4-5` | Default cheap model for proof comparison |
| `ENABLE_LLM_JUDGE` | `true` | Enable LLM judge for subjective scoring (costs extra API calls) |
| `ENABLE_PDF_EXPORT` | `false` | Enable PDF report export (requires weasyprint) |
| `MAX_CONCURRENT_LLM_CALLS` | `3` | Max concurrent provider API calls |

In **Settings**, BYOK storage defaults to **session-only**. Switch to **Remember in this browser** only if you explicitly want persistent local storage.

### Optional: Disable LLM Judge

By default, the LLM judge is enabled for subjective criteria. To run deterministic-only scoring, set:

```env
ENABLE_LLM_JUDGE=false
```

This removes ~1 extra API call per scaffold per run and redistributes judge weights to deterministic metrics.

### Optional: Enable PDF Export

```env
ENABLE_PDF_EXPORT=true
```

Then install weasyprint:

```bash
uv add weasyprint
```

## Troubleshooting

### Backend won't start

- Check that at least one provider key is set in `backend/.env`
- If using a Claude model, set `ANTHROPIC_API_KEY`
- If using an OpenAI model, set `OPENAI_API_KEY`
- If using a Gemini model, set `GEMINI_API_KEY`
- If using an OpenRouter model, set `OPENROUTER_API_KEY`
- Ensure Python 3.11+ is active: `python --version`
- Try `uv sync` to reinstall dependencies

### Frontend shows "Failed to fetch"

- Confirm the backend is running on port 8000
- Check CORS_ORIGINS includes your frontend URL

### Port already in use (5173 or 8000)

- Find the process:
  - `lsof -i tcp:5173 -n -P`
  - `lsof -i tcp:8000 -n -P`
- Stop the process (replace `<PID>`):
  - `kill <PID>`
- Or run with alternate ports:
  - Backend: `uv run uvicorn main:app --reload --port 8010`
  - Frontend: `pnpm dev -- --port 5174`

### Streaming stops mid-run

- Check your provider key has sufficient credits/quota
- Check the backend terminal for error messages
- The SSE connection has a 15-second heartbeat — if the backend crashes, the frontend will notice

### Scores seem low

- This is expected for the Bare Prompt scaffold — that's the whole point
- Ensure the model has enough output tokens (default: 2048)
- Check evaluation notes in the score breakdown tooltip for specific issues

## Next Steps

- [User Guide](user-guide.md) — Complete walkthrough of every feature
- [Evaluation Methodology](evaluation.md) — How scoring works in detail
- [Scaffold Architectures](scaffolds.md) — Deep dive into each scaffold approach
- [Architecture](architecture.md) — Technical system design
