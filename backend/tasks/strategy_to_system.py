"""Strategy-to-system task: compile strategy memo into an implementation plan."""

from tasks.base import BaseTask


class StrategyToSystemTask(BaseTask):
    id = "strategy_to_system"
    name = "Strategy To System"
    subtitle = "Memo to architecture, evals, and backlog"
    task_type = "strategy"
    synthetic_sources = True

    def get_input_text(self) -> str:
        return """SYNTHETIC STRATEGY MEMO

We want to launch an internal AI analyst that summarizes customer calls, extracts follow-up obligations, and proposes risk flags for account teams. The system must not expose raw call transcripts outside the account workspace. Leadership wants faster account prep, but legal requires an audit trail and human review before customer-facing follow-up. The first release should support 30 enterprise accounts, stay under $0.40 per analyzed call, and allow rollback if risk flags become noisy.

Compile this memo into:
- architecture decisions
- assumptions
- risks
- eval plan
- implementation backlog
- success metrics
- open questions"""

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "required": [
                "architecture_decisions",
                "assumptions",
                "risks",
                "eval_plan",
                "implementation_backlog",
                "success_metrics",
                "open_questions",
            ],
            "properties": {
                "architecture_decisions": {"type": "array", "items": {"type": "string"}},
                "assumptions": {"type": "array", "items": {"type": "string"}},
                "risks": {"type": "array", "items": {"type": "string"}},
                "eval_plan": {"type": "array", "items": {"type": "string"}},
                "implementation_backlog": {"type": "array", "items": {"type": "string"}},
                "success_metrics": {"type": "array", "items": {"type": "string"}},
                "open_questions": {"type": "array", "items": {"type": "string"}},
            },
        }

    def get_gold(self) -> dict:
        return {
            "required_sections": [
                "architecture_decisions",
                "assumptions",
                "risks",
                "eval_plan",
                "implementation_backlog",
                "success_metrics",
                "open_questions",
            ],
            "required_terms": [
                "audit trail",
                "human review",
                "raw call transcripts",
                "$0.40",
                "rollback",
                "risk flags",
            ],
            "forbidden_terms": [
                "guaranteed 40% productivity",
                "40% productivity lift",
                "guaranteed",
            ],
        }
