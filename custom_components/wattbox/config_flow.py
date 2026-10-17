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

from .api import BaseWattBox, WattBoxAuthError, WattBoxError, WattBoxLoggedOut
from .connection import async_connect
from .const import (
    CONF_CONNECTION_TYPE,
    CONF_NAME_REGEXP,
    CONF_OUTLET_METERING,
    CONF_OUTLET_METERING_SUPPORTED,
    CONF_SKIP_REGEXP,
    CONNECTION_TYPES,
    DEFAULT_CONNECTION_TYPE,
    DEFAULT_NAME,
    DEFAULT_OUTLET_METERING,
    DEFAULT_PASSWORD,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USER,
    DOMAIN,
    DOMAIN_DATA,
)

_LOGGER = logging.getLogger(__name__)


async def validate_input(hass: HomeAssistant, data: dict) -> dict:
    """Validate the user input allows us to connect."""
    host = data[CONF_HOST]
    port = data[CONF_PORT]
    username = data[CONF_USERNAME]
    password = data[CONF_PASSWORD]
    name = data[CONF_NAME]

    wattbox: BaseWattBox | None = None
    try:
        wattbox = await async_connect(
            hass,
            host,
            port,
            username,
            password,
            transport=data.get(CONF_CONNECTION_TYPE),
        )

        return {
            "title": name,
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "name": name,
            "serial_number": wattbox.serial_number,
            # Whether this device reports power per outlet, known only now that
            # it has answered.
            "outlet_metering_supported": wattbox.supports_outlet_metering,
        }
    except (WattBoxAuthError, WattBoxLoggedOut) as exc:
        # A probe starts from a session of its own, so a device that answers it
        # with the login page -- or with any page that is not its data -- is
        # rejecting these credentials, not replaying a stale login the way a
        # long-running entry can (#67).
        _LOGGER.error("WattBox %s rejected the login: %s", host, exc)
        raise InvalidAuth from exc
    except WattBoxError as exc:
        _LOGGER.error("Error connecting to WattBox %s: %s", host, exc)
        raise CannotConnect from exc
    finally:
        # Probing opens a session on a device that caps concurrent
        # connections. Release it whether or not validation succeeded,
        # otherwise a few failed attempts lock the user out.
        if wattbox is not None:
            await wattbox.async_close()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for WattBox."""

    VERSION = 1

    _reauth_entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            # The connection type picks the port, so the driver is chosen
            # explicitly rather than guessed. Leaving it implicit is what sends
            # 800-series users to the HTTP driver and an opaque 401.
            # Stored as well as the port, so the transport never has to be
            # guessed back from a port number later on.
            user_input = dict(user_input)
            connection_type = user_input.setdefault(
                CONF_CONNECTION_TYPE, DEFAULT_CONNECTION_TYPE
            )
            user_input[CONF_PORT] = CONNECTION_TYPES[connection_type]

            # Captured here, not only in the options flow, so an outlet feeding
            # the site's own network equipment never gets a switch entity --
            # not even for the moment between adding the entry and opening
            # options for the first time.
            options: dict[str, Any] = {
                CONF_OUTLET_METERING: user_input.pop(
                    CONF_OUTLET_METERING, DEFAULT_OUTLET_METERING
                )
            }
            if skip_regexp := (user_input.pop(CONF_SKIP_REGEXP, "") or "").strip():
                try:
                    re.compile(skip_regexp)
                except re.error:
                    errors[CONF_SKIP_REGEXP] = "invalid_regex"
                else:
                    options[CONF_SKIP_REGEXP] = skip_regexp

            info = (
                None
                if errors
                else await _async_try_validate(
                    self.hass, user_input, errors, placeholders
                )
            )
            if info is not None:
                # Outside the `try` above: the abort is raised as an exception,
                # and the catch-all there used to turn "already configured"
                # into "unexpected error".
                unique_id = (
                    info.get("serial_number") or f"{info['host']}_{info['port']}"
                )
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                # The form has to offer metering before the model is known,
                # so reconcile it against what the device actually reports.
                # Storing a preference the hardware cannot honour leaves a
                # ticked box that does nothing.
                if not info["outlet_metering_supported"]:
                    options[CONF_OUTLET_METERING] = False

                return self.async_create_entry(
                    title=info["title"],
                    data={
                        **user_input,
                        CONF_OUTLET_METERING_SUPPORTED: info[
                            "outlet_metering_supported"
                        ],
                    },
                    options=options,
                )

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
                vol.Optional(
                    CONF_OUTLET_METERING, default=DEFAULT_OUTLET_METERING
                ): bool,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders=placeholders,
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
        placeholders: dict[str, str] = {}

        if user_input is not None:
            new_data = {**self._reauth_entry.data, **user_input}
            if (
                await _async_try_validate(self.hass, new_data, errors, placeholders)
                is not None
            ):
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
            description_placeholders=placeholders,
        )


class WattBoxOptionsFlow(OptionsFlow):
    """Retune a configured WattBox without re-adding it.

    ``skip_regexp`` is the important one and the reason this flow exists: the
    config entry path previously created a switch for every outlet with no way
    to exclude any. On a WattBox that powers its own network equipment, that
    puts a one-click way to cut your own remote access on the dashboard.
    """

    def _supports_outlet_metering(self) -> bool:
        """Whether the connected device reports power per outlet.

        Recorded on the entry when it was created. Entries older than that
        fall back to asking the live client.

        Defaults to True when the entry is not loaded — a device that cannot
        be reached should not have the option silently dropped from the form,
        which would discard the stored value on save.
        """
        supported = self.config_entry.data.get(CONF_OUTLET_METERING_SUPPORTED)
        if isinstance(supported, bool):
            return supported

        name = self.config_entry.data.get(CONF_NAME)
        wattbox: BaseWattBox | None = self.hass.data.get(DOMAIN_DATA, {}).get(name)
        if wattbox is None:
            return True
        return wattbox.supports_outlet_metering

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
                # Merged, not replaced: the metering field is absent from the
                # form on devices that do not support it, and a bare
                # `data=user_input` would drop every option not on screen.
                return self.async_create_entry(
                    data={**self.config_entry.options, **user_input}
                )

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
            }
        )

        # Offered only where it can do something. On an HTTP device the XML API
        # reports power for the unit as a whole and never per outlet, so the
        # checkbox would be a control with no effect.
        if self._supports_outlet_metering():
            data_schema = data_schema.extend(
                {
                    vol.Optional(
                        CONF_OUTLET_METERING,
                        default=options.get(
                            CONF_OUTLET_METERING, DEFAULT_OUTLET_METERING
                        ),
                    ): bool,
                }
            )

        return self.async_show_form(
            step_id="init", data_schema=data_schema, errors=errors
        )


async def _async_try_validate(
    hass: HomeAssistant,
    data: dict[str, Any],
    errors: dict[str, str],
    placeholders: dict[str, str],
) -> dict[str, Any] | None:
    """Validate *data*, filling in the form errors if it does not work.

    The client's own explanation goes under the form as well, since "failed
    to connect" on its own is what left people reading logs to find out why.
    """
    try:
        return await validate_input(hass, data)
    except CannotConnect as err:
        errors["base"] = "cannot_connect"
        placeholders["error_detail"] = str(err.__cause__ or err)
    except InvalidAuth as err:
        errors["base"] = "invalid_auth"
        placeholders["error_detail"] = str(err.__cause__ or err)
    except Exception:  # pylint: disable=broad-except
        _LOGGER.exception("Unexpected exception")
        errors["base"] = "unknown"
    return None


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""
