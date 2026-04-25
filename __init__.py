"""The Bitaxe/NerdAxe integration."""

import logging
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api_client import BitaxeAPIClient
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
    OVERHEAT_THRESHOLD_DEFAULT_C,
    PLATFORMS_FLEET,
    PLATFORMS_MINER,
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
            "device_name": entry.data.get(CONF_DEVICE_NAME, "AxeOS Fleet"),
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
    api_client = BitaxeAPIClient(host, session)

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

    # Prefer discovered hostname for UI/device naming, with fallback to host.
    discovered_hostname = coordinator.data.get("info", {}).get("hostname")
    if isinstance(discovered_hostname, str) and discovered_hostname.strip():
        cleaned_hostname = discovered_hostname.strip()
        device_name = f"{miner_type.capitalize()} {cleaned_hostname}"
        device_slug = normalize_identifier(cleaned_hostname)
    else:
        device_name = f"{miner_type.capitalize()} {host}"
        device_slug = normalize_identifier(host)

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
    hass.data[DOMAIN][entry.entry_id] = {
        "entry_type": ENTRY_TYPE_MINER,
        "coordinator": coordinator,
        "api_client": api_client,
        "host": host,
        "device_name": entry.data.get(CONF_DEVICE_NAME, device_name),
        "device_slug": entry.data.get(CONF_DEVICE_SLUG, device_slug),
        "pools": entry.data.get(CONF_POOLS, []),
        CONF_OVERHEAT_THRESHOLD_C: float(
            entry.options.get(
                CONF_OVERHEAT_THRESHOLD_C,
                OVERHEAT_THRESHOLD_DEFAULT_C,
            )
        ),
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
