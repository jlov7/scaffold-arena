"""Structured extraction task: schema-valid JSON extraction from a legal document."""

from tasks.base import BaseTask


class ExtractionTask(BaseTask):
    id = "extraction"
    name = "Structured Extraction"
    subtitle = "Schema-valid JSON extraction"
    task_type = "extraction"
    synthetic_sources = False

    def get_input_text(self) -> str:
        return """AMENDMENT TO SERVICE AGREEMENT

This Amendment ("Amendment") is entered into as of March 15, 2025, by and between TechFlow Solutions Inc., a Delaware corporation with principal offices at 2847 Innovation Drive, Suite 400, Austin, TX 78701 ("Provider"), and Meridian Healthcare Group, LLC, a California limited liability company with principal offices at 1200 Harbor Boulevard, Floor 12, San Francisco, CA 94111 ("Client").

WHEREAS, Provider and Client entered into a Master Service Agreement dated September 1, 2023 (the "Original Agreement"); and WHEREAS, the parties wish to modify certain terms of the Original Agreement;

NOW, THEREFORE, the parties agree as follows:

1. SCOPE MODIFICATION: Section 3.2 of the Original Agreement is hereby amended to include artificial intelligence consulting services, including but not limited to: model evaluation, deployment architecture review, and ongoing performance monitoring.

2. FEE ADJUSTMENT: The monthly retainer specified in Section 5.1 is increased from $45,000 to $78,500 per month, effective April 1, 2025. Additionally, a one-time implementation fee of $125,000 shall be due within 30 days of this Amendment's execution.

3. TERM EXTENSION: The term of the Original Agreement is extended by twenty-four (24) months from its current expiration date of December 31, 2025, to December 31, 2027.

4. DATA PROTECTION: Provider shall comply with all applicable data protection regulations including HIPAA, CCPA, and SOC 2 Type II requirements. Provider shall maintain cyber liability insurance with minimum coverage of $5,000,000.

5. LIMITATION OF LIABILITY: Provider's total aggregate liability under this Amendment shall not exceed the total fees paid by Client in the twelve (12) months preceding any claim.

All other terms and conditions of the Original Agreement shall remain in full force and effect."""

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "required": [
                "document_type",
                "effective_date",
                "parties",
                "references_agreement",
                "amendments",
                "compliance_requirements",
                "financial_summary",
                "new_expiration_date",
            ],
            "properties": {
                "document_type": {"type": "string"},
                "effective_date": {"type": "string"},
                "parties": {
                    "type": "array",
                    "minItems": 2,
                    "items": {
                        "type": "object",
                        "required": ["name", "role", "entity_type", "jurisdiction", "address"],
                        "properties": {
                            "name": {"type": "string"},
                            "role": {"type": "string"},
                            "entity_type": {"type": "string"},
                            "jurisdiction": {"type": "string"},
                            "address": {"type": "string"},
                        },
                    },
                },
                "references_agreement": {
                    "type": "object",
                    "required": ["name", "date"],
                    "properties": {
                        "name": {"type": "string"},
                        "date": {"type": "string"},
                    },
                },
                "amendments": {
                    "type": "array",
                    "minItems": 3,
                    "items": {
                        "type": "object",
                        "required": ["section", "type", "summary", "key_values"],
                        "properties": {
                            "section": {"type": "string"},
                            "type": {"type": "string"},
                            "summary": {"type": "string"},
                            "key_values": {"type": "object"},
                        },
                    },
                },
                "compliance_requirements": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "financial_summary": {
                    "type": "object",
                    "required": [
                        "monthly_retainer_old",
                        "monthly_retainer_new",
                        "one_time_fees",
                        "liability_cap",
                        "insurance_minimum",
                    ],
                    "properties": {
                        "monthly_retainer_old": {"type": "number"},
                        "monthly_retainer_new": {"type": "number"},
                        "one_time_fees": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["amount", "description"],
                                "properties": {
                                    "amount": {"type": "number"},
                                    "description": {"type": "string"},
                                },
                            },
                        },
                        "liability_cap": {"type": "string"},
                        "insurance_minimum": {"type": "number"},
                    },
                },
                "new_expiration_date": {"type": "string"},
            },
        }

    def get_gold(self) -> dict:
        return {
            "document_type": "Amendment to Service Agreement",
            "effective_date": "2025-03-15",
            "parties": [
                {
                    "name": "TechFlow Solutions Inc.",
                    "role": "Provider",
                    "entity_type": "corporation",
                    "jurisdiction": "Delaware",
                    "address": "2847 Innovation Drive, Suite 400, Austin, TX 78701",
                },
                {
                    "name": "Meridian Healthcare Group, LLC",
                    "role": "Client",
                    "entity_type": "limited liability company",
                    "jurisdiction": "California",
                    "address": "1200 Harbor Boulevard, Floor 12, San Francisco, CA 94111",
                },
            ],
            "references_agreement": {
                "name": "Master Service Agreement",
                "date": "2023-09-01",
            },
            "new_expiration_date": "2027-12-31",
            "compliance_requirements": ["HIPAA", "CCPA", "SOC 2 Type II"],
            "financial_summary": {
                "monthly_retainer_old": 45000,
                "monthly_retainer_new": 78500,
                "one_time_fees": [
                    {
                        "amount": 125000,
                        "description": "Implementation fee due within 30 days",
                    }
                ],
                "liability_cap": "Total fees paid in the 12 months preceding any claim",
                "insurance_minimum": 5000000,
            },
        }
