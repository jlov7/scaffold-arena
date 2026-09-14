"""Pinned Pi external-harness wrapper."""

from .base import PinnedExternalAdapter, UpstreamRelease

PI_RELEASE = UpstreamRelease(
    name="Pi",
    source_url="https://github.com/earendil-works/pi",
    version="v0.84.2",
    commit="914cf1472e715297caa30db4b9535d534a9eb718",
    maturity="pinned external release",
)


class PiAdapter(PinnedExternalAdapter):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(adapter_id="pi-external", release=PI_RELEASE, **kwargs)
