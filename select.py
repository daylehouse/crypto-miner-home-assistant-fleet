"""Select entities for Bitaxe/NerdAxe integration."""

import logging
from typing import Any
from urllib.parse import urlparse

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DEVICE_NAME,
    CONF_DEVICE_SLUG,
    CONF_HOST,
    CONF_MINER_TYPE,
    CONF_POOLS,
    CONF_AVALON_USERNAME,
    CONF_AVALON_PASSWORD,
    DOMAIN,
    MINER_TYPE_AVALON,
    MINER_TYPE_GOLDSHELL,
)
from .coordinator import BitaxeDataUpdateCoordinator
from .utils import normalize_identifier

_LOGGER = logging.getLogger(__name__)

AVALON_WORK_MODES = {
    "Low": 0,
    "Mid": 1,
    "High": 2,
}
AVALON_REVERSE_WORK_MODES = {value: key for key, value in AVALON_WORK_MODES.items()}

GOLDSHELL_DEFAULT_POWER_OPTIONS = {
    "High Power": 0,
    "Standard Power": 2,
}
GOLDSHELL_POWER_LEVEL_NAMES = {
    0: "High Power",
    2: "Standard Power",
}
GOLDSHELL_PAUSED_OPTION = "Paused"


def _normalize_pool_url(value: Any) -> str | None:
    """Normalize pool URL to hostname for reliable comparison across API variants."""
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
    
    # Extract Avalon credentials if available
    avalon_username = config_entry.data.get(CONF_AVALON_USERNAME)
    avalon_password = config_entry.data.get(CONF_AVALON_PASSWORD)

    entities: list[SelectEntity] = []

    if pools:
        entities.append(
            BitaxePoolSelectEntity(
                coordinator,
                api_client,
                miner_type,
                device_name,
                device_slug,
                pools,
                avalon_username=avalon_username,
                avalon_password=avalon_password,
            )
        )

    if miner_type == MINER_TYPE_AVALON:
        entities.append(
            AvalonWorkModeSelectEntity(
                coordinator,
                api_client,
                device_name,
                device_slug,
            )
        )

    if miner_type == MINER_TYPE_GOLDSHELL:
        _cleanup_legacy_goldshell_power_mode_selects(hass, config_entry.entry_id, device_slug)

        goldshell_setting: dict[str, Any] = {}
        try:
            goldshell_setting = await api_client.get_goldshell_setting()
        except Exception as e:
            _LOGGER.debug("Could not fetch Goldshell setting at setup: %s", e)

        entities.append(
            GoldshellPowerModeSelectEntity(
                coordinator,
                api_client,
                device_name,
                device_slug,
                setting=goldshell_setting,
            )
        )

    if not entities:
        return

    async_add_entities(entities)


def _cleanup_legacy_goldshell_power_mode_selects(
    hass: HomeAssistant,
    entry_id: str,
    device_slug: str,
) -> None:
    """Remove old ALEO/LTC power mode select entities after consolidation."""
    registry = er.async_get(hass)
    legacy_ids = {
        f"goldshell_{device_slug}_aleo_power_mode",
        f"goldshell_{device_slug}_ltc_power_mode",
    }
    for reg_entry in er.async_entries_for_config_entry(registry, entry_id):
        if reg_entry.domain != "select":
            continue
        if (reg_entry.unique_id or "") in legacy_ids:
            registry.async_remove(reg_entry.entity_id)


class AvalonWorkModeSelectEntity(CoordinatorEntity, SelectEntity):
    """Select Avalon mining work mode."""

    _attr_has_entity_name = True
    _attr_options = list(AVALON_WORK_MODES.keys())

    def __init__(
        self,
        coordinator: BitaxeDataUpdateCoordinator,
        api_client: Any,
        device_name: str,
        device_slug: str,
    ) -> None:
        super().__init__(coordinator)
        self._api_client = api_client
        self._device_name = device_name
        self._device_slug = device_slug
        self._attr_name = "Work Mode"
        self._attr_unique_id = f"avalon_{device_slug}_work_mode"
        self._attr_icon = "mdi:tune-variant"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"avalon_{device_slug}")},
            "name": self._device_name,
            "manufacturer": "Canaan",
            "model": "Avalon",
        }

    @property
    def current_option(self) -> str:
        """Return current Avalon work mode."""
        info = self.coordinator.data.get("info", {}) if self.coordinator.data else {}
        workmode = info.get("workModeLevel")
        try:
            return AVALON_REVERSE_WORK_MODES[int(workmode)]
        except (TypeError, ValueError, KeyError):
            return "Low"

    async def async_select_option(self, option: str) -> None:
        """Set Avalon work mode and refresh data."""
        level = AVALON_WORK_MODES.get(option)
        if level is None:
            raise ValueError(f"Unknown Avalon work mode: {option}")

        await self._api_client.set_workmode(level)
        await self.coordinator.async_request_refresh()


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
        avalon_username: str | None = None,
        avalon_password: str | None = None,
    ) -> None:
        """Initialize pool profile selector."""
        super().__init__(coordinator)
        self._api_client = api_client
        self._miner_type = miner_type
        self._device_name = device_name
        self._device_slug = device_slug
        self._avalon_username = avalon_username
        self._avalon_password = avalon_password

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
            avalon_username=self._avalon_username,
            avalon_password=self._avalon_password,
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


class GoldshellPowerModeSelectEntity(CoordinatorEntity, SelectEntity):
    """Select Goldshell shared power mode."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BitaxeDataUpdateCoordinator,
        api_client: Any,
        device_name: str,
        device_slug: str,
        setting: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._api_client = api_client
        self._device_name = device_name
        self._device_slug = device_slug
        self._option_to_level = self._build_options(setting)
        if not self._option_to_level:
            self._option_to_level = dict(GOLDSHELL_DEFAULT_POWER_OPTIONS)
        self._level_to_option = {level: option for option, level in self._option_to_level.items()}

        self._attr_name = "Power Mode"
        self._attr_unique_id = f"goldshell_{device_slug}_power_mode"
        self._attr_icon = "mdi:flash-outline"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_options = [GOLDSHELL_PAUSED_OPTION, *self._option_to_level.keys()]
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"goldshell_{device_slug}")},
            "name": self._device_name,
            "manufacturer": "Goldshell",
            "model": "Goldshell Byte",
        }

    @staticmethod
    def _build_options(setting: dict[str, Any]) -> dict[str, int]:
        cpbs = setting.get("cpbs") if isinstance(setting, dict) else None
        if not isinstance(cpbs, list):
            return {}

        level_labels: dict[int, str] = {}
        shared_levels: set[int] | None = None

        for board in cpbs:
            if not isinstance(board, dict):
                continue

            modes = board.get("mode")
            if not isinstance(modes, list) or not modes:
                continue
            mode_index = int(board.get("algo_select", 0) or 0)
            if mode_index < 0 or mode_index >= len(modes):
                mode_index = 0
            mode_data = modes[mode_index]
            if not isinstance(mode_data, dict):
                continue

            powerplans = mode_data.get("powerplans")
            if not isinstance(powerplans, list):
                continue

            board_levels: set[int] = set()
            for plan in powerplans:
                if not isinstance(plan, dict):
                    continue
                try:
                    level = int(plan.get("level"))
                except (TypeError, ValueError):
                    continue

                board_levels.add(level)
                if level not in level_labels:
                    label = GOLDSHELL_POWER_LEVEL_NAMES.get(level, f"Level {level}")
                    level_labels[level] = label

            if shared_levels is None:
                shared_levels = board_levels
            else:
                shared_levels &= board_levels

        if not level_labels:
            return {}

        selectable_levels = shared_levels if shared_levels else set(level_labels.keys())
        options: dict[str, int] = {}
        for level in sorted(selectable_levels):
            options[level_labels[level]] = level
        return options

    @property
    def current_option(self) -> str | None:
        """Return currently selected shared power mode option from live miner data."""
        info = self.coordinator.data.get("info", {}) if self.coordinator.data else {}
        if bool(info.get("idle_mode", False)):
            return GOLDSHELL_PAUSED_OPTION

        minfos = info.get("minfos") if isinstance(info, dict) else None
        if isinstance(minfos, list) and minfos:
            detected_levels: list[int] = []
            for board in minfos:
                if not isinstance(board, dict):
                    continue
                infos = board.get("infos")
                if not isinstance(infos, list) or not infos:
                    continue
                board_info = infos[0]
                if not isinstance(board_info, dict):
                    continue
                try:
                    detected_levels.append(int(board_info.get("powerplan")))
                except (TypeError, ValueError):
                    continue

            if detected_levels:
                shared_level = detected_levels[0]
                return self._level_to_option.get(shared_level)
        return None

    async def async_select_option(self, option: str) -> None:
        """Set selected shared power mode for all Goldshell cards."""
        if option == GOLDSHELL_PAUSED_OPTION:
            await self._api_client.set_goldshell_idle_mode(True)
            if self.coordinator.data and isinstance(self.coordinator.data.get("info"), dict):
                self.coordinator.data["info"]["idle_mode"] = True
            await self.coordinator.async_request_refresh()
            return

        level = self._option_to_level.get(option)
        if level is None:
            raise ValueError(f"Unknown Goldshell power mode option: {option}")

        # Ensure idle mode is off before applying a power profile.
        await self._api_client.set_goldshell_idle_mode(False)
        if self.coordinator.data and isinstance(self.coordinator.data.get("info"), dict):
            self.coordinator.data["info"]["idle_mode"] = False
        await self._api_client.set_goldshell_power_mode(level)
        await self.coordinator.async_request_refresh()
