"""Config flow for WattBox integration."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries, exceptions
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.importlib import async_import_module
from pywattbox.base import BaseWattBox

from .const import (
    CONF_CONNECTION_TYPE,
    CONF_NAME_REGEXP,
    CONF_OUTLET_METERING,
    CONF_SKIP_REGEXP,
    CONNECTION_TYPES,
    DEFAULT_CONNECTION_TYPE,
    DEFAULT_NAME,
    DEFAULT_OUTLET_METERING,
    DEFAULT_PASSWORD,
    DEFAULT_SCAN_INTERVAL,
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

    wattbox: BaseWattBox | None = None
    try:
        if port in (22, 23):
            from pywattbox.ip_wattbox import async_create_ip_wattbox

            # scrapli imports its transport plugin lazily inside the driver
            # constructor, which blocks the event loop. Pre-import it here, as
            # `async_setup_entry` already does for the same reason.
            transport = "asyncssh" if port == 22 else "asynctelnet"
            await async_import_module(
                hass, f"scrapli.transport.plugins.{transport}.transport"
            )

            wattbox = await async_create_ip_wattbox(
                host=host, user=username, password=password, port=port
            )
        else:
            from pywattbox.http_wattbox import async_create_http_wattbox

            await async_import_module(hass, "encodings.ascii")

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
    finally:
        # Probing opens a session on a device that caps concurrent
        # connections. Release it whether or not validation succeeded,
        # otherwise a few failed attempts lock the user out.
        if wattbox is not None and hasattr(wattbox, "async_close"):
            try:
                await wattbox.async_close()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Error closing probe connection", exc_info=True)


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
            # The connection type picks the port, so the driver is chosen
            # explicitly rather than guessed. Leaving it implicit is what sends
            # 800-series users to the HTTP driver and an opaque 401.
            user_input = dict(user_input)
            connection_type = user_input.pop(
                CONF_CONNECTION_TYPE, DEFAULT_CONNECTION_TYPE
            )
            user_input[CONF_PORT] = CONNECTION_TYPES[connection_type]

            # Captured here, not only in the options flow, so an outlet feeding
            # the site's own network equipment never gets a switch entity --
            # not even for the moment between adding the entry and opening
            # options for the first time.
            options: dict[str, Any] = {}
            if skip_regexp := (user_input.pop(CONF_SKIP_REGEXP, "") or "").strip():
                try:
                    re.compile(skip_regexp)
                except re.error:
                    errors[CONF_SKIP_REGEXP] = "invalid_regex"
                else:
                    options[CONF_SKIP_REGEXP] = skip_regexp

            if not errors:
                try:
                    info = await validate_input(self.hass, user_input)

                    unique_id = (
                        info.get("serial_number") or f"{info['host']}_{info['port']}"
                    )
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=info["title"], data=user_input, options=options
                    )
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
                vol.Required(
                    CONF_CONNECTION_TYPE, default=DEFAULT_CONNECTION_TYPE
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(CONNECTION_TYPES),
                        translation_key=CONF_CONNECTION_TYPE,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_USERNAME, default=DEFAULT_USER): str,
                vol.Optional(CONF_PASSWORD, default=DEFAULT_PASSWORD): str,
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Optional(CONF_SKIP_REGEXP, default=""): str,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> WattBoxOptionsFlow:
        """Return the options flow handler."""
        return WattBoxOptionsFlow()

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


class WattBoxOptionsFlow(OptionsFlow):
    """Retune a configured WattBox without re-adding it.

    ``skip_regexp`` is the important one and the reason this flow exists: the
    config entry path previously created a switch for every outlet with no way
    to exclude any. On a WattBox that powers its own network equipment, that
    puts a one-click way to cut your own remote access on the dashboard.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            for key in (CONF_SKIP_REGEXP, CONF_NAME_REGEXP):
                if pattern := user_input.get(key):
                    try:
                        re.compile(pattern)
                    except re.error:
                        errors[key] = "invalid_regex"
            if not errors:
                return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SKIP_REGEXP,
                    description={"suggested_value": options.get(CONF_SKIP_REGEXP, "")},
                ): str,
                vol.Optional(
                    CONF_NAME_REGEXP,
                    description={"suggested_value": options.get(CONF_NAME_REGEXP, "")},
                ): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=options.get(
                        CONF_SCAN_INTERVAL,
                        int(DEFAULT_SCAN_INTERVAL.total_seconds()),
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5, max=3600, step=1, unit_of_measurement="s"
                    )
                ),
                vol.Optional(
                    CONF_OUTLET_METERING,
                    default=options.get(CONF_OUTLET_METERING, DEFAULT_OUTLET_METERING),
                ): bool,
            }
        )

        return self.async_show_form(
            step_id="init", data_schema=data_schema, errors=errors
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""
