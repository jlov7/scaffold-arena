# Trace-Driven Frontier Audit

## Summary

- Runs audited: 2
- Scaffold results audited: 3
- Findings: 9

## Severity Summary

| Severity | Count |
| --- | ---: |
| critical | 0 |
| high | 8 |
| medium | 1 |
| low | 0 |
| info | 0 |

## Failure Taxonomy

| Type | Count |
| --- | ---: |
| `low_total_score` | 2 |
| `extraction_wrong_values` | 1 |
| `research_missing_citations` | 1 |
| `research_missing_required_findings` | 1 |
| `schema_missing_required_fields` | 1 |
| `schema_validity_low` | 1 |
| `winner_not_highest_score` | 1 |
| `zero_cost_with_token_usage` | 1 |

## Findings

### [HIGH] `extraction_wrong_values`

- Scope: `run_audit_001 / bare`
- Task: `extraction`
- Model: `claude-sonnet-4-6`
- Evidence: Metric field_accuracy scored 30.
- Recommendation: Add or update an extraction regression case that checks the missed field values.
- Regression key: `extraction.bare.extraction_wrong_values`

### [HIGH] `low_total_score`

- Scope: `run_audit_001 / bare`
- Task: `extraction`
- Model: `claude-sonnet-4-6`
- Evidence: Evaluation total_score is 42.
- Recommendation: Queue autopsy, patch, and rerun before treating this scaffold as production evidence.
- Regression key: `extraction.bare.low_total_score`

### [HIGH] `schema_missing_required_fields`

- Scope: `run_audit_001 / bare`
- Task: `extraction`
- Model: `claude-sonnet-4-6`
- Evidence: Evaluation notes mention missing required fields: Missing required fields: effective_date, renewal_term; Incorrect value: notice period
- Recommendation: Promote this note into a fixture-level schema regression.
- Regression key: `extraction.bare.schema_missing_required_fields`

### [HIGH] `schema_validity_low`

- Scope: `run_audit_001 / bare`
- Task: `extraction`
- Model: `claude-sonnet-4-6`
- Evidence: Metric schema_validity scored 45.
- Recommendation: Treat schema validity as a blocking regression before trusting downstream scoring.
- Regression key: `extraction.bare.schema_validity_low`

### [HIGH] `winner_not_highest_score`

- Scope: `run_audit_001 / bare`
- Task: `extraction`
- Model: `claude-sonnet-4-6`
- Evidence: Winner bare scored 42, but plan_execute_verify scored 88.
- Recommendation: Add a winner-selection regression using this run as a fixture.
- Regression key: `extraction.bare.winner_not_highest_score`

### [HIGH] `zero_cost_with_token_usage`

- Scope: `run_audit_001 / bare`
- Task: `extraction`
- Model: `claude-sonnet-4-6`
- Evidence: Metrics show 1560 tokens but cost_usd is 0.0.
- Recommendation: Recompute cost from provider usage via the centralized model price table.
- Regression key: `extraction.bare.zero_cost_with_token_usage`

### [HIGH] `research_missing_citations`

- Scope: `run_audit_002 / tool_error_recovery`
- Task: `research_synthesis`
- Model: `claude-sonnet-4-6`
- Evidence: Metric citation_coverage scored 35. Evaluation notes mention citation gaps: Missing citations for two market-size claims
- Recommendation: Add a research-synthesis regression that requires source-backed claims. Require source-backed claims in the research regression fixture.
- Regression key: `research_synthesis.tool_error_recovery.research_missing_citations`

### [HIGH] `research_missing_required_findings`

- Scope: `run_audit_002 / tool_error_recovery`
- Task: `research_synthesis`
- Model: `claude-sonnet-4-6`
- Evidence: Metric required_findings_coverage scored 58.
- Recommendation: Add a research-synthesis regression for the missing required findings.
- Regression key: `research_synthesis.tool_error_recovery.research_missing_required_findings`

### [MEDIUM] `low_total_score`

- Scope: `run_audit_002 / tool_error_recovery`
- Task: `research_synthesis`
- Model: `claude-sonnet-4-6`
- Evidence: Evaluation total_score is 63.
- Recommendation: Queue autopsy, patch, and rerun before treating this scaffold as production evidence.
- Regression key: `research_synthesis.tool_error_recovery.low_total_score`
