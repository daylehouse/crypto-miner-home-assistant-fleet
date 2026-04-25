"""Select entities for Bitaxe/NerdAxe integration."""

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DEVICE_NAME,
    CONF_DEVICE_SLUG,
    CONF_HOST,
    CONF_MINER_TYPE,
    CONF_POOLS,
    DOMAIN,
)
from .coordinator import BitaxeDataUpdateCoordinator
from .utils import normalize_identifier

_LOGGER = logging.getLogger(__name__)


def _normalize_pool_url(value: Any) -> str | None:
    """Normalize pool URL for reliable comparison across API variants."""
    if value is None:
        return None
    url = str(value).strip().lower()
    if not url:
        return None
    for prefix in ("stratum+tcp://", "stratum+ssl://", "stratum://"):
        if url.startswith(prefix):
            url = url[len(prefix) :]
            break
    return url.rstrip("/")


def _normalize_pool_user(value: Any) -> str | None:
    """Normalize pool username for comparison."""
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


def _current_pool_from_info(info: dict[str, Any]) -> tuple[str | None, int | None, str | None]:
    """Return current URL/port/user based on active primary/fallback pool state."""
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


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities for Bitaxe/NerdAxe."""
    pools = config_entry.data.get(CONF_POOLS, [])
    if not pools:
        return

    coordinator: BitaxeDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id][
        "coordinator"
    ]
    api_client = hass.data[DOMAIN][config_entry.entry_id]["api_client"]
    host = config_entry.data[CONF_HOST]
    miner_type = config_entry.data[CONF_MINER_TYPE]
    device_name = config_entry.data.get(
        CONF_DEVICE_NAME, f"{miner_type.capitalize()} {host}"
    )
    device_slug = config_entry.data.get(CONF_DEVICE_SLUG, normalize_identifier(host))

    async_add_entities(
        [
            BitaxePoolSelectEntity(
                coordinator,
                api_client,
                miner_type,
                device_name,
                device_slug,
                pools,
            )
        ]
    )


class BitaxePoolSelectEntity(CoordinatorEntity, SelectEntity):
    """Select active pool profile for the miner."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BitaxeDataUpdateCoordinator,
        api_client: Any,
        miner_type: str,
        device_name: str,
        device_slug: str,
        pools: list[dict[str, Any]],
    ) -> None:
        """Initialize pool profile selector."""
        super().__init__(coordinator)
        self._api_client = api_client
        self._miner_type = miner_type
        self._device_name = device_name
        self._device_slug = device_slug

        option_names: list[str] = []
        self._pool_by_option: dict[str, dict[str, Any]] = {}
        for index, pool in enumerate(pools, start=1):
            name = str(pool.get("name") or f"Pool {index}").strip()
            option = name
            dedupe = 2
            while option in self._pool_by_option:
                option = f"{name} ({dedupe})"
                dedupe += 1
            self._pool_by_option[option] = pool
            option_names.append(option)

        self._attr_options = option_names
        self._attr_name = "Active Pool"
        self._attr_unique_id = f"{miner_type}_{device_slug}_active_pool"
        self._attr_icon = "mdi:pool"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{miner_type}_{device_slug}")},
            "name": self._device_name,
            "manufacturer": "Bitaxe Project",
            "model": miner_type.capitalize(),
        }

    @property
    def current_option(self) -> str | None:
        """Return selected option by matching current stratum config."""
        info = self.coordinator.data.get("info", {}) if self.coordinator.data else {}
        current_url, current_port, current_user = _current_pool_from_info(info)

        best_option: str | None = None
        best_score = -1

        for option, pool in self._pool_by_option.items():
            pool_url = _normalize_pool_url(pool.get("stratum_url"))
            pool_port = _normalize_pool_port(pool.get("stratum_port"))
            pool_user = _normalize_pool_user(pool.get("stratum_user"))

            if pool_url is None or current_url is None or pool_url != current_url:
                continue

            # Ranked matching to tolerate minor API differences on first add:
            # 3: URL+user+port, 2: URL+user, 1: URL+port, 0: URL only.
            user_match = pool_user is not None and current_user is not None and pool_user == current_user
            port_match = pool_port is not None and current_port is not None and pool_port == current_port

            if user_match and port_match:
                return option
            if user_match:
                score = 2
            elif port_match:
                score = 1
            else:
                score = 0

            if score > best_score:
                best_score = score
                best_option = option

        if best_option is not None:
            return best_option

        return None

    async def async_select_option(self, option: str) -> None:
        """Set selected pool on miner via API, then reboot to apply."""
        if option not in self._pool_by_option:
            raise ValueError(f"Unknown pool option: {option}")

        pool = self._pool_by_option[option]
        await self._api_client.set_pool_settings(
            stratum_url=pool["stratum_url"],
            stratum_port=pool["stratum_port"],
            stratum_user=pool["stratum_user"],
            stratum_password=pool["stratum_password"],
        )

        _LOGGER.info(
            "Switched %s to pool '%s' (%s:%s) — rebooting to apply",
            self._device_name,
            option,
            pool["stratum_url"],
            pool["stratum_port"],
        )
        await self._api_client.restart_system()
        await self.coordinator.async_request_refresh()
