"""UI configuration; cloud credentials exist only during bootstrap submission."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import poll_status
from .const import (
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MIN_POLL_INTERVAL,
    REGIONS,
)


def _identifier(value: str) -> str:
    value = vol.All(str, vol.Length(min=1, max=128))(value)
    if value != value.strip() or any(c.isspace() for c in value):
        raise vol.Invalid("Invalid identifier")
    return value


def _host(value: str) -> str:
    value = _identifier(value)
    if value.lower() in ("auto", "0.0.0.0", "::") or "/" in value or "://" in value:
        raise vol.Invalid("Use a specific device address")
    return value


def _local_key(value: str) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) != 16:
        raise vol.Invalid("Expected a 16-byte key")
    return value


def _secret_selector() -> TextSelector:
    return TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _local_schema(*, reconfigure: bool = False) -> vol.Schema:
    fields = {vol.Required(CONF_HOST): _host}
    if not reconfigure:
        fields[vol.Required(CONF_DEVICE_ID)] = _identifier
    # Validate secrets after the selector; never populate defaults from an entry.
    fields[vol.Required(CONF_LOCAL_KEY)] = _secret_selector()
    return vol.Schema(fields)


class SmartSpinConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a local read-only device, optionally retrieving its key once."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SmartSpinOptionsFlow()

    async def async_step_user(self, user_input=None):
        return self.async_show_menu(step_id="user", menu_options=["local", "companion"])

    async def _verify_local(self, data: dict) -> None:
        _host(data[CONF_HOST])
        _identifier(data[CONF_DEVICE_ID])
        _local_key(data[CONF_LOCAL_KEY])
        await self.hass.async_add_executor_job(
            poll_status,
            data[CONF_DEVICE_ID],
            data[CONF_HOST],
            data[CONF_LOCAL_KEY],
        )

    async def async_step_local(self, user_input=None):
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
            self._abort_if_unique_id_configured()
            data = {
                k: user_input[k] for k in (CONF_HOST, CONF_DEVICE_ID, CONF_LOCAL_KEY)
            }
            try:
                await self._verify_local(data)
            except vol.Invalid:
                errors["base"] = "invalid_input"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="ScoopFree SmartSpin", data=data)
        return self.async_show_form(
            step_id="local", data_schema=_local_schema(), errors=errors
        )

    async def async_step_companion(self, user_input=None):
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
            self._abort_if_unique_id_configured()
            # Import lazily: local-only setup never needs the cloud implementation.
            from .cloud_bootstrap import (
                BootstrapError,
                CannotConnect,
                InteractionRequired,
                InvalidAuth,
                InvalidProfile,
                async_get_local_key,
            )

            try:
                _host(user_input[CONF_HOST])
                _identifier(user_input[CONF_DEVICE_ID])
                local_key = await async_get_local_key(
                    async_get_clientsession(self.hass),
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                    country_code=user_input["country_code"],
                    region=user_input["region"],
                    device_id=user_input[CONF_DEVICE_ID],
                    profile_json=user_input["app_profile"],
                )
                data = {
                    CONF_HOST: user_input[CONF_HOST],
                    CONF_DEVICE_ID: user_input[CONF_DEVICE_ID],
                    CONF_LOCAL_KEY: local_key,
                }
                await self._verify_local(data)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except InteractionRequired:
                errors["base"] = "interaction_required"
            except InvalidProfile:
                errors["base"] = "invalid_profile"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except BootstrapError:
                errors["base"] = "bootstrap_failed"
            except vol.Invalid:
                errors["base"] = "invalid_input"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="ScoopFree SmartSpin", data=data)
        return self.async_show_form(
            step_id="companion",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): _secret_selector(),
                    vol.Required("country_code", default="1"): vol.All(
                        str, vol.Match(r"^[0-9]{1,4}$")
                    ),
                    vol.Required("region", default="us"): vol.In(REGIONS),
                    vol.Required(CONF_HOST): _host,
                    vol.Required(CONF_DEVICE_ID): _identifier,
                    vol.Required("app_profile"): _secret_selector(),
                }
            ),
        )

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            data = {
                CONF_HOST: user_input[CONF_HOST],
                CONF_DEVICE_ID: entry.data[CONF_DEVICE_ID],
                CONF_LOCAL_KEY: user_input[CONF_LOCAL_KEY],
            }
            try:
                await self._verify_local(data)
            except vol.Invalid:
                errors["base"] = "invalid_input"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_local_schema(reconfigure=True),
            errors=errors,
        )


class SmartSpinOptionsFlow(config_entries.OptionsFlow):
    """Poll no faster than once every five seconds."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=MIN_POLL_INTERVAL)),
                }
            ),
        )
