"""The Bitaxe/NerdAxe integration."""

import ipaddress
import logging
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac

from .api_client import BitaxeAPIClient
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
    CONF_MINER_NAME,
    CONF_MINER_TYPE,
    CONF_OVERHEAT_THRESHOLD_C,
    CONF_POOLS,
    CONF_TARGET_TEMP_C,
    CONF_VR_OVERHEAT_THRESHOLD_C,
    CONF_AVALON_USERNAME,
    CONF_AVALON_PASSWORD,
    DOMAIN,
    ENTRY_TYPE_FLEET,
    ENTRY_TYPE_MINER,
    MINER_TYPE_BITAXE,
    MINER_TYPE_NERDAXE,
    PLATFORMS_FLEET,
    PLATFORMS_MINER,
    overheat_threshold_profile,
)
from .coordinator import BitaxeDataUpdateCoordinator
from .services import async_register_services, async_unregister_services
from .utils import normalize_identifier

_LOGGER: logging.Logger = logging.getLogger(__name__)


def _normalize_host(raw_host: str) -> str:
    """Normalize host to plain IP/hostname without scheme/path."""
    candidate = raw_host.strip()
    if "://" in candidate:
        parsed = urlparse(candidate)
        candidate = parsed.hostname or ""
    return candidate.split("/", 1)[0].strip()


def _entry_type(entry: ConfigEntry) -> str:
    """Return entry type with backward-compatible default."""
    return entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_MINER)


def _is_ip_address(value: str) -> bool:
    """Return True when value is a valid IPv4/IPv6 address."""
    try:
        ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return True


def _preferred_device_host(configured_host: str, discovered_host: str | None) -> str:
    """Prefer configured hostname when discovery only returns an IP address."""
    configured_host = configured_host.strip()
    if not isinstance(discovered_host, str) or not discovered_host.strip():
        return configured_host

    discovered_host = discovered_host.strip()
    if (
        _is_ip_address(discovered_host)
        and configured_host
        and not _is_ip_address(configured_host)
    ):
        return configured_host

    return discovered_host


def _is_hostname(value: str) -> bool:
    """Return True when value looks like a hostname rather than an IP."""
    return bool(value and not _is_ip_address(value))


def _normalized_entry_host(entry: ConfigEntry) -> str:
    """Return normalized host value from a config entry."""
    return _normalize_host(str(entry.data.get(CONF_HOST, "")))


def _is_miner_entry(entry: ConfigEntry) -> bool:
    """Return True for miner entries (not fleet entries)."""
    return _entry_type(entry) == ENTRY_TYPE_MINER


def _api_first_numeric(info: dict[str, object], keys: tuple[str, ...]) -> float | None:
    """Return first numeric value found in info for any candidate key."""
    for key in keys:
        raw = info.get(key)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _api_bitaxe_temperature_target_c(info: dict[str, object]) -> float | None:
    """Return Bitaxe temp target from API payload when available."""
    return _api_first_numeric(info, ("temptarget", "tempTarget", "temp_target"))


def _api_nerdaxe_asic_shutdown_temp_c(info: dict[str, object]) -> float | None:
    """Return NerdAxe ASIC shutdown threshold from API payload when available."""
    fans = info.get("fans")
    if isinstance(fans, list) and fans:
        first = fans[0]
        if isinstance(first, dict):
            fan_value = _api_first_numeric(first, ("overheatTemp", "overheat_temp"))
            if fan_value is not None:
                return fan_value

    return _api_first_numeric(
        info,
        (
            "overheat_temp",
            "overheatTemp",
            "shutdownTempAsic",
            "shutdownTempASIC",
            "shutdownTempAsics",
            "shutdownTemp",
            "shutdown_temp",
            "asicShutdownTemp",
            "asic_shutdown",
            "asic_shutdown_temp",
            "shutdown_temp_asic",
            "overheatTempAsic",
            "overheat_temp_asic",
        ),
    )


def _api_nerdaxe_vr_shutdown_temp_c(info: dict[str, object]) -> float | None:
    """Return NerdAxe VR shutdown threshold from API payload when available."""
    fans = info.get("fans")
    if isinstance(fans, list) and len(fans) > 1:
        second = fans[1]
        if isinstance(second, dict):
            fan_value = _api_first_numeric(second, ("overheatTemp", "overheat_temp"))
            if fan_value is not None:
                return fan_value

    return _api_first_numeric(
        info,
        (
            "vrShutdownTemp",
            "vrShutdownTemperature",
            "shutdownTempVr",
            "shutdownTempVR",
            "vr_shutdown_temp",
            "shutdown_temp_vr",
            "voltageRegulatorShutdownTemp",
            "voltageRegulatorShutdownTemperature",
            "voltage_regulator_shutdown_temp",
            "vregShutdownTemp",
            "overheatTempVr",
            "overheat_temp_vr",
        ),
    )


async def _async_cleanup_duplicate_ip_entries(
    hass: HomeAssistant,
    entry: ConfigEntry,
    host: str,
    discovered_hostname: str | None,
    unique_id: str | None,
) -> bool:
    """Remove duplicate IP-based entries when a hostname entry exists.

    Returns True when the current entry was removed and setup should stop.
    """
    if not isinstance(discovered_hostname, str) or not discovered_hostname.strip():
        return False

    discovered_hostname = discovered_hostname.strip()
    if not _is_hostname(discovered_hostname):
        return False

    current_host = host.strip()
    all_entries = [e for e in hass.config_entries.async_entries(DOMAIN) if _is_miner_entry(e)]

    # If current entry is IP-based and we already have the hostname entry,
    # remove current IP entry and keep the hostname as canonical.
    if _is_ip_address(current_host):
        hostname_entries = [
            other
            for other in all_entries
            if other.entry_id != entry.entry_id
            and _normalized_entry_host(other) == discovered_hostname
        ]

        if not hostname_entries:
            return False

        if unique_id:
            same_unique_id_match = any(other.unique_id == unique_id for other in hostname_entries)
            any_unset_unique_id = any(not other.unique_id for other in hostname_entries)
            if not same_unique_id_match and not any_unset_unique_id:
                return False

        _LOGGER.info(
            "Removing duplicate IP entry %s (%s); hostname entry already exists for %s",
            entry.entry_id,
            current_host,
            discovered_hostname,
        )
        await hass.config_entries.async_remove(entry.entry_id)
        return True

    # If current entry is hostname-based, remove any IP duplicates with same unique ID.
    if _is_hostname(current_host) and unique_id:
        for other in all_entries:
            if other.entry_id == entry.entry_id:
                continue
            other_host = _normalized_entry_host(other)
            if _is_ip_address(other_host) and other.unique_id == unique_id:
                _LOGGER.info(
                    "Removing duplicate IP entry %s (%s) in favor of hostname %s",
                    other.entry_id,
                    other_host,
                    current_host,
                )
                await hass.config_entries.async_remove(other.entry_id)

    return False


def _has_runtime_miner_entries(hass: HomeAssistant) -> bool:
    """Return True if any loaded runtime entries are miner entries."""
    for entry_data in hass.data.get(DOMAIN, {}).values():
        if (
            isinstance(entry_data, dict)
            and entry_data.get("entry_type", ENTRY_TYPE_MINER) == ENTRY_TYPE_MINER
        ):
            return True
    return False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Bitaxe/NerdAxe from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    entry_type = _entry_type(entry)
    if entry_type == ENTRY_TYPE_FLEET:
        hass.data[DOMAIN][entry.entry_id] = {
            "entry_type": ENTRY_TYPE_FLEET,
            "device_name": entry.data.get(CONF_DEVICE_NAME, "Crypto Miner Fleet Monitor"),
            "device_slug": entry.data.get(CONF_DEVICE_SLUG, "fleet"),
        }
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_FLEET)
        return True

    original_host = entry.data[CONF_HOST]
    host = _normalize_host(original_host)
    miner_type = entry.data[CONF_MINER_TYPE]

    if host and host != original_host:
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_HOST: host,
            },
        )

    _LOGGER.debug(f"Setting up {miner_type} at {host}")

    # Create API client
    session = async_get_clientsession(hass)
    
    # Extract Avalon credentials if available
    avalon_username = entry.data.get(CONF_AVALON_USERNAME, "admin")
    avalon_password = entry.data.get(CONF_AVALON_PASSWORD, "admin")
    
    api_client = BitaxeAPIClient(
        host,
        session,
        miner_type=miner_type,
        avalon_web_user=avalon_username,
        avalon_web_password=avalon_password,
        miner_name=entry.data.get(CONF_MINER_NAME),
    )

    # Create coordinator with 30-second update interval
    coordinator = BitaxeDataUpdateCoordinator(
        hass,
        _LOGGER,
        api_client,
        host,
        miner_type,
        update_interval=30,
    )

    # Initial data fetch
    await coordinator.async_config_entry_first_refresh()

    discovered_mac = coordinator.data.get("info", {}).get("macAddr")
    resolved_unique_id = entry.unique_id
    if isinstance(discovered_mac, str) and discovered_mac.strip():
        try:
            normalized_mac = format_mac(discovered_mac)
            resolved_unique_id = normalized_mac
            if entry.unique_id != normalized_mac:
                hass.config_entries.async_update_entry(entry, unique_id=normalized_mac)
        except ValueError:
            _LOGGER.debug("Invalid discovered macAddr for entry %s: %s", entry.entry_id, discovered_mac)

    # Prefer discovered hostname for UI/device naming, with fallback to host.
    discovered_hostname = coordinator.data.get("info", {}).get("hostname")
    removed_current_entry = await _async_cleanup_duplicate_ip_entries(
        hass,
        entry,
        host,
        discovered_hostname if isinstance(discovered_hostname, str) else None,
        resolved_unique_id,
    )
    if removed_current_entry:
        return True

    # Prefer a user-provided miner name (Avalon) for naming, then the
    # discovered hostname, with fallback to host.
    configured_miner_name = entry.data.get(CONF_MINER_NAME)
    if isinstance(configured_miner_name, str) and configured_miner_name.strip():
        device_name = f"{miner_type.capitalize()} {configured_miner_name.strip()}"
        device_slug = normalize_identifier(configured_miner_name)
    else:
        preferred_host = _preferred_device_host(host, discovered_hostname)
        device_name = f"{miner_type.capitalize()} {preferred_host}"
        device_slug = normalize_identifier(preferred_host)

    if (
        entry.data.get(CONF_DEVICE_NAME) != device_name
        or entry.data.get(CONF_DEVICE_SLUG) != device_slug
        or CONF_POOLS not in entry.data
    ):
        hass.config_entries.async_update_entry(
            entry,
            title=device_name,
            data={
                **entry.data,
                CONF_DEVICE_NAME: device_name,
                CONF_DEVICE_SLUG: device_slug,
                CONF_POOLS: entry.data.get(CONF_POOLS, []),
                CONF_HOST: host,
            },
        )

    # Store coordinator, API client, and host for service lookups
    _, _, threshold_default = overheat_threshold_profile(miner_type)
    asic_threshold = float(
        entry.options.get(
            CONF_ASIC_OVERHEAT_THRESHOLD_C,
            entry.options.get(
                CONF_OVERHEAT_THRESHOLD_C,
                threshold_default,
            ),
        )
    )
    vr_threshold = float(
        entry.options.get(
            CONF_VR_OVERHEAT_THRESHOLD_C,
            threshold_default,
        )
    )
    goldshell_temp1_threshold = float(
        entry.options.get(
            CONF_GOLDSHELL_ALEO_OVERHEAT_THRESHOLD_C,
            entry.options.get(
                CONF_GOLDSHELL_TEMP1_OVERHEAT_THRESHOLD_C,
                asic_threshold,
            ),
        )
    )
    goldshell_temp2_threshold = float(
        entry.options.get(
            CONF_GOLDSHELL_LTC_OVERHEAT_THRESHOLD_C,
            entry.options.get(
                CONF_GOLDSHELL_TEMP2_OVERHEAT_THRESHOLD_C,
                vr_threshold,
            ),
        )
    )

    if miner_type in (MINER_TYPE_BITAXE, MINER_TYPE_NERDAXE):
        info = coordinator.data.get("info", {}) if coordinator.data else {}
        if isinstance(info, dict):
            options = dict(entry.options)
            options_changed = False

            if miner_type == MINER_TYPE_BITAXE:
                api_target = _api_bitaxe_temperature_target_c(info)
                if api_target is not None:
                    options[CONF_TARGET_TEMP_C] = float(api_target)
                    options_changed = True

            if miner_type == MINER_TYPE_NERDAXE:
                asic_api_target = _api_nerdaxe_asic_shutdown_temp_c(info)
                vr_api_target = _api_nerdaxe_vr_shutdown_temp_c(info)

                if asic_api_target is not None:
                    asic_threshold = float(asic_api_target)
                    options[CONF_ASIC_OVERHEAT_THRESHOLD_C] = asic_threshold
                    options[CONF_OVERHEAT_THRESHOLD_C] = asic_threshold
                    options_changed = True

                if vr_api_target is not None:
                    vr_threshold = float(vr_api_target)
                    options[CONF_VR_OVERHEAT_THRESHOLD_C] = vr_threshold
                    options_changed = True

            if options_changed and options != entry.options:
                hass.config_entries.async_update_entry(entry, options=options)

    hass.data[DOMAIN][entry.entry_id] = {
        "entry_type": ENTRY_TYPE_MINER,
        "miner_type": miner_type,
        "coordinator": coordinator,
        "api_client": api_client,
        "host": host,
        "device_name": entry.data.get(CONF_DEVICE_NAME, device_name),
        "device_slug": entry.data.get(CONF_DEVICE_SLUG, device_slug),
        "pools": entry.data.get(CONF_POOLS, []),
        CONF_TARGET_TEMP_C: float(
            entry.options.get(
                CONF_TARGET_TEMP_C,
                _api_bitaxe_temperature_target_c(coordinator.data.get("info", {}))
                if miner_type == MINER_TYPE_BITAXE and coordinator.data and isinstance(coordinator.data.get("info", {}), dict)
                else threshold_default,
            )
        ),
        CONF_OVERHEAT_THRESHOLD_C: asic_threshold,
        CONF_ASIC_OVERHEAT_THRESHOLD_C: asic_threshold,
        CONF_VR_OVERHEAT_THRESHOLD_C: vr_threshold,
        CONF_GOLDSHELL_ALEO_OVERHEAT_THRESHOLD_C: goldshell_temp1_threshold,
        CONF_GOLDSHELL_LTC_OVERHEAT_THRESHOLD_C: goldshell_temp2_threshold,
        CONF_GOLDSHELL_TEMP1_OVERHEAT_THRESHOLD_C: goldshell_temp1_threshold,
        CONF_GOLDSHELL_TEMP2_OVERHEAT_THRESHOLD_C: goldshell_temp2_threshold,
    }

    # Register services (only once per domain)
    if not hass.services.has_service(DOMAIN, "set_pool"):
        async_register_services(hass)

    # Load platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_MINER)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    runtime_entry = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    entry_type = runtime_entry.get("entry_type", _entry_type(entry))
    platforms = (
        PLATFORMS_FLEET if entry_type == ENTRY_TYPE_FLEET else PLATFORMS_MINER
    )
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

        # Unregister miner services when no miner entries remain loaded.
        if not _has_runtime_miner_entries(hass):
            async_unregister_services(hass)

    return unload_ok
