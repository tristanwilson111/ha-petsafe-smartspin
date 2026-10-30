"""Optional, read-only Companion cloud history using deliberately saved sessions.

Unlike local-key bootstrap, this opt-in backend returns persistent app/session
credentials. It never retains a password or username, and never writes device DPs.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import struct
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import aiohttp

from . import cloud_bootstrap as bootstrap
from .vendor import errors as sdk_errors
from .vendor.client import TuyaMobileClient
from .vendor.password_client import _business_error, _walk
from .vendor.signer import PurePythonTuyaSigner

__all__ = [
    "CloudAuthError",
    "CloudHistoryError",
    "CloudSnapshot",
    "Visit",
    "async_create_cloud_credentials",
    "async_fetch_history",
]


class CloudHistoryError(Exception):
    """History configuration, transport, or response could not be validated."""


class CloudAuthError(CloudHistoryError):
    """The account or saved session requires authentication again."""


@dataclass(frozen=True)
class Visit:
    """One validated DP102 visit."""

    timestamp: datetime
    duration_seconds: int
    weight_kg: float


@dataclass(frozen=True)
class CloudSnapshot:
    """At most twenty visits, newest first, and the UTC fetch time."""

    visits: tuple[Visit, ...]
    fetched_at: datetime


_MESSAGES = {
    CloudHistoryError: "Cloud history could not be safely retrieved or validated.",
    CloudAuthError: "Cloud history authentication is required. Reconnect the companion account.",
}
_HISTORY_PAYLOAD = {"dpIds": "102", "offset": 0, "limit": 20, "sortType": "DESC"}


def _device_id(value: Any) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise CloudHistoryError()


def _session_fields(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"sid", "ecode", "uid"}:
        raise CloudAuthError()
    if any(
        not isinstance(item, str)
        or not 1 <= len(item) <= 4096
        or not item.isascii()
        or any(ord(c) < 33 or ord(c) == 127 for c in item)
        for item in value.values()
    ):
        raise CloudAuthError()
    return dict(value)


def _check_response(value: Any, profile: Any) -> None:
    # The SDK's general classifier does not recognize all expired-session codes.
    for node in _walk(value):
        if node.get("success") is False or node.get("errorCode"):
            marker = str(node.get("errorCode", "")) + ":" + str(node.get("errorMsg", ""))
            if any(
                token in marker.upper()
                for token in (
                    "SESSION",
                    "SID",
                    "LOGIN",
                    "AUTH",
                    "USER_NOT_EXIST",
                    "TOKEN_EXPIRED",
                )
            ):
                raise CloudAuthError()
    if error := _business_error(value, "history", profile):
        raise error


def _failure_type(error: Exception) -> type[CloudHistoryError]:
    if isinstance(
        error,
        (
            CloudAuthError,
            bootstrap.InvalidAuth,
            bootstrap.InteractionRequired,
            sdk_errors.TuyaMobileInvalidAuth,
            sdk_errors.TuyaMobileMFARequired,
            sdk_errors.TuyaMobileCaptchaRequired,
            sdk_errors.TuyaMobileAccountLocked,
        ),
    ):
        return CloudAuthError
    # Password-client transport wrappers can retain the provider code only in
    # their cause; classify it here, then discard the entire exception chain.
    current = error
    for _ in range(8):
        if isinstance(current, (RuntimeError, sdk_errors.TuyaMobileApiError)) and any(
            token in str(current).upper()
            for token in (
                "SESSION",
                "SID_INVALID",
                "SID_EXPIRED",
                "LOGIN_REQUIRED",
                "TOKEN_EXPIRED",
                "INVALID_AUTH",
                "PASSWORD_ERROR",
                "USER_NOT_EXIST",
            )
        ):
            return CloudAuthError
        if current.__cause__ is None:
            break
        current = current.__cause__
    return CloudHistoryError


def _clear_client(client: Any) -> None:
    if client is not None:
        if getattr(client, "signer", None) is not None:
            client.signer.__dict__.clear()
        client.__dict__.clear()


def _parse_history(response: Any, fetched_at: datetime, profile: Any) -> CloudSnapshot:
    _check_response(response, profile)
    if not isinstance(response, dict) or response.get("success") is not True:
        raise CloudHistoryError()
    result = response.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("dps"), list):
        raise CloudHistoryError()
    visits: dict[int, Visit] = {}
    for entry in result["dps"]:
        if (
            not isinstance(entry, dict)
            or type(entry.get("dpId")) is not int
            or entry["dpId"] != 102
        ):
            raise CloudHistoryError()
        timestamp = entry.get("timeStamp")
        # Integer Unix seconds only (not bool, floats, strings, or milliseconds).
        if (
            type(timestamp) is not int
            or timestamp < 946684800
            or timestamp > int(fetched_at.timestamp())
        ):
            raise CloudHistoryError()
        value = entry.get("value")
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9+/]{6}==", value):
            raise CloudHistoryError()
        raw = base64.b64decode(value, validate=True)
        if len(raw) != 4 or base64.b64encode(raw).decode("ascii") != value:
            raise CloudHistoryError()
        seconds, grams = struct.unpack(">HH", raw)
        visit = Visit(datetime.fromtimestamp(timestamp, UTC), seconds, grams / 1000)
        if timestamp in visits and visits[timestamp] != visit:
            raise CloudHistoryError()
        visits[timestamp] = visit
    return CloudSnapshot(tuple(visits[t] for t in sorted(visits, reverse=True)[:20]), fetched_at)


class _HistoryClient(TuyaMobileClient):
    """Only a single exact-device read is allowed, at the pinned regional URL."""

    def __init__(self, *args: Any, endpoint: str, target_device: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.mobile_url = self._pinned_endpoint = endpoint
        self._target_device = target_device

    async def _call(
        self, action: str, payload: dict[str, Any], *, version: str = "1.0"
    ) -> dict[str, Any]:
        if (
            action != "m.smart.operate.log"
            or version != "2.0"
            or self.mobile_url != self._pinned_endpoint
            or payload != {"devId": self._target_device, **_HISTORY_PAYLOAD}
            or any(type(payload[k]) is not int for k in ("offset", "limit"))
        ):
            raise CloudHistoryError()
        return await super()._call(action, payload, version=version)


async def async_create_cloud_credentials(
    session: aiohttp.ClientSession,
    *,
    username: str,
    password: str,
    country_code: str,
    region: str,
    device_id: str,
    profile_json: str,
) -> dict[str, Any]:
    """Authenticate once, verify the exact existing device, return savable credentials.

    Caller owns the HTTP session. Private app identity and mobile session are
    deliberately persisted only by callers opting into cloud history.
    """
    client = profile = response = matches = candidate = identities = saved = None
    failure = CloudHistoryError
    cancelled = False
    try:
        if not isinstance(region, str) or region not in bootstrap.REGION_ENDPOINTS:
            raise CloudHistoryError()
        _device_id(device_id)
        if (
            not isinstance(username, str)
            or len(username) > 254
            or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", username)
            or not isinstance(password, str)
            or not 1 <= len(password) <= 4096
            or not isinstance(country_code, str)
            or not re.fullmatch(r"[1-9][0-9]{0,3}", country_code)
        ):
            raise CloudAuthError()
        endpoint = bootstrap.REGION_ENDPOINTS[region]
        profile = bootstrap._parse_profile(profile_json, endpoint)
        client = bootstrap._ReadOnlyPasswordClient(
            profile, session, username=username, endpoint=endpoint
        )
        await client.login_with_password(password, country_code)
        response = await client._mobile_call("thing.m.device.get", "4.1", {"devId": device_id})
        _check_response(response, profile)
        matches = []
        for candidate in _walk(response):
            identities = [
                candidate[name] for name in ("devId", "deviceId", "id") if name in candidate
            ]
            if identities and all(
                type(value) is str and value == device_id for value in identities
            ):
                matches.append(candidate)
        if len(matches) != 1:
            raise CloudHistoryError()
        saved = _session_fields({"sid": client.sid, "ecode": client.ecode, "uid": client.uid})
        return {
            "profile": json.loads(json.dumps(asdict(profile))),
            "session": saved,
            "installation_id": profile.stable_device_id(username),
            "region": region,
        }
    except asyncio.CancelledError:
        cancelled = True
    except Exception as error:
        failure = _failure_type(error)
    finally:
        _clear_client(client)
        username = password = country_code = profile_json = device_id = ""
        client = profile = response = matches = candidate = identities = saved = None
    if cancelled:
        raise asyncio.CancelledError() from None
    raise failure(_MESSAGES[failure]) from None


async def async_fetch_history(
    session: aiohttp.ClientSession,
    *,
    credentials: dict[str, Any],
    device_id: str,
) -> CloudSnapshot:
    """Read only DP102 history using a saved session; never log in or retry."""
    client = profile = signer = saved = response = None
    failure = CloudHistoryError
    cancelled = False
    try:
        _device_id(device_id)
        if not isinstance(credentials, dict) or set(credentials) != {
            "profile",
            "session",
            "installation_id",
            "region",
        }:
            raise CloudHistoryError()
        region = credentials["region"]
        if not isinstance(region, str) or region not in bootstrap.REGION_ENDPOINTS:
            raise CloudHistoryError()
        endpoint = bootstrap.REGION_ENDPOINTS[region]
        if not isinstance(credentials["profile"], dict):
            raise CloudHistoryError()
        profile = bootstrap._parse_profile(json.dumps(credentials["profile"]), endpoint)
        saved = _session_fields(credentials["session"])
        installation_id = credentials["installation_id"]
        if not isinstance(installation_id, str) or not re.fullmatch(
            r"[0-9a-f]{44}", installation_id
        ):
            raise CloudHistoryError()
        signer = PurePythonTuyaSigner(
            **{
                name: getattr(profile, name)
                for name in (
                    "app_id",
                    "app_secret",
                    "cert_sha256_hex",
                    "app_key",
                    "package",
                )
            }
        )
        client = _HistoryClient(
            signer,
            session,
            profile=profile,
            device_id=installation_id,
            endpoint=endpoint,
            target_device=device_id,
        )
        client.sid, client.ecode, client.uid = saved["sid"], saved["ecode"], saved["uid"]
        response = await client._call(
            "m.smart.operate.log", {"devId": device_id, **_HISTORY_PAYLOAD}, version="2.0"
        )
        return _parse_history(response, datetime.now(UTC), profile)
    except asyncio.CancelledError:
        cancelled = True
    except Exception as error:
        failure = _failure_type(error)
    finally:
        _clear_client(client)
        if signer is not None:
            signer.__dict__.clear()
        client = signer = profile = saved = response = credentials = None
        device_id = ""
    if cancelled:
        raise asyncio.CancelledError() from None
    raise failure(_MESSAGES[failure]) from None
