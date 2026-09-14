# Context-handoff local study

This is a frozen local-only protocol for one question: should a worker receive an isolated prompt, all declared context, or a fixed curated subset? It is not a leaderboard and it has no completed comparative result.

The StudyPack fixes 24 cells: four scenarios, three delivery policies, and two repetitions. The required runtime is local Ollama 0.34.0 serving the pinned qwen3.5:4b model digest declared in [the StudyPack](../study_packs/context-handoff-local-v1/study-pack.json). It permits no tools, retries, substitutes, or paid calls.

Run the no-inference preflight first from a clean committed candidate. It checks the declared pack, declared runtime binding, budget, and local adapter contract without creating a study execution or probing a live runtime:

~~~bash
uv run --project backend python scripts/run-context-handoff-local.py --preflight-only
~~~

Dispatch is explicit. Use a new evidence path outside the checkout; the target must not already exist:

~~~bash
evidence_parent="$(mktemp -d "${TMPDIR:-/tmp}/scaffold-context-handoff.XXXXXX")"
evidence_root="$evidence_parent/evidence"
uv run --project backend python scripts/run-context-handoff-local.py --dispatch --output "$evidence_root"
~~~

The runner stops on a fatal condition, retains a ledger for every planned cell, and returns nonzero unless all 24 cells and their deterministic evaluations complete. Verify the retained output separately:

~~~bash
uv run --project backend python scripts/check-context-handoff-evidence.py "$evidence_root"
~~~

An integrity PASS proves only the checked local custody and retained bytes. It does not establish a policy ranking, causal effect, transfer, human calibration, or independent reproduction. The first pilot stopped after a GET connection failure before any /api/chat POST; it is partial and is not a comparative result.
