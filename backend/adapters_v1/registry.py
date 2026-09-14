"""In-memory trusted installation registry; it never imports adapter code."""

from __future__ import annotations

from .base import HarnessAdapter
from .models import AdapterCapabilities


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, tuple[str, HarnessAdapter]] = {}
        self._capabilities: dict[str, AdapterCapabilities] = {}

    async def install_trusted(self, adapter: HarnessAdapter, expected_digest: str) -> AdapterCapabilities:
        capabilities = await adapter.describe_capabilities()
        if capabilities.adapter_digest != expected_digest:
            raise ValueError("trusted installation digest mismatch")
        if capabilities.adapter_id in self._adapters:
            raise ValueError("adapter id is already installed; replacement requires a new registry")
        self._adapters[capabilities.adapter_id] = (capabilities.adapter_digest, adapter)
        self._capabilities[capabilities.adapter_id] = capabilities
        return capabilities

    def get(self, adapter_id: str, digest: str) -> HarnessAdapter:
        try:
            installed_digest, adapter = self._adapters[adapter_id]
        except KeyError as exc:
            raise KeyError("adapter is not explicitly trusted and installed") from exc
        if installed_digest != digest:
            raise ValueError("requested adapter digest does not match trusted installation")
        return adapter

    def capabilities(self, adapter_id: str, digest: str) -> AdapterCapabilities:
        """Return the installation-time capability snapshot without invoking an adapter.

        Registry preflight is intentionally synchronous and must never wake a
        provider merely to discover what an already-installed adapter declared.
        """
        self.get(adapter_id, digest)
        try:
            installed_digest, _ = self._adapters[adapter_id]
        except KeyError as exc:  # defensive; get() above gives the public error.
            raise KeyError("adapter is not explicitly trusted and installed") from exc
        if installed_digest != digest:
            raise ValueError("requested adapter digest does not match trusted installation")
        # install_trusted validated this value before committing the entry. Do
        # not re-await describe_capabilities here: that could be a provider call
        # in a third-party implementation.
        return self._capabilities[adapter_id]
