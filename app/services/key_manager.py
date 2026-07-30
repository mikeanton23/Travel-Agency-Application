# -*- coding: utf-8 -*-

"""
Encrypted API-key management + validation (backend for the Settings page).

Responsibilities:
* Store keys encrypted at rest (Fernet, see :mod:`app.utils.crypto`)
  in the ``api_keys`` table — plaintext is never persisted.
* Resolve keys with a clear precedence: DB override → environment.
* Validate any provider's key with a real, minimal API call and record
  the result (``is_valid``, ``last_validated_at``, ``last_error``).
* Report health across all providers for the admin dashboard.

Provider names are lowercase identifiers: "amadeus", "geoapify",
"pexels", "ticketmaster", "openrouteservice", "openweather",
"openexchangerates", "numbeo", "openai", "anthropic".
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.utils import config
from app.utils.crypto import SecretBox
from app.utils.http_client import ApiError, HttpJsonClient, RetryPolicy

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Validation registry: how to cheaply prove a key works, per provider
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class ValidatorSpec:
    method: str
    url: str
    params: Callable[[str], Dict[str, Any]] = lambda key: {}
    headers: Callable[[str], Dict[str, str]] = lambda key: {}
    data: Callable[[str], Dict[str, Any]] = lambda key: {}
    ok: Callable[[Any], bool] = lambda payload: payload is not None


VALIDATORS: Dict[str, ValidatorSpec] = {
    "geoapify": ValidatorSpec(
        "GET", "https://api.geoapify.com/v1/geocode/search",
        params=lambda k: {"text": "Athens", "limit": 1, "apiKey": k},
        ok=lambda p: bool((p or {}).get("features")),
    ),
    "pexels": ValidatorSpec(
        "GET", "https://api.pexels.com/v1/curated",
        params=lambda k: {"per_page": 1},
        headers=lambda k: {"Authorization": k},
        ok=lambda p: "photos" in (p or {}),
    ),
    "ticketmaster": ValidatorSpec(
        "GET", "https://app.ticketmaster.com/discovery/v2/events.json",
        params=lambda k: {"size": 1, "apikey": k},
        ok=lambda p: "_embedded" in (p or {}) or "page" in (p or {}),
    ),
    "openrouteservice": ValidatorSpec(
        "GET", "https://api.openrouteservice.org/geocode/search",
        params=lambda k: {"api_key": k, "text": "Athens", "size": 1},
        ok=lambda p: "features" in (p or {}),
    ),
    "openweather": ValidatorSpec(
        "GET", "https://api.openweathermap.org/data/2.5/weather",
        params=lambda k: {"q": "Athens", "appid": k},
        ok=lambda p: "weather" in (p or {}),
    ),
    "openexchangerates": ValidatorSpec(
        "GET", "https://openexchangerates.org/api/latest.json",
        params=lambda k: {"app_id": k},
        ok=lambda p: "rates" in (p or {}),
    ),
    "numbeo": ValidatorSpec(
        "GET", "https://www.numbeo.com/api/city_prices",
        params=lambda k: {"api_key": k, "query": "London"},
        ok=lambda p: bool((p or {}).get("prices"))
        and not (p or {}).get("error"),
    ),
    "openai": ValidatorSpec(
        "GET", "https://api.openai.com/v1/models",
        headers=lambda k: {"Authorization": f"Bearer {k}"},
        ok=lambda p: "data" in (p or {}),
    ),
    "anthropic": ValidatorSpec(
        "GET", "https://api.anthropic.com/v1/models",
        headers=lambda k: {"x-api-key": k, "anthropic-version": "2023-06-01"},
        ok=lambda p: "data" in (p or {}),
    ),
}

# Amadeus needs key+secret, so it has a dedicated path (see validate()).
COMPOSITE_PROVIDERS = {"amadeus"}

# Developer-facing info: where to get each key and what it costs.
PROVIDER_INFO: Dict[str, Dict[str, str]] = {
    "amadeus": {
        "label": "Amadeus (flights & hotels)",
        "signup": "https://developers.amadeus.com/register",
        "tier": "Free self-service tier, instant keys",
    },
    "geoapify": {
        "label": "Geoapify (places & geocoding)",
        "signup": "https://myprojects.geoapify.com/register",
        "tier": "Free: 3k requests/day",
    },
    "pexels": {
        "label": "Pexels (images)",
        "signup": "https://www.pexels.com/api/",
        "tier": "Free",
    },
    "ticketmaster": {
        "label": "Ticketmaster (events)",
        "signup": "https://developer.ticketmaster.com/",
        "tier": "Free tier",
    },
    "openrouteservice": {
        "label": "OpenRouteService (routing)",
        "signup": "https://openrouteservice.org/dev/#/signup",
        "tier": "Free tier",
    },
    "openweather": {
        "label": "OpenWeather",
        "signup": "https://home.openweathermap.org/users/sign_up",
        "tier": "Free tier",
    },
    "openexchangerates": {
        "label": "OpenExchangeRates (currency)",
        "signup": "https://openexchangerates.org/signup/free",
        "tier": "Free: 1k requests/month; keyless ECB fallback built in",
    },
    "numbeo": {
        "label": "Numbeo (cost of living & safety)",
        "signup": "https://www.numbeo.com/common/api.jsp",
        "tier": "Paid only — app shows 'unavailable' without it",
    },
    "openai": {
        "label": "OpenAI (LLM + embeddings)",
        "signup": "https://platform.openai.com/api-keys",
        "tier": "Pay-as-you-go",
    },
    "anthropic": {
        "label": "Anthropic Claude (LLM)",
        "signup": "https://console.anthropic.com/",
        "tier": "Pay-as-you-go",
    },
}

# Environment fallbacks (config module attribute per provider).
ENV_ATTR: Dict[str, str] = {
    "geoapify": "GEOAPIFY_API_KEY",
    "pexels": "PEXELS_API_KEY",
    "ticketmaster": "TICKETMASTER_API_KEY",
    "openrouteservice": "OPENROUTESERVICE_API_KEY",
    "openweather": "OPENWEATHER_API_KEY",
    "openexchangerates": "OPENEXCHANGERATES_API_KEY",
    "numbeo": "NUMBEO_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "amadeus": "AMADEUS_API_KEY",
    "amadeus_secret": "AMADEUS_API_SECRET",
}


class KeyManager:
    """Encrypted key store with validation. Session factory injectable
    for tests; lazily binds to the app DB otherwise."""

    def __init__(
        self,
        secret_key: Optional[str] = None,
        session_factory: Optional[Callable[[], Any]] = None,
        http: Optional[HttpJsonClient] = None,
    ) -> None:
        self._secret_key = (
            secret_key if secret_key is not None else config.APP_SECRET_KEY
        )
        self._box: Optional[SecretBox] = None
        self._session_factory = session_factory
        # Validation should fail fast, not retry for minutes.
        self.http = http or HttpJsonClient(
            retry=RetryPolicy(max_attempts=2, base_delay=0.3)
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _sessions(self) -> Callable[[], Any]:
        if self._session_factory is None:
            from app.db.database import SessionLocal
            self._session_factory = SessionLocal
        return self._session_factory

    def _get_box(self) -> SecretBox:
        if self._box is None:
            self._box = SecretBox(self._secret_key)
        return self._box

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def set_key(self, provider: str, value: str) -> None:
        """Encrypt and store (or update) a provider key."""
        from app.db.models import ApiKey

        provider = provider.strip().lower()
        ciphertext = self._get_box().encrypt(value.strip())
        session = self._sessions()()
        try:
            row = (
                session.query(ApiKey)
                .filter(ApiKey.provider == provider)
                .one_or_none()
            )
            if row is None:
                row = ApiKey(provider=provider)
                session.add(row)
            row.encrypted_value = ciphertext
            row.is_valid = None          # unknown until re-validated
            row.last_error = None
            session.commit()
        finally:
            session.close()

    def delete_key(self, provider: str) -> bool:
        from app.db.models import ApiKey

        session = self._sessions()()
        try:
            row = (
                session.query(ApiKey)
                .filter(ApiKey.provider == provider.strip().lower())
                .one_or_none()
            )
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True
        finally:
            session.close()

    def get_key(self, provider: str) -> Optional[str]:
        """Resolve a key: DB override first, then environment."""
        from app.db.models import ApiKey

        provider = provider.strip().lower()
        session = self._sessions()()
        try:
            row = (
                session.query(ApiKey)
                .filter(ApiKey.provider == provider)
                .one_or_none()
            )
        finally:
            session.close()
        if row is not None:
            plaintext = self._get_box().decrypt(row.encrypted_value)
            if plaintext:
                return plaintext
            logger.warning(
                "Stored key for %s cannot be decrypted "
                "(APP_SECRET_KEY rotated?) — falling back to env",
                provider,
            )
        attr = ENV_ATTR.get(provider)
        value = getattr(config, attr, "") if attr else ""
        return value or None

    def list_keys(self) -> List[Dict[str, Any]]:
        """Status of every known provider (values never included)."""
        from app.db.models import ApiKey

        session = self._sessions()()
        try:
            rows = {r.provider: r for r in session.query(ApiKey).all()}
        finally:
            session.close()
        providers = sorted(set(VALIDATORS) | COMPOSITE_PROVIDERS)
        result = []
        for provider in providers:
            row = rows.get(provider)
            env_attr = ENV_ATTR.get(provider)
            has_env = bool(getattr(config, env_attr, "")) if env_attr else False
            info = PROVIDER_INFO.get(provider, {})
            result.append({
                "provider": provider,
                "label": info.get("label", provider),
                "signup": info.get("signup"),
                "tier": info.get("tier"),
                "stored": row is not None,
                "env_fallback": has_env,
                "configured": row is not None or has_env,
                "is_valid": row.is_valid if row else None,
                "last_validated_at": (
                    row.last_validated_at.isoformat()
                    if row and row.last_validated_at else None
                ),
                "last_error": row.last_error if row else None,
            })
        return result

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    async def validate(self, provider: str) -> Dict[str, Any]:
        """Test a provider key with a real minimal call; persist result."""
        provider = provider.strip().lower()
        key = self.get_key(provider)
        if not key:
            return self._record(provider, False, "No key configured")

        if provider == "amadeus":
            return await self._validate_amadeus(key)

        spec = VALIDATORS.get(provider)
        if spec is None:
            return self._record(provider, False,
                                f"Unknown provider '{provider}'")
        try:
            payload = await self.http.arequest_json(
                spec.method, spec.url,
                params=spec.params(key) or None,
                headers=spec.headers(key) or None,
                data=spec.data(key) or None,
            )
        except ApiError as exc:
            return self._record(provider, False, str(exc)[:400])
        if spec.ok(payload):
            return self._record(provider, True, None)
        return self._record(provider, False,
                            "Unexpected response shape from provider")

    async def _validate_amadeus(self, key: str) -> Dict[str, Any]:
        secret = self.get_key("amadeus_secret") or config.AMADEUS_API_SECRET
        if not secret:
            return self._record("amadeus", False,
                                "AMADEUS_API_SECRET missing")
        try:
            payload = await self.http.arequest_json(
                "POST",
                f"{config.AMADEUS_BASE_URL}/v1/security/oauth2/token",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                data={
                    "grant_type": "client_credentials",
                    "client_id": key,
                    "client_secret": secret,
                },
            )
        except ApiError as exc:
            return self._record("amadeus", False, str(exc)[:400])
        if (payload or {}).get("access_token"):
            return self._record("amadeus", True, None)
        return self._record("amadeus", False, "Token response invalid")

    async def health(self) -> List[Dict[str, Any]]:
        """Validate every configured provider concurrently."""
        statuses = self.list_keys()
        configured = [s["provider"] for s in statuses if s["configured"]]
        results = await asyncio.gather(
            *[self.validate(p) for p in configured]
        )
        by_provider = {r["provider"]: r for r in results}
        for status in statuses:
            check = by_provider.get(status["provider"])
            if check:
                status.update(check)
        return statuses

    def _record(
        self, provider: str, valid: bool, error: Optional[str]
    ) -> Dict[str, Any]:
        from app.db.models import ApiKey

        try:
            session = self._sessions()()
            try:
                row = (
                    session.query(ApiKey)
                    .filter(ApiKey.provider == provider)
                    .one_or_none()
                )
                if row is not None:
                    row.is_valid = valid
                    row.last_error = error
                    row.last_validated_at = datetime.now(timezone.utc)
                    session.commit()
            finally:
                session.close()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not persist validation for %s: %s",
                           provider, exc)
        return {"provider": provider, "is_valid": valid, "error": error}
