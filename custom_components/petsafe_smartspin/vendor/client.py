"""Encrypted Tuya *mobile* API client (the flow used by Tuya Android apps).

Generic across Tuya apps: the request signing / session-key derivation is
delegated to a signer (see :mod:`tuya_mobile.signer`), and the app identity
(``app_id``) comes from that signer or is passed explicitly. Nothing here is
vendor-specific.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import gzip
import hashlib
import json
import os
import time
import uuid
from collections.abc import Iterable
from typing import Any

import aiohttp
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .models import TuyaMobileAppProfile

SIGN_KEYS = {
    "a", "appVersion", "chKey", "clientId", "deviceId", "et", "h5",
    "h5Token", "lang", "lat", "lon", "n4h5", "os", "postData", "requestId",
    "sid", "sp", "time", "ttid", "v",
}


def _swap_md5(value: str) -> str:
    digest = hashlib.md5(value.encode()).hexdigest()
    return digest[8:16] + digest[0:8] + digest[24:32] + digest[16:24]


def canonical_string(params: dict[str, str]) -> str:
    parts = []
    for key in sorted(params):
        value = params[key]
        if key in SIGN_KEYS and value:
            if key == "postData":
                value = _swap_md5(value)
            parts.append(f"{key}={value}")
    return "||".join(parts)


def _encrypt(key: bytes, payload: dict[str, Any]) -> str:
    nonce = os.urandom(12)
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, body, None)).decode()


def _decrypt(key: bytes, value: str) -> dict[str, Any]:
    raw = base64.b64decode(value)
    plain = AESGCM(key).decrypt(raw[:12], raw[12:], None)
    with contextlib.suppress(OSError):
        plain = gzip.decompress(plain)
    return json.loads(plain.decode())


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


class TuyaMobileClient:
    """Call the encrypted Tuya mobile endpoints used by Tuya Android apps."""

    BASE_URL = "https://a1.tuyaeu.com/api.json"
    APP_VERSION = "2.2.1"

    def __init__(
        self,
        signer,
        session: aiohttp.ClientSession,
        *,
        app_id: str | None = None,
        device_id: str = "",
        request_timeout: float = 20,
        profile: TuyaMobileAppProfile | None = None,
    ) -> None:
        self.signer = signer
        self.session = session
        # App identity comes from the signer (which holds the app credentials)
        # unless overridden explicitly.
        self.app_id = app_id or getattr(signer, "app_id", "") or ""
        self.sid: str | None = None
        self.ecode: str | None = None
        self.uid: str | None = None
        self.mobile_url = self.BASE_URL
        # Tuya validates a stable installation ID; supply the captured value.
        self.device_id = device_id or ""
        self.request_timeout = request_timeout
        self.profile = profile

    async def _call(
        self, action: str, payload: dict[str, Any], *, version: str = "1.0"
    ) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        key = await asyncio.to_thread(self.signer.derive_key, request_id, self.ecode)
        encrypted = _encrypt(key, payload)
        profile = self.profile
        params: dict[str, str] = {
            "a": action,
            "v": version,
            "clientId": self.app_id,
            "os": "Android",
            "appVersion": profile.app_version if profile else self.APP_VERSION,
            "channel": profile.channel if profile else "sdk",
            "osSystem": profile.os_system if profile else "14",
            "sdkVersion": profile.sdk_version if profile else "6.7.0",
            "deviceCoreVersion": (profile.device_core_version if profile else "6.7.0"),
            "platform": profile.platform if profile else "Pixel 7",
            "timeZoneId": "UTC",
            "cp": "gzip",
            "nd": "1",
            "lang": "en",
            "ttid": profile.ttid if profile else "android",
            "et": profile.et if profile else "3",
            "chKey": await asyncio.to_thread(self.signer.channel_key),
            "deviceId": self.device_id or self.uid or "",
            "time": str(int(time.time())),
            "requestId": request_id,
            "postData": encrypted,
        }
        if profile and profile.app_rn_version:
            params["appRnVersion"] = profile.app_rn_version
        if profile and profile.business_domain:
            params["bizDM"] = profile.business_domain
        elif not profile:
            # Preserve the historical camera-oriented default for existing users.
            params["bizDM"] = "ipc"
        if self.sid:
            params["sid"] = self.sid
        params["sign"] = await asyncio.to_thread(
            self.signer.sign, canonical_string(params)
        )
        async with self.session.post(
            self.mobile_url,
            data=params,
            timeout=aiohttp.ClientTimeout(total=self.request_timeout),
            allow_redirects=False,
        ) as response:
            if response.status != 200:
                raise aiohttp.ClientError("Unexpected HTTP status")
            envelope = await response.json(content_type=None)
        if "result" not in envelope:
            error_code = envelope.get("errorCode") or envelope.get("code") or "unknown"
            error_msg = envelope.get("errorMsg") or envelope.get("msg") or "no result"
            raise RuntimeError(
                f"Tuya mobile API request {action} failed: {error_code} {error_msg}"
            )
        return _decrypt(key, envelope["result"])

