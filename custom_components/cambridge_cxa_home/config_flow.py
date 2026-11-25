"""Config flow: add or reconfigure an amplifier from the UI.

Validation only reads (power query plus versions). It never powers the
amplifier on, unmutes it or changes its source.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .client import (
    CXAConnectError,
    CXARejectedError,
    CXATimeoutError,
    DeviceInfo,
    fetch_device_info,
)
from .const import CONF_MODEL, DOMAIN, MANUFACTURER
from .protocol import Model

_LOGGER = logging.getLogger(__name__)

_PORT_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
)
_MODEL_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        # Translation keys must be lowercase; the stored value stays e.g. "CXA81".
        options=[m.value.lower() for m in Model],
        mode=SelectSelectorMode.DROPDOWN,
        translation_key="model",
    )
)


def _connection_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, vol.UNDEFINED)): TextSelector(),
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, vol.UNDEFINED)): _PORT_SELECTOR,
        }
    )


async def _validate(host: str, port: int) -> tuple[DeviceInfo | None, dict[str, str]]:
    """Run the read-only connection test; map failures to form errors."""
    try:
        return await fetch_device_info(host, port), {}
    except CXAConnectError:
        return None, {"base": "cannot_connect"}
    except CXATimeoutError:
        return None, {"base": "no_response"}
    except CXARejectedError:
        return None, {"base": "rejected"}
    except Exception:
        _LOGGER.exception("Unexpected error while testing %s:%s", host, port)
        return None, {"base": "unknown"}


class CXAConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for model, bridge host and port, then test read-only."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            self._async_abort_entries_match({CONF_HOST: host, CONF_PORT: port})
            _, errors = await _validate(host, port)
            if not errors:
                # The protocol exposes no serial number, and IP or firmware are
                # not identities, so the device gets a generated stable ID.
                await self.async_set_unique_id(uuid.uuid4().hex)
                model = Model(user_input[CONF_MODEL].upper()).value
                return self.async_create_entry(
                    title=f"{MANUFACTURER} {model}",
                    data={CONF_HOST: host, CONF_PORT: port, CONF_MODEL: model},
                )
        schema = vol.Schema(
            {vol.Required(CONF_MODEL, default=Model.CXA81.value.lower()): _MODEL_SELECTOR}
        ).extend(_connection_schema(user_input or {}).schema)
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change host/port (e.g. new bridge IP), keeping the same device identity."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            self._async_abort_entries_match({CONF_HOST: host, CONF_PORT: port})
            _, errors = await _validate(host, port)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_HOST: host, CONF_PORT: port}
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(user_input or dict(entry.data)),
            errors=errors,
        )
