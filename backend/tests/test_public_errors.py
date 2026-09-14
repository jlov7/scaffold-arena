from __future__ import annotations

from api.public_errors import public_service_error


class SyntheticProviderError(Exception):
    code = "provider_rejection"
    status_code = 502

    def __str__(self) -> str:
        return "Traceback /srv/secret.py SELECT * FROM keys digest=deadbeef Authorization: Bearer sk-live"


def test_public_service_errors_use_static_messages_and_safe_codes() -> None:
    response = public_service_error(SyntheticProviderError())
    body = response.body.decode()

    assert response.status_code == 502
    assert '"code":"provider_rejection"' in body
    assert '"message":"The service is temporarily unavailable."' in body
    for value in ("Traceback", "/srv", "SELECT", "deadbeef", "Bearer", "sk-live"):
        assert value not in body
