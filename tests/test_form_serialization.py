"""Exercise the serializer used by HA's real HTTP configuration-flow views."""

import json
from types import MappingProxyType

import pytest
import voluptuous_serialize
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_validation as cv

from custom_components.petsafe_smartspin.config_flow import SmartSpinConfigFlow, _local_schema
from custom_components.petsafe_smartspin.const import DOMAIN


def serialize(schema):
    return json.dumps(voluptuous_serialize.convert(schema, custom_serializer=cv.custom_serializer))


@pytest.mark.parametrize("reconfigure", [False, True])
def test_local_form_http_serializable(reconfigure):
    assert serialize(_local_schema(reconfigure=reconfigure))


@pytest.mark.asyncio
async def test_companion_form_http_serializable(hass, enable_custom_integrations):
    flow = SmartSpinConfigFlow()
    flow.hass = hass
    form = await flow.async_step_companion()
    assert serialize(form["data_schema"])


@pytest.mark.asyncio
async def test_options_and_cloud_form_http_serializable(hass, enable_custom_integrations):
    e = ConfigEntry(
        domain=DOMAIN,
        version=1,
        minor_version=1,
        data={"host": "192.0.2.40", "device_id": "synthetic", "local_key": "0123456789abcdef"},
        options={},
        unique_id="synthetic",
        title="Synthetic",
        source="user",
        discovery_keys=MappingProxyType({}),
        subentries_data=[],
    )
    hass.config_entries._entries[e.entry_id] = e
    form = await hass.config_entries.options.async_init(e.entry_id)
    assert serialize(form["data_schema"])
    form = await hass.config_entries.options.async_configure(
        form["flow_id"], {"poll_interval": 10, "cloud_history": True}
    )
    assert serialize(form["data_schema"])
