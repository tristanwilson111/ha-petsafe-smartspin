"""Synthetic HA lifecycle tests for optional history and local independence."""

from datetime import UTC, datetime, timedelta
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType

from custom_components.petsafe_smartspin import async_setup_entry, async_unload_entry
from custom_components.petsafe_smartspin.api import parse_status
from custom_components.petsafe_smartspin.cloud_coordinator import CloudHistoryCoordinator
from custom_components.petsafe_smartspin.const import DOMAIN
from custom_components.petsafe_smartspin.diagnostics import async_get_config_entry_diagnostics
from custom_components.petsafe_smartspin.sensor import CLOUD_DESCRIPTIONS, SmartSpinCloudSensor

PREFIX = "custom_components.petsafe_smartspin"
LOCAL = {"host": "192.0.2.40", "device_id": "synthetic-device", "local_key": "0123456789abcdef"}
CREDENTIALS = {
    "profile": {"synthetic": "PRIVATE_PROFILE"},
    "session": {"sid": "PRIVATE_SID", "ecode": "PRIVATE_ECODE", "uid": "PRIVATE_UID"},
    "region": "us",
    "installation_id": "PRIVATE_INSTALL",
}
FORM = {
    "username": "synthetic@example.invalid",
    "password": "PRIVATE_PASSWORD",
    "country_code": "1",
    "region": "us",
    "app_profile": "PRIVATE_PROFILE",
    "consent_store_cloud_session": True,
}
RESPONSE = {"dps": {"7": 2, "22": 0, "24": "standby", "106": "standby", "107": "finish_clean"}}


def entry(cloud=False, **kwargs):
    return ConfigEntry(
        domain=DOMAIN,
        version=1,
        minor_version=1,
        data={**LOCAL, **({"cloud_history": CREDENTIALS} if cloud else {})},
        options={},
        unique_id=LOCAL["device_id"],
        title="SmartSpin",
        source="user",
        discovery_keys=MappingProxyType({}),
        subentries_data=[],
        **kwargs,
    )


def snapshot(empty=False):
    now = datetime.now(UTC)
    return SimpleNamespace(
        fetched_at=now,
        visits=()
        if empty
        else (SimpleNamespace(timestamp=now, duration_seconds=107, weight_kg=3.85),),
    )


@pytest.mark.asyncio
async def test_enable_requires_explicit_consent(hass, enable_custom_integrations):
    e = entry()
    hass.config_entries._entries[e.entry_id] = e
    result = await hass.config_entries.options.async_init(e.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"poll_interval": 10, "cloud_history": True}
    )
    assert result["step_id"] == "cloud"
    with patch(f"{PREFIX}.cloud_history.async_create_cloud_credentials") as create:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**FORM, "consent_store_cloud_session": False}
        )
    assert result["errors"] == {"base": "cloud_consent_required"}
    create.assert_not_called()
    assert "cloud_history" not in e.data


@pytest.mark.asyncio
async def test_enable_and_disable_cloud(hass, enable_custom_integrations):
    e = entry()
    hass.config_entries._entries[e.entry_id] = e
    with patch.object(hass.config_entries, "async_reload", new=AsyncMock()):
        result = await hass.config_entries.options.async_init(e.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"poll_interval": 15, "cloud_history": True}
        )
        with (
            patch(
                f"{PREFIX}.cloud_history.async_create_cloud_credentials",
                new=AsyncMock(return_value=CREDENTIALS),
            ),
            patch(
                f"{PREFIX}.cloud_history.async_fetch_history",
                new=AsyncMock(return_value=snapshot()),
            ),
        ):
            result = await hass.config_entries.options.async_configure(result["flow_id"], FORM)
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert e.data["cloud_history"] == CREDENTIALS and "PRIVATE_PASSWORD" not in repr(
            dict(e.data)
        )
        assert e.options == {"poll_interval": 15}
        result = await hass.config_entries.options.async_init(e.entry_id)
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"poll_interval": 15, "cloud_history": False}
        )
        assert dict(e.data) == LOCAL


@pytest.mark.asyncio
async def test_failed_renewal_preserves_cloud_and_local(hass, enable_custom_integrations):
    e = entry(True)
    hass.config_entries._entries[e.entry_id] = e
    result = await hass.config_entries.options.async_init(e.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"poll_interval": 10, "cloud_history": True, "renew_cloud_session": True}
    )
    with patch(
        f"{PREFIX}.cloud_history.async_create_cloud_credentials",
        new=AsyncMock(side_effect=RuntimeError("PRIVATE_PASSWORD")),
    ):
        result = await hass.config_entries.options.async_configure(result["flow_id"], FORM)
    assert result["errors"] == {"base": "cloud_cannot_connect"}
    assert "PRIVATE_PASSWORD" not in repr(result)
    assert e.data["cloud_history"] == CREDENTIALS and e.data["local_key"] == LOCAL["local_key"]


@pytest.mark.asyncio
async def test_cloud_cooldown_and_error_backoff(hass):
    co = CloudHistoryCoordinator(hass, entry(True))
    snap = snapshot()
    with (
        patch(
            f"{PREFIX}.cloud_history.async_fetch_history", new=AsyncMock(return_value=snap)
        ) as fetch,
        patch(f"{PREFIX}.cloud_coordinator.async_get_clientsession", return_value=Mock()),
    ):
        await co.async_refresh()
        await co.async_refresh()
    assert fetch.await_count == 1
    assert co.data is snap
    assert co.update_interval == timedelta(minutes=5)
    co._next_allowed = 0
    with (
        patch(
            f"{PREFIX}.cloud_history.async_fetch_history",
            new=AsyncMock(side_effect=RuntimeError("PRIVATE_SID")),
        ),
        patch(f"{PREFIX}.cloud_coordinator.async_get_clientsession", return_value=Mock()),
    ):
        await co.async_refresh()
    assert not co.last_update_success
    assert co.update_interval == timedelta(minutes=10)
    assert "PRIVATE_SID" not in str(co.last_exception)
    await co.async_shutdown()


@pytest.mark.asyncio
async def test_expired_auth_does_not_keep_requesting(hass):
    from custom_components.petsafe_smartspin.cloud_history import CloudAuthError

    co = CloudHistoryCoordinator(hass, entry(True))
    with (
        patch(
            f"{PREFIX}.cloud_history.async_fetch_history",
            new=AsyncMock(side_effect=CloudAuthError("synthetic")),
        ) as fetch,
        patch(f"{PREFIX}.cloud_coordinator.async_get_clientsession", return_value=Mock()),
    ):
        await co.async_refresh()
        co._next_allowed = 0
        await co.async_refresh()
    assert fetch.await_count == 1 and co.auth_expired and not co.last_update_success
    await co.async_shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("cloud_failure", [False, True])
async def test_cloud_lifecycle_local_independence_and_unload(
    hass, enable_custom_integrations, cloud_failure
):
    e = entry(True, state=ConfigEntryState.SETUP_IN_PROGRESS)
    hass.config_entries._entries[e.entry_id] = e
    with (
        patch(f"{PREFIX}.coordinator.poll_status", return_value=parse_status(RESPONSE)),
        patch(
            f"{PREFIX}.cloud_history.async_fetch_history",
            new=AsyncMock(
                side_effect=RuntimeError("PRIVATE_SID") if cloud_failure else None,
                return_value=snapshot(),
            ),
        ),
    ):
        async with e.setup_lock:
            assert await async_setup_entry(hass, e)
        await hass.async_block_till_done()
    assert e.runtime_data.last_update_success
    assert e.runtime_data.cloud_coordinator.last_update_success is not cloud_failure
    states = hass.states.async_all("sensor")
    assert len(states) == 10
    assert sum(s.state == "unavailable" for s in states) == (4 if cloud_failure else 0)
    if not cloud_failure:
        weights = [s for s in states if s.attributes.get("device_class") == "weight"]
        assert len(weights) == 1 and weights[0].state == "3.85"
        assert weights[0].attributes["unit_of_measurement"] == "kg"
        assert any(s.attributes.get("recent_visits") for s in states)
    diagnostics = await async_get_config_entry_diagnostics(hass, e)
    for secret in [
        "PRIVATE_PROFILE",
        "PRIVATE_SID",
        "PRIVATE_ECODE",
        "PRIVATE_INSTALL",
        "PRIVATE_UID",
        *LOCAL.values(),
    ]:
        assert secret not in repr(diagnostics)
    co = e.runtime_data.cloud_coordinator
    assert await async_unload_entry(hass, e)
    await hass.async_block_till_done()
    assert not co._listeners and co._unsub_refresh is None


@pytest.mark.parametrize("empty", [False, True])
def test_cloud_sensor_values_and_history(empty):
    co = Mock()
    co.device_id = "synthetic"
    co.last_update_success = True
    co.data = snapshot(empty)
    sensors = {d.key: SmartSpinCloudSensor(co, d) for d in CLOUD_DESCRIPTIONS}
    assert sensors["last_visit_weight"].native_value == (None if empty else 3.85)
    assert sensors["last_visit_duration"].native_value == (None if empty else 107)
    assert len(sensors["last_visit"].extra_state_attributes["recent_visits"]) == (0 if empty else 1)
    assert sensors["cloud_last_checked"].native_value == co.data.fetched_at
    co.last_update_success = False
    assert all(s.native_value is None for s in sensors.values())
    assert sensors["last_visit"].extra_state_attributes is None
