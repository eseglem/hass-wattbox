"""Config flow for WattBox integration."""

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries, exceptions
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from pywattbox.base import BaseWattBox

from .const import (
    DEFAULT_NAME,
    DEFAULT_PASSWORD,
    DEFAULT_PORT,
    DEFAULT_USER,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def validate_input(hass: HomeAssistant, data: dict) -> dict:
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    host = data[CONF_HOST]
    port = data[CONF_PORT]
    username = data[CONF_USERNAME]
    password = data[CONF_PASSWORD]
    name = data[CONF_NAME]

    # Try to create a connection to validate the input
    try:
        if port in (22, 23):
            from pywattbox.ip_wattbox import async_create_ip_wattbox

            wattbox: BaseWattBox = await async_create_ip_wattbox(
                host=host, user=username, password=password, port=port
            )
        else:
            from pywattbox.http_wattbox import async_create_http_wattbox

            wattbox = await async_create_http_wattbox(
                host=host, user=username, password=password, port=port
            )

        # Try to get basic info to validate connection
        await wattbox.async_update()

        config = {
            "title": name,
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "name": name,
            "serial_number": wattbox.serial_number,
        }
        _LOGGER.debug("generated config data: %s", config)
        return config
    except Exception as exc:
        _LOGGER.error("Error connecting to WattBox %s: %s", host, exc)
        raise CannotConnect from exc


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for WattBox."""

    VERSION = 1

    async def async_step_user(self, user_input: Any | None = None) -> Any:
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)

                # Use serial number as unique_id if available
                unique_id = (
                    info.get("serial_number") or f"{info['host']}_{info['port']}"
                )
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(title=info["title"], data=user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Optional(CONF_USERNAME, default=DEFAULT_USER): str,
                vol.Optional(CONF_PASSWORD, default=DEFAULT_PASSWORD): str,
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""
