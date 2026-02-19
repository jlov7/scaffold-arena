# Getting Started

> From zero to your first arena run in under 5 minutes.

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11+ | [python.org](https://python.org) |
| Node.js | 18+ | [fnm](https://github.com/Schniz/fnm) or [nvm](https://github.com/nvm-sh/nvm) |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| pnpm | latest | `npm install -g pnpm` |
| Anthropic API key | — | [console.anthropic.com](https://console.anthropic.com/) |

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

Open `.env` and add your Anthropic API key:

```env
ANTHROPIC_API_KEY=sk-ant-...your-key-here...
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
  VITE v6.x.x  ready in XXXms

  ➜  Local:   http://localhost:5173/
```

### 3. Open the Arena

Navigate to **http://localhost:5173** in your browser.

You'll see the Scaffold Arena interface with:
- Task cards along the top (Structured Extraction, Risk Analysis, Research Synthesis)
- A model dropdown
- A "Run Arena" button

## Your First Arena Run

### Step 1: Select a Task

Click any task card. **Structured Extraction** is a good starting point — it's the fastest and most visual.

### Step 2: Select a Model

The default model is Claude Sonnet 4.6. You can switch to Claude Haiku 4.5 for faster, cheaper runs.

### Step 3: Click "Run Arena"

Four panels appear, each running a different scaffold architecture on your selected task. You'll see:

- **Live streaming text** as each scaffold generates output
- **Phase indicators** showing what each scaffold is doing (planning, executing, verifying, etc.)
- **Real-time metrics** (tokens, cost, time) as each scaffold completes

### Step 4: Review Scores

Once all scaffolds finish, the Score Dashboard shows ranked results with:
- Total score (0–100)
- Hover any score to see the metric breakdown
- The winner gets highlighted

### Step 5: Run Proof Comparison

Click "Run Proof Comparison" to prove that the winning scaffold on a cheap model beats an expensive model running bare. This is the key insight.

### Step 6: Diagnose Failures (Optional)

Click "Autopsy" on any losing scaffold to see exactly why it scored lower. The autopsy provides:
- Classified failure types with evidence
- Machine-applicable patches
- One-click "Apply Patch & Rerun" to verify the fix

### Step 7: Export Report (Optional)

Click "Export Report" to generate a comprehensive Markdown report documenting the full arena results. Download as `.md` or `.pdf`.

## Configuration

### Environment Variables

All configuration is via environment variables in `backend/.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | *(required)* | Your Anthropic API key |
| `APP_ENV` | `development` | Environment mode |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed CORS origins (comma-separated) |
| `DEFAULT_MAIN_MODEL_ID` | `claude-sonnet-4-6` | Default model for arena runs |
| `DEFAULT_CHEAP_MODEL_ID` | `claude-haiku-4-5` | Default cheap model for proof comparison |
| `ENABLE_LLM_JUDGE` | `false` | Enable LLM judge for subjective scoring (costs extra API calls) |
| `ENABLE_PDF_EXPORT` | `false` | Enable PDF report export (requires weasyprint) |
| `MAX_CONCURRENT_LLM_CALLS` | `8` | Max concurrent Anthropic API calls |

### Optional: Enable LLM Judge

By default, only deterministic metrics are used for scoring (weights are redistributed proportionally). To enable the LLM judge for subjective criteria:

```env
ENABLE_LLM_JUDGE=true
```

This adds ~1 extra API call per scaffold per run for subjective scoring (completeness, reasoning clarity, recommendation quality).

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

- Check that `ANTHROPIC_API_KEY` is set in `backend/.env`
- Ensure Python 3.11+ is active: `python --version`
- Try `uv sync` to reinstall dependencies

### Frontend shows "Failed to fetch"

- Confirm the backend is running on port 8000
- Check CORS_ORIGINS includes your frontend URL

### Streaming stops mid-run

- Check your Anthropic API key has sufficient credits
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
