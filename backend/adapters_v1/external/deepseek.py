"""Pinned experimental official DeepSeek Harness wrapper."""

from .base import PinnedExternalAdapter, UpstreamRelease

DEEPSEEK_HARNESS_RELEASE = UpstreamRelease(
    name="DeepSeek Harness",
    source_url="https://github.com/deepseek-ai/deepseek-harness",
    version="developer-preview-0.1.0-rc.5",
    commit="47f943859bef60e4160492346772ded9b24f765a",
    maturity="experimental developer preview; protocol-only",
)


class DeepSeekHarnessAdapter(PinnedExternalAdapter):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(adapter_id="deepseek-harness-external", release=DEEPSEEK_HARNESS_RELEASE, preview_only=True, **kwargs)
