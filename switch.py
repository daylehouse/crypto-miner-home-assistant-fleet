"""Switch entities for Bitaxe/NerdAxe integration."""

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DEVICE_NAME,
    CONF_DEVICE_SLUG,
    CONF_MINER_TYPE,
    DOMAIN,
    MINER_TYPE_BITAXE,
    MINER_TYPE_GOLDSHELL,
    MINER_TYPE_NERDAXE,
)
from .coordinator import BitaxeDataUpdateCoordinator
from .utils import bitaxe_mining_active, normalize_identifier

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities for Bitaxe/NerdAxe."""
    entity_registry = er.async_get(hass)
    if config_entry.data.get(CONF_MINER_TYPE) not in (
        MINER_TYPE_BITAXE,
        MINER_TYPE_NERDAXE,
    ):
        for registry_entry in er.async_entries_for_config_entry(entity_registry, config_entry.entry_id):
            if registry_entry.domain != "switch":
                continue
            unique_id = registry_entry.unique_id or ""
            if unique_id.endswith("_mining_active"):
                entity_registry.async_remove(registry_entry.entity_id)

    coordinator: BitaxeDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id][
        "coordinator"
    ]
    api_client = hass.data[DOMAIN][config_entry.entry_id]["api_client"]
    miner_type = config_entry.data.get(CONF_MINER_TYPE)
    device_name = config_entry.data.get(
        CONF_DEVICE_NAME,
        f"{miner_type.capitalize()} {coordinator.host}",
    )
    device_slug = config_entry.data.get(CONF_DEVICE_SLUG, normalize_identifier(coordinator.host))

    entities: list[SwitchEntity] = []
    if miner_type in (MINER_TYPE_BITAXE, MINER_TYPE_NERDAXE):
        entities.append(
            BitaxeMiningActiveSwitchEntity(
                coordinator,
                api_client,
                miner_type,
                device_name,
                device_slug,
            )
        )

    if miner_type == MINER_TYPE_GOLDSHELL:
        entities.append(
            GoldshellIdleModeSwitchEntity(
                coordinator,
                api_client,
                device_name,
                device_slug,
            )
        )

    if entities:
        async_add_entities(entities)


class GoldshellIdleModeSwitchEntity(CoordinatorEntity, SwitchEntity):
    """Switch Goldshell idle mode on/off."""

    _attr_has_entity_name = True

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
        self._attr_name = "Idle Mode"
        self._attr_unique_id = f"goldshell_{device_slug}_idle_mode"
        self._attr_icon = "mdi:sleep"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"goldshell_{device_slug}")},
            "name": self._device_name,
            "manufacturer": "Goldshell",
            "model": "Goldshell Byte",
        }

    @property
    def is_on(self) -> bool:
        """Return True when Goldshell idle mode is enabled."""
        info = self.coordinator.data.get("info", {}) if self.coordinator.data else {}
        return bool(info.get("idle_mode", False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable Goldshell idle mode."""
        await self._api_client.set_goldshell_idle_mode(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable Goldshell idle mode."""
        await self._api_client.set_goldshell_idle_mode(False)
        await self.coordinator.async_request_refresh()


class BitaxeMiningActiveSwitchEntity(CoordinatorEntity, SwitchEntity):
    """Switch mining on/off (Bitaxe pause/resume, NerdAxe shutdown/restart)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BitaxeDataUpdateCoordinator,
        api_client: Any,
        miner_type: str,
        device_name: str,
        device_slug: str,
    ) -> None:
        super().__init__(coordinator)
        self._api_client = api_client
        self._miner_type = miner_type
        self._device_name = device_name
        self._device_slug = device_slug
        self._attr_name = "Mining Active"
        self._attr_unique_id = f"{miner_type}_{device_slug}_mining_active"
        self._attr_icon = "mdi:pickaxe"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{miner_type}_{device_slug}")},
            "name": self._device_name,
            "manufacturer": "Bitaxe Project",
            "model": miner_type.capitalize(),
        }
        self._pending_state: bool | None = None

    @property
    def is_on(self) -> bool:
        """Return True when Bitaxe mining is active."""
        info = self.coordinator.data.get("info", {}) if self.coordinator.data else {}
        if self._pending_state is not None:
            return self._pending_state
        return bitaxe_mining_active(info)

    def _handle_coordinator_update(self) -> None:
        """Refresh state and clear optimistic override once the API catches up."""
        if self._pending_state is not None:
            info = self.coordinator.data.get("info", {}) if self.coordinator.data else {}
            actual_state = bitaxe_mining_active(info)
            if actual_state == self._pending_state:
                self._pending_state = None
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Resume mining (NerdAxe resumes by rebooting)."""
        self._pending_state = True
        try:
            await self._api_client.resume_mining()
            await self.coordinator.async_request_refresh()
        except Exception:
            self._pending_state = None
            raise

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Pause mining (NerdAxe pauses by shutting mining down)."""
        self._pending_state = False
        try:
            await self._api_client.pause_mining()
            await self.coordinator.async_request_refresh()
        except Exception:
            self._pending_state = None
            raise
