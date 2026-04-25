"""Data update coordinator for Bitaxe/NerdAxe integration."""

import asyncio
import logging
from datetime import timedelta
from typing import Any, Dict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_client import BitaxeAPIClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class BitaxeDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator to manage data updates from Bitaxe/NerdAxe API."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        api_client: BitaxeAPIClient,
        host: str,
        miner_type: str,
        update_interval: int = 30,
    ):
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance
            logger: Logger instance
            api_client: BitaxeAPIClient instance
            host: Miner host/IP
            miner_type: Type of miner (bitaxe or nerdaxe)
            update_interval: Update interval in seconds
        """
        super().__init__(
            hass,
            logger,
            name=f"Bitaxe {host}",
            update_interval=timedelta(seconds=update_interval),
        )
        self.api_client = api_client
        self.host = host
        self.miner_type = miner_type

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from Bitaxe API.

        Returns:
            Dictionary with 'info' and 'asic' keys containing API responses.
            Returns empty dict on transient errors (timeout/connection) to avoid
            error logging during expected reboots.

        Raises:
            UpdateFailed: Only for non-transient failures
        """
        info_task = asyncio.create_task(self.api_client.get_system_info())
        asic_task = asyncio.create_task(self.api_client.get_asic_info())

        results = await asyncio.gather(info_task, asic_task, return_exceptions=True)

        info_result, asic_result = results

        # Surface the first exception (both are checked so neither task is orphaned)
        for result in results:
            if isinstance(result, (TimeoutError, ConnectionError)):
                _LOGGER.debug(
                    "Transient error from %s: %s (miner may be rebooting)",
                    self.host,
                    result,
                )
                return {}
            if isinstance(result, ValueError):
                raise UpdateFailed(f"Invalid response from {self.host}: {result}") from result
            if isinstance(result, Exception):
                raise UpdateFailed(f"Error fetching data from {self.host}: {result}") from result

        return {
            "info": info_result,
            "asic": asic_result,
        }
