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
    CONF_DEVICE_NAME,
    CONF_DEVICE_SLUG,
    CONF_ENTRY_TYPE,
    CONF_HOST,
    CONF_MINER_TYPE,
    CONF_OVERHEAT_THRESHOLD_C,
    CONF_POOLS,
    DOMAIN,
    ENTRY_TYPE_FLEET,
    ENTRY_TYPE_MINER,
    MINER_TYPE_AVALON,
    OVERHEAT_THRESHOLD_DEFAULT_C,
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


def _overheat_source_temp_c(miner_type: str, info: dict[str, Any]) -> float | None:
    """Return temperature source for overheat checks by miner type.

    Avalon miners should use VR temperature, while Bitaxe/NerdAxe use ASIC temp.
    """
    try:
        if miner_type == MINER_TYPE_AVALON:
            raw = info.get("vrTemp")
            return float(raw) if raw is not None else None
        raw = info.get("temp")
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


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


SENSOR_ICONS: dict[str, str] = {
    "mining_active": "mdi:pickaxe",
    "overheated": "mdi:thermometer-alert",
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
        name="Overheated",
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
            BitaxeFleetSensorEntity(hass, "fleet_miners_online", "Fleet Miners Online"),
            BitaxeFleetSensorEntity(hass, "fleet_miners_offline", "Fleet Miners Offline"),
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
                "Fleet Miners Unknown Pool",
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
        for sensor_description in BITAXE_SENSORS
        if not (
            miner_type == MINER_TYPE_AVALON and sensor_description.key in [
                "core_voltage_set", "voltage", "current", "free_heap"
            ]
        )
        if not (
            miner_type != MINER_TYPE_AVALON and sensor_description.key == "temp_exhaust"
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
            "fleet_power": "mdi:flash",
            "fleet_energy_efficiency": "mdi:gauge",
            "fleet_hashrate_per_watt": "mdi:lightning-bolt-circle",
            "fleet_miners_total": "mdi:server",
            "fleet_miners_online": "mdi:account-hard-hat",
            "fleet_miners_offline": "mdi:account-hard-hat-outline",
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

    def _overheated_miner_hostnames(self) -> list[str]:
        """Return hostnames for online miners above their configured threshold."""
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
            temp_c = _overheat_source_temp_c(miner_type, info)
            if temp_c is None:
                continue

            threshold = float(
                entry_data.get(
                    CONF_OVERHEAT_THRESHOLD_C,
                    OVERHEAT_THRESHOLD_DEFAULT_C,
                )
            )
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
        if self._key == "fleet_miners_overheated":
            return {"overheated_miner_hostnames": self._overheated_miner_hostnames()}
        return None

    @property
    def native_value(self) -> Any:
        """Return fleet sensor value."""
        entries = self._fleet_entries()
        online_entries = self._online_entries()

        total_hashrate_gh = 0.0
        total_power_w = 0.0
        for entry_data in online_entries:
            coordinator = entry_data.get("coordinator")
            if not isinstance(coordinator, BitaxeDataUpdateCoordinator):
                continue
            info = coordinator.data.get("info", {}) if coordinator.data else {}
            if not isinstance(info, dict):
                continue
            try:
                total_hashrate_gh += float(info.get("hashRate") or 0)
            except (TypeError, ValueError):
                pass
            try:
                total_power_w += float(info.get("power") or 0)
            except (TypeError, ValueError):
                pass
        total_hashrate_th = total_hashrate_gh / 1000.0

        if self._key == "fleet_hashrate":
            return round(total_hashrate_gh, 2)

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

        if self._key == "fleet_miners_online":
            return len(online_entries)

        if self._key == "fleet_miners_offline":
            return max(len(self._configured_miner_entries()) - len(online_entries), 0)

        if self._key == "fleet_miners_overheated":
            overheated_count = 0
            for entry_data in online_entries:
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
                temp_c = _overheat_source_temp_c(miner_type, info)
                if temp_c is None:
                    continue
                threshold = float(
                    entry_data.get(
                        CONF_OVERHEAT_THRESHOLD_C,
                        OVERHEAT_THRESHOLD_DEFAULT_C,
                    )
                )
                if temp_c >= threshold:
                    overheated_count += 1
            return overheated_count

        if self._key == "fleet_online_percentage":
            total = len(self._configured_miner_entries())
            if total == 0:
                return 0
            return round((len(online_entries) / total) * 100, 2)

        if self._key == "fleet_miners_unknown_pool":
            matched_total = sum(self._pool_active_counts().values())
            return max(len(online_entries) - matched_total, 0)

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
        if self.entity_description.key == "overheated":
            if not self.coordinator.data:
                return 0

            info = self.coordinator.data.get("info", {})
            if not isinstance(info, dict):
                return 0

            temp_c = _overheat_source_temp_c(self._miner_type, info)
            if temp_c is None:
                return 0

            runtime_entry = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
            threshold = float(
                runtime_entry.get(
                    CONF_OVERHEAT_THRESHOLD_C,
                    OVERHEAT_THRESHOLD_DEFAULT_C,
                )
            )
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
