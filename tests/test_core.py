"""Synthetic, offline tests against the real Home Assistant runtime (2026.7.4)."""

from __future__ import annotations

import json
import logging
from types import MappingProxyType
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType

from custom_components.petsafe_smartspin import (
    api,
    async_reload_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.petsafe_smartspin.const import DOMAIN
from custom_components.petsafe_smartspin.coordinator import SmartSpinCoordinator
from custom_components.petsafe_smartspin.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.petsafe_smartspin.sensor import DESCRIPTIONS, SmartSpinSensor

PREFIX = "custom_components.petsafe_smartspin"
LOCAL = {
    "host": "192.0.2.40",
    "device_id": "synthetic-device",
    "local_key": "0123456789abcdef",
}
RESPONSE = {
    "dps": {"7": 2, "22": 0, "24": "standby", "106": "standby", "107": "finish_clean"}
}


def make_entry(**kwargs):
    return ConfigEntry(
        domain=DOMAIN,
        version=1,
        minor_version=1,
        data=kwargs.pop("data", LOCAL.copy()),
        options=kwargs.pop("options", {}),
        unique_id=LOCAL["device_id"],
        title="SmartSpin",
        source="user",
        discovery_keys=MappingProxyType({}),
        subentries_data=[],
        **kwargs,
    )


@pytest_asyncio.fixture
async def core_hass(hass, enable_custom_integrations):
    """Use the official HA test fixture and managers, with only I/O mocked."""
    # Completing a flow normally schedules integration setup. Test it separately.
    with (
        patch.object(
            hass.config_entries, "async_setup", new=AsyncMock(return_value=True)
        ),
        patch(f"{PREFIX}.config_flow.async_get_clientsession", return_value=Mock()),
    ):
        yield hass


@pytest.mark.asyncio
async def test_local_flow_success_and_duplicate(core_hass):
    result = await core_hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.MENU
    result = await core_hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "local"}
    )
    assert result["step_id"] == "local"
    with patch(
        f"{PREFIX}.config_flow.poll_status", return_value=api.parse_status(RESPONSE)
    ) as poll:
        result = await core_hass.config_entries.flow.async_configure(
            result["flow_id"], LOCAL
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == LOCAL
    assert result["result"].unique_id == LOCAL["device_id"]
    poll.assert_called_once_with(LOCAL["device_id"], LOCAL["host"], LOCAL["local_key"])
    result = await core_hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await core_hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "local"}
    )
    with patch(f"{PREFIX}.config_flow.poll_status") as poll:
        result = await core_hass.config_entries.flow.async_configure(
            result["flow_id"], LOCAL
        )
    assert result["reason"] == "already_configured"
    poll.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,expected",
    [
        (RuntimeError("SECRET"), "cannot_connect"),
        (vol.Invalid("SECRET"), "invalid_input"),
    ],
)
async def test_local_flow_failure(core_hass, failure, expected):
    result = await core_hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await core_hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "local"}
    )
    with patch(f"{PREFIX}.config_flow.poll_status", side_effect=failure):
        result = await core_hass.config_entries.flow.async_configure(
            result["flow_id"], LOCAL
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}
    assert "SECRET" not in repr(result)
    assert not core_hass.config_entries.async_entries(DOMAIN)


@pytest.mark.asyncio
async def test_invalid_local_key(core_hass):
    result = await core_hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await core_hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "local"}
    )
    with patch(f"{PREFIX}.config_flow.poll_status") as poll:
        result = await core_hass.config_entries.flow.async_configure(
            result["flow_id"], {**LOCAL, "local_key": "bad"}
        )
    assert result["errors"] == {"base": "invalid_input"}
    poll.assert_not_called()


async def companion_form(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "companion"}
    )


COMPANION = {
    "host": LOCAL["host"],
    "device_id": LOCAL["device_id"],
    "username": "synthetic@example.invalid",
    "password": "SYNTHETIC_PASSWORD",
    "country_code": "1",
    "region": "us",
    "app_profile": '{"synthetic":"PRIVATE_PROFILE"}',
}


@pytest.mark.asyncio
async def test_companion_success_discards_credentials(core_hass):
    result = await companion_form(core_hass)
    with (
        patch(
            f"{PREFIX}.cloud_bootstrap.async_get_local_key",
            new=AsyncMock(return_value=LOCAL["local_key"]),
        ) as bootstrap,
        patch(
            f"{PREFIX}.config_flow.poll_status", return_value=api.parse_status(RESPONSE)
        ),
    ):
        result = await core_hass.config_entries.flow.async_configure(
            result["flow_id"], COMPANION
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == LOCAL
    assert result["result"].data == LOCAL
    assert "SYNTHETIC_PASSWORD" not in repr(result["result"].as_dict())
    assert bootstrap.call_args.kwargs["profile_json"] == COMPANION["app_profile"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,error",
    [
        ("InvalidAuth", "invalid_auth"),
        ("InteractionRequired", "interaction_required"),
        ("InvalidProfile", "invalid_profile"),
        ("CannotConnect", "cannot_connect"),
        ("BootstrapError", "bootstrap_failed"),
    ],
)
async def test_companion_fixed_errors(core_hass, name, error):
    from custom_components.petsafe_smartspin import cloud_bootstrap

    result = await companion_form(core_hass)
    with patch(
        f"{PREFIX}.cloud_bootstrap.async_get_local_key",
        new=AsyncMock(side_effect=getattr(cloud_bootstrap, name)("SECRET")),
    ):
        result = await core_hass.config_entries.flow.async_configure(
            result["flow_id"], COMPANION
        )
    assert result["errors"] == {"base": error}
    assert "SECRET" not in repr(result)
    assert "SYNTHETIC_PASSWORD" not in repr(result)
    assert not core_hass.config_entries.async_entries(DOMAIN)


@pytest.mark.asyncio
async def test_companion_local_validation_required(core_hass):
    result = await companion_form(core_hass)
    with (
        patch(
            f"{PREFIX}.cloud_bootstrap.async_get_local_key",
            new=AsyncMock(return_value=LOCAL["local_key"]),
        ),
        patch(f"{PREFIX}.config_flow.poll_status", side_effect=RuntimeError("SECRET")),
    ):
        result = await core_hass.config_entries.flow.async_configure(
            result["flow_id"], COMPANION
        )
    assert result["errors"] == {"base": "cannot_connect"}
    assert not core_hass.config_entries.async_entries(DOMAIN)


@pytest.mark.asyncio
async def test_options_and_reconfigure(core_hass):
    entry = make_entry()
    core_hass.config_entries._entries[entry.entry_id] = entry
    result = await core_hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"]
    with pytest.raises(vol.Invalid):
        schema({"poll_interval": 4})
    result = await core_hass.config_entries.options.async_configure(
        result["flow_id"], {"poll_interval": 5}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"poll_interval": 5}
    entry.add_update_listener(async_reload_entry)
    result = await core_hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id}
    )
    with (
        patch(
            f"{PREFIX}.config_flow.poll_status", return_value=api.parse_status(RESPONSE)
        ),
        patch.object(
            core_hass.config_entries, "async_reload", new=AsyncMock()
        ) as reload,
    ):
        result = await core_hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.0.2.41", "local_key": "fedcba9876543210"}
        )
        await core_hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {
        **LOCAL,
        "host": "192.0.2.41",
        "local_key": "fedcba9876543210",
    }
    reload.assert_awaited_once_with(entry.entry_id)


@pytest.mark.asyncio
async def test_entry_setup_unload_reload(core_hass):
    entry = make_entry(
        options={"poll_interval": 15}, state=ConfigEntryState.SETUP_IN_PROGRESS
    )
    with (
        patch(
            f"{PREFIX}.coordinator.poll_status", return_value=api.parse_status(RESPONSE)
        ),
        patch.object(
            core_hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ) as forward,
    ):
        assert await async_setup_entry(core_hass, entry)
    assert isinstance(entry.runtime_data, SmartSpinCoordinator)
    assert entry.runtime_data.update_interval.total_seconds() == 15
    forward.assert_awaited_once()
    with patch.object(
        core_hass.config_entries,
        "async_unload_platforms",
        new=AsyncMock(return_value=True),
    ):
        assert await async_unload_entry(core_hass, entry)
    with patch.object(
        core_hass.config_entries,
        "async_unload_platforms",
        new=AsyncMock(return_value=False),
    ):
        assert not await async_unload_entry(core_hass, entry)
    with patch.object(
        core_hass.config_entries, "async_reload", new=AsyncMock()
    ) as reload:
        await async_reload_entry(core_hass, entry)
    reload.assert_awaited_once_with(entry.entry_id)
    await entry.runtime_data.async_shutdown()


@pytest.mark.asyncio
async def test_coordinator_and_six_sensors_recover(core_hass):
    coordinator = SmartSpinCoordinator(core_hass, make_entry())
    with patch(
        f"{PREFIX}.coordinator.poll_status", return_value=api.parse_status(RESPONSE)
    ):
        await coordinator.async_refresh()
    sensors = [
        SmartSpinSensor(coordinator, description) for description in DESCRIPTIONS
    ]
    assert len(sensors) == 6
    assert len({sensor.unique_id for sensor in sensors}) == 6
    assert all(sensor.available for sensor in sensors)
    assert sensors[0].device_info["identifiers"] == {(DOMAIN, LOCAL["device_id"])}
    with patch(f"{PREFIX}.coordinator.poll_status", side_effect=RuntimeError("SECRET")):
        await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert all(
        not sensor.available and sensor.native_value is None for sensor in sensors
    )
    assert "SECRET" not in str(coordinator.last_exception)
    with patch(
        f"{PREFIX}.coordinator.poll_status", return_value=api.parse_status(RESPONSE)
    ):
        await coordinator.async_refresh()
    assert all(sensor.available for sensor in sensors)
    assert sensors[4].native_value == 2
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_diagnostics_allowlist_nested_private_values(core_hass):
    entry = make_entry(
        data={**LOCAL, "nested": {"unknown": ["PRIVATE_PROFILE", "PRIVATE_PASSWORD"]}}
    )
    entry.runtime_data = SmartSpinCoordinator(core_hass, entry)
    result = await async_get_config_entry_diagnostics(core_hass, entry)
    text = json.dumps(result)
    for value in [
        *LOCAL.values(),
        "PRIVATE_PROFILE",
        "PRIVATE_PASSWORD",
        entry.entry_id,
    ]:
        assert value not in text
    assert result["sensor_count"] == 6


@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {"Error": "SECRET", **RESPONSE},
        {"dps": {"7": True}},
        {"dps": {**RESPONSE["dps"], "22": -1}},
        {"dps": {**RESPONSE["dps"], "107": None}},
    ],
)
def test_parse_rejects_bad_data(response):
    with pytest.raises(api.StatusReadError):
        api.parse_status(response)


def test_dp_mapping_only():
    value = api.parse_status(RESPONSE)
    assert (
        value.visits_today,
        value.fault,
        value.status,
        value.clean_control_state,
        value.history_record,
    ) == (2, 0, "standby", "standby", "finish_clean")
    assert value.last_seen.tzinfo is not None
    assert not hasattr(value, "bin_full")


@pytest.mark.parametrize("failure", [False, True])
def test_status_only_transport_and_close(failure):
    device = Mock()
    device.status.return_value = RESPONSE
    if failure:
        device.status.side_effect = RuntimeError("SECRET")
    with patch.object(api, "StatusDevice", return_value=device) as factory:
        if failure:
            with pytest.raises(
                api.StatusReadError, match=r"^SmartSpin local status read failed$"
            ):
                api.poll_status(LOCAL["device_id"], LOCAL["host"], LOCAL["local_key"])
        else:
            assert (
                api.poll_status(
                    LOCAL["device_id"], LOCAL["host"], LOCAL["local_key"]
                ).visits_today
                == 2
            )
    assert [call[0] for call in device.method_calls] == ["status", "close"]
    assert factory.call_args.kwargs == {
        "address": LOCAL["host"],
        "local_key": LOCAL["local_key"],
        "version": 3.5,
        "connection_timeout": 5,
        "connection_retry_limit": 0,
        "persist": False,
    }


@pytest.mark.parametrize("failure", [False, True])
def test_adapter_initial_socket_only(failure):
    device = api.StatusDevice(
        LOCAL["device_id"],
        address=LOCAL["host"],
        local_key=LOCAL["local_key"],
        version=3.5,
        connection_retry_limit=0,
    )
    seen = []

    def socket_attempt(renew):
        seen.append(device.socketRetryLimit)
        if failure:
            raise OSError("synthetic")
        return True

    with patch.object(api.tinytuya.Device, "_get_socket", side_effect=socket_attempt):
        if failure:
            with pytest.raises(OSError):
                device._get_socket(False)
        else:
            assert device._get_socket(False)
    assert seen == [1]
    assert device.socketRetryLimit == 0
    device.close()


def test_sdk_logging_scoped_privacy(caplog):
    logger = logging.getLogger("tinytuya.core.Xenon")
    device = Mock()

    def status():
        logger.warning("SYNTHETIC_SECRET")
        return RESPONSE

    device.status.side_effect = status
    with patch.object(api, "StatusDevice", return_value=device):
        api.poll_status(LOCAL["device_id"], LOCAL["host"], LOCAL["local_key"])
    assert "SYNTHETIC_SECRET" not in caplog.text
    logger.warning("unrelated user still visible")
    assert "unrelated user still visible" in caplog.text
    assert not logger.disabled


@pytest.mark.asyncio
async def test_real_sensor_platform_lifecycle(core_hass):
    """Exercise real entity/device registries, forward setup, and platform unload."""
    entry = make_entry(state=ConfigEntryState.SETUP_IN_PROGRESS)
    core_hass.config_entries._entries[entry.entry_id] = entry
    with patch(
        f"{PREFIX}.coordinator.poll_status", return_value=api.parse_status(RESPONSE)
    ):
        async with entry.setup_lock:
            assert await async_setup_entry(core_hass, entry)
        await core_hass.async_block_till_done()
    states = core_hass.states.async_all("sensor")
    assert len(states) == 6
    assert all(state.state != "unavailable" for state in states)
    assert len(entry.runtime_data._listeners) == 6
    assert await async_unload_entry(core_hass, entry)
    await core_hass.async_block_till_done()
    assert len(entry.runtime_data._listeners) == 0
    assert entry.runtime_data._unsub_refresh is None


@pytest.mark.asyncio
async def test_options_listener_reloads(core_hass):
    entry = make_entry()
    core_hass.config_entries._entries[entry.entry_id] = entry
    entry.add_update_listener(async_reload_entry)
    result = await core_hass.config_entries.options.async_init(entry.entry_id)
    with patch.object(core_hass.config_entries, "async_reload", new=AsyncMock()) as reload:
        await core_hass.config_entries.options.async_configure(result["flow_id"], {"poll_interval": 15})
        await core_hass.async_block_till_done()
    reload.assert_awaited_once_with(entry.entry_id)
    assert entry.options == {"poll_interval": 15}


@pytest.mark.asyncio
async def test_reconfigure_failure_preserves_connection(core_hass):
    entry = make_entry()
    core_hass.config_entries._entries[entry.entry_id] = entry
    result = await core_hass.config_entries.flow.async_init(DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id})
    with patch(f"{PREFIX}.config_flow.poll_status", side_effect=api.StatusReadError("SECRET")):
        result = await core_hass.config_entries.flow.async_configure(result["flow_id"], {"host": "192.0.2.41", "local_key": "fedcba9876543210"})
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data == LOCAL


@pytest.mark.asyncio
async def test_setup_read_failure_defers_entry(core_hass):
    from homeassistant.exceptions import ConfigEntryNotReady
    entry = make_entry(state=ConfigEntryState.SETUP_IN_PROGRESS)
    with patch(f"{PREFIX}.coordinator.poll_status", side_effect=api.StatusReadError("SECRET")):
        with pytest.raises(ConfigEntryNotReady, match="SmartSpin local status read failed"):
            await async_setup_entry(core_hass, entry)


def test_adapter_real_socket_initial_attempt_only():
    device = api.StatusDevice(LOCAL["device_id"], address=LOCAL["host"], local_key=LOCAL["local_key"], version=3.5, connection_retry_limit=0)
    socket = Mock()
    with patch("tinytuya.core.XenonDevice.socket.socket", return_value=socket), patch.object(device, "_negotiate_session_key", return_value=True):
        assert device._get_socket(False)
    socket.connect.assert_called_once_with((LOCAL["host"], 6668))
    assert device.socketRetryLimit == 0
    device.close()
