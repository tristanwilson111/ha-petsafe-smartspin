"""Entirely synthetic offline tests, including real Tuya signing/AES/RSA."""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import importlib.util
import json
import struct
import sys
import types
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

import aiohttp
import pytest
from cryptography.hazmat.primitives.asymmetric import padding, rsa

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "petsafe_smartspin"
PACKAGE = "_smartspin_history_test"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
spec = importlib.util.spec_from_file_location(f"{PACKAGE}.cloud_history", ROOT / "cloud_history.py")
cloud = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cloud
spec.loader.exec_module(cloud)
transport = import_module(f"{PACKAGE}.vendor.client")

DEVICE = "synthetic_device_42"
PROFILE = {
    "name": "Synthetic identity",
    "app_id": "synthetic-id",
    "app_secret": "synthetic-secret",
    "cert_sha256_hex": "cd" * 32,
    "app_key": "synthetic-key",
    "package": "invalid.example.history",
    "app_version": "1.0",
    "ttid": "synthetic",
    "sdk_version": "6.7.0",
    "device_core_version": "6.7.0",
}
ARGS = {
    "username": "history@example.invalid",
    "password": "synthetic-password",
    "country_code": "1",
    "region": "us",
    "device_id": DEVICE,
    "profile_json": json.dumps(PROFILE),
}
NOW = datetime(2025, 1, 2, tzinfo=UTC)
STAMP = 1735689600
SESSION = {"sid": "synthetic-sid", "ecode": "synthetic-ecode", "uid": "synthetic-uid"}


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    async def deny(*args, **kwargs):
        raise AssertionError("External network forbidden")

    monkeypatch.setattr(aiohttp.ClientSession, "_request", deny)


@pytest.fixture(scope="module")
def private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=1024)


def record(timestamp=STAMP, seconds=123, grams=4321):
    return {
        "dpId": 102,
        "timeStamp": timestamp,
        "value": base64.b64encode(struct.pack(">HH", seconds, grams)).decode(),
    }


def envelope(dps=None):
    return {
        "success": True,
        "result": {"dps": [record()] if dps is None else dps, "hasNext": False, "total": 1},
    }


def credentials():
    return {
        "profile": copy.deepcopy(PROFILE),
        "session": dict(SESSION),
        "installation_id": "a" * 44,
        "region": "us",
    }


class Reply:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self, **kwargs):
        return self.body


class HTTP:
    def __init__(
        self,
        private_key=None,
        *,
        stage="history",
        failure=None,
        device=None,
        history=None,
        status=200,
    ):
        self.private_key = private_key
        self.stage, self.failure, self.status = stage, failure, status
        self.device = {"devId": DEVICE} if device is None else device
        self.history = envelope() if history is None else history
        self.calls = []
        self.signer = cloud.PurePythonTuyaSigner(
            **{
                name: PROFILE[name]
                for name in ("app_id", "app_secret", "cert_sha256_hex", "app_key", "package")
            }
        )

    def post(self, url, *, data, timeout, allow_redirects):
        action = data["a"]
        stage = {
            "thing.m.user.username.token.get": "token",
            "thing.m.user.email.password.login": "login",
            "thing.m.device.get": "device",
            "m.smart.operate.log": "history",
        }[action]
        key = self.signer.derive_key(
            data["requestId"], SESSION["ecode"] if data.get("sid") else None
        )
        payload = transport._decrypt(key, data["postData"])
        self.calls.append((url, data.copy(), payload, allow_redirects))
        assert data["sign"] == self.signer.sign(
            transport.canonical_string({k: v for k, v in data.items() if k != "sign"})
        )
        if self.stage == stage and self.failure is not None:
            if isinstance(self.failure, BaseException):
                raise self.failure
            return Reply(self.failure, self.status)
        if stage == "token":
            numbers = self.private_key.public_key().public_numbers()
            result = {
                "token": "synthetic-token",
                "publicKey": str(numbers.n),
                "exponent": str(numbers.e),
            }
        elif stage == "login":
            digest = self.private_key.decrypt(bytes.fromhex(payload["passwd"]), padding.PKCS1v15())
            assert digest == hashlib.md5(ARGS["password"].encode()).hexdigest().encode()
            result = SESSION | {"domain": {"mobileApiUrl": "https://attacker.invalid"}}
        elif stage == "device":
            assert payload == {"devId": DEVICE}
            result = self.device
        else:
            result = self.history
        return Reply({"result": transport._encrypt(key, result)}, self.status)


def create(http, **overrides):
    return asyncio.run(cloud.async_create_cloud_credentials(http, **(ARGS | overrides)))


def fetch(http, saved=None, device_id=DEVICE):
    return asyncio.run(
        cloud.async_fetch_history(
            http, credentials=credentials() if saved is None else saved, device_id=device_id
        )
    )


def test_real_protocol_roundtrip(private_key):
    http = HTTP(private_key)
    saved = create(http)
    assert set(saved) == {"profile", "session", "installation_id", "region"}
    assert saved["session"] == SESSION
    profile = cloud.bootstrap._parse_profile(
        ARGS["profile_json"], cloud.bootstrap.REGION_ENDPOINTS["us"]
    )
    assert saved["installation_id"] == profile.stable_device_id(ARGS["username"])
    assert ARGS["username"] not in json.dumps(saved) and ARGS["password"] not in json.dumps(saved)
    snapshot = fetch(http, json.loads(json.dumps(saved)))
    assert snapshot.visits == (cloud.Visit(datetime.fromtimestamp(STAMP, UTC), 123, 4.321),)
    assert snapshot.fetched_at.tzinfo is UTC
    assert [(x[1]["a"], x[1]["v"]) for x in http.calls] == [
        ("thing.m.user.username.token.get", "2.0"),
        ("thing.m.user.email.password.login", "3.0"),
        ("thing.m.device.get", "4.1"),
        ("m.smart.operate.log", "2.0"),
    ]
    assert http.calls[-1][2] == {
        "devId": DEVICE,
        "dpIds": "102",
        "offset": 0,
        "limit": 20,
        "sortType": "DESC",
    }
    assert http.calls[-1][1]["deviceId"] == saved["installation_id"]
    assert all(x[0] == cloud.bootstrap.REGION_ENDPOINTS["us"] and x[3] is False for x in http.calls)


@pytest.mark.parametrize("region", ["us", "eu", "cn", "in", "sg"])
def test_endpoint_pins(private_key, region):
    http = HTTP(private_key)
    saved = create(
        http,
        region=region,
        profile_json=json.dumps(
            PROFILE | {"endpoints": list(cloud.bootstrap.REGION_ENDPOINTS.values())}
        ),
    )
    fetch(http, saved)
    assert {x[0] for x in http.calls} == {cloud.bootstrap.REGION_ENDPOINTS[region]}
    assert saved["profile"]["endpoints"] == [cloud.bootstrap.REGION_ENDPOINTS[region]]


@pytest.mark.parametrize(
    "device",
    [
        {"devId": "other"},
        {},
        {"id": 42},
        {"devId": DEVICE, "deviceId": "other"},
        [{"devId": DEVICE}, {"id": DEVICE}],
        {"result": [{"devId": "other", "localKey": "unused"}]},
    ],
)
def test_exact_device_rejected(private_key, device):
    with pytest.raises(cloud.CloudHistoryError):
        create(HTTP(private_key, device=device))


@pytest.mark.parametrize(
    "device",
    [
        {"id": DEVICE},
        {"deviceId": DEVICE},
        {"success": True, "result": {"devId": DEVICE, "id": DEVICE}},
    ],
)
def test_device_aliases_without_local_key(private_key, device):
    assert create(HTTP(private_key, device=device))["session"] == SESSION


def test_parser_sort_dedupe_trim():
    rows = [record(STAMP - n) for n in range(25)]
    snapshot = cloud._parse_history(envelope([*rows[::-1], rows[0]]), NOW, None)
    assert len(snapshot.visits) == 20
    assert [v.timestamp.timestamp() for v in snapshot.visits] == list(range(STAMP, STAMP - 20, -1))
    assert cloud._parse_history(envelope([]), NOW, None).visits == ()


@pytest.mark.parametrize("seconds,grams", [(0, 0), (65535, 65535), (42, 5678)])
def test_uint16_big_endian(seconds, grams):
    visit = cloud._parse_history(
        envelope([record(seconds=seconds, grams=grams)]), NOW, None
    ).visits[0]
    assert visit.duration_seconds == seconds and visit.weight_kg == grams / 1000


@pytest.mark.parametrize(
    "timestamp",
    [
        None,
        True,
        False,
        -1,
        0,
        946684799,
        "1735689600",
        1735689600.0,
        STAMP * 1000,
        999999999999999999999999,
        int(NOW.timestamp()) + 1,
    ],
)
def test_bad_timestamps(timestamp):
    with pytest.raises(cloud.CloudHistoryError):
        cloud._parse_history(envelope([record() | {"timeStamp": timestamp}]), NOW, None)


@pytest.mark.parametrize(
    "value",
    [
        None,
        42,
        b"AAAAAA==",
        "",
        "!!!!AA==",
        "AAAA",
        "AAAAAAAA",
        "AAAAAAA=",
        "AAAAAA==\n",
        "AAAAAB==",
        "éAAAAA==",
        base64.b64encode(b"12345").decode(),
    ],
)
def test_bad_encodings(value):
    with pytest.raises(cloud.CloudHistoryError):
        cloud._parse_history(envelope([record() | {"value": value}]), NOW, None)


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {},
        {"success": 1, "result": {"dps": []}},
        {"success": False},
        {"success": True},
        {"success": True, "result": []},
        {"success": True, "result": {"dps": {}}},
        envelope([None]),
        envelope([{}]),
        envelope([record() | {"dpId": "102"}]),
        envelope([record() | {"dpId": True}]),
        envelope([record() | {"dpId": 101}]),
        envelope([record(), record(seconds=124)]),
    ],
)
def test_malformed_history_sanitized(body):
    http = HTTP(history=body) if body is not None else HTTP(history=[])
    with pytest.raises(cloud.CloudHistoryError) as caught:
        fetch(http)
    assert caught.value.__context__ is None and caught.value.__cause__ is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"username": "not-email"},
        {"username": None},
        {"password": ""},
        {"password": 123},
        {"country_code": "US"},
        {"region": "auto"},
        {"region": []},
        {"device_id": "../bad"},
        {"device_id": True},
        {"profile_json": "{"},
        {"profile_json": "null"},
        {"profile_json": json.dumps(PROFILE | {"password": "private"})},
        {"profile_json": json.dumps(PROFILE | {"endpoints": ["https://attacker.invalid"]})},
        {"profile_json": json.dumps(PROFILE | {"app_key": 42})},
    ],
)
def test_invalid_create_no_io(overrides):
    http = HTTP()
    with pytest.raises(cloud.CloudHistoryError):
        create(http, **overrides)
    assert http.calls == []


@pytest.mark.parametrize(
    "patch",
    [
        {"region": []},
        {"region": "auto"},
        {"profile": None},
        {"profile": PROFILE | {"username": "private"}},
        {"profile": PROFILE | {"app_secret": False}},
        {"session": {}},
        {"session": SESSION | {"sid": True}},
        {"session": SESSION | {"ecode": ""}},
        {"session": SESSION | {"uid": "bad\n"}},
        {"session": SESSION | {"password": "private"}},
        {"installation_id": "https://attacker.invalid"},
        {"installation_id": True},
        {"username": "private"},
        {"password": "private"},
    ],
)
def test_bad_saved_credentials_no_io(patch):
    http = HTTP()
    with pytest.raises(cloud.CloudHistoryError):
        fetch(http, credentials() | patch)
    assert not http.calls


@pytest.mark.parametrize(
    "code",
    ["USER_SESSION_INVALID", "SID_EXPIRED", "LOGIN_REQUIRED", "TOKEN_EXPIRED", "PASSWORD_ERROR"],
)
@pytest.mark.parametrize("encrypted", [True, False])
def test_session_auth_errors(code, encrypted):
    error = {"success": False, "errorCode": code, "errorMsg": "PRIVATE-RAW-ERROR"}
    http = HTTP(history=error) if encrypted else HTTP(failure=error)
    with pytest.raises(cloud.CloudAuthError) as caught:
        fetch(http)
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert "PRIVATE" not in str(caught.value)
    assert len(http.calls) == 1


@pytest.mark.parametrize("stage", ["token", "login", "device", "history"])
@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("PRIVATE"),
        aiohttp.ClientError("PRIVATE"),
        RuntimeError("PRIVATE"),
        {"errorCode": "UNKNOWN", "errorMsg": "PRIVATE"},
    ],
)
def test_errors_redacted_no_retry(private_key, stage, failure, caplog):
    http = HTTP(private_key, stage=stage, failure=failure)
    with pytest.raises(cloud.CloudHistoryError) as caught:
        fetch(http) if stage == "history" else create(http)
    assert "PRIVATE" not in str(caught.value)
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert "PRIVATE" not in caplog.text and ARGS["password"] not in caplog.text
    assert sum(x[1]["a"] == "thing.m.user.email.password.login" for x in http.calls) <= 1
    assert len({x[0] for x in http.calls}) == 1


@pytest.mark.parametrize("stage", ["token", "login", "device", "history"])
def test_cancel_propagates(private_key, stage):
    http = HTTP(private_key, stage=stage, failure=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        fetch(http) if stage == "history" else create(http)


def test_client_and_traceback_scrubbing(private_key, monkeypatch):
    clients = []
    original = cloud.bootstrap._ReadOnlyPasswordClient.__init__

    def capture(self, *args, **kwargs):
        original(self, *args, **kwargs)
        clients.append(self)

    monkeypatch.setattr(cloud.bootstrap._ReadOnlyPasswordClient, "__init__", capture)
    create(HTTP(private_key))
    with pytest.raises(cloud.CloudHistoryError) as caught:
        create(HTTP(private_key, stage="device", failure=RuntimeError("PRIVATE")))
    assert all(client.__dict__ == {} for client in clients)
    tb = caught.value.__traceback__
    while tb:
        if tb.tb_frame.f_code.co_name == "async_create_cloud_credentials":
            assert all(
                tb.tb_frame.f_locals[name] == ""
                for name in ("username", "password", "profile_json")
            )
            assert tb.tb_frame.f_locals["response"] is None
        tb = tb.tb_next


def test_history_whitelist_and_pin():
    async def exercise():
        profile = cloud.bootstrap._parse_profile(
            json.dumps(PROFILE), cloud.bootstrap.REGION_ENDPOINTS["us"]
        )
        client = cloud._HistoryClient(
            None,
            HTTP(),
            profile=profile,
            endpoint=cloud.bootstrap.REGION_ENDPOINTS["us"],
            target_device=DEVICE,
        )
        expected = {"devId": DEVICE, **cloud._HISTORY_PAYLOAD}
        for action, version, payload in [
            ("thing.m.device.dp.publish", "2.0", expected),
            ("m.smart.operate.log", "1.0", expected),
            ("m.smart.operate.log", "2.0", expected | {"devId": "other"}),
            ("m.smart.operate.log", "2.0", expected | {"offset": False}),
            ("m.smart.operate.log", "2.0", expected | {"limit": 100}),
        ]:
            with pytest.raises(cloud.CloudHistoryError):
                await client._call(action, payload, version=version)
        client.mobile_url = cloud.bootstrap.REGION_ENDPOINTS["eu"]
        with pytest.raises(cloud.CloudHistoryError):
            await client._call("m.smart.operate.log", expected, version="2.0")
        assert ("m.smart.operate.log", "2.0") not in cloud.bootstrap._ALLOWED

    asyncio.run(exercise())


@pytest.mark.parametrize("stage", ["token", "login", "device"])
@pytest.mark.parametrize(
    "code", ["PASSWORD_ERROR", "MFA_REQUIRED", "CAPTCHA_REQUIRED", "USER_SESSION_INVALID"]
)
def test_create_auth_errors(private_key, stage, code):
    http = HTTP(private_key, stage=stage, failure={"errorCode": code, "errorMsg": "PRIVATE"})
    with pytest.raises(cloud.CloudAuthError) as caught:
        create(http)
    assert caught.value.__context__ is None and "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize("saved", [None, [], {}, "private", {"region": "us"}])
def test_noncredential_objects(saved):
    http = HTTP()
    with pytest.raises(cloud.CloudHistoryError):
        asyncio.run(cloud.async_fetch_history(http, credentials=saved, device_id=DEVICE))
    assert not http.calls


def test_missing_timestamp():
    entry = record()
    del entry["timeStamp"]
    with pytest.raises(cloud.CloudHistoryError):
        fetch(HTTP(history=envelope([entry])))


@pytest.mark.parametrize("status", [301, 302, 401, 403, 500])
def test_http_status_rejected(status):
    with pytest.raises(cloud.CloudHistoryError):
        fetch(HTTP(status=status))
