"""Process-local capability for the trusted offline-demo launcher.

This state is intentionally not configuration or an environment variable.
Only ``arena serve --enable-offline-demo`` may enable it after validating a
literal loopback bind in the same process that imports the ASGI application.
"""

from __future__ import annotations

_local_offline_demo_capability = False


def enable_local_offline_demo_capability() -> None:
    global _local_offline_demo_capability
    _local_offline_demo_capability = True


def local_offline_demo_capability_enabled() -> bool:
    return _local_offline_demo_capability
