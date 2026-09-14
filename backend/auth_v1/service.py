"""OIDC Authorization Code + PKCE and opaque server-side session policy."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from joserfc import jwt
from joserfc.jwk import KeySet

from config.settings import Settings
from persistence_v1.auth import AuthRepository


class AuthError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 401):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class OIDCIdentity:
    issuer: str
    subject: str
    email: str | None
    display_name: str | None


@dataclass(frozen=True)
class LoginStart:
    authorization_url: str
    browser_transaction: str


class OIDCProvider(Protocol):
    async def authorization_url(self, *, state: str, nonce: str, code_challenge: str, redirect_uri: str) -> str: ...
    async def exchange(self, *, code: str, code_verifier: str, nonce: str, redirect_uri: str) -> OIDCIdentity: ...


class AuthlibOIDCProvider:
    """Standards-based public OIDC client; no client secret is accepted or stored."""

    def __init__(self, issuer: str, client_id: str):
        self.issuer = issuer.rstrip("/")
        self.client_id = client_id
        self._discovery: dict[str, Any] | None = None

    async def _metadata(self) -> dict[str, Any]:
        if self._discovery is None:
            url = f"{self.issuer}/.well-known/openid-configuration"
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
                response = await client.get(url)
                response.raise_for_status()
                metadata = response.json()
            if not isinstance(metadata, dict) or metadata.get("issuer") != self.issuer:
                raise AuthError("oidc_discovery_invalid", "OIDC discovery issuer did not match configured issuer.", 502)
            for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                if not isinstance(metadata.get(key), str) or not str(metadata[key]).startswith("https://"):
                    raise AuthError("oidc_discovery_invalid", "OIDC discovery is missing a secure required endpoint.", 502)
            self._discovery = metadata
        return self._discovery

    async def authorization_url(self, *, state: str, nonce: str, code_challenge: str, redirect_uri: str) -> str:
        metadata = await self._metadata()
        query = urlencode({
            "response_type": "code", "client_id": self.client_id, "redirect_uri": redirect_uri,
            "scope": "openid profile email", "state": state, "nonce": nonce,
            "code_challenge": code_challenge, "code_challenge_method": "S256",
        })
        return f"{metadata['authorization_endpoint']}?{query}"

    def _validate_id_token(
        self,
        id_token: str,
        *,
        keys: dict[str, Any],
        advertised_algorithms: Any,
        nonce: str,
    ) -> dict[str, Any]:
        if not isinstance(keys.get("keys"), list):
            raise TypeError("JWKS response was not a key set object")
        if not isinstance(advertised_algorithms, list):
            raise TypeError("OIDC discovery did not advertise ID-token signing algorithms")
        allowed_algorithms = tuple(
            algorithm
            for algorithm in advertised_algorithms
            if algorithm in {
                "RS256",
                "RS384",
                "RS512",
                "ES256",
                "ES384",
                "ES512",
                "PS256",
                "PS384",
                "PS512",
                "EdDSA",
            }
        )
        if not allowed_algorithms:
            raise TypeError("OIDC discovery did not advertise an allowed ID-token signing algorithm")
        token = jwt.decode(id_token, KeySet.import_key_set(keys), algorithms=allowed_algorithms)
        claims_registry = jwt.JWTClaimsRegistry(
            leeway=60,
            iss={"essential": True, "value": self.issuer},
            aud={"essential": True, "value": self.client_id},
            nonce={"essential": True, "value": nonce},
            sub={"essential": True},
        )
        claims_registry.validate(token.claims)
        return token.claims

    async def exchange(self, *, code: str, code_verifier: str, nonce: str, redirect_uri: str) -> OIDCIdentity:
        metadata = await self._metadata()
        client = AsyncOAuth2Client(client_id=self.client_id, code_challenge_method="S256", timeout=10.0)
        try:
            token = await client.fetch_token(metadata["token_endpoint"], code=code, redirect_uri=redirect_uri, code_verifier=code_verifier)
        except Exception as exc:
            raise AuthError("oidc_code_exchange_failed", "OIDC authorization code exchange failed.", 401) from exc
        id_token = token.get("id_token")
        if not isinstance(id_token, str):
            raise AuthError("oidc_id_token_missing", "OIDC provider did not return an ID token.", 401)
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as http:
                jwks_response = await http.get(metadata["jwks_uri"])
                jwks_response.raise_for_status()
                keys = jwks_response.json()
            if not isinstance(keys, dict):
                raise TypeError("JWKS response was not a key set object")
            claims = self._validate_id_token(
                id_token,
                keys=keys,
                advertised_algorithms=metadata.get("id_token_signing_alg_values_supported"),
                nonce=nonce,
            )
        except Exception as exc:
            raise AuthError("oidc_id_token_invalid", "OIDC ID token validation failed.", 401) from exc
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise AuthError("oidc_id_token_invalid", "OIDC ID token did not contain a subject.", 401)
        return OIDCIdentity(
            issuer=self.issuer, subject=subject,
            email=claims.get("email") if isinstance(claims.get("email"), str) else None,
            display_name=claims.get("name") if isinstance(claims.get("name"), str) else None,
        )


@dataclass(frozen=True)
class AuthPrincipal:
    identity_user_id: str
    issuer: str
    subject: str
    email: str | None
    display_name: str | None
    session_id: str
    csrf_token: str
    expires_at: datetime


class AuthService:
    def __init__(self, repository: AuthRepository, settings: Settings, provider: OIDCProvider | None = None):
        self.repository = repository
        self.settings = settings
        self.provider: OIDCProvider = provider or AuthlibOIDCProvider(settings.protocol_v1_oidc_issuer, settings.protocol_v1_oidc_client_id)
        self._secret = settings.protocol_v1_session_secret.encode()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _random(size: int = 32) -> str:
        return secrets.token_urlsafe(size)

    @staticmethod
    def _pkce_challenge(verifier: str) -> str:
        return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()

    def _session_digest(self, raw_token: str) -> str:
        return hmac.new(self._secret, raw_token.encode(), hashlib.sha256).hexdigest()

    async def start_login(self, *, request_id: str) -> LoginStart:
        state, nonce, verifier, browser_transaction = self._random(), self._random(), self._random(48), self._random(48)
        self.repository.create_login_transaction(
            state_digest=hashlib.sha256(state.encode()).hexdigest(), nonce=nonce,
            browser_binding_digest=self._session_digest(browser_transaction),
            code_verifier=verifier, redirect_uri=self.settings.protocol_v1_oidc_redirect_uri,
            expires_at=self._now() + timedelta(seconds=self.settings.protocol_v1_oidc_transaction_ttl_seconds),
        )
        self.repository.audit(request_id=request_id, event_type="auth.login_started")
        return LoginStart(
            authorization_url=await self.provider.authorization_url(state=state, nonce=nonce, code_challenge=self._pkce_challenge(verifier), redirect_uri=self.settings.protocol_v1_oidc_redirect_uri),
            browser_transaction=browser_transaction,
        )

    async def complete_login(self, *, state: str, code: str, browser_transaction: str | None, request_id: str, prior_cookie: str | None = None) -> tuple[str, AuthPrincipal]:
        if not state or not code:
            raise AuthError("oidc_callback_invalid", "OIDC callback requires state and code.", 400)
        if not browser_transaction:
            raise AuthError("oidc_browser_binding_invalid", "OIDC callback did not include its initiating browser transaction.", 400)
        transaction = self.repository.consume_login_transaction(hashlib.sha256(state.encode()).hexdigest(), self._session_digest(browser_transaction), self._now())
        if transaction is None:
            raise AuthError("oidc_state_invalid", "OIDC login state or browser transaction is invalid, expired, or already consumed.", 400)
        identity = await self.provider.exchange(code=code, code_verifier=str(transaction["code_verifier"]), nonce=str(transaction["nonce"]), redirect_uri=str(transaction["redirect_uri"]))
        user_id = self.repository.upsert_identity(issuer=identity.issuer, subject=identity.subject, email=identity.email, display_name=identity.display_name)
        raw_token = self._random(48)
        previous = self.principal(prior_cookie) if prior_cookie else None
        session_id = self.repository.create_session(
            token_digest=self._session_digest(raw_token), identity_user_id=user_id, csrf_token=self._random(),
            expires_at=self._now() + timedelta(seconds=self.settings.protocol_v1_session_ttl_seconds),
            rotated_from_id=None if previous is None else previous.session_id,
        )
        principal = self.principal(raw_token)
        assert principal is not None and principal.session_id == session_id
        self.repository.audit(request_id=request_id, event_type="auth.login_completed", identity_user_id=user_id)
        return raw_token, principal

    def principal(self, raw_token: str | None) -> AuthPrincipal | None:
        if not raw_token:
            return None
        row = self.repository.session(self._session_digest(raw_token), self._now())
        if row is None:
            return None
        return AuthPrincipal(identity_user_id=str(row["identity_user_id"]), issuer=str(row["issuer"]), subject=str(row["subject"]), email=row["email"], display_name=row["display_name"], session_id=str(row["session_id"]), csrf_token=str(row["csrf_token"]), expires_at=row["expires_at"])

    def logout(self, raw_token: str | None, *, request_id: str, actor_id: str | None = None) -> None:
        if raw_token:
            self.repository.revoke_session(self._session_digest(raw_token), self._now())
        self.repository.audit(request_id=request_id, event_type="auth.logout", identity_user_id=actor_id)
