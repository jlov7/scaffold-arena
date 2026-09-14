"""Fixture-only adapter conformance certification.

Certification is evidence about one adapter implementation and fixture.  It
never upgrades a fixture/protocol adapter into a live-provider claim.
"""

from .kit import certify_adapter

__all__ = ["certify_adapter"]
