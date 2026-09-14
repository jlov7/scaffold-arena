"""Risk analysis task: must-flag clauses and recommendations for a cloud services agreement."""

from tasks.base import BaseTask


class RiskAnalysisTask(BaseTask):
    id = "risk"
    name = "Risk Analysis"
    subtitle = "Must-flag clauses + recommendations"
    task_type = "risk"
    synthetic_sources = False

    def get_input_text(self) -> str:
        return """CLOUD SERVICES AGREEMENT — KEY TERMS

1. SERVICE LEVELS: Provider guarantees 99.5% monthly uptime for core services. Downtime for scheduled maintenance (up to 8 hours per month, with 48 hours notice) is excluded from uptime calculations. Credits for SLA breaches are limited to 10% of monthly fees.

2. DATA HANDLING: All Client data remains Client's property. Provider may use anonymized, aggregated data derived from Client's usage for service improvement and benchmarking purposes. Upon termination, Provider will make Client data available for download for 30 days, after which data will be permanently deleted.

3. INTELLECTUAL PROPERTY: Any custom configurations, workflows, or integrations developed by Provider specifically for Client shall be owned by Provider. Client receives a non-exclusive, non-transferable license to use such developments during the term of this agreement.

4. LIABILITY: Provider's total liability shall not exceed fees paid in the three (3) months preceding the claim. Provider is not liable for indirect, consequential, or punitive damages, including lost profits, data loss, or business interruption, regardless of cause.

5. TERMINATION: Either party may terminate with 90 days written notice. Provider may terminate immediately for non-payment exceeding 60 days. Upon termination by Provider for any reason other than Client breach, all prepaid fees shall be refunded on a pro-rata basis.

6. INDEMNIFICATION: Client shall indemnify Provider against all claims arising from Client's use of the services, including any regulatory fines or penalties. Provider's indemnification obligation is limited to claims arising from Provider's gross negligence or willful misconduct.

7. GOVERNING LAW: This agreement shall be governed by the laws of the State of Delaware. Any disputes shall be resolved through binding arbitration in Wilmington, Delaware, with each party bearing its own costs.

8. AUTO-RENEWAL: This agreement automatically renews for successive twelve-month periods unless either party provides written notice of non-renewal at least 60 days prior to the end of the then-current term.

9. MODIFICATION: Provider reserves the right to modify service features and pricing with 30 days notice. Continued use after such notice constitutes acceptance. Material changes to these terms require mutual written consent."""

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "required": ["risk_items", "overall_risk_score", "top_3_priorities", "negotiation_leverage_points"],
            "properties": {
                "risk_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["clause_number", "clause_title", "risk_level", "risk_description", "specific_concern", "recommendation"],
                        "properties": {
                            "clause_number": {"type": "string"},
                            "clause_title": {"type": "string"},
                            "risk_level": {"type": "string", "enum": ["high", "medium", "low"]},
                            "risk_description": {"type": "string"},
                            "specific_concern": {"type": "string"},
                            "recommendation": {"type": "string"},
                        },
                    },
                },
                "overall_risk_score": {"type": "number"},
                "top_3_priorities": {"type": "array", "minItems": 3, "items": {"type": "string"}},
                "negotiation_leverage_points": {"type": "array", "items": {"type": "string"}},
            },
        }

    def get_gold(self) -> list:
        return [
            {"clause": "2", "level": "high", "keywords": ["benchmarking", "anonymized", "aggregated data"]},
            {"clause": "3", "level": "high", "keywords": ["IP ownership", "owned by Provider"]},
            {"clause": "4", "level": "high", "keywords": ["3-month", "liability cap", "data loss", "consequential"]},
            {"clause": "6", "level": "high", "keywords": ["asymmetric", "indemnification", "client indemnifies"]},
            {"clause": "9", "level": "high", "keywords": ["unilateral", "pricing", "modification"]},
            {"clause": "1", "level": "medium", "keywords": ["99.5%", "uptime", "credit cap", "10%"]},
            {"clause": "2", "level": "medium", "keywords": ["30-day", "data download", "termination"]},
            {"clause": "7", "level": "medium", "keywords": ["binding arbitration", "Delaware"]},
            {"clause": "8", "level": "low", "keywords": ["auto-renewal", "60-day"]},
        ]
