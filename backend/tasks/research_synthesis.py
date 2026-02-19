"""Research synthesis task: synthesize multi-source findings into a structured briefing."""

from tasks.base import BaseTask


class ResearchSynthesisTask(BaseTask):
    id = "research"
    name = "Research Synthesis"
    subtitle = "Synthetic sources (demo only)"
    task_type = "research"
    synthetic_sources = True

    def get_input_text(self) -> str:
        return """Synthesize the following research findings into a coherent briefing on the current state of LLM agent reliability for enterprise deployment. Cite specific findings by their source labels.

[SOURCE A - MIT/Stanford Survey 2025]
Survey of 847 enterprise deployments found that 67% of LLM agent failures occur not in the model's reasoning but in the orchestration layer — tool selection errors (31%), context window overflow (22%), and retry logic failures (14%). Only 18% of failures were attributable to model capability limitations. Organizations with structured agent scaffolding reported 3.2x fewer production incidents than those using raw API calls.

[SOURCE B - Gartner Hype Cycle Analysis Q3 2025]
LLM agents have moved from "Peak of Inflated Expectations" to "Trough of Disillusionment" for 62% of surveyed organizations. However, the 15% that report being in "Slope of Enlightenment" share a common trait: they invested in agent testing infrastructure before scaling deployment. Average time to production for tested agents: 4.2 months. For untested: 11.7 months (but with 4.1x higher post-deployment failure rates).

[SOURCE C - Anthropic Technical Report on Agent Architectures 2025]
Comparing 12 agent scaffold patterns across 1,847 tasks, the study found that adding a verification gate improved task completion by 23% on average, while adding self-critique improved quality scores by 18%. The combination of both yielded 34% improvement — less than the sum, suggesting partial overlap in failure modes addressed. Memory-augmented scaffolds showed the largest gains on multi-step tasks (41% improvement) but minimal benefit on single-step tasks (3%).

[SOURCE D - McKinsey Digital Practice Survey 2025]
78% of Fortune 500 companies have piloted LLM agents; only 12% have deployed at scale. Top barriers: reliability concerns (cited by 71%), integration complexity (58%), and lack of evaluation frameworks (52%). Companies that deployed successfully spent on average 2.3x more on agent testing and scaffolding than on model fine-tuning or selection."""

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "required": ["executive_summary", "key_findings", "synthesis", "recommendations", "source_reliability_notes"],
            "properties": {
                "executive_summary": {"type": "string"},
                "key_findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["finding", "sources", "confidence", "enterprise_implication"],
                        "properties": {
                            "finding": {"type": "string"},
                            "sources": {"type": "array", "items": {"type": "string"}},
                            "confidence": {"type": "string"},
                            "enterprise_implication": {"type": "string"},
                        },
                    },
                },
                "synthesis": {"type": "string"},
                "recommendations": {"type": "array", "items": {"type": "string"}},
                "source_reliability_notes": {"type": "string"},
            },
        }

    def get_gold(self) -> dict:
        return {
            "required_findings": [
                {"id": 1, "description": "Most failures occur in orchestration layer", "source": "A", "keywords": ["orchestration", "67%", "failures"]},
                {"id": 2, "description": "Tool selection + context overflow + retry failures breakdown", "source": "A", "keywords": ["tool selection", "31%", "context", "22%", "retry", "14%"]},
                {"id": 3, "description": "Testing infrastructure predicts production success", "source": "B", "keywords": ["testing", "infrastructure", "4.2", "11.7"]},
                {"id": 4, "description": "Verification gates improve completion", "source": "C", "keywords": ["verification", "23%", "gate"]},
                {"id": 5, "description": "Memory helps multi-step tasks, minimal benefit single-step", "source": "C", "keywords": ["memory", "multi-step", "41%", "3%"]},
                {"id": 6, "description": "Scaffolding/testing spend correlates with scaled deployment", "source": "D", "keywords": ["2.3x", "scaffolding", "testing"]},
            ],
            "required_sources": ["A", "B", "C", "D"],
        }
