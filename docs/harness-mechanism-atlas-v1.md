# Harness Mechanism Atlas v1

This generated Atlas is a curated, provider-free evidence ledger. It does not import, execute, certify, or compare an external harness.

Source date: `2026-08-18`. Atlas digest: `sha256:e26aab5c96fb15d2bb3a1b1c1bb4b214d45b6979680d9302567a5d22b0419bc7`.

## Claim ceiling

Source-backed declarations and synthetic metadata fixture shapes only; no execution, interoperability, safety, deployment, performance, human-calibration, or independent-reproduction claim.

## Purpose and non-goals

It preserves identity, family-specific semantics, declared state, observation status, evidence links, and explicit unknowns. A source pointer is not activation evidence; a fixture is metadata shape evidence only.

## Family contracts

| Family | Semantic namespace | Mechanisms |
| --- | --- | --- |
| `agent_protocol` | agent.protocol | `a2a.task_artifact_lifecycle`, `acp.session_lifecycle` |
| `coding_cli` | coding.cli | `claude_code.permission_surface`, `codex_cli.approval_surface`, `gemini_cli.approval_mode` |
| `graph_orchestrator` | langgraph | `langgraph.checkpoint_store`, `langgraph.graph_state`, `langgraph.interrupt_resume` |
| `native_scaffold` | arena.native | `native.bare.single_shot`, `native.memory_critique`, `native.plan_execute_verify`, `native.tool_error_recovery` |
| `sdk_runtime` | sdk.runtime | `google_adk.sub_agents`, `openai_agents.agent_loop`, `openai_agents.guardrail`, `openai_agents.handoff` |
| `telemetry_surface` | otel.gen_ai | `otel.gen_ai_semconv` |
| `tool_protocol` | mcp | `mcp.tools_resources_prompts` |

## Mechanism ledger

| Family | Mechanism | Identity source | Declaration | Activation | Evidence maturity | Claim ceiling | Known unknowns | Citations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `agent_protocol` | `a2a.task_artifact_lifecycle` | `a2a` | `declared` | `not_observed` | `source_metadata` | Official source metadata only; no execution or interoperability claim. | `unknown-no-runtime`, `unknown-upstream-custody` | [cite-a2a](https://a2a-protocol.org/latest/specification/) |
| `agent_protocol` | `acp.session_lifecycle` | `agent-client-protocol` | `declared` | `not_observed` | `source_metadata` | Official source metadata only; no execution or interoperability claim. | `unknown-no-runtime` | [cite-acp](https://github.com/agentclientprotocol/agent-client-protocol) |
| `coding_cli` | `claude_code.permission_surface` | `claude-code-cli` | `declared` | `not_observed` | `source_metadata` | Official source metadata only; no execution or interoperability claim. | `unknown-no-runtime`, `unknown-upstream-custody` | [cite-claude-code](https://github.com/anthropics/claude-code/releases) |
| `coding_cli` | `codex_cli.approval_surface` | `codex-cli` | `declared` | `not_observed` | `source_metadata` | Official source metadata only; no execution or interoperability claim. | `unknown-no-runtime`, `unknown-upstream-custody` | [cite-codex-cli](https://github.com/openai/codex) |
| `coding_cli` | `gemini_cli.approval_mode` | `gemini-cli` | `declared` | `not_observed` | `source_metadata` | Official source metadata only; no execution or interoperability claim. | `unknown-no-runtime`, `unknown-upstream-custody` | [cite-gemini-cli](https://github.com/google-gemini/gemini-cli) |
| `sdk_runtime` | `google_adk.sub_agents` | `google-adk` | `declared` | `not_observed` | `source_metadata` | Official source metadata only; no execution or interoperability claim. | `unknown-no-runtime`, `unknown-upstream-custody` | [cite-google-adk](https://github.com/google/adk-python) |
| `graph_orchestrator` | `langgraph.checkpoint_store` | `langgraph` | `declared` | `not_observed` | `source_metadata` | Official source metadata only; no execution or interoperability claim. | `unknown-no-runtime`, `unknown-upstream-custody` | [cite-langgraph](https://github.com/langchain-ai/langgraph) |
| `graph_orchestrator` | `langgraph.graph_state` | `langgraph` | `declared` | `not_observed` | `source_metadata` | Official source metadata only; no execution or interoperability claim. | `unknown-no-runtime`, `unknown-upstream-custody` | [cite-langgraph](https://github.com/langchain-ai/langgraph) |
| `graph_orchestrator` | `langgraph.interrupt_resume` | `langgraph` | `declared` | `not_observed` | `source_metadata` | Official source metadata only; no execution or interoperability claim. | `unknown-no-runtime`, `unknown-upstream-custody` | [cite-langgraph](https://github.com/langchain-ai/langgraph) |
| `tool_protocol` | `mcp.tools_resources_prompts` | `mcp` | `declared` | `not_observed` | `source_metadata` | Official source metadata only; no execution or interoperability claim. | `unknown-no-runtime`, `unknown-upstream-custody` | [cite-mcp](https://modelcontextprotocol.io/specification) |
| `native_scaffold` | `native.bare.single_shot` | `bare single shot` | `declared` | `not_observed` | `source_metadata` | Source and synthetic metadata only; no execution or interoperability claim. | `unknown-no-runtime` | [cite-native-fixture](https://github.com/jlov7/scaffold-arena/blob/4fe131587919edec8e709df921c8dbc4e8eecdab/backend/genome_v1/fixtures/native-genome-v1.json), [cite-native-models](https://github.com/jlov7/scaffold-arena/blob/4fe131587919edec8e709df921c8dbc4e8eecdab/backend/genome_v1/models.py) |
| `native_scaffold` | `native.memory_critique` | `memory critique` | `declared` | `not_observed` | `source_metadata` | Source metadata only; no execution or interoperability claim. | `unknown-no-runtime` | [cite-native-models](https://github.com/jlov7/scaffold-arena/blob/4fe131587919edec8e709df921c8dbc4e8eecdab/backend/genome_v1/models.py) |
| `native_scaffold` | `native.plan_execute_verify` | `plan execute verify` | `declared` | `not_observed` | `source_metadata` | Source metadata only; no execution or interoperability claim. | `unknown-no-runtime` | [cite-native-models](https://github.com/jlov7/scaffold-arena/blob/4fe131587919edec8e709df921c8dbc4e8eecdab/backend/genome_v1/models.py) |
| `native_scaffold` | `native.tool_error_recovery` | `tool error recovery` | `declared` | `not_observed` | `source_metadata` | Source metadata only; no execution or interoperability claim. | `unknown-no-runtime` | [cite-native-models](https://github.com/jlov7/scaffold-arena/blob/4fe131587919edec8e709df921c8dbc4e8eecdab/backend/genome_v1/models.py) |
| `sdk_runtime` | `openai_agents.agent_loop` | `openai-agents-sdk` | `declared` | `not_observed` | `source_metadata` | Official source metadata only; no execution or interoperability claim. | `unknown-no-runtime`, `unknown-upstream-custody` | [cite-openai-agents](https://github.com/openai/openai-agents-python) |
| `sdk_runtime` | `openai_agents.guardrail` | `openai-agents-sdk` | `declared` | `not_observed` | `source_metadata` | Official source metadata only; no execution or interoperability claim. | `unknown-no-runtime`, `unknown-upstream-custody` | [cite-openai-agents](https://github.com/openai/openai-agents-python) |
| `sdk_runtime` | `openai_agents.handoff` | `openai-agents-sdk` | `declared` | `not_observed` | `source_metadata` | Official source metadata only; no execution or interoperability claim. | `unknown-no-runtime`, `unknown-upstream-custody` | [cite-openai-agents](https://github.com/openai/openai-agents-python) |
| `telemetry_surface` | `otel.gen_ai_semconv` | `otel-genai` | `declared` | `not_observed` | `source_metadata` | Official source metadata only; no execution or interoperability claim. | `unknown-no-runtime`, `unknown-upstream-custody` | [cite-otel-genai](https://github.com/open-telemetry/semantic-conventions-genai) |

## Evidence and unknowns

Every record is integrity-not-truth custody metadata. No current observation is a live runtime observation.

| Evidence | Kind | Maturity | Limitations |
| --- | --- | --- | --- |
| `ev-a2a` | `official_source_metadata` | `source_metadata` | No remote task execution evidence. |
| `ev-acp` | `official_source_metadata` | `source_metadata` | No operator receipt or runtime evidence. |
| `ev-claude-code` | `official_source_metadata` | `source_metadata` | No command execution evidence. |
| `ev-codex-cli` | `official_source_metadata` | `source_metadata` | No local process or containment evidence. |
| `ev-gemini-cli` | `official_source_metadata` | `source_metadata` | No shell or sandbox evidence. |
| `ev-google-adk` | `official_source_metadata` | `source_metadata` | No runtime or deployment evidence. |
| `ev-langgraph` | `official_source_metadata` | `source_metadata` | No graph replay or persistence equivalence evidence. |
| `ev-mcp` | `official_source_metadata` | `source_metadata` | No protocol runtime evidence. |
| `ev-native-fixture` | `synthetic_fixture_metadata` | `synthetic_fixture` | Fixture bytes are integrity custody, not runtime truth. |
| `ev-native-source` | `local_source_snapshot` | `source_metadata` | Local source identity is not an activation record. |
| `ev-openai-agents` | `official_source_metadata` | `source_metadata` | No SDK invocation or trace evidence. |
| `ev-otel-genai` | `official_source_metadata` | `source_metadata` | No collector, exporter, or trace evidence. |

## Reproduce and verify

```bash
uv run --project backend python scripts/generate-protocol-v1-schemas.py --check
uv run --project backend python scripts/generate-harness-mechanism-atlas.py --check
uv run --project backend python scripts/validate-harness-mechanism-atlas.py --release-digest release/harness-mechanism-atlas-v1.digest.json
```

A release requires a real keyless signature bundle created by the tag workflow. Until then the release-signature state is `HOLD_RELEASE_SIGNATURE_REQUIRED`.
