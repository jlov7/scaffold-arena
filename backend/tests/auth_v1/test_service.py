from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from joserfc import jwt
from joserfc.errors import InvalidClaimError
from joserfc.jwk import RSAKey

from auth_v1.service import AuthError, AuthlibOIDCProvider, AuthService, OIDCIdentity
from config.settings import Settings
from persistence_v1 import ArenaRepository, AuthRepository, create_persistence_engine
from persistence_v1.schema import metadata


class FakeProvider:
    def __init__(self) -> None:
        self.exchanges: list[tuple[str, str, str]] = []

    async def authorization_url(self, *, state: str, nonce: str, code_challenge: str, redirect_uri: str) -> str:
        return f"https://issuer.example/authorize?state={state}&nonce={nonce}&code_challenge={code_challenge}&code_challenge_method=S256"

    async def exchange(self, *, code: str, code_verifier: str, nonce: str, redirect_uri: str) -> OIDCIdentity:
        self.exchanges.append((code, code_verifier, nonce))
        return OIDCIdentity("https://issuer.example", "subject-one", "person@example.test", "Person")


def _service(tmp_path):
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    metadata.create_all(engine)
    provider = FakeProvider()
    settings = Settings(
        protocol_v1_deployment_profile="team", protocol_v1_database_url="postgresql://example.invalid/arena",
        protocol_v1_oidc_issuer="https://issuer.example", protocol_v1_oidc_client_id="client",
        protocol_v1_oidc_redirect_uri="https://arena.example/api/v1/callback",
        protocol_v1_oidc_allowed_redirect_uris="https://arena.example/api/v1/callback",
        protocol_v1_session_secret="x" * 32, protocol_v1_session_cookie_secure=True,
    )
    return AuthService(AuthRepository(ArenaRepository(engine)), settings, provider), provider


@pytest.mark.asyncio
async def test_callback_requires_its_own_browser_transaction_and_is_single_use(tmp_path) -> None:
    service, provider = _service(tmp_path)
    started = await service.start_login(request_id="request-one")
    state = parse_qs(urlparse(started.authorization_url).query)["state"][0]
    with pytest.raises(AuthError, match="initiating browser transaction"):
        await service.complete_login(state=state, code="code", browser_transaction=None, request_id="request-two")
    with pytest.raises(AuthError, match="state or browser transaction"):
        await service.complete_login(state=state, code="code", browser_transaction="wrong", request_id="request-three")
    token, principal = await service.complete_login(state=state, code="code", browser_transaction=started.browser_transaction, request_id="request-four")
    assert principal.subject == "subject-one"
    assert service.principal(token) is not None
    assert len(provider.exchanges) == 1
    with pytest.raises(AuthError, match="state or browser transaction"):
        await service.complete_login(state=state, code="code", browser_transaction=started.browser_transaction, request_id="request-five")
    assert len(provider.exchanges) == 1


@pytest.mark.asyncio
async def test_pkce_and_session_rotation_revoke_the_old_session(tmp_path) -> None:
    service, provider = _service(tmp_path)
    started = await service.start_login(request_id="request-one")
    query = parse_qs(urlparse(started.authorization_url).query)
    assert query["code_challenge_method"] == ["S256"]
    first_token, first = await service.complete_login(state=query["state"][0], code="one", browser_transaction=started.browser_transaction, request_id="request-two")
    second_started = await service.start_login(request_id="request-three")
    second_state = parse_qs(urlparse(second_started.authorization_url).query)["state"][0]
    second_token, second = await service.complete_login(state=second_state, code="two", browser_transaction=second_started.browser_transaction, prior_cookie=first_token, request_id="request-four")
    assert first.session_id != second.session_id
    assert service.principal(first_token) is None
    assert service.principal(second_token) is not None
    assert len(provider.exchanges) == 2


def test_team_configuration_fails_closed_without_secure_complete_inputs() -> None:
    with pytest.raises(RuntimeError, match="team deployment configuration missing"):
        Settings(protocol_v1_deployment_profile="team").validate_protocol_v1_team_configuration()
    configured = Settings(
        protocol_v1_deployment_profile="team", protocol_v1_database_url="sqlite:///not-team.db",
        protocol_v1_oidc_issuer="https://issuer.example", protocol_v1_oidc_client_id="client",
        protocol_v1_oidc_redirect_uri="https://arena.example/api/v1/callback",
        protocol_v1_oidc_allowed_redirect_uris="https://arena.example/api/v1/callback",
        protocol_v1_session_secret="x" * 32, protocol_v1_session_cookie_secure=True,
    )
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        configured.validate_protocol_v1_team_configuration()


def test_id_token_validation_accepts_only_advertised_safe_algorithms_and_bound_claims() -> None:
    provider = AuthlibOIDCProvider("https://issuer.example", "client")
    key = RSAKey.generate_key(2048, private=True)
    public_key = key.as_dict(private=False)
    public_key["kid"] = "signing-key"
    claims = {
        "iss": "https://issuer.example",
        "aud": "client",
        "sub": "subject-one",
        "nonce": "nonce-one",
        "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
    }
    encoded = jwt.encode({"alg": "RS256", "kid": "signing-key"}, claims, key)

    validated = provider._validate_id_token(
        encoded,
        keys={"keys": [public_key]},
        advertised_algorithms=["none", "HS256", "RS256"],
        nonce="nonce-one",
    )
    assert validated["sub"] == "subject-one"

    with pytest.raises(TypeError, match="allowed ID-token signing algorithm"):
        provider._validate_id_token(
            encoded,
            keys={"keys": [public_key]},
            advertised_algorithms=["none", "HS256"],
            nonce="nonce-one",
        )
    with pytest.raises(InvalidClaimError, match="nonce"):
        provider._validate_id_token(
            encoded,
            keys={"keys": [public_key]},
            advertised_algorithms=["RS256"],
            nonce="wrong-nonce",
        )
