"""Offline tests of the real bootstrap and vendored encryption/password client."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import sys
import types
from importlib import import_module
from pathlib import Path

import aiohttp
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

# Import the actual module without Home Assistant or sibling package __init__.
ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "petsafe_smartspin"
PACKAGE = "_smartspin_cloud_test"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
spec = importlib.util.spec_from_file_location(f"{PACKAGE}.cloud_bootstrap", ROOT / "cloud_bootstrap.py")
cloud = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cloud
spec.loader.exec_module(cloud)
transport = sys.modules[f"{PACKAGE}.vendor.client"]
signer_module = import_module(f"{PACKAGE}.vendor.signer")
profiles_module = import_module(f"{PACKAGE}.vendor.profiles")

KEY = "0123456789abcdef"
DEVICE = "test_device_123"
PROFILE = {
    "name": "Offline test identity", "app_id": "test-id", "app_secret": "test-only-secret",
    "cert_sha256_hex": "ab" * 32, "app_key": "test-only-app-key",
    "package": "org.example.offline", "app_version": "1.0", "ttid": "offline",
    "sdk_version": "6.7.0", "device_core_version": "6.7.0",
}
ARGS = {
    "username": "offline@example.invalid",
    "password": "test-password-only",
    "country_code": "1",
    "region": "us",
    "device_id": DEVICE,
    "profile_json": json.dumps(PROFILE),
}


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    async def deny(*args, **kwargs):
        raise AssertionError("External network forbidden")
    monkeypatch.setattr(aiohttp.ClientSession, "_request", deny)


@pytest.fixture(scope="module")
def public_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=1024).public_key().public_numbers()


class Reply:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self, **kwargs):
        return self.body


class FakeHTTP:
    def __init__(self, public_key, *, failure=None, stage="login", device=None, status=200):
        self.public_key = public_key
        self.failure, self.stage, self.status = failure, stage, status
        self.device = device if device is not None else {"devId": DEVICE, "localKey": KEY}
        self.calls = []
        self.ecode = None
        self.signer = signer_module.PurePythonTuyaSigner(**{
            name: PROFILE[name] for name in ("app_id", "app_secret", "cert_sha256_hex", "app_key", "package")
        })

    def post(self, url, *, data, timeout, allow_redirects):
        action = data["a"]
        stage = "token" if "token.get" in action else "device" if action == "thing.m.device.get" else "login"
        key = self.signer.derive_key(data["requestId"], self.ecode)
        payload = transport._decrypt(key, data["postData"])
        self.calls.append((url, action, data["v"], allow_redirects, payload))
        assert data["sign"] == self.signer.sign(transport.canonical_string({k: v for k, v in data.items() if k != "sign"}))
        if stage == self.stage and self.failure:
            if isinstance(self.failure, BaseException):
                raise self.failure
            return Reply(self.failure, self.status)
        if stage == "token":
            result = {"token": "ephemeral-token", "publicKey": str(self.public_key.n), "exponent": str(self.public_key.e)}
        elif stage == "login":
            assert payload["passwd"] != ARGS["password"]
            result = {"sid": "ephemeral-sid", "uid": "ephemeral-uid", "ecode": "ephemeral-ecode",
                      "domain": {"mobileApiUrl": "https://attacker.invalid"}}
            self.ecode = result["ecode"]
        else:
            assert payload == {"devId": DEVICE}
            result = self.device
        return Reply({"result": transport._encrypt(key, result)}, self.status)


def run(http, **overrides):
    return asyncio.run(cloud.async_get_local_key(http, **(ARGS | overrides)))


def test_real_protocol_and_whitelist_no_seckey(public_key):
    http = FakeHTTP(public_key)
    assert run(http) == KEY
    assert [(x[1], x[2]) for x in http.calls] == [
        ("thing.m.user.username.token.get", "2.0"),
        ("thing.m.user.email.password.login", "3.0"),
        ("thing.m.device.get", "4.1"),
    ]
    assert all(x[0] == cloud.REGION_ENDPOINTS["us"] and x[3] is False for x in http.calls)


@pytest.mark.parametrize("region", ["us", "eu", "cn", "in", "sg"])
def test_explicit_region_pinned_despite_profile_and_login_domains(public_key, region):
    http = FakeHTTP(public_key)
    profile = PROFILE | {"endpoints": list(cloud.REGION_ENDPOINTS.values())}
    assert run(http, region=region, profile_json=json.dumps(profile)) == KEY
    assert {x[0] for x in http.calls} == {cloud.REGION_ENDPOINTS[region]}


@pytest.mark.parametrize("profile", ["{", "[]", "null", "{}", "{\"name\":1,\"name\":2}",
    json.dumps(PROFILE | {"app_secret": 42}), json.dumps(PROFILE | {"app_key": []}),
    json.dumps(PROFILE | {"cert_sha256_hex": "ab"}),
    json.dumps(PROFILE | {"package": "not a package"}),
    json.dumps(PROFILE | {"unknown": "value"}),
    json.dumps(PROFILE | {"endpoints": ["https://attacker.invalid"]}),
    json.dumps(PROFILE | {"endpoints": "https://a1.tuyaus.com/api.json"}),
    json.dumps(PROFILE | {"app_id": "a\n"}),
    json.dumps(PROFILE | {"app_secret": "\u00e9"}), "x" * 32769, None])
def test_malformed_profiles_never_reach_network(public_key, profile):
    http = FakeHTTP(public_key)
    with pytest.raises(cloud.InvalidProfile):
        run(http, profile_json=profile)
    assert not http.calls


@pytest.mark.parametrize("overrides,exception", [
    ({"username": "+15555550123"}, cloud.InvalidAuth),
    ({"username": " offline@example.invalid"}, cloud.InvalidAuth),
    ({"country_code": "US"}, cloud.InvalidAuth),
    ({"password": ""}, cloud.InvalidAuth),
    ({"region": "auto"}, cloud.InvalidProfile),
    ({"region": "US"}, cloud.InvalidProfile),
    ({"region": None}, cloud.InvalidProfile),
    ({"device_id": "../device"}, cloud.BootstrapError),
])
def test_reject_invalid_inputs_before_network(public_key, overrides, exception):
    http = FakeHTTP(public_key)
    with pytest.raises(exception):
        run(http, **overrides)
    assert not http.calls


@pytest.mark.parametrize("device", [
    {"devId": "other-device", "localKey": KEY},
    {"localKey": KEY}, {"devId": DEVICE, "localKey": 123},
    {"devId": DEVICE, "localKey": "short"},
    {"devId": DEVICE, "localKey": "\u00e9" * 16},
    {"devId": DEVICE, "localKey": KEY, "deviceId": "wrong"},
    {"devId": DEVICE, "localKey": KEY, "local_key": "fedcba9876543210"},
    [{"devId": DEVICE, "localKey": KEY}, {"devId": DEVICE, "localKey": KEY}],
    {"devId": DEVICE, "secKey": KEY},
])
def test_wrong_device_or_invalid_key_denied(public_key, device):
    with pytest.raises(cloud.BootstrapError):
        run(FakeHTTP(public_key, device=device))


@pytest.mark.parametrize("code,exception", [
    ("PASSWORD_ERROR", cloud.InvalidAuth), ("USER_NOT_EXIST", cloud.InvalidAuth),
    ("MFA_REQUIRED", cloud.InteractionRequired), ("CAPTCHA_REQUIRED", cloud.InteractionRequired),
    ("ACCOUNT_LOCKED", cloud.InteractionRequired), ("SIGN_INVALID", cloud.InvalidProfile),
    ("API_NOT_SUPPORTED", cloud.InvalidProfile), ("UNKNOWN", cloud.BootstrapError),
])
@pytest.mark.parametrize("stage", ["token", "login", "device"])
def test_safe_error_mapping(public_key, code, exception, stage):
    http = FakeHTTP(public_key, stage=stage, failure={"errorCode": code, "errorMsg": "PRIVATE-RAW-ERROR"})
    with pytest.raises(exception) as caught:
        run(http)
    error = caught.value
    assert error.__context__ is None and error.__cause__ is None
    assert "PRIVATE" not in str(error) and ARGS["password"] not in str(error)
    assert sum(x[1] == "thing.m.user.email.password.login" for x in http.calls) <= 1
    assert {x[0] for x in http.calls} == {cloud.REGION_ENDPOINTS["us"]}


@pytest.mark.parametrize("error", [aiohttp.ClientError("PRIVATE"), TimeoutError("PRIVATE"), OSError("PRIVATE")])
@pytest.mark.parametrize("stage", ["token", "login", "device"])
def test_transport_never_retries_password_or_region(public_key, error, stage):
    http = FakeHTTP(public_key, failure=error, stage=stage)
    with pytest.raises(cloud.CannotConnect) as caught:
        run(http)
    assert str(caught.value) == "Cannot connect to the selected cloud region."
    assert caught.value.__context__ is None
    assert sum(x[1] == "thing.m.user.email.password.login" for x in http.calls) <= 1
    assert {x[0] for x in http.calls} == {cloud.REGION_ENDPOINTS["us"]}


def test_redirect_rejected(public_key):
    http = FakeHTTP(public_key, status=302)
    with pytest.raises(cloud.CannotConnect):
        run(http)
    assert len(http.calls) == 1


def test_no_client_secret_retention_or_logs(public_key, monkeypatch, caplog):
    clients = []
    original = cloud._ReadOnlyPasswordClient.__init__
    def capture(self, *args, **kwargs):
        original(self, *args, **kwargs)
        clients.append(self)
    monkeypatch.setattr(cloud._ReadOnlyPasswordClient, "__init__", capture)
    # Only this integration's own logger is asserted; unrelated libraries
    # (for example asyncio's event-loop debug lines) may log freely.
    with caplog.at_level(logging.DEBUG, logger=cloud.__name__):
        assert run(FakeHTTP(public_key)) == KEY
        with pytest.raises(cloud.InvalidAuth) as caught:
            run(FakeHTTP(public_key, failure={"errorCode": "PASSWORD_ERROR", "errorMsg": "PRIVATE"}))
    assert all(client.__dict__ == {} for client in clients)
    own_records = [r for r in caplog.records if r.name == cloud.__name__]
    assert not own_records, [r.getMessage() for r in own_records]
    assert not any(
        secret in record.getMessage()
        for record in caplog.records
        for secret in (KEY, "PRIVATE")
    )
    tb = caught.value.__traceback__
    while tb:
        if tb.tb_frame.f_code.co_name == "async_get_local_key":
            for name in ("password", "username", "profile_json"):
                assert tb.tb_frame.f_locals[name] == ""
            for name in ("client", "profile", "response", "candidate", "matches"):
                assert tb.tb_frame.f_locals[name] is None
        tb = tb.tb_next


def test_sdk_cannot_bypass_attempt_budget_or_whitelist(public_key):
    async def exercise():
        http = FakeHTTP(public_key)
        profile = cloud._parse_profile(ARGS["profile_json"], cloud.REGION_ENDPOINTS["us"])
        client = cloud._ReadOnlyPasswordClient(profile, http, username=ARGS["username"], endpoint=cloud.REGION_ENDPOINTS["us"])
        await client.login_with_password(ARGS["password"], "1")
        with pytest.raises(cloud.InvalidAuth):
            await client.login_with_password(ARGS["password"], "1")
        for action, version in [("thing.m.device.dp.publish", "1.0"), ("thing.m.device.get", "1.0"),
                                ("thing.m.user.token.create", "1.0")]:
            with pytest.raises(cloud.InvalidProfile):
                await client._call(action, {}, version=version)
        client.mobile_url = cloud.REGION_ENDPOINTS["eu"]
        with pytest.raises(cloud.InvalidProfile):
            await client._call("thing.m.device.get", {}, version="4.1")
        assert sum(x[1] == "thing.m.user.email.password.login" for x in http.calls) == 1
    asyncio.run(exercise())


def test_no_bundled_profiles_or_native_execution():
    assert list(profiles_module.TuyaMobileApp) == []
    assert not profiles_module._is_bundled_mobile_app_profile(PROFILE)
    with pytest.raises(ValueError):
        profiles_module.get_mobile_app_profile("smartlife")
    sources = "\n".join(p.read_text() for p in (ROOT / "vendor").glob("*.py"))
    for forbidden in ("subprocess", "NativeTuyaSigner", "thing.m.device.dp.publish", "thing.m.user.third.login"):
        assert forbidden not in sources
    assert not hasattr(signer_module, "NativeTuyaSigner")
    assert "tuya-mobile contributors" in (ROOT / "vendor" / "LICENSE").read_text()


@pytest.mark.parametrize("code,exception", [
    ("MFA_REQUIRED", cloud.InteractionRequired),
    ("CAPTCHA_REQUIRED", cloud.InteractionRequired),
    ("PASSWORD_ERROR", cloud.InvalidAuth),
    ("SIGN_INVALID", cloud.InvalidProfile),
])
def test_encrypted_device_business_errors(public_key, code, exception):
    with pytest.raises(exception) as caught:
        run(FakeHTTP(public_key, device={"success": False, "errorCode": code, "errorMsg": "PRIVATE"}))
    assert caught.value.__context__ is None
    assert "PRIVATE" not in str(caught.value)


def test_does_not_borrow_key_from_another_record(public_key):
    device = [{"devId": DEVICE}, {"devId": "another", "localKey": KEY}]
    with pytest.raises(cloud.BootstrapError):
        run(FakeHTTP(public_key, device=device))


def test_unknown_sdk_exception_is_sanitized(public_key, monkeypatch):
    async def crash(*args, **kwargs):
        raise RuntimeError("PRIVATE password profile sid token")
    monkeypatch.setattr(cloud._ReadOnlyPasswordClient, "login_with_password", crash)
    with pytest.raises(cloud.BootstrapError) as caught:
        run(FakeHTTP(public_key))
    assert type(caught.value) is cloud.BootstrapError
    assert "PRIVATE" not in str(caught.value)
    assert caught.value.__context__ is None


def test_cancellation_scrubs_client(public_key, monkeypatch):
    clients = []
    async def cancel(self, *args, **kwargs):
        clients.append(self)
        raise asyncio.CancelledError()
    monkeypatch.setattr(cloud._ReadOnlyPasswordClient, "login_with_password", cancel)
    with pytest.raises(asyncio.CancelledError):
        run(FakeHTTP(public_key))
    assert clients[0].__dict__ == {}
