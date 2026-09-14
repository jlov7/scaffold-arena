"""Pinned Prime Agent external-harness wrapper."""

from .base import PinnedExternalAdapter, UpstreamRelease

PRIME_AGENT_RELEASE = UpstreamRelease(
    name="Prime Agent",
    source_url="https://github.com/PrimeIntellect-ai/prime-agent",
    version="v0.7.2",
    commit="83a0f9f9566219551fcb6ffaf7f519a815749a58",
    maturity="pinned external release",
)


class PrimeAgentAdapter(PinnedExternalAdapter):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(adapter_id="prime-agent-external", release=PRIME_AGENT_RELEASE, **kwargs)
