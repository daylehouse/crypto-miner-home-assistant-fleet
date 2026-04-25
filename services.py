"""Services for Bitaxe/NerdAxe integration."""

import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv

from .const import CONF_HOST, DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_POOL = "set_pool"

SET_POOL_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("stratum_url"): cv.string,
        vol.Required("stratum_port"): cv.port,
        vol.Required("stratum_user"): cv.string,
        vol.Required("stratum_password"): cv.string,
    }
)


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register services for the integration."""

    async def async_set_pool_service(call: ServiceCall) -> None:
        """Handle set_pool service call."""
        device_id = call.data.get("device_id")
        stratum_url = call.data.get("stratum_url")
        stratum_port = call.data.get("stratum_port")
        stratum_user = call.data.get("stratum_user")
        stratum_password = call.data.get("stratum_password")

        # Find the config entry and API client for this device
        api_client = None
        for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
            if entry_data.get("host") == device_id or device_id in str(entry_id):
                api_client = entry_data.get("api_client")
                break

        if not api_client:
            _LOGGER.error(f"Could not find miner with device_id: {device_id}")
            raise ValueError(f"Unknown device: {device_id}")

        try:
            result = await api_client.set_pool_settings(
                stratum_url=stratum_url,
                stratum_port=stratum_port,
                stratum_user=stratum_user,
                stratum_password=stratum_password,
            )
            _LOGGER.info(
                f"Pool settings updated for {device_id}: "
                f"{stratum_url}:{stratum_port} (user: {stratum_user})"
            )
        except Exception as e:
            _LOGGER.error(f"Failed to set pool for {device_id}: {e}")
            raise

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_POOL,
        async_set_pool_service,
        schema=SET_POOL_SCHEMA,
    )


@callback
def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister services."""
    hass.services.async_remove(DOMAIN, SERVICE_SET_POOL)
