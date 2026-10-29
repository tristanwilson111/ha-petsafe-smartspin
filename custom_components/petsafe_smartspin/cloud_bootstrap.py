"""One-shot, read-only retrieval of an existing device's Wi-Fi local key.

Private application identities are supplied by the user, never bundled. Account
credentials and mobile sessions are ephemeral; only the returned local key may
be saved by the caller. This does not pair, activate, or modify any device.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import fields
from typing import Any

import aiohttp

from .vendor import errors as sdk_errors
from .vendor.models import TuyaMobileAppProfile
from .vendor.password_client import TuyaPasswordClient, _business_error, _walk

# Tuya mobile API regional endpoints (upstream models.py); no discovery or retry
# against another region, even if the server advertises a different login domain.
REGION_ENDPOINTS = {
    "us": "https://a1.tuyaus.com/api.json",
    "eu": "https://a1.tuyaeu.com/api.json",
    "cn": "https://a1.tuyacn.com/api.json",
    "in": "https://a1.tuyain.com/api.json",
    "sg": "https://a1-sg.iotbing.com/api.json",
}
_ALLOWED = frozenset({
    ("thing.m.user.username.token.get", "2.0"),
    ("thing.m.user.email.password.login", "3.0"),
    ("thing.m.device.get", "4.1"),
})


class BootstrapError(Exception):
    """Cloud bootstrap could not safely complete."""


class CannotConnect(BootstrapError):
    """The selected cloud endpoint could not be reached."""


class InvalidAuth(BootstrapError):
    """The account credentials were rejected."""


class InteractionRequired(BootstrapError):
    """The account requires interaction in its companion application."""


class InvalidProfile(BootstrapError):
    """The private application identity is invalid or unsupported."""


_MESSAGES = {
    BootstrapError: "Cloud bootstrap could not validate the requested device and local key.",
    CannotConnect: "Cannot connect to the selected cloud region.",
    InvalidAuth: "Email account credentials were rejected.",
    InteractionRequired: "Complete account verification in the companion app before trying again.",
    InvalidProfile: "The private application profile or selected region is invalid or unsupported.",
}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise InvalidProfile()
        result[name] = value
    return result


def _parse_profile(profile_json: str, endpoint: str) -> TuyaMobileAppProfile:
    if not isinstance(profile_json, str) or not 1 <= len(profile_json) <= 32768:
        raise InvalidProfile()
    data = json.loads(profile_json, object_pairs_hook=_unique_object)
    names = {field.name for field in fields(TuyaMobileAppProfile)}
    required = {
        "name", "app_id", "app_secret", "cert_sha256_hex", "app_key", "package",
        "app_version", "ttid", "sdk_version", "device_core_version",
    }
    if not isinstance(data, dict) or not required <= data.keys() or data.keys() - names:
        raise InvalidProfile()
    for name, value in data.items():
        if name == "endpoints":
            if (not isinstance(value, list) or not value or len(value) > 5
                    or any(not isinstance(item, str) or item not in REGION_ENDPOINTS.values()
                           for item in value)):
                raise InvalidProfile()
        elif (not isinstance(value, str) or len(value) > 1024
              or not value.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in value)
              or (name in required and not value.strip())):
            raise InvalidProfile()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", data["cert_sha256_hex"]):
        raise InvalidProfile()
    if not re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+", data["package"]):
        raise InvalidProfile()
    # Never use profile-supplied endpoints as fallback targets.
    data["endpoints"] = (endpoint,)
    return TuyaMobileAppProfile(**data)


class _ReadOnlyPasswordClient(TuyaPasswordClient):
    """Enforce permissions and attempt budget independently of the upstream SDK."""

    def __init__(self, *args: Any, endpoint: str, **kwargs: Any) -> None:
        super().__init__(*args, endpoint=endpoint, max_login_attempts=1, **kwargs)
        self._pinned_endpoint = endpoint
        self._password_submitted = False

    @staticmethod
    def _endpoint_from_login(result: dict[str, Any]) -> None:
        # Login-domain metadata must not redirect an authenticated request.
        return None

    async def _call(self, action: str, payload: dict[str, Any], *, version: str = "1.0") -> dict[str, Any]:
        if (action, version) not in _ALLOWED or self.mobile_url != self._pinned_endpoint:
            raise InvalidProfile()
        if action == "thing.m.user.email.password.login":
            if self._password_submitted:
                raise InvalidAuth()
            # Consume the budget BEFORE transport, including timeouts.
            self._password_submitted = True
        return await super()._call(action, payload, version=version)


def _error_type(error: Exception) -> type[BootstrapError]:
    if isinstance(error, BootstrapError):
        return type(error)
    if isinstance(error, (sdk_errors.TuyaMobileMFARequired,
                          sdk_errors.TuyaMobileCaptchaRequired,
                          sdk_errors.TuyaMobileAccountLocked)):
        return InteractionRequired
    if isinstance(error, sdk_errors.TuyaMobileInvalidAuth):
        return InvalidAuth
    if isinstance(error, (sdk_errors.TuyaMobileProfileExpired,
                          sdk_errors.TuyaMobileEndpointUnsupported)):
        return InvalidProfile
    if isinstance(error, (sdk_errors.TuyaMobileTransportError,
                          aiohttp.ClientError, TimeoutError, OSError)):
        return CannotConnect
    if isinstance(error, (ValueError, TypeError, KeyError, RecursionError)):
        return InvalidProfile
    return BootstrapError


async def async_get_local_key(
    session: aiohttp.ClientSession, *, username: str, password: str,
    country_code: str, region: str, device_id: str, profile_json: str,
) -> str:
    """Retrieve one existing device key without persisting an account/session.

    Only email accounts are supported. No phone endpoint probing or automatic
    password retry is performed. Caller owns ``session``; it is not closed.
    Errors contain fixed messages, not SDK exceptions or cloud responses.
    """
    client = None
    profile = response = device = key = None
    failure: type[BootstrapError] | None = None
    cancelled = False
    try:
        if not isinstance(region, str) or region not in REGION_ENDPOINTS:
            raise InvalidProfile()
        if (not isinstance(username, str) or len(username) > 254
                or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", username)
                or not isinstance(password, str) or not password or len(password) > 4096
                or not isinstance(country_code, str)
                or not re.fullmatch(r"[1-9][0-9]{0,3}", country_code)):
            raise InvalidAuth()
        if (not isinstance(device_id, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", device_id)):
            raise BootstrapError()
        profile = _parse_profile(profile_json, REGION_ENDPOINTS[region])
        client = _ReadOnlyPasswordClient(
            profile, session, username=username, endpoint=REGION_ENDPOINTS[region],
        )
        await client.login_with_password(password, country_code)
        # Do NOT use get_device_credentials: it requires an unnecessary BLE secKey.
        response = await client._mobile_call("thing.m.device.get", "4.1", {"devId": device_id})
        if error := _business_error(response, "device lookup", profile):
            raise error
        matches = []
        for candidate in _walk(response):
            identities = [candidate[name] for name in ("devId", "deviceId", "id") if name in candidate]
            if (
                identities
                and all(value == device_id for value in identities)
                and ("localKey" in candidate or "local_key" in candidate)
            ):
                matches.append(candidate)
        if len(matches) != 1:
            raise BootstrapError()
        device = matches[0]
        key = device.get("localKey", device.get("local_key"))
        if (not isinstance(key, str) or len(key) != 16 or not key.isascii()
                or ("local_key" in device and device["local_key"] != key)):
            raise BootstrapError()
        return key
    except asyncio.CancelledError:
        cancelled = True
    except Exception as error:
        failure = _error_type(error)
    finally:
        # Remove our own references even on failure/cancellation. Python strings
        # cannot be reliably zeroized; nothing is stored on the shared session.
        if client is not None:
            if getattr(client, "signer", None) is not None:
                client.signer.__dict__.clear()
            client.__dict__.clear()
        username = password = country_code = profile_json = device_id = ""
        client = profile = response = device = key = None
        # Also clear response aliases retained by the function's traceback.
        matches = candidate = identities = None
    # Raise OUTSIDE the handler: even __context__ must not retain a raw SDK error.
    if cancelled:
        raise asyncio.CancelledError() from None
    assert failure is not None
    raise failure(_MESSAGES.get(failure, _MESSAGES[BootstrapError])) from None
