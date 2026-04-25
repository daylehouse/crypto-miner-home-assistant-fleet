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

    async def set_workmode(
        self,
        level: int,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Set Avalon work mode using the CGMiner ascset command."""
        if self.miner_type != MINER_TYPE_AVALON:
            raise ValueError(f"Unsupported miner type for work mode: {self.miner_type}")

        result = await self._avalon_command(
            "ascset",
            f"0,workmode,set,{int(level)}",
            timeout=timeout,
        )
        if not result.get("success"):
            raise ConnectionError(result.get("message", "Avalon workmode update failed"))
        return result

    async def set_pool_settings(
        self,
        stratum_url: str,
        stratum_port: int,
        stratum_user: str,
        stratum_password: str,
        timeout: Optional[float] = None,
        avalon_username: Optional[str] = None,
        avalon_password: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update pool settings via PATCH /api/system.

        Args:
            stratum_url: Stratum server URL
            stratum_port: Stratum server port
            stratum_user: Stratum username (usually wallet address)
            stratum_password: Stratum password (usually 'x')
            timeout: Request timeout in seconds
            avalon_username: Avalon miner admin username (overrides stored credentials)
            avalon_password: Avalon miner admin password (overrides stored credentials)

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
            # Use provided credentials if available, otherwise fall back to stored ones
            web_user = avalon_username or self._avalon_web_user
            web_password = avalon_password or self._avalon_web_password

            url_with_port = str(stratum_url).strip()
            if ":" not in url_with_port.rsplit("/", 1)[-1]:
                url_with_port = f"{url_with_port}:{int(stratum_port)}"

            raw_param = (
                f"{web_user},{web_password},0,"
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
        stats_task = asyncio.create_task(self._avalon_command("stats", timeout=timeout))
        devs_task = asyncio.create_task(self._avalon_command("devs", timeout=timeout))
        pools_task = asyncio.create_task(self._avalon_command("pools", timeout=timeout))
        estats_task = asyncio.create_task(self._avalon_command("estats", timeout=timeout))
        version_task = asyncio.create_task(self._avalon_command("version", timeout=timeout))

        results = await asyncio.gather(
            summary_task,
            stats_task,
            devs_task,
            pools_task,
            estats_task,
            version_task,
            return_exceptions=True,
        )

        (
            summary_result,
            stats_result,
            devs_result,
            pools_result,
            estats_result,
            version_result,
        ) = results
        for result in results:
            if isinstance(result, Exception):
                raise result

        summary = summary_result.get("sections", {}).get("SUMMARY", [{}])[0]
        stats_sections = stats_result.get("sections", {})
        devs_sections = devs_result.get("sections", {})
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

        if not isinstance(stats_sections, dict):
            stats_sections = {}
        if not isinstance(devs_sections, dict):
            devs_sections = {}

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
        misc = estats.get("misc") if isinstance(estats.get("misc"), dict) else {}
        workmode = estats.get("WORKMODE")

        hashboard_voltage = (
            ps.get("PS_HashboardVoltage")
            or misc.get("hashboard_voltage")
            or misc.get("HashboardVoltage")
        )
        block_height = (
            active_pool.get("Current Block Height") if isinstance(active_pool, dict) else None
        ) or misc.get("P1 Block Height") or misc.get("Block Height")
        frequency_mhz = self._avalon_find_numeric_value(
            ("freq", "frequency", "frequencymhz", "clock", "asicfreq"),
            misc,
            temps,
            version,
            stats_sections,
            devs_sections,
            summary,
        )
        mac_address = self._avalon_find_mac_address(
            misc,
            version,
            stats_sections,
            devs_sections,
            summary,
            active_pool or {},
        )
        chip_type = self._avalon_find_chip_type(
            version,
            devs_sections,
            stats_sections,
            misc,
            summary,
        )
        hostname = self._avalon_find_hostname(misc, version, stats_sections, devs_sections) or self.host

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
            "coreVoltageActual": hashboard_voltage,
            "frequency": frequency_mhz,
            "temp": temps.get("TMax") or temps.get("MTmax") or temps.get("OTemp") or 0,
            "exhaustTemp": temps.get("OTemp"),
            "vrTemp": temps.get("TAvg") or temps.get("MTavg"),
            "fanspeed": fans.get("FanR") or 0,
            "fanrpm": fans.get("Fan1"),
            "sharesAccepted": summary.get("Accepted") or 0,
            "sharesRejected": summary.get("Rejected") or 0,
            "errorPercentage": summary.get("Device Rejected%") or 0,
            "bestDiff": summary.get("Best Share"),
            "bestSessionDiff": summary.get("Best Share"),
            "blockHeight": block_height,
            "currentBlockHeight": block_height,
            "poolDifficulty": pool_diff,
            "stratumURL": pool_url,
            "stratumPort": pool_port,
            "stratumUser": pool_user,
            "hostname": hostname,
            "macAddr": mac_address,
            "version": version.get("CGMiner") or version.get("LVERSION") or "Avalon",
            "ASICModel": chip_type,
            "workModeLevel": workmode,
            "uptimeSeconds": summary.get("Elapsed") or 0,
            "stratum": {"pools": pools},
        }
        return info

    def _avalon_find_chip_type(self, *payloads: Any) -> str:
        """Return the best available Avalon chip type for ASIC model reporting."""
        preferred_keys = {
            "chip",
            "chiptype",
            "chipmodel",
            "asictype",
            "asics",
            "asicchip",
            "asicmodel",
        }
        fallback_keys = {
            "model",
            "devicename",
            "devmodel",
            "machinetype",
        }

        def normalize_key(value: Any) -> str:
            return re.sub(r"[^a-z0-9]", "", str(value).lower())

        def map_known_chip_type(text: str) -> str:
            normalized = normalize_key(text)
            known_mappings = {
                "avalonnano3s": "A3197S",
                "nano3s": "A3197S",
                "avalonnano": "A3197S",
            }
            return known_mappings.get(normalized, text)

        def normalize_value(value: Any) -> str | None:
            text = str(value).strip()
            if not text:
                return None
            if len(text) > 120:
                return None
            return map_known_chip_type(text)

        def visit(node: Any, candidate_keys: set[str]) -> str | None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if normalize_key(key) in candidate_keys:
                        normalized = normalize_value(value)
                        if normalized:
                            return normalized
                for value in node.values():
                    normalized = visit(value, candidate_keys)
                    if normalized:
                        return normalized
                return None

            if isinstance(node, list):
                for item in node:
                    normalized = visit(item, candidate_keys)
                    if normalized:
                        return normalized
                return None

            return None

        for payload in payloads:
            chip_type = visit(payload, preferred_keys)
            if chip_type:
                return chip_type

        for payload in payloads:
            chip_type = visit(payload, fallback_keys)
            if chip_type:
                return chip_type

        return "Avalon"

    def _avalon_find_mac_address(self, *payloads: Any) -> str | None:
        """Return first MAC-like value found anywhere in Avalon payloads."""
        preferred_keys = {
            "mac",
            "macaddress",
            "mac_address",
            "macaddr",
            "ethaddr",
            "ethernetmac",
            "ethernet_mac",
            "lanmac",
            "lan_mac",
            "wifi_mac",
            "wifimac",
        }

        def normalize_key(value: Any) -> str:
            return re.sub(r"[^a-z0-9]", "", str(value).lower())

        def normalize_mac(value: Any) -> str | None:
            text = str(value).strip()
            if not text:
                return None
            hex_only = re.sub(r"[^0-9A-Fa-f]", "", text)
            if len(hex_only) == 12:
                return ":".join(hex_only[i : i + 2] for i in range(0, 12, 2)).lower()
            match = re.search(r"([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}", text)
            if match:
                return match.group(0).replace("-", ":").lower()
            return None

        def visit(node: Any) -> str | None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if normalize_key(key) in preferred_keys:
                        normalized = normalize_mac(value)
                        if normalized:
                            return normalized
                for value in node.values():
                    normalized = visit(value)
                    if normalized:
                        return normalized
                return None

            if isinstance(node, list):
                for item in node:
                    normalized = visit(item)
                    if normalized:
                        return normalized
                return None

            return normalize_mac(node)

        for payload in payloads:
            normalized = visit(payload)
            if normalized:
                return normalized
        return None

    def _avalon_find_hostname(self, *payloads: Any) -> str | None:
        """Return first hostname-like value found in Avalon payloads."""
        preferred_keys = {
            "hostname",
            "host",
            "devicename",
            "device_name",
            "devname",
            "name",
            "device_id",
            "deviceid",
            "boardid",
            "board_id",
        }

        def normalize_key(value: Any) -> str:
            return re.sub(r"[^a-z0-9]", "", str(value).lower())

        def is_hostname_like(value: Any) -> bool:
            text = str(value).strip()
            if not text or len(text) > 255:
                return False
            return bool(re.match(r"^[a-zA-Z0-9._-]+$", text))

        def visit(node: Any) -> str | None:
            if isinstance(node, dict):
                # Check preferred keys first
                for key, value in node.items():
                    if normalize_key(key) in preferred_keys and is_hostname_like(value):
                        return str(value).strip()
                # Fallback to any string-like value
                for value in node.values():
                    result = visit(value)
                    if result:
                        return result
                return None

            if isinstance(node, list):
                for item in node:
                    result = visit(item)
                    if result:
                        return result
                return None

            return None

        for payload in payloads:
            result = visit(payload)
            if result:
                return result
        return None

    def _avalon_find_numeric_value(
        self, preferred_keys: tuple[str, ...], *payloads: Any
    ) -> int | float | None:
        """Return first numeric-like value found for the given normalized keys."""

        normalized_keys = {re.sub(r"[^a-z0-9]", "", key.lower()) for key in preferred_keys}

        def convert_numeric(value: Any) -> int | float | None:
            if isinstance(value, bool):
                return None
            if isinstance(value, (int, float)):
                return value

            text = str(value).strip()
            if not text:
                return None

            match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
            if not match:
                return None

            number_text = match.group(0)
            try:
                return int(number_text)
            except ValueError:
                try:
                    return float(number_text)
                except ValueError:
                    return None

        def visit(node: Any) -> int | float | None:
            if isinstance(node, dict):
                for key, value in node.items():
                    normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
                    if normalized_key in normalized_keys:
                        numeric = convert_numeric(value)
                        if numeric is not None:
                            return numeric
                for value in node.values():
                    numeric = visit(value)
                    if numeric is not None:
                        return numeric
                return None

            if isinstance(node, list):
                for item in node:
                    numeric = visit(item)
                    if numeric is not None:
                        return numeric
                return None

            return None

        for payload in payloads:
            numeric = visit(payload)
            if numeric is not None:
                return numeric
        return None

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
            elif key == "WORKMODE":
                out["WORKMODE"] = self._avalon_convert_value(val)
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
