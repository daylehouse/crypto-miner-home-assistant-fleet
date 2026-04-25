"""API client for Bitaxe/NerdAxe/Avalon miners."""

import asyncio
import logging
import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import aiohttp

from .const import (
    API_SYSTEM,
    API_SYSTEM_ASIC,
    API_SYSTEM_INFO,
    API_SYSTEM_RESTART,
    DEFAULT_TIMEOUT,
    MINER_TYPE_AVALON,
    MINER_TYPE_BITAXE,
    MINER_TYPE_NERDAXE,
)

_LOGGER = logging.getLogger(__name__)


class BitaxeAPIClient:
    """API client for Bitaxe/NerdAxe (HTTP) and Avalon (CGMiner socket)."""

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession,
        miner_type: str = MINER_TYPE_BITAXE,
        avalon_port: int = 4028,
        avalon_web_user: str = "admin",
        avalon_web_password: str = "admin",
    ):
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
        self.miner_type = miner_type
        self.base_url = f"http://{self.host}"
        self._avalon_port = avalon_port
        self._avalon_web_user = avalon_web_user
        self._avalon_web_password = avalon_web_password

    async def get_system_info(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Fetch system information from /api/system/info.

        Returns:
            Dictionary with system info (hashrate, power, temp, pool settings, etc.)

        Raises:
            TimeoutError: If request times out
            ConnectionError: If connection fails
            ValueError: If response is invalid JSON
        """
        if self.miner_type in (MINER_TYPE_BITAXE, MINER_TYPE_NERDAXE):
            return await self._async_request(
                "GET", API_SYSTEM_INFO, timeout=timeout or DEFAULT_TIMEOUT
            )

        if self.miner_type == MINER_TYPE_AVALON:
            return await self._avalon_system_info(timeout=timeout or DEFAULT_TIMEOUT)

        raise ValueError(f"Unsupported miner type: {self.miner_type}")

    async def get_asic_info(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Fetch ASIC information from /api/system/asic.

        Returns:
            Dictionary with ASIC model, frequencies, voltages, etc.

        Raises:
            TimeoutError: If request times out
            ConnectionError: If connection fails
            ValueError: If response is invalid JSON
        """
        if self.miner_type in (MINER_TYPE_BITAXE, MINER_TYPE_NERDAXE):
            return await self._async_request(
                "GET", API_SYSTEM_ASIC, timeout=timeout or DEFAULT_TIMEOUT
            )

        if self.miner_type == MINER_TYPE_AVALON:
            return await self._avalon_asic_info(timeout=timeout or DEFAULT_TIMEOUT)

        raise ValueError(f"Unsupported miner type: {self.miner_type}")

    async def restart_system(self, timeout: Optional[float] = None) -> bool:
        """Trigger system restart via POST /api/system/restart.

        Returns:
            True if restart was initiated successfully

        Raises:
            TimeoutError: If request times out
            ConnectionError: If connection fails
        """
        try:
            if self.miner_type in (MINER_TYPE_BITAXE, MINER_TYPE_NERDAXE):
                await self._async_request(
                    "POST", API_SYSTEM_RESTART, timeout=timeout or DEFAULT_TIMEOUT
                )
                return True

            if self.miner_type == MINER_TYPE_AVALON:
                result = await self._avalon_command("ascset", "0,reboot,0", timeout=timeout)
                return bool(result.get("success"))

            raise ValueError(f"Unsupported miner type: {self.miner_type}")
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
        if self.miner_type in (MINER_TYPE_BITAXE, MINER_TYPE_NERDAXE):
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

        if self.miner_type == MINER_TYPE_AVALON:
            url_with_port = str(stratum_url).strip()
            if ":" not in url_with_port.rsplit("/", 1)[-1]:
                url_with_port = f"{url_with_port}:{int(stratum_port)}"

            raw_param = (
                f"{self._avalon_web_user},{self._avalon_web_password},0,"
                f"{url_with_port},{stratum_user},{stratum_password}"
            )
            result = await self._avalon_command("setpool", raw_param, timeout=timeout)
            if not result.get("success"):
                raise ConnectionError(result.get("message", "Avalon setpool failed"))
            return {
                "success": True,
                "message": result.get("message", "OK"),
            }

        raise ValueError(f"Unsupported miner type: {self.miner_type}")

    async def _avalon_system_info(self, timeout: float) -> Dict[str, Any]:
        """Fetch and normalize Avalon runtime data to axeos info schema."""
        summary_task = asyncio.create_task(self._avalon_command("summary", timeout=timeout))
        pools_task = asyncio.create_task(self._avalon_command("pools", timeout=timeout))
        estats_task = asyncio.create_task(self._avalon_command("estats", timeout=timeout))
        version_task = asyncio.create_task(self._avalon_command("version", timeout=timeout))

        results = await asyncio.gather(
            summary_task,
            pools_task,
            estats_task,
            version_task,
            return_exceptions=True,
        )

        summary_result, pools_result, estats_result, version_result = results
        for result in results:
            if isinstance(result, Exception):
                raise result

        summary = summary_result.get("sections", {}).get("SUMMARY", [{}])[0]
        pools = pools_result.get("sections", {}).get("POOL", [])
        estats = estats_result.get("estats", {})
        version = version_result.get("sections", {}).get("VERSION", [{}])[0]

        if not isinstance(summary, dict):
            summary = {}
        if not isinstance(pools, list):
            pools = []
        if not isinstance(estats, dict):
            estats = {}
        if not isinstance(version, dict):
            version = {}

        active_pool: dict[str, Any] | None = None
        for pool in pools:
            if not isinstance(pool, dict):
                continue
            active = pool.get("Stratum Active")
            if str(active).lower() in ("y", "yes", "1", "true"):
                active_pool = pool
                break
        if active_pool is None:
            for pool in pools:
                if isinstance(pool, dict):
                    active_pool = pool
                    break

        pool_url = ""
        pool_port = 3333
        pool_user = ""
        pool_diff = None
        if isinstance(active_pool, dict):
            raw_url = str(active_pool.get("URL") or active_pool.get("Stratum URL") or "").strip()
            pool_user = str(active_pool.get("User") or "").strip()
            pool_diff = active_pool.get("Stratum Difficulty") or active_pool.get("Difficulty Accepted")
            if raw_url:
                parsed = urlparse(raw_url if "://" in raw_url else f"stratum+tcp://{raw_url}")
                if parsed.hostname:
                    pool_url = parsed.hostname
                else:
                    pool_url = raw_url
                if parsed.port:
                    pool_port = parsed.port
                else:
                    tail = raw_url.rsplit(":", 1)
                    if len(tail) == 2 and tail[1].isdigit():
                        pool_port = int(tail[1])

        ps = estats.get("PS") if isinstance(estats.get("PS"), dict) else {}
        temps = estats.get("temperatures") if isinstance(estats.get("temperatures"), dict) else {}
        fans = estats.get("fans") if isinstance(estats.get("fans"), dict) else {}

        hashrate_gh = 0.0
        try:
            hashrate_gh = float(summary.get("MHS av") or summary.get("MHS 5s") or 0) / 1000.0
        except (TypeError, ValueError):
            hashrate_gh = 0.0

        info: Dict[str, Any] = {
            "hashRate": round(hashrate_gh, 3),
            "hashRate_1m": round(hashrate_gh, 3),
            "hashRate_10m": round(hashrate_gh, 3),
            "hashRate_1h": round(hashrate_gh, 3),
            "power": ps.get("PS_Power") or 0,
            "temp": temps.get("TMax") or temps.get("MTmax") or temps.get("OTemp") or 0,
            "vrTemp": temps.get("TAvg") or temps.get("MTavg"),
            "fanspeed": fans.get("FanR") or 0,
            "fanrpm": fans.get("Fan1"),
            "sharesAccepted": summary.get("Accepted") or 0,
            "sharesRejected": summary.get("Rejected") or 0,
            "errorPercentage": summary.get("Device Rejected%") or 0,
            "bestDiff": summary.get("Best Share"),
            "bestSessionDiff": summary.get("Best Share"),
            "poolDifficulty": pool_diff,
            "stratumURL": pool_url,
            "stratumPort": pool_port,
            "stratumUser": pool_user,
            "hostname": self.host,
            "version": version.get("CGMiner") or version.get("LVERSION") or "Avalon",
            "ASICModel": version.get("MODEL") or "Avalon",
            "uptimeSeconds": summary.get("Elapsed") or 0,
            "stratum": {"pools": pools},
        }
        return info

    async def _avalon_asic_info(self, timeout: float) -> Dict[str, Any]:
        """Fetch and normalize Avalon static/device details."""
        version_result = await self._avalon_command("version", timeout=timeout)
        version = version_result.get("sections", {}).get("VERSION", [{}])[0]
        if not isinstance(version, dict):
            version = {}
        return {
            "deviceModel": version.get("MODEL") or "Avalon Nano",
            "firmware": version.get("LVERSION") or version.get("CGMiner") or "",
        }

    async def _avalon_send_raw(self, message: str, timeout: float) -> str:
        """Send raw CGMiner socket command to Avalon miner."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self._avalon_port),
                timeout=timeout,
            )
        except asyncio.TimeoutError as e:
            raise TimeoutError(f"Request timeout to {self.host}") from e
        except OSError as e:
            raise ConnectionError(f"Cannot connect to {self.host}") from e

        try:
            writer.write(message.encode("utf-8"))
            await writer.drain()
            raw = b""
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=timeout)
                if not chunk:
                    break
                raw += chunk
            return raw.decode("utf-8", errors="ignore").strip()
        finally:
            writer.close()
            await writer.wait_closed()

    def _avalon_parse_generic(self, data: str) -> Dict[str, Any]:
        """Parse standard CGMiner pipe/comma formatted responses."""
        sections: Dict[str, list[Dict[str, Any]]] = {}
        if not data:
            return sections

        for part in data.split("|"):
            part = part.strip()
            if not part:
                continue
            tokens = [tok.strip() for tok in part.split(",") if tok.strip()]
            if not tokens:
                continue

            section_name = tokens[0]
            values: Dict[str, Any] = {}

            first = tokens[0]
            if "=" in first:
                first_k, first_v = first.split("=", 1)
                if first_k == "POOL":
                    section_name = "POOL"
                    values["POOL"] = self._avalon_convert_value(first_v)
                    tokens = tokens[1:]
                else:
                    section_name = first_k
                    values[first_k] = self._avalon_convert_value(first_v)
                    tokens = tokens[1:]
            else:
                tokens = tokens[1:]

            for token in tokens:
                if "=" not in token:
                    continue
                k, v = token.split("=", 1)
                values[k.strip()] = self._avalon_convert_value(v.strip())

            sections.setdefault(section_name, []).append(values)

        return sections

    def _avalon_convert_value(self, value: str) -> Any:
        """Convert CGMiner string values to int/float where possible."""
        text = str(value).strip()
        if text == "":
            return text
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            return int(text)
        try:
            return float(text)
        except ValueError:
            return text

    def _avalon_parse_estats(self, raw: str) -> Dict[str, Any]:
        """Parse Avalon-specific estats bracket response format."""
        if not raw or "|" not in raw:
            return {}

        payload = raw.split("|", 1)[1].strip()
        out: Dict[str, Any] = {
            "temperatures": {},
            "fans": {},
            "PS": {},
            "misc": {},
        }
        pattern = re.compile(r"(\w+)\[([^\]]*)\]")
        for match in pattern.finditer(payload):
            key, val = match.group(1), match.group(2).strip()
            if key in {"ITemp", "OTemp", "TMax", "TAvg", "TarT", "MTmax", "MTavg"}:
                out["temperatures"][key] = self._avalon_convert_value(val)
            elif key.startswith("Fan"):
                out["fans"][key] = self._avalon_convert_value(val.replace("%", ""))
            elif key == "PS":
                parts = [p.strip() for p in val.split() if p.strip()]
                if len(parts) >= 7:
                    out["PS"] = {
                        "PS_Status": self._avalon_convert_value(parts[0]),
                        "PS_ControlVoltage": self._avalon_convert_value(parts[1]),
                        "PS_HashboardVoltage": self._avalon_convert_value(parts[2]),
                        "PS_Ping": self._avalon_convert_value(parts[3]),
                        "PS_Reserved": self._avalon_convert_value(parts[4]),
                        "PS_CurrentOutput": self._avalon_convert_value(parts[5]),
                        "PS_Power": self._avalon_convert_value(parts[6]),
                    }
            else:
                out["misc"][key] = val
        return out

    async def _avalon_command(
        self,
        cmd: str,
        param: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Execute an Avalon CGMiner command and return parsed response."""
        effective_timeout = timeout or DEFAULT_TIMEOUT
        message = cmd if param is None else f"{cmd}|{param}"
        raw = await self._avalon_send_raw(message, timeout=effective_timeout)
        if not raw:
            raise ConnectionError(f"Empty response from {self.host}")

        if cmd == "estats":
            return {
                "success": True,
                "raw": raw,
                "estats": self._avalon_parse_estats(raw),
            }

        sections = self._avalon_parse_generic(raw)
        status_items = sections.get("STATUS", [{}])
        status = status_items[0] if status_items else {}
        status_code = str(status.get("STATUS", "")).upper()
        success = status_code in ("S", "I")
        message_text = str(status.get("Msg", "OK"))

        return {
            "success": success,
            "message": message_text,
            "raw": raw,
            "sections": sections,
        }

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
