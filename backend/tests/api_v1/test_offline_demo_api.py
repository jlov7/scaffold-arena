from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from api.v1.offline_demo import OfflineDemoError, _require_local_request, router


def test_offline_demo_api_is_unavailable_without_the_personal_profile_service() -> None:
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).post("/api/v1/offline-demo")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "offline_demo_unavailable"


def test_offline_demo_rejects_nonlocal_peer_and_nonlocal_origin() -> None:
    remote = Request({"type": "http", "headers": [(b"host", b"127.0.0.1")], "client": ("203.0.113.9", 1234), "scheme": "http", "method": "POST", "path": "/api/v1/offline-demo"})
    with pytest.raises(OfflineDemoError, match="direct loopback"):
        _require_local_request(remote)
    origin = Request({"type": "http", "headers": [(b"host", b"127.0.0.1"), (b"origin", b"https://example.test")], "client": ("127.0.0.1", 1234), "scheme": "http", "method": "POST", "path": "/api/v1/offline-demo"})
    with pytest.raises(OfflineDemoError, match="loopback browser origin"):
        _require_local_request(origin)
