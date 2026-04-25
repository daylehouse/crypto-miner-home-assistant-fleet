"""API client for Bitaxe/NerdAxe miners."""

import asyncio
import logging
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import aiohttp

from .const import (
    API_SYSTEM,
    API_SYSTEM_ASIC,
    API_SYSTEM_INFO,
    API_SYSTEM_RESTART,
    DEFAULT_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class BitaxeAPIClient:
    """HTTP client for Bitaxe/NerdAxe API."""

    def __init__(self, host: str, session: aiohttp.ClientSession):
        """Initialize the API client.

        Args:
            host: Host IP or hostname (e.g., "192.168.3.199" or "bitaxe.local")
            session: aiohttp ClientSession for HTTP requests
        """
        normalized_host = host.strip()
        if "://" in normalized_host:
            parsed = urlparse(normalized_host)
            normalized_host = (parsed.hostname or "").strip()
        normalized_host = normalized_host.split("/", 1)[0].strip()

        self.host = normalized_host
        self.session = session
        self.base_url = f"http://{self.host}"

    async def get_system_info(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Fetch system information from /api/system/info.

        Returns:
            Dictionary with system info (hashrate, power, temp, pool settings, etc.)

        Raises:
            TimeoutError: If request times out
            ConnectionError: If connection fails
            ValueError: If response is invalid JSON
        """
        return await self._async_request(
            "GET", API_SYSTEM_INFO, timeout=timeout or DEFAULT_TIMEOUT
        )

    async def get_asic_info(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Fetch ASIC information from /api/system/asic.

        Returns:
            Dictionary with ASIC model, frequencies, voltages, etc.

        Raises:
            TimeoutError: If request times out
            ConnectionError: If connection fails
            ValueError: If response is invalid JSON
        """
        return await self._async_request(
            "GET", API_SYSTEM_ASIC, timeout=timeout or DEFAULT_TIMEOUT
        )

    async def restart_system(self, timeout: Optional[float] = None) -> bool:
        """Trigger system restart via POST /api/system/restart.

        Returns:
            True if restart was initiated successfully

        Raises:
            TimeoutError: If request times out
            ConnectionError: If connection fails
        """
        try:
            await self._async_request(
                "POST", API_SYSTEM_RESTART, timeout=timeout or DEFAULT_TIMEOUT
            )
            return True
        except Exception as e:
            _LOGGER.error(f"Failed to restart system: {e}")
            raise

    async def set_pool_settings(
        self,
        stratum_url: str,
        stratum_port: int,
        stratum_user: str,
        stratum_password: str,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Update pool settings via PATCH /api/system.

        Args:
            stratum_url: Stratum server URL
            stratum_port: Stratum server port
            stratum_user: Stratum username (usually wallet address)
            stratum_password: Stratum password (usually 'x')
            timeout: Request timeout in seconds

        Returns:
            Updated system info from response

        Raises:
            TimeoutError: If request times out
            ConnectionError: If connection fails
            ValueError: If response is invalid
        """
        payload = {
            "stratumURL": stratum_url,
            "stratumPort": stratum_port,
            "stratumUser": stratum_user,
            "stratumPassword": stratum_password,
        }

        return await self._async_request(
            "PATCH",
            API_SYSTEM,
            json_payload=payload,
            timeout=timeout or DEFAULT_TIMEOUT,
        )

    async def _async_request(
        self,
        method: str,
        endpoint: str,
        json_payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Make an async HTTP request to the API.

        Args:
            method: HTTP method (GET, POST, PATCH, etc.)
            endpoint: API endpoint (e.g., "/api/system/info")
            json_payload: JSON payload for POST/PATCH requests
            timeout: Request timeout in seconds

        Returns:
            Parsed JSON response

        Raises:
            TimeoutError: If request times out
            ConnectionError: If connection fails
            ValueError: If response is not valid JSON
        """
        url = f"{self.base_url}{endpoint}"
        headers = {"Content-Type": "application/json"}

        try:
            async with self.session.request(
                method,
                url,
                json=json_payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout or DEFAULT_TIMEOUT),
            ) as response:
                if response.status == 200:
                    try:
                        data = await response.json(content_type=None)
                    except (aiohttp.ContentTypeError, ValueError):
                        data = {}
                    return data
                elif response.status == 400:
                    raise ValueError(f"Bad request: {response.reason}")
                elif response.status == 401:
                    raise ConnectionError(f"Unauthorized: {response.reason}")
                elif response.status == 500:
                    raise ConnectionError(f"Server error: {response.reason}")
                else:
                    raise ConnectionError(
                        f"Unexpected status {response.status}: {response.reason}"
                    )

        except asyncio.TimeoutError as e:
            _LOGGER.debug(f"Timeout on {method} {url}: {e} (miner may be rebooting)")
            raise TimeoutError(f"Request timeout to {self.host}") from e
        except aiohttp.ClientConnectorError as e:
            _LOGGER.debug(f"Connection error to {self.host}: {e} (miner may be rebooting)")
            raise ConnectionError(f"Cannot connect to {self.host}") from e
        except aiohttp.ClientError as e:
            _LOGGER.debug(f"HTTP error on {method} {url}: {e}")
            raise ConnectionError(f"HTTP error: {e}") from e
