"""Password login and device-credential retrieval for Tuya mobile APIs."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any

import aiohttp
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .client import TuyaMobileClient
from .errors import (
    TuyaMobileAccountLocked,
    TuyaMobileApiError,
    TuyaMobileCaptchaRequired,
    TuyaMobileEndpointUnsupported,
    TuyaMobileInvalidAuth,
    TuyaMobileLoginAttemptsExceeded,
    TuyaMobileMFARequired,
    TuyaMobileProfileExpired,
    TuyaMobileTransportError,
)
from .models import (
    TuyaMobileAppProfile,
    TuyaMobileSession,
)
from .profiles import (
    _is_bundled_mobile_app_profile,
)
from .signer import PurePythonTuyaSigner

TOKEN_API = ("thing.m.user.username.token.get", "2.0")
EMAIL_LOGIN_API = ("thing.m.user.email.password.login", "3.0")
DEVICE_CREDENTIALS_API = ("thing.m.device.get", "4.1")
LOGIN_OPTIONS = '{"group":1,"mfaCode":""}'
DEFAULT_MAX_LOGIN_ATTEMPTS = 1
DEFAULT_KEY_LENGTH = 16


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _business_error(
    value: Any,
    context: str,
    profile: TuyaMobileAppProfile | None = None,
) -> TuyaMobileApiError | None:
    for response in _walk(value):
        if response.get("success") is not False and not response.get("errorCode"):
            continue
        code = str(response.get("errorCode") or response.get("code") or "unknown")
        message = str(response.get("errorMsg") or response.get("msg") or "")
        marker = f"{code}:{message}".upper()
        safe_message = f"Tuya mobile {context} failed ({code})"
        if any(
            item in marker
            for item in (
                "API_NOT_SUPPORTED",
                "API_NOT_EXIST",
                "METHOD_NOT_FOUND",
                "UNKNOWN_ACTION",
                "UNKNOWN ACTION",
                "NO SUCH API",
            )
        ):
            return TuyaMobileEndpointUnsupported(safe_message)
        if "CAPTCHA" in marker:
            return TuyaMobileCaptchaRequired(safe_message)
        if any(item in marker for item in ("MFA", "VERIFYCODE", "VERIFY_CODE")):
            return TuyaMobileMFARequired(safe_message)
        if any(item in marker for item in ("LOCK", "FROZEN", "TOO MANY")):
            return TuyaMobileAccountLocked(safe_message)
        if any(
            item in marker
            for item in ("CLIENT", "SIGN", "APP VERSION", "ILLEGAL APP", "APPKEY")
        ):
            if profile is not None and _is_bundled_mobile_app_profile(profile):
                return TuyaMobileProfileExpired(
                    f"bundled {profile.name} profile {profile.app_version} was "
                    "rejected; the app build has probably rotated"
                )
            return TuyaMobileProfileExpired(safe_message)
        if any(
            item in marker
            for item in ("PASSWORD", "PASSWD", "INVALID CREDENTIAL", "USER_NOT_EXIST")
        ):
            return TuyaMobileInvalidAuth(safe_message)
        return TuyaMobileApiError(safe_message)
    return None


def _required_dict(
    value: Any,
    fields: set[str],
    context: str,
    *,
    profile: TuyaMobileAppProfile | None = None,
) -> dict[str, Any]:
    if error := _business_error(value, context, profile):
        raise error
    for candidate in _walk(value):
        if fields.issubset(candidate):
            return candidate
    missing = ", ".join(sorted(fields))
    raise TuyaMobileApiError(
        f"Tuya mobile {context} response is missing required fields: {missing}"
    )




def _required_login(
    value: Any,
    context: str,
    *,
    profile: TuyaMobileAppProfile | None = None,
) -> dict[str, Any]:
    if error := _business_error(value, context, profile):
        raise error
    aliases = {
        "sid": ("sid", "session", "sessionId"),
        "ecode": ("ecode", "eCode", "encryptCode"),
        "uid": ("uid", "userId"),
    }
    for candidate in _walk(value):
        normalized = dict(candidate)
        for field, names in aliases.items():
            normalized[field] = next(
                (candidate[name] for name in names if candidate.get(name)), None
            )
        if all(normalized[field] for field in aliases):
            return normalized
    missing = "sid, ecode, uid"
    raise TuyaMobileApiError(
        f"Tuya mobile {context} response is missing session fields: {missing}"
    )


def _rsa_encrypt_password(password: str, token: dict[str, Any]) -> str:
    try:
        public_key = rsa.RSAPublicNumbers(
            int(token["exponent"]), int(token["publicKey"])
        ).public_key()
    except (KeyError, TypeError, ValueError) as error:
        raise TuyaMobileProfileExpired(
            "Tuya mobile login token returned an invalid public key"
        ) from error
    # Tuya requires RSA-PKCS1v15 over the MD5 hex digest on the wire. This is
    # protocol encoding, not password storage or a password-verification hash.
    digest = (
        hashlib.md5(password.encode(), usedforsecurity=False)
        .hexdigest()
        .encode("ascii")
    )
    return public_key.encrypt(digest, padding.PKCS1v15()).hex()


class TuyaPasswordClient(TuyaMobileClient):
    """Encrypted Tuya mobile client with password authentication."""


    def __init__(
        self,
        profile: TuyaMobileAppProfile,
        session: aiohttp.ClientSession,
        *,
        username: str,
        endpoint: str | None = None,
        request_timeout: float = 20,
        max_login_attempts: int = DEFAULT_MAX_LOGIN_ATTEMPTS,
    ) -> None:
        if max_login_attempts < 1:
            raise ValueError("max_login_attempts must be at least 1")
        signer = PurePythonTuyaSigner(
            app_id=profile.app_id,
            app_secret=profile.app_secret,
            cert_sha256_hex=profile.cert_sha256_hex,
            app_key=profile.app_key,
            package=profile.package,
        )
        super().__init__(
            signer,
            session,
            device_id=profile.stable_device_id(username),
            request_timeout=request_timeout,
            profile=profile,
        )
        self.profile = profile
        self.username = username.strip()
        self.APP_VERSION = profile.app_version
        self.mobile_url = endpoint or profile.endpoints[0]
        self.mobile_session: TuyaMobileSession | None = None
        self.max_login_attempts = max_login_attempts
        self._login_attempts_used = 0

    async def _mobile_call(
        self,
        action: str,
        version: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return await self._call(action, payload, version=version)
        except (TimeoutError, aiohttp.ClientError, ValueError) as error:
            raise TuyaMobileTransportError(
                f"Tuya mobile endpoint failed for {action}"
            ) from error
        except RuntimeError as error:
            typed = _business_error(
                {"errorCode": "MOBILE_API", "errorMsg": str(error)},
                action,
                self.profile,
            )
            raise typed or TuyaMobileApiError(
                f"Tuya mobile request failed for {action}"
            ) from error

    async def login_with_password(
        self, password: str, country_code: str
    ) -> TuyaMobileSession:
        """Authenticate an email or telephone account without retaining password."""
        self._login_attempts_used = 0
        if "@" in self.username:
            token = await self._get_login_token(country_code)
            login = await self._submit_login(
                *EMAIL_LOGIN_API,
                {
                    "countryCode": country_code,
                    "email": self.username,
                    "passwd": _rsa_encrypt_password(password, token),
                    "options": LOGIN_OPTIONS,
                    "token": str(token["token"]),
                    "ifencrypt": 1,
                },
                context="email password login",
            )
        else:
            raise TuyaMobileInvalidAuth("Email accounts only")
        self.sid = str(login["sid"])
        self.ecode = str(login["ecode"])
        self.uid = str(login["uid"])
        if endpoint := self._endpoint_from_login(login):
            self.mobile_url = endpoint
        mobile_session = TuyaMobileSession(
            sid=self.sid,
            ecode=self.ecode,
            uid=self.uid,
            endpoint=self.mobile_url,
        )
        self.mobile_session = mobile_session
        return mobile_session

    async def _get_login_token(self, country_code: str) -> dict[str, Any]:
        """Fetch a short-lived token, trying only transport-safe endpoints."""
        endpoints = tuple(dict.fromkeys((self.mobile_url, *self.profile.endpoints)))
        last_transport: TuyaMobileTransportError | None = None
        for endpoint in endpoints:
            self.mobile_url = endpoint
            try:
                token_envelope = await self._mobile_call(
                    *TOKEN_API,
                    {
                        "countryCode": country_code,
                        "username": self.username,
                        "isUid": False,
                    },
                )
            except TuyaMobileTransportError as error:
                last_transport = error
                continue
            return _required_dict(
                token_envelope,
                {"publicKey", "exponent", "token"},
                "login token",
                profile=self.profile,
            )
        raise last_transport or TuyaMobileTransportError(
            "No Tuya mobile endpoint accepted the request"
        )

    def _ensure_login_attempt_available(self) -> None:
        if self._login_attempts_used >= self.max_login_attempts:
            raise TuyaMobileLoginAttemptsExceeded(
                "Tuya mobile login attempt budget exhausted "
                f"({self._login_attempts_used} of {self.max_login_attempts} "
                "login attempts used)"
            )

    def _claim_login_attempt(self) -> None:
        self._ensure_login_attempt_available()
        self._login_attempts_used += 1

    async def _submit_login(
        self,
        action: str,
        version: str,
        payload: dict[str, Any],
        *,
        context: str,
    ) -> dict[str, Any]:
        """Submit a password exactly once and account for that attempt."""
        self._claim_login_attempt()
        response = await self._mobile_call(action, version, payload)
        return _required_login(response, context, profile=self.profile)


    @staticmethod
    def _endpoint_from_login(result: dict[str, Any]) -> str | None:
        domain = result.get("domain")
        if isinstance(domain, dict) and domain.get("mobileApiUrl"):
            return str(domain["mobileApiUrl"]).rstrip("/") + "/api.json"
        if result.get("mobileApiUrl"):
            return str(result["mobileApiUrl"]).rstrip("/") + "/api.json"
        return None


