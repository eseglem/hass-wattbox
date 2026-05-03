"""Config flow for WattBox integration."""

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries, exceptions
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
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


def _is_auth_error(err: BaseException) -> bool:
    """Best-effort detection of auth failures across pywattbox transports."""
    try:
        from httpx import HTTPStatusError

        if isinstance(err, HTTPStatusError):
            status = getattr(err.response, "status_code", None)
            if status in (401, 403):
                return True
    except ImportError:  # pragma: no cover
        pass
    return "auth" in type(err).__name__.lower()


async def validate_input(hass: HomeAssistant, data: dict) -> dict:
    """Validate the user input allows us to connect."""
    host = data[CONF_HOST]
    port = data[CONF_PORT]
    username = data[CONF_USERNAME]
    password = data[CONF_PASSWORD]
    name = data[CONF_NAME]

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

        await wattbox.async_update()

        return {
            "title": name,
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "name": name,
            "serial_number": wattbox.serial_number,
        }
    except Exception as exc:
        _LOGGER.error("Error connecting to WattBox %s: %s", host, exc)
        if _is_auth_error(exc):
            raise InvalidAuth from exc
        raise CannotConnect from exc


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for WattBox."""

    VERSION = 1

    _reauth_entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)

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

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauthentication after credentials become invalid."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Prompt the user for new credentials."""
        assert self._reauth_entry is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            new_data = {**self._reauth_entry.data, **user_input}
            try:
                await validate_input(self.hass, new_data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during reauth")
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry, data=new_data
                )
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=self._reauth_entry.data.get(
                            CONF_USERNAME, DEFAULT_USER
                        ),
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""
