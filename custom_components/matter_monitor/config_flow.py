"""Config flow for Matter Monitor."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_MATTER_URL, DEFAULT_MATTER_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class MatterMonitorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Matter Monitor."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_MATTER_URL]

            # Test connection
            if await self._test_connection(url):
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Matter Monitor",
                    data=user_input,
                )
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MATTER_URL, default=DEFAULT_MATTER_URL
                    ): str,
                }
            ),
            errors=errors,
        )

    async def _test_connection(self, url: str) -> bool:
        """Test if we can connect to the Matter Server."""
        session = aiohttp.ClientSession()
        try:
            async with session.ws_connect(url, timeout=5) as ws:
                await ws.close()
            return True
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            _LOGGER.warning("Could not connect to Matter Server at %s", url)
            return False
        finally:
            await session.close()
