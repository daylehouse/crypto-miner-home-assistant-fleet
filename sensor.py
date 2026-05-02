"""Sensor entities for Bitaxe/NerdAxe integration."""

import logging
import ipaddress
from dataclasses import dataclass
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ASIC_OVERHEAT_THRESHOLD_C,
    CONF_DEVICE_NAME,
    CONF_DEVICE_SLUG,
    CONF_ENTRY_TYPE,
    CONF_GOLDSHELL_ALEO_OVERHEAT_THRESHOLD_C,
    CONF_GOLDSHELL_LTC_OVERHEAT_THRESHOLD_C,
    CONF_GOLDSHELL_TEMP1_OVERHEAT_THRESHOLD_C,
    CONF_GOLDSHELL_TEMP2_OVERHEAT_THRESHOLD_C,
    CONF_HOST,
    CONF_MINER_TYPE,
    CONF_OVERHEAT_THRESHOLD_C,
    CONF_POOLS,
    CONF_VR_OVERHEAT_THRESHOLD_C,
    DOMAIN,
    ENTRY_TYPE_FLEET,
    ENTRY_TYPE_MINER,
    MINER_TYPE_AVALON,
    MINER_TYPE_GOLDSHELL,
    overheat_threshold_profile,
)
from .coordinator import BitaxeDataUpdateCoordinator
from .utils import normalize_identifier

_LOGGER = logging.getLogger(__name__)


def _normalize_pool_url(value: Any) -> str | None:
    """Normalize pool URL to hostname for reliable comparison."""
    if value is None:
        return None

    raw_url = str(value).strip().lower()
    if not raw_url:
        return None

    parsed = urlparse(raw_url if "://" in raw_url else f"stratum+tcp://{raw_url}")
    if parsed.hostname:
        return parsed.hostname.lower()

    normalized = raw_url
    for prefix in ("stratum+tcp://", "stratum+ssl://", "stratum://"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break

    return normalized.split("/", 1)[0].split(":", 1)[0].rstrip("/") or None


def _normalize_pool_user(value: Any) -> str | None:
    """Normalize pool username."""
    if value is None:
        return None
    user = str(value).strip()
    return user or None


def _normalize_pool_port(value: Any) -> int | None:
    """Normalize pool port from int/string input."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _active_pool_tuple(info: dict[str, Any]) -> tuple[str | None, int | None, str | None]:
    """Return active pool tuple (url, port, user) from miner info."""
    stratum_obj = info.get("stratum") if isinstance(info.get("stratum"), dict) else {}
    using_fallback = bool(
        info.get("isUsingFallbackStratum")
        or info.get("usingFallback")
        or stratum_obj.get("usingFallback")
        or stratum_obj.get("activePoolMode") == 1
    )

    if using_fallback:
        return (
            _normalize_pool_url(
                info.get("fallbackStratumURL")
                or info.get("fallbackStratumUrl")
                or info.get("fallbackPoolURL")
            ),
            _normalize_pool_port(
                info.get("fallbackStratumPort")
                or info.get("fallbackStratum_port")
                or info.get("fallbackPoolPort")
            ),
            _normalize_pool_user(
                info.get("fallbackStratumUser")
                or info.get("fallbackStratum_user")
                or info.get("fallbackPoolUser")
            ),
        )

    return (
        _normalize_pool_url(
            info.get("stratumURL") or info.get("stratumUrl") or info.get("poolURL")
        ),
        _normalize_pool_port(
            info.get("stratumPort") or info.get("stratum_port") or info.get("poolPort")
        ),
        _normalize_pool_user(
            info.get("stratumUser") or info.get("stratum_user") or info.get("poolUser")
        ),
    )


def _configured_pool_tuple(pool: dict[str, Any]) -> tuple[str | None, int | None, str | None]:
    """Return configured pool tuple (url, port, user)."""
    return (
        _normalize_pool_url(pool.get("stratum_url")),
        _normalize_pool_port(pool.get("stratum_port")),
        _normalize_pool_user(pool.get("stratum_user")),
    )


def _matches_pool(
    current: tuple[str | None, int | None, str | None],
    configured: tuple[str | None, int | None, str | None],
) -> bool:
    """Return True when current pool matches configured pool."""
    current_url, current_port, current_user = current
    pool_url, pool_port, pool_user = configured

    if pool_url is None or current_url is None or pool_url != current_url:
        return False
    if pool_user is not None and current_user is not None and pool_user != current_user:
        return False
    if pool_port is not None and current_port is not None and pool_port != current_port:
        return False
    return True


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    """Return the first non-empty value found for the given keys."""
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return None


def _numeric_first_present(mapping: dict[str, Any], *keys: str) -> Any:
    """Return the first present numeric-like value for the given keys."""
    value = _first_present(mapping, *keys)
    if isinstance(value, str):
        stripped = value.replace(",", "").strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            try:
                return float(stripped)
            except ValueError:
                return None
    return value


def _recursive_first_present(payload: Any, *keys: str) -> Any:
    """Return the first matching value found anywhere in a nested payload."""
    if isinstance(payload, dict):
        normalized_keys = {normalize_identifier(key) for key in keys}

        for key, value in payload.items():
            if normalize_identifier(str(key)) in normalized_keys:
                if value is not None and value != "":
                    return value

        for value in payload.values():
            found = _recursive_first_present(value, *keys)
            if found is not None and found != "":
                return found

    elif isinstance(payload, list):
        for item in payload:
            found = _recursive_first_present(item, *keys)
            if found is not None and found != "":
                return found

    return None


def _numeric_recursive_first_present(payload: Any, *keys: str) -> Any:
    """Return the first numeric-like matching value found in a nested payload."""
    value = _recursive_first_present(payload, *keys)
    if isinstance(value, str):
        stripped = value.replace(",", "").strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            try:
                return float(stripped)
            except ValueError:
                return None
    return value


def _host_ipv4_or_none(host: str) -> str | None:
    """Return host if it is a literal IPv4 address."""
    try:
        return str(ipaddress.ip_address(host)) if ipaddress.ip_address(host).version == 4 else None
    except ValueError:
        return None


def _first_pool_numeric(info: dict[str, Any], *keys: str) -> Any:
    """Return first numeric-like value from stratum.pools[0] for given keys."""
    stratum = info.get("stratum")
    if not isinstance(stratum, dict):
        return None

    pools = stratum.get("pools")
    if not isinstance(pools, list) or not pools:
        return None

    first_pool = pools[0]
    if not isinstance(first_pool, dict):
        return None

    return _numeric_recursive_first_present(first_pool, *keys)


def _asic_temp_c(info: dict[str, Any]) -> float | None:
    """Return ASIC temperature in Celsius when available."""
    try:
        raw = info.get("temp")
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _vr_temp_c(info: dict[str, Any]) -> float | None:
    """Return VR temperature in Celsius when available."""
    try:
        raw = info.get("vrTemp")
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _default_overheat_threshold_c(miner_type: str) -> float:
    """Return default overheat threshold for miner type."""
    _, _, threshold_default = overheat_threshold_profile(miner_type)
    return float(threshold_default)


def _cleanup_fleet_entities_for_entry(hass: HomeAssistant, entry_id: str) -> None:
    """Remove stale fleet sensor entities bound to a specific config entry."""
    entity_registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(entity_registry, entry_id):
        if registry_entry.domain != "sensor":
            continue
        unique_id = registry_entry.unique_id or ""
        if unique_id.startswith(f"{DOMAIN}_fleet_"):
            entity_registry.async_remove(registry_entry.entity_id)


def _cleanup_avalon_unsupported_entities_for_entry(
    hass: HomeAssistant,
    entry_id: str,
) -> None:
    """Remove stale Avalon-only unsupported entities for a config entry."""
    entity_registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(entity_registry, entry_id):
        if registry_entry.domain != "sensor":
            continue
        unique_id = registry_entry.unique_id or ""
        if unique_id.endswith("_core_voltage_set"):
            entity_registry.async_remove(registry_entry.entity_id)


def _cleanup_legacy_goldshell_overheat_entities_for_entry(
    hass: HomeAssistant,
    entry_id: str,
) -> None:
    """Remove stale Goldshell overheat sensor entities with legacy Temp1/Temp2 keys."""
    entity_registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(entity_registry, entry_id):
        if registry_entry.domain != "sensor":
            continue
        unique_id = registry_entry.unique_id or ""
        if unique_id.endswith("_goldshell_temp_1_overheated") or unique_id.endswith(
            "_goldshell_temp_2_overheated"
        ):
            entity_registry.async_remove(registry_entry.entity_id)


SENSOR_ICONS: dict[str, str] = {
    "mining_active": "mdi:pickaxe",
    "overheated": "mdi:chip",
    "vr_overheated": "mdi:thermometer-lines",
    "aleo_overheated": "mdi:thermometer-alert",
    "ltc_overheated": "mdi:thermometer-alert",
    "aleo_hashrate": "mdi:speedometer",
    "ltc_hashrate": "mdi:speedometer",
    "aleo_power": "mdi:flash",
    "ltc_power": "mdi:flash",
    "aleo_temp_1": "mdi:thermometer",
    "aleo_temp_2": "mdi:thermometer",
    "ltc_temp_1": "mdi:thermometer",
    "ltc_temp_2": "mdi:thermometer",
    "aleo_fan_rpm": "mdi:fan-speed-3",
    "ltc_fan_rpm": "mdi:fan-speed-3",
    "aleo_shares_accepted": "mdi:check-circle-outline",
    "ltc_shares_accepted": "mdi:check-circle-outline",
    "aleo_shares_rejected": "mdi:close-circle-outline",
    "ltc_shares_rejected": "mdi:close-circle-outline",
    "aleo_reject_rate": "mdi:percent-outline",
    "ltc_reject_rate": "mdi:percent-outline",
    "aleo_hw_error_rate": "mdi:alert-circle-outline",
    "ltc_hw_error_rate": "mdi:alert-circle-outline",
    "aleo_uptime": "mdi:timer-outline",
    "ltc_uptime": "mdi:timer-outline",
    "aleo_pool_url": "mdi:server-network",
    "aleo_pool_port": "mdi:lan-connect",
    "aleo_pool_user": "mdi:account-outline",
    "aleo_pool_active": "mdi:check-circle-outline",
    "ltc_pool_url": "mdi:server-network",
    "ltc_pool_port": "mdi:lan-connect",
    "ltc_pool_user": "mdi:account-outline",
    "ltc_pool_active": "mdi:check-circle-outline",
    "hashrate": "mdi:speedometer",
    "hashrate_1m": "mdi:speedometer-medium",
    "hashrate_10m": "mdi:speedometer-slow",
    "hashrate_1h": "mdi:speedometer",
    "power": "mdi:flash",
    "voltage": "mdi:sine-wave",
    "current": "mdi:current-ac",
    "temp_asic": "mdi:thermometer",
    "temp_exhaust": "mdi:thermometer-chevron-down",
    "temp_vr": "mdi:thermometer-lines",
    "core_voltage_set": "mdi:tune-vertical",
    "core_voltage_actual": "mdi:lightning-bolt",
    "frequency": "mdi:pulse",
    "uptime": "mdi:timer-outline",
    "fan_speed": "mdi:fan",
    "fan_rpm": "mdi:fan-speed-3",
    "shares_accepted": "mdi:check-circle-outline",
    "shares_rejected": "mdi:close-circle-outline",
    "error_percentage": "mdi:alert-circle-outline",
    "best_diff": "mdi:trophy-outline",
    "best_session_diff": "mdi:medal-outline",
    "pool_url": "mdi:server-network",
    "pool_port": "mdi:lan-connect",
    "pool_user": "mdi:account-outline",
    "pool_difficulty": "mdi:stairs",
    "asic_model": "mdi:chip",
    "device_model": "mdi:memory",
    "hostname": "mdi:badge-account-horizontal-outline",
    "mac_address": "mdi:card-account-details-outline",
    "ipv4_address": "mdi:ip-network-outline",
    "firmware_version": "mdi:application-cog-outline",
    "axeos_version": "mdi:tag-outline",
    "block_height": "mdi:cube-outline",
    "network_difficulty": "mdi:chart-bell-curve",
    "free_heap": "mdi:database-outline",
}


@dataclass
class BitaxeSensorEntityDescription(SensorEntityDescription):
    """Bitaxe sensor entity description."""

    value_fn: Callable[[dict], Optional[Any]] = None


BITAXE_SENSORS: list[BitaxeSensorEntityDescription] = [
    # Main mining metrics
    BitaxeSensorEntityDescription(
        key="mining_active",
        name="Mining Active",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: 1 if data.get("info", {}).get("hashRate", 0) > 0 else 0,
    ),
    BitaxeSensorEntityDescription(
        key="hashrate",
        name="Hashrate",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="GH/s",
        value_fn=lambda data: round(data.get("info", {}).get("hashRate", 0), 2),
    ),
    BitaxeSensorEntityDescription(
        key="hashrate_1m",
        name="Hashrate 1m",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="GH/s",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: round(data.get("info", {}).get("hashRate_1m", 0), 2),
    ),
    BitaxeSensorEntityDescription(
        key="hashrate_10m",
        name="Hashrate 10m",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="GH/s",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: round(data.get("info", {}).get("hashRate_10m", 0), 2),
    ),
    BitaxeSensorEntityDescription(
        key="hashrate_1h",
        name="Hashrate 1h",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="GH/s",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: round(data.get("info", {}).get("hashRate_1h", 0), 2),
    ),
    # Power metrics
    BitaxeSensorEntityDescription(
        key="power",
        name="Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda data: round(data.get("info", {}).get("power", 0), 2),
    ),
    BitaxeSensorEntityDescription(
        key="voltage",
        name="Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: round(data.get("info", {}).get("voltage", 0), 2),
    ),
    BitaxeSensorEntityDescription(
        key="current",
        name="Current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="mA",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: round(data.get("info", {}).get("current", 0), 2),
    ),
    # Temperature metrics
    BitaxeSensorEntityDescription(
        key="temp_asic",
        name="ASIC Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda data: round(data.get("info", {}).get("temp", 0), 2),
    ),
    BitaxeSensorEntityDescription(
        key="temp_exhaust",
        name="Exhaust Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("exhaustTemp"),
    ),
    BitaxeSensorEntityDescription(
        key="overheated",
        name="ASIC Overheated",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BitaxeSensorEntityDescription(
        key="temp_vr",
        name="VR Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("vrTemp"),
    ),
    BitaxeSensorEntityDescription(
        key="vr_overheated",
        name="VR Overheated",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # Chip voltage
    BitaxeSensorEntityDescription(
        key="core_voltage_set",
        name="Core Voltage (Set)",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("coreVoltage"),
    ),
    BitaxeSensorEntityDescription(
        key="core_voltage_actual",
        name="Core Voltage (Actual)",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("coreVoltageActual"),
    ),
    # Frequency
    BitaxeSensorEntityDescription(
        key="frequency",
        name="Frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("frequency"),
    ),
    # Uptime
    BitaxeSensorEntityDescription(
        key="uptime",
        name="Uptime",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("uptimeSeconds"),
    ),
    # Fan metrics
    BitaxeSensorEntityDescription(
        key="fan_speed",
        name="Fan Speed",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: round(data.get("info", {}).get("fanspeed", 0), 2),
    ),
    BitaxeSensorEntityDescription(
        key="fan_rpm",
        name="Fan RPM",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="rpm",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("fanrpm"),
    ),
    # Mining stats
    BitaxeSensorEntityDescription(
        key="shares_accepted",
        name="Shares Accepted",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("sharesAccepted"),
    ),
    BitaxeSensorEntityDescription(
        key="shares_rejected",
        name="Shares Rejected",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("sharesRejected"),
    ),
    BitaxeSensorEntityDescription(
        key="error_percentage",
        name="Error Percentage",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: round(data.get("info", {}).get("errorPercentage", 0), 2),
    ),
    # Best difficulty
    BitaxeSensorEntityDescription(
        key="best_diff",
        name="Best Difficulty",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("bestDiff"),
    ),
    BitaxeSensorEntityDescription(
        key="best_session_diff",
        name="Best Session Difficulty",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("bestSessionDiff"),
    ),
    # Pool info (read-only)
    BitaxeSensorEntityDescription(
        key="pool_url",
        name="Pool URL",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("stratumURL"),
    ),
    BitaxeSensorEntityDescription(
        key="pool_port",
        name="Pool Port",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: str(v) if (v := data.get("info", {}).get("stratumPort")) is not None else None,
    ),
    BitaxeSensorEntityDescription(
        key="pool_user",
        name="Pool User",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("stratumUser"),
    ),
    BitaxeSensorEntityDescription(
        key="pool_difficulty",
        name="Pool Difficulty",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("poolDifficulty"),
    ),
    # Device info
    BitaxeSensorEntityDescription(
        key="asic_model",
        name="ASIC Model",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("ASICModel"),
    ),
    BitaxeSensorEntityDescription(
        key="device_model",
        name="Device Model",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("asic", {}).get("deviceModel"),
    ),
    BitaxeSensorEntityDescription(
        key="hostname",
        name="Hostname",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("hostname"),
    ),
    BitaxeSensorEntityDescription(
        key="mac_address",
        name="MAC Address",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("macAddr"),
    ),
    BitaxeSensorEntityDescription(
        key="ipv4_address",
        name="IPv4 Address",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _recursive_first_present(
            data.get("info", {}),
            "ipv4",
            "hostip",
            "ip",
            "ipAddress",
            "ip_addr",
            "IPAddress",
            "wifiIP",
            "wifiIp",
            "ip_addr_str",
        ),
    ),
    # Software versions
    BitaxeSensorEntityDescription(
        key="firmware_version",
        name="Firmware Version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("version"),
    ),
    BitaxeSensorEntityDescription(
        key="axeos_version",
        name="OS Version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _first_present(
            data.get("info", {}),
            "axeOSVersion",
            "axeOsVersion",
            "axe_os_version",
            "AxeOSVersion",
            "version",
        ),
    ),
    # Other metrics
    BitaxeSensorEntityDescription(
        key="block_height",
        name="Block Height",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _numeric_recursive_first_present(
            data.get("info", {}),
            "blockHeight",
            "block_height",
            "blockheight",
            "height",
            "networkBlockHeight",
            "currentBlockHeight",
            "chainHeight",
            "tipHeight",
            "bestHeight",
        ),
    ),
    BitaxeSensorEntityDescription(
        key="network_difficulty",
        name="Network Difficulty",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: (
            _numeric_recursive_first_present(
                data.get("info", {}),
                "networkDifficulty",
                "network_difficulty",
                "networkDiff",
                "network_diff",
                "difficulty",
                "stratumDifficulty",
                "poolDifficulty",
            )
            or _first_pool_numeric(
                data.get("info", {}),
                "networkDifficulty",
                "networkDiff",
                "poolDifficulty",
                "difficulty",
            )
        ),
    ),
    BitaxeSensorEntityDescription(
        key="free_heap",
        name="Free Heap",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="B",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("freeHeap"),
    ),
]


def _goldshell_get_coin_data(info: dict[str, Any], coin_index: int) -> dict[str, Any]:
    """Extract Goldshell coin data by index (0=ALEO, 1=LTC) from minfos array."""
    minfos = info.get("minfos", [])
    if not isinstance(minfos, list) or coin_index >= len(minfos):
        return {}
    device = minfos[coin_index]
    if not isinstance(device, dict):
        return {}
    infos = device.get("infos", [])
    if not isinstance(infos, list) or not infos:
        return {}
    return infos[0] if isinstance(infos[0], dict) else {}


def _goldshell_parse_temp(data: dict[str, Any], temp_index: int = 0) -> float | None:
    """Parse Goldshell temperature (format: "XX°C/YY°C", temp_index: 0 or 1)."""
    try:
        temp_str = str(data.get("temp", "")).strip()
        if not temp_str:
            return None
        parts = temp_str.split("/")
        if temp_index >= len(parts):
            return None
        temp_val = float(parts[temp_index].replace("°C", "").strip())
        return round(temp_val, 2)
    except (TypeError, ValueError, IndexError):
        return None


def _goldshell_parse_fanrpm(data: dict[str, Any]) -> int | None:
    """Parse Goldshell fan speed (format: "NNrpm")."""
    try:
        fan_str = str(data.get("fanspeed", "")).replace("rpm", "").strip()
        return int(fan_str) if fan_str else None
    except (TypeError, ValueError):
        return None


def _goldshell_mining_active(payload: dict[str, Any]) -> int:
    """Return 1 when either Goldshell card has positive hashrate, else 0."""
    info = payload.get("info", {}) if isinstance(payload, dict) else {}
    for coin_index in (0, 1):
        coin_data = _goldshell_get_coin_data(info, coin_index)
        try:
            if float(coin_data.get("hashrate", 0) or 0) > 0:
                return 1
        except (TypeError, ValueError):
            continue
    return 0


def _goldshell_pool_for_algo(info: dict[str, Any], algo_label: str) -> dict[str, Any]:
    """Return selected pool dict for an algo label from Goldshell /mcb/pools data."""
    pools_root = info.get("goldshell_pools", [])
    if not isinstance(pools_root, list):
        return {}

    for group in pools_root:
        if not isinstance(group, dict):
            continue
        name = str(group.get("name", "")).upper()
        if algo_label.upper() not in name:
            continue

        pools = group.get("pools", [])
        if not isinstance(pools, list) or not pools:
            return {}

        for pool in pools:
            if isinstance(pool, dict) and bool(pool.get("active", False)):
                return pool
        return pools[0] if isinstance(pools[0], dict) else {}

    return {}


def _goldshell_pool_url(info: dict[str, Any], algo_label: str) -> str:
    """Return pool URL for a Goldshell algo without port."""
    raw_url = str(_goldshell_pool_for_algo(info, algo_label).get("url", "") or "").strip()
    if not raw_url:
        return ""

    parsed = urlparse(raw_url if "://" in raw_url else f"stratum+tcp://{raw_url}")
    if parsed.hostname:
        if parsed.scheme:
            return f"{parsed.scheme}://{parsed.hostname}"
        return parsed.hostname

    # Fallback: remove trailing :port from host-like strings.
    host_part = raw_url.split("/", 1)[0]
    if ":" in host_part:
        host_part = host_part.rsplit(":", 1)[0]
    return host_part


def _goldshell_pool_port(info: dict[str, Any], algo_label: str) -> str:
    """Return pool port for a Goldshell algo by parsing pool URL."""
    url = str(_goldshell_pool_for_algo(info, algo_label).get("url", "") or "").strip()
    if not url:
        return ""

    parsed = urlparse(url if "://" in url else f"stratum+tcp://{url}")
    if parsed.port is not None:
        return str(parsed.port)

    raw = url.split("/", 1)[0]
    if ":" in raw:
        return raw.rsplit(":", 1)[-1]
    return ""


def _goldshell_pool_user(info: dict[str, Any], algo_label: str) -> str:
    """Return pool user for a Goldshell algo."""
    return str(_goldshell_pool_for_algo(info, algo_label).get("user", "") or "")


def _goldshell_pool_active(info: dict[str, Any], algo_label: str) -> int:
    """Return 1 when selected Goldshell algo pool is active, else 0."""
    pool = _goldshell_pool_for_algo(info, algo_label)
    return 1 if bool(pool.get("active", False)) else 0


def _goldshell_reject_rate_pct(coin_data: dict[str, Any]) -> float:
    """Return reject rate percentage from accepted/rejected counters."""
    try:
        accepted = float(coin_data.get("accepted", 0) or 0)
        rejected = float(coin_data.get("rejected", 0) or 0)
        total = accepted + rejected
        if total <= 0:
            return 0.0
        return round((rejected / total) * 100.0, 2)
    except (TypeError, ValueError):
        return 0.0


def _goldshell_hw_error_rate_pct(coin_data: dict[str, Any]) -> float:
    """Return hardware error percentage from hwerr_ration/rate-like fields."""
    raw = coin_data.get("hwerr_ration", coin_data.get("hwerr_ratio", 0))
    try:
        value = float(raw or 0)
    except (TypeError, ValueError):
        return 0.0

    # Some firmwares return a ratio (0..1), others return percent-like values.
    if 0.0 <= value <= 1.0:
        value *= 100.0
    return round(value, 2)


GOLDSHELL_SENSORS: list[BitaxeSensorEntityDescription] = [
    BitaxeSensorEntityDescription(
        key="mining_active",
        name="Mining Active",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _goldshell_mining_active(data),
    ),
    # ALEO Sensors (coin_index=0)
    BitaxeSensorEntityDescription(
        key="aleo_hashrate",
        name="ALEO Hashrate",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="H/s",
        value_fn=lambda data: round(
            float(_goldshell_get_coin_data(data.get("info", {}), 0).get("hashrate", 0)), 2
        ),
    ),
    BitaxeSensorEntityDescription(
        key="aleo_power",
        name="ALEO Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda data: round(
            float(_goldshell_get_coin_data(data.get("info", {}), 0).get("power", 0)), 2
        ),
    ),
    BitaxeSensorEntityDescription(
        key="aleo_temp_1",
        name="ALEO Temperature 1",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda data: _goldshell_parse_temp(
            _goldshell_get_coin_data(data.get("info", {}), 0), 0
        ),
    ),
    BitaxeSensorEntityDescription(
        key="aleo_temp_2",
        name="ALEO Temperature 2",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda data: _goldshell_parse_temp(
            _goldshell_get_coin_data(data.get("info", {}), 0), 1
        ),
    ),
    BitaxeSensorEntityDescription(
        key="aleo_overheated",
        name="ALEO Overheated",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BitaxeSensorEntityDescription(
        key="aleo_fan_rpm",
        name="ALEO Fan RPM",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="rpm",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _goldshell_parse_fanrpm(
            _goldshell_get_coin_data(data.get("info", {}), 0)
        ),
    ),
    BitaxeSensorEntityDescription(
        key="aleo_shares_accepted",
        name="ALEO Shares Accepted",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: int(
            _goldshell_get_coin_data(data.get("info", {}), 0).get("accepted", 0)
        ),
    ),
    BitaxeSensorEntityDescription(
        key="aleo_shares_rejected",
        name="ALEO Shares Rejected",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: int(
            _goldshell_get_coin_data(data.get("info", {}), 0).get("rejected", 0)
        ),
    ),
    BitaxeSensorEntityDescription(
        key="aleo_reject_rate",
        name="ALEO Reject Rate",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _goldshell_reject_rate_pct(
            _goldshell_get_coin_data(data.get("info", {}), 0)
        ),
    ),
    BitaxeSensorEntityDescription(
        key="aleo_hw_error_rate",
        name="ALEO HW Error Rate",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _goldshell_hw_error_rate_pct(
            _goldshell_get_coin_data(data.get("info", {}), 0)
        ),
    ),
    BitaxeSensorEntityDescription(
        key="aleo_uptime",
        name="ALEO Uptime",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: int(_goldshell_get_coin_data(data.get("info", {}), 0).get("time", 0)),
    ),
    BitaxeSensorEntityDescription(
        key="aleo_pool_url",
        name="ALEO Pool URL",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _goldshell_pool_url(data.get("info", {}), "ALEO"),
    ),
    BitaxeSensorEntityDescription(
        key="aleo_pool_port",
        name="ALEO Pool Port",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _goldshell_pool_port(data.get("info", {}), "ALEO"),
    ),
    BitaxeSensorEntityDescription(
        key="aleo_pool_user",
        name="ALEO Pool User",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _goldshell_pool_user(data.get("info", {}), "ALEO"),
    ),
    BitaxeSensorEntityDescription(
        key="aleo_pool_active",
        name="ALEO Pool Active",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _goldshell_pool_active(data.get("info", {}), "ALEO"),
    ),
    # LTC Sensors (coin_index=1)
    BitaxeSensorEntityDescription(
        key="ltc_hashrate",
        name="LTC Hashrate",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="MH/s",
        value_fn=lambda data: round(
            float(_goldshell_get_coin_data(data.get("info", {}), 1).get("hashrate", 0)), 2
        ),
    ),
    BitaxeSensorEntityDescription(
        key="ltc_power",
        name="LTC Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda data: round(
            float(_goldshell_get_coin_data(data.get("info", {}), 1).get("power", 0)), 2
        ),
    ),
    BitaxeSensorEntityDescription(
        key="ltc_temp_1",
        name="LTC Temperature 1",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda data: _goldshell_parse_temp(
            _goldshell_get_coin_data(data.get("info", {}), 1), 0
        ),
    ),
    BitaxeSensorEntityDescription(
        key="ltc_temp_2",
        name="LTC Temperature 2",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda data: _goldshell_parse_temp(
            _goldshell_get_coin_data(data.get("info", {}), 1), 1
        ),
    ),
    BitaxeSensorEntityDescription(
        key="ltc_overheated",
        name="LTC Overheated",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BitaxeSensorEntityDescription(
        key="ltc_fan_rpm",
        name="LTC Fan RPM",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="rpm",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _goldshell_parse_fanrpm(
            _goldshell_get_coin_data(data.get("info", {}), 1)
        ),
    ),
    BitaxeSensorEntityDescription(
        key="ltc_shares_accepted",
        name="LTC Shares Accepted",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: int(
            _goldshell_get_coin_data(data.get("info", {}), 1).get("accepted", 0)
        ),
    ),
    BitaxeSensorEntityDescription(
        key="ltc_shares_rejected",
        name="LTC Shares Rejected",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: int(
            _goldshell_get_coin_data(data.get("info", {}), 1).get("rejected", 0)
        ),
    ),
    BitaxeSensorEntityDescription(
        key="ltc_reject_rate",
        name="LTC Reject Rate",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _goldshell_reject_rate_pct(
            _goldshell_get_coin_data(data.get("info", {}), 1)
        ),
    ),
    BitaxeSensorEntityDescription(
        key="ltc_hw_error_rate",
        name="LTC HW Error Rate",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _goldshell_hw_error_rate_pct(
            _goldshell_get_coin_data(data.get("info", {}), 1)
        ),
    ),
    BitaxeSensorEntityDescription(
        key="ltc_uptime",
        name="LTC Uptime",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: int(_goldshell_get_coin_data(data.get("info", {}), 1).get("time", 0)),
    ),
    BitaxeSensorEntityDescription(
        key="ltc_pool_url",
        name="LTC Pool URL",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _goldshell_pool_url(data.get("info", {}), "LTC"),
    ),
    BitaxeSensorEntityDescription(
        key="ltc_pool_port",
        name="LTC Pool Port",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _goldshell_pool_port(data.get("info", {}), "LTC"),
    ),
    BitaxeSensorEntityDescription(
        key="ltc_pool_user",
        name="LTC Pool User",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _goldshell_pool_user(data.get("info", {}), "LTC"),
    ),
    BitaxeSensorEntityDescription(
        key="ltc_pool_active",
        name="LTC Pool Active",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _goldshell_pool_active(data.get("info", {}), "LTC"),
    ),
    # Device Info Sensors
    BitaxeSensorEntityDescription(
        key="firmware_version",
        name="Firmware Version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("firmware_version", ""),
    ),
    BitaxeSensorEntityDescription(
        key="device_model",
        name="Device Model",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("device_model")
        or data.get("info", {}).get("ASICModel", ""),
    ),
    BitaxeSensorEntityDescription(
        key="hardware_version",
        name="Hardware Version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("hardware_version", ""),
    ),
    BitaxeSensorEntityDescription(
        key="mac_address",
        name="MAC Address",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("info", {}).get("mac_address", ""),
    ),
    BitaxeSensorEntityDescription(
        key="ipv4_address",
        name="IPv4 Address",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _recursive_first_present(
            data.get("info", {}),
            "ipv4",
            "hostip",
            "ip",
            "ipAddress",
            "ip_addr",
            "IPAddress",
            "wifiIP",
            "wifiIp",
            "ip_addr_str",
        ),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities for Bitaxe/NerdAxe."""
    entry_type = config_entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_MINER)

    if entry_type == ENTRY_TYPE_FLEET:
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id == config_entry.entry_id:
                continue
            if entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_MINER) == ENTRY_TYPE_MINER:
                _cleanup_fleet_entities_for_entry(hass, entry.entry_id)

        configured_pool_names: list[str] = []
        seen_pool_names: set[str] = set()
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_MINER) != ENTRY_TYPE_MINER:
                continue
            pools = entry.data.get(CONF_POOLS, [])
            for pool in pools:
                pool_name = str(pool.get("name") or "").strip()
                if pool_name and pool_name not in seen_pool_names:
                    configured_pool_names.append(pool_name)
                    seen_pool_names.add(pool_name)

        fleet_entities: list[SensorEntity] = [
            BitaxeFleetSensorEntity(hass, "fleet_hashrate", "Fleet Hashrate", "GH/s"),
            BitaxeFleetSensorEntity(
                hass,
                "fleet_aleo_hashrate",
                "Fleet ALEO Hashrate",
                "H/s",
            ),
            BitaxeFleetSensorEntity(
                hass,
                "fleet_ltc_hashrate",
                "Fleet LTC Hashrate",
                "MH/s",
            ),
            BitaxeFleetSensorEntity(
                hass,
                "fleet_aleo_power",
                "Fleet ALEO Power",
                UnitOfPower.WATT,
            ),
            BitaxeFleetSensorEntity(
                hass,
                "fleet_ltc_power",
                "Fleet LTC Power",
                UnitOfPower.WATT,
            ),
            BitaxeFleetSensorEntity(hass, "fleet_power", "Fleet Power", UnitOfPower.WATT),
            BitaxeFleetSensorEntity(
                hass,
                "fleet_energy_efficiency",
                "Fleet Energy Efficiency",
                "J/TH",
            ),
            BitaxeFleetSensorEntity(
                hass,
                "fleet_hashrate_per_watt",
                "Fleet Hashrate per Watt",
                "TH/W",
            ),
            BitaxeFleetSensorEntity(hass, "fleet_miners_total", "Fleet Miners Configured"),
            BitaxeFleetSensorEntity(hass, "fleet_miners_active", "Fleet Miners Active"),
            BitaxeFleetSensorEntity(hass, "fleet_miners_inactive", "Fleet Miners Inactive"),
            BitaxeFleetSensorEntity(hass, "fleet_miners_online", "Fleet Miners Online"),
            BitaxeFleetSensorEntity(hass, "fleet_miners_offline", "Fleet Miners Offline"),
            BitaxeFleetSensorEntity(
                hass,
                "fleet_miners_asic_overheated",
                "Fleet Miners ASIC Overheated",
            ),
            BitaxeFleetSensorEntity(
                hass,
                "fleet_miners_vr_overheated",
                "Fleet Miners VR Overheated",
            ),
            BitaxeFleetSensorEntity(
                hass,
                "fleet_miners_overheated",
                "Fleet Miners Overheated",
            ),
            BitaxeFleetSensorEntity(
                hass,
                "fleet_online_percentage",
                "Fleet Miners Online Percentage",
                PERCENTAGE,
            ),
            BitaxeFleetSensorEntity(
                hass,
                "fleet_miners_unknown_pool",
                "Fleet Miners Other Pools",
            ),
        ]
        fleet_entities.extend(
            [
                BitaxeFleetSensorEntity(
                    hass,
                    f"fleet_pool_{normalize_identifier(pool_name)}_active",
                    f"Fleet {pool_name} Active Miners",
                )
                for pool_name in configured_pool_names
            ]
        )
        async_add_entities(fleet_entities)
        return

    _cleanup_fleet_entities_for_entry(hass, config_entry.entry_id)

    coordinator: BitaxeDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id][
        "coordinator"
    ]
    host = config_entry.data[CONF_HOST]
    miner_type = config_entry.data[CONF_MINER_TYPE]
    device_name = config_entry.data.get(
        CONF_DEVICE_NAME, f"{miner_type.capitalize()} {host}"
    )
    device_slug = config_entry.data.get(CONF_DEVICE_SLUG, normalize_identifier(host))

    if miner_type == MINER_TYPE_AVALON:
        _cleanup_avalon_unsupported_entities_for_entry(hass, config_entry.entry_id)
    if miner_type == MINER_TYPE_GOLDSHELL:
        _cleanup_legacy_goldshell_overheat_entities_for_entry(hass, config_entry.entry_id)

    # Determine which sensor list to use based on miner type
    sensor_list = GOLDSHELL_SENSORS if miner_type == MINER_TYPE_GOLDSHELL else BITAXE_SENSORS

    entities = [
        BitaxeSensorEntity(
            coordinator,
            config_entry.entry_id,
            host,
            miner_type,
            device_name,
            device_slug,
            sensor_description,
        )
        for sensor_description in sensor_list
        if not (
            miner_type == MINER_TYPE_AVALON and sensor_description.key in [
                "core_voltage_set", "voltage", "current", "free_heap"
            ]
        )
        if not (
            miner_type != MINER_TYPE_AVALON and sensor_description.key == "temp_exhaust"
        )
        if not (
            miner_type == MINER_TYPE_GOLDSHELL and sensor_description.key in [
                "pool_url", "pool_port", "pool_user", "pool_difficulty"
            ]
        )
    ]

    async_add_entities(entities)


class BitaxeFleetSensorEntity(SensorEntity):
    """Representation of a fleet-level sensor across all configured miners."""

    _attr_has_entity_name = True
    _attr_should_poll = True

    def __init__(
        self,
        hass: HomeAssistant,
        key: str,
        name: str,
        unit: str | None = None,
    ) -> None:
        """Initialize the fleet sensor."""
        self._hass = hass
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{key}"
        self._attr_icon = {
            "fleet_hashrate": "mdi:speedometer",
            "fleet_aleo_hashrate": "mdi:alpha-a-circle-outline",
            "fleet_ltc_hashrate": "mdi:alpha-l-circle-outline",
            "fleet_aleo_power": "mdi:flash-outline",
            "fleet_ltc_power": "mdi:flash",
            "fleet_power": "mdi:flash",
            "fleet_energy_efficiency": "mdi:gauge",
            "fleet_hashrate_per_watt": "mdi:lightning-bolt-circle",
            "fleet_miners_total": "mdi:server",
            "fleet_miners_active": "mdi:account-group",
            "fleet_miners_inactive": "mdi:account-group-outline",
            "fleet_miners_online": "mdi:account-hard-hat",
            "fleet_miners_offline": "mdi:account-hard-hat-outline",
            "fleet_miners_asic_overheated": "mdi:chip",
            "fleet_miners_vr_overheated": "mdi:thermometer-lines",
            "fleet_miners_overheated": "mdi:thermometer-alert",
            "fleet_online_percentage": "mdi:sack-percent",
            "fleet_miners_unknown_pool": "mdi:help-network-outline",
        }.get(key, "mdi:server-network")
        if unit is not None:
            self._attr_native_unit_of_measurement = unit
            self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "fleet")},
            "name": "AxeOS Fleet",
            "manufacturer": "Bitaxe Project",
            "model": "Fleet",
        }

    def _configured_miner_entries(self) -> list[ConfigEntry]:
        """Return all configured miner entries."""
        return [
            entry
            for entry in self._hass.config_entries.async_entries(DOMAIN)
            if entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_MINER) == ENTRY_TYPE_MINER
        ]

    def _fleet_entries(self) -> list[dict[str, Any]]:
        """Return loaded entry runtime data for all miners."""
        domain_data = self._hass.data.get(DOMAIN, {})
        return [
            entry_data
            for entry_data in domain_data.values()
            if isinstance(entry_data, dict)
            and entry_data.get("entry_type", ENTRY_TYPE_MINER) == ENTRY_TYPE_MINER
            and "coordinator" in entry_data
        ]

    def _online_entries(self) -> list[dict[str, Any]]:
        """Return runtime data for miners that are currently online."""
        return [
            entry_data
            for entry_data in self._fleet_entries()
            if isinstance(entry_data.get("coordinator"), BitaxeDataUpdateCoordinator)
            and entry_data["coordinator"].last_update_success
        ]

    def _active_mining_entries(self) -> list[dict[str, Any]]:
        """Return online miners that are currently mining (hashrate > 0)."""
        active_entries: list[dict[str, Any]] = []
        for entry_data in self._online_entries():
            if self._entry_hashrate_gh(entry_data) > 0:
                active_entries.append(entry_data)
        return active_entries

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        """Convert value to float when possible."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _entry_hashrate_gh(self, entry_data: dict[str, Any]) -> float:
        """Return hashrate in GH/s for mixed miner types.

        Bitaxe/NerdAxe/Avalon already expose hashRate in GH/s.
        Goldshell Byte exposes per-coin rates in different units:
        - ALEO (index 0): H/s
        - LTC  (index 1): MH/s
        """
        coordinator = entry_data.get("coordinator")
        if not isinstance(coordinator, BitaxeDataUpdateCoordinator):
            return 0.0

        info = coordinator.data.get("info", {}) if coordinator.data else {}
        if not isinstance(info, dict):
            return 0.0

        miner_type = str(entry_data.get("miner_type") or "").strip().lower()
        if miner_type != MINER_TYPE_GOLDSHELL:
            return self._safe_float(info.get("hashRate"))

        minfos = info.get("minfos", [])
        if not isinstance(minfos, list):
            return 0.0

        # Goldshell Byte dual-card conversion to GH/s
        # index 0 (ALEO): H/s -> GH/s, index 1 (LTC): MH/s -> GH/s
        total_gh = 0.0
        unit_divisors = {0: 1_000_000_000.0, 1: 1_000.0}
        for coin_index, divisor in unit_divisors.items():
            if coin_index >= len(minfos) or not isinstance(minfos[coin_index], dict):
                continue
            infos = minfos[coin_index].get("infos", [])
            if not isinstance(infos, list) or not infos or not isinstance(infos[0], dict):
                continue
            total_gh += self._safe_float(infos[0].get("hashrate")) / divisor

        return total_gh

    def _entry_power_w(self, entry_data: dict[str, Any]) -> float:
        """Return miner power in watts, summing Goldshell dual-card power."""
        coordinator = entry_data.get("coordinator")
        if not isinstance(coordinator, BitaxeDataUpdateCoordinator):
            return 0.0

        info = coordinator.data.get("info", {}) if coordinator.data else {}
        if not isinstance(info, dict):
            return 0.0

        miner_type = str(entry_data.get("miner_type") or "").strip().lower()
        if miner_type != MINER_TYPE_GOLDSHELL:
            return self._safe_float(info.get("power"))

        minfos = info.get("minfos", [])
        if not isinstance(minfos, list):
            return 0.0

        total_power = 0.0
        for coin_index in (0, 1):
            if coin_index >= len(minfos) or not isinstance(minfos[coin_index], dict):
                continue
            infos = minfos[coin_index].get("infos", [])
            if not isinstance(infos, list) or not infos or not isinstance(infos[0], dict):
                continue
            total_power += self._safe_float(infos[0].get("power"))

        return total_power

    def _pool_active_counts(self) -> dict[str, int]:
        """Return active miner count per configured pool name."""
        counts: dict[str, int] = {}
        for entry_data in self._online_entries():
            coordinator = entry_data.get("coordinator")
            if not isinstance(coordinator, BitaxeDataUpdateCoordinator):
                continue

            info = coordinator.data.get("info", {}) if coordinator.data else {}
            if not isinstance(info, dict):
                continue

            current_pool = _active_pool_tuple(info)
            pools = entry_data.get("pools", [])
            matched_name: str | None = None
            for pool in pools:
                if not isinstance(pool, dict):
                    continue
                configured_pool = _configured_pool_tuple(pool)
                if _matches_pool(current_pool, configured_pool):
                    matched_name = str(pool.get("name") or "").strip()
                    break

            if matched_name:
                counts[matched_name] = counts.get(matched_name, 0) + 1

        return counts

    def _overheated_miner_hostnames(self, temp_source: str) -> list[str]:
        """Return hostnames for online miners above threshold for a temp source."""
        hostnames: list[str] = []
        for entry_data in self._online_entries():
            coordinator = entry_data.get("coordinator")
            if not isinstance(coordinator, BitaxeDataUpdateCoordinator):
                continue

            info = coordinator.data.get("info", {}) if coordinator.data else {}
            if not isinstance(info, dict):
                continue

            miner_type = str(
                entry_data.get("miner_type")
                or getattr(coordinator, "miner_type", "")
                or ""
            ).strip().lower()
            threshold_default = _default_overheat_threshold_c(miner_type)

            if miner_type == MINER_TYPE_GOLDSHELL:
                if temp_source != "asic":
                    continue

                temp1_c = _goldshell_parse_temp(_goldshell_get_coin_data(info, 0), 0)
                temp2_c = _goldshell_parse_temp(_goldshell_get_coin_data(info, 1), 0)
                threshold_temp1 = float(
                    entry_data.get(
                        CONF_GOLDSHELL_ALEO_OVERHEAT_THRESHOLD_C,
                        entry_data.get(
                            CONF_GOLDSHELL_TEMP1_OVERHEAT_THRESHOLD_C,
                            threshold_default,
                        ),
                    )
                )
                threshold_temp2 = float(
                    entry_data.get(
                        CONF_GOLDSHELL_LTC_OVERHEAT_THRESHOLD_C,
                        entry_data.get(
                            CONF_GOLDSHELL_TEMP2_OVERHEAT_THRESHOLD_C,
                            threshold_default,
                        ),
                    )
                )

                is_overheated = bool(
                    (temp1_c is not None and temp1_c >= threshold_temp1)
                    or (temp2_c is not None and temp2_c >= threshold_temp2)
                )
                if not is_overheated:
                    continue

                hostname = str(info.get("hostname") or "").strip()
                if not hostname:
                    hostname = str(entry_data.get("host") or entry_data.get("device_name") or "").strip()
                if hostname:
                    hostnames.append(hostname)
                continue

            if temp_source == "asic":
                temp_c = _asic_temp_c(info)
                threshold = float(
                    entry_data.get(
                        CONF_ASIC_OVERHEAT_THRESHOLD_C,
                        entry_data.get(
                            CONF_OVERHEAT_THRESHOLD_C,
                            threshold_default,
                        ),
                    )
                )
            else:
                temp_c = _vr_temp_c(info)
                threshold = float(
                    entry_data.get(
                        CONF_VR_OVERHEAT_THRESHOLD_C,
                        threshold_default,
                    )
                )

            if temp_c is None:
                continue
            if temp_c < threshold:
                continue

            hostname = str(info.get("hostname") or "").strip()
            if not hostname:
                hostname = str(entry_data.get("host") or entry_data.get("device_name") or "").strip()
            if hostname:
                hostnames.append(hostname)

        return sorted(set(hostnames))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes for fleet sensors."""
        if self._key in {"fleet_hashrate", "fleet_energy_efficiency", "fleet_hashrate_per_watt"}:
            return {
                "hashrate_basis": "normalized_to_ghs",
                "hashrate_normalization": {
                    "bitaxe_nerdaxe_avalon": "hashRate (GH/s)",
                    "goldshell_aleo": "hashrate (H/s) / 1e9",
                    "goldshell_ltc": "hashrate (MH/s) / 1e3",
                },
            }
        if self._key == "fleet_miners_asic_overheated":
            return {"overheated_miner_hostnames": self._overheated_miner_hostnames("asic")}
        if self._key == "fleet_miners_vr_overheated":
            return {"overheated_miner_hostnames": self._overheated_miner_hostnames("vr")}
        if self._key == "fleet_miners_overheated":
            asic_hostnames = self._overheated_miner_hostnames("asic")
            vr_hostnames = self._overheated_miner_hostnames("vr")
            return {
                "overheated_miner_hostnames": sorted(set(asic_hostnames + vr_hostnames)),
                "asic_overheated_miner_hostnames": asic_hostnames,
                "vr_overheated_miner_hostnames": vr_hostnames,
            }
        return None

    @property
    def native_value(self) -> Any:
        """Return fleet sensor value."""
        entries = self._fleet_entries()
        online_entries = self._online_entries()
        active_mining_entries = self._active_mining_entries()

        total_hashrate_gh = 0.0
        total_power_w = 0.0
        total_aleo_hashrate_hs = 0.0
        total_ltc_hashrate_mhs = 0.0
        total_aleo_power_w = 0.0
        total_ltc_power_w = 0.0
        for entry_data in online_entries:
            total_hashrate_gh += self._entry_hashrate_gh(entry_data)
            total_power_w += self._entry_power_w(entry_data)

            miner_type = str(entry_data.get("miner_type") or "").strip().lower()
            if miner_type == MINER_TYPE_GOLDSHELL:
                coordinator = entry_data.get("coordinator")
                if isinstance(coordinator, BitaxeDataUpdateCoordinator):
                    info = coordinator.data.get("info", {}) if coordinator.data else {}
                    if isinstance(info, dict):
                        minfos = info.get("minfos", [])
                        if isinstance(minfos, list):
                            if len(minfos) > 0 and isinstance(minfos[0], dict):
                                infos = minfos[0].get("infos", [])
                                if isinstance(infos, list) and infos and isinstance(infos[0], dict):
                                    total_aleo_hashrate_hs += self._safe_float(infos[0].get("hashrate"))
                                    total_aleo_power_w += self._safe_float(infos[0].get("power"))
                            if len(minfos) > 1 and isinstance(minfos[1], dict):
                                infos = minfos[1].get("infos", [])
                                if isinstance(infos, list) and infos and isinstance(infos[0], dict):
                                    total_ltc_hashrate_mhs += self._safe_float(infos[0].get("hashrate"))
                                    total_ltc_power_w += self._safe_float(infos[0].get("power"))
        total_hashrate_th = total_hashrate_gh / 1000.0

        if self._key == "fleet_hashrate":
            return round(total_hashrate_gh, 2)

        if self._key == "fleet_aleo_hashrate":
            return round(total_aleo_hashrate_hs, 2)

        if self._key == "fleet_ltc_hashrate":
            return round(total_ltc_hashrate_mhs, 2)

        if self._key == "fleet_aleo_power":
            return round(total_aleo_power_w, 2)

        if self._key == "fleet_ltc_power":
            return round(total_ltc_power_w, 2)

        if self._key == "fleet_power":
            return round(total_power_w, 2)

        if self._key == "fleet_energy_efficiency":
            if total_hashrate_th <= 0:
                return 0
            # J/TH = W / (TH/s)
            return round(total_power_w / total_hashrate_th, 2)

        if self._key == "fleet_hashrate_per_watt":
            if total_power_w <= 0:
                return 0
            # TH/W = (TH/s) / W
            return round(total_hashrate_th / total_power_w, 4)

        if self._key == "fleet_miners_total":
            return len(self._configured_miner_entries())

        if self._key == "fleet_miners_active":
            return len(active_mining_entries)

        if self._key == "fleet_miners_inactive":
            return max(len(self._configured_miner_entries()) - len(active_mining_entries), 0)

        if self._key == "fleet_miners_online":
            return len(online_entries)

        if self._key == "fleet_miners_offline":
            return max(len(self._configured_miner_entries()) - len(online_entries), 0)

        if self._key == "fleet_miners_asic_overheated":
            return len(self._overheated_miner_hostnames("asic"))

        if self._key == "fleet_miners_vr_overheated":
            return len(self._overheated_miner_hostnames("vr"))

        if self._key == "fleet_miners_overheated":
            asic_hostnames = self._overheated_miner_hostnames("asic")
            vr_hostnames = self._overheated_miner_hostnames("vr")
            return len(set(asic_hostnames + vr_hostnames))

        if self._key == "fleet_online_percentage":
            total = len(self._configured_miner_entries())
            if total == 0:
                return 0
            return round((len(online_entries) / total) * 100, 2)

        if self._key == "fleet_miners_unknown_pool":
            online_pool_capable = [
                entry_data
                for entry_data in online_entries
                if isinstance(entry_data.get("pools"), list) and len(entry_data.get("pools", [])) > 0
            ]
            matched_total = sum(self._pool_active_counts().values())
            return max(len(online_pool_capable) - matched_total, 0)

        if self._key.startswith("fleet_pool_") and self._key.endswith("_active"):
            pool_slug = self._key[len("fleet_pool_") : -len("_active")]
            counts = self._pool_active_counts()
            for pool_name, count in counts.items():
                if normalize_identifier(pool_name) == pool_slug:
                    return count
            return 0

        return 0


class BitaxeSensorEntity(CoordinatorEntity, SensorEntity):
    """Representation of a Bitaxe sensor."""

    entity_description: BitaxeSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BitaxeDataUpdateCoordinator,
        entry_id: str,
        host: str,
        miner_type: str,
        device_name: str,
        device_slug: str,
        sensor_description: BitaxeSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = sensor_description
        self._entry_id = entry_id
        self._host = host
        self._miner_type = miner_type
        self._device_name = device_name
        self._device_slug = device_slug
        self._attr_unique_id = (
            f"{miner_type}_{self._device_slug}_{sensor_description.key}"
        )
        self._attr_icon = SENSOR_ICONS.get(sensor_description.key)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{miner_type}_{self._device_slug}")},
            "name": self._device_name,
            "manufacturer": "Bitaxe Project",
            "model": miner_type.capitalize(),
        }

    @property
    def native_value(self) -> Optional[Any]:
        """Return the state of the sensor."""
        if self.entity_description.key in {
            "overheated",
            "vr_overheated",
            "aleo_overheated",
            "ltc_overheated",
        }:
            if not self.coordinator.data:
                return 0

            info = self.coordinator.data.get("info", {})
            if not isinstance(info, dict):
                return 0

            threshold_default = _default_overheat_threshold_c(self._miner_type)
            runtime_entry = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})

            if self.entity_description.key == "overheated":
                temp_c = _asic_temp_c(info)
                threshold = float(
                    runtime_entry.get(
                        CONF_ASIC_OVERHEAT_THRESHOLD_C,
                        runtime_entry.get(
                            CONF_OVERHEAT_THRESHOLD_C,
                            threshold_default,
                        ),
                    )
                )
            elif self.entity_description.key == "vr_overheated":
                temp_c = _vr_temp_c(info)
                threshold = float(
                    runtime_entry.get(
                        CONF_VR_OVERHEAT_THRESHOLD_C,
                        threshold_default,
                    )
                )
            elif self.entity_description.key == "aleo_overheated":
                temp_c = _goldshell_parse_temp(_goldshell_get_coin_data(info, 0), 0)
                threshold = float(
                    runtime_entry.get(
                        CONF_GOLDSHELL_ALEO_OVERHEAT_THRESHOLD_C,
                        runtime_entry.get(
                            CONF_GOLDSHELL_TEMP1_OVERHEAT_THRESHOLD_C,
                            threshold_default,
                        ),
                    )
                )
            else:
                temp_c = _goldshell_parse_temp(_goldshell_get_coin_data(info, 1), 0)
                threshold = float(
                    runtime_entry.get(
                        CONF_GOLDSHELL_LTC_OVERHEAT_THRESHOLD_C,
                        runtime_entry.get(
                            CONF_GOLDSHELL_TEMP2_OVERHEAT_THRESHOLD_C,
                            threshold_default,
                        ),
                    )
                )

            if temp_c is None:
                return 0
            return 1 if temp_c >= threshold else 0

        if not self.coordinator.data or not self.entity_description.value_fn:
            # For numeric sensors, return 0 to avoid breaking float sums during reboots
            if self.entity_description.native_unit_of_measurement:
                return 0
            return None

        try:
            value = self.entity_description.value_fn(self.coordinator.data)
            if value is None and self.entity_description.key == "ipv4_address":
                return _host_ipv4_or_none(self._host)
            if (
                value is None
                and self.entity_description.key != "ipv4_address"
                and (
                    self.entity_description.native_unit_of_measurement is not None
                    or self.entity_description.state_class is not None
                )
            ):
                return 0
            return value
        except (KeyError, TypeError) as e:
            _LOGGER.debug(
                f"Error getting value for {self.entity_description.key}: {e}"
            )
            # For numeric sensors, return 0 to avoid breaking float sums
            if self.entity_description.native_unit_of_measurement:
                return 0
            return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
