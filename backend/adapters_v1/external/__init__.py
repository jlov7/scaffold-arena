"""Pinned, fail-closed wrappers for externally managed harnesses."""

from .base import (
    ExternalHarnessTransport,
    ExternalOciEvidence,
    OciEvidenceProbe,
    PinnedExternalAdapter,
    UpstreamRelease,
)
from .deepseek import DEEPSEEK_HARNESS_RELEASE, DeepSeekHarnessAdapter
from .pi import PI_RELEASE, PiAdapter
from .prime import PRIME_AGENT_RELEASE, PrimeAgentAdapter

__all__ = [
    "DEEPSEEK_HARNESS_RELEASE",
    "PI_RELEASE",
    "PRIME_AGENT_RELEASE",
    "DeepSeekHarnessAdapter",
    "ExternalHarnessTransport",
    "ExternalOciEvidence",
    "OciEvidenceProbe",
    "PiAdapter",
    "PinnedExternalAdapter",
    "PrimeAgentAdapter",
    "UpstreamRelease",
]
