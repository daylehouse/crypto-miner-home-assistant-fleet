"""Button entities for Bitaxe/NerdAxe integration."""

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DEVICE_NAME,
    CONF_DEVICE_SLUG,
    CONF_HOST,
    CONF_MINER_TYPE,
    DOMAIN,
)
from .coordinator import BitaxeDataUpdateCoordinator
from .utils import normalize_identifier

_LOGGER = logging.getLogger(__name__)


class BitaxeButtonEntityDescription(ButtonEntityDescription):
    """Bitaxe button entity description."""

    action_fn: callable = None


BITAXE_BUTTONS = [
    BitaxeButtonEntityDescription(
        key="restart",
        name="Restart",
        entity_category=EntityCategory.CONFIG,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities for Bitaxe/NerdAxe."""
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

    entities = [
        BitaxeButtonEntity(
            coordinator,
            api_client,
            host,
            miner_type,
            device_name,
            device_slug,
            button_description,
        )
        for button_description in BITAXE_BUTTONS
    ]

    async_add_entities(entities)


class BitaxeButtonEntity(CoordinatorEntity, ButtonEntity):
    """Representation of a Bitaxe button."""

    entity_description: BitaxeButtonEntityDescription

    def __init__(
        self,
        coordinator: BitaxeDataUpdateCoordinator,
        api_client: Any,
        host: str,
        miner_type: str,
        device_name: str,
        device_slug: str,
        button_description: BitaxeButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.entity_description = button_description
        self._api_client = api_client
        self._host = host
        self._miner_type = miner_type
        self._device_name = device_name
        self._device_slug = device_slug
        self._attr_unique_id = f"{miner_type}_{self._device_slug}_{button_description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{miner_type}_{self._device_slug}")},
            "name": self._device_name,
            "manufacturer": "Bitaxe Project",
            "model": miner_type.capitalize(),
        }

    async def async_press(self) -> None:
        """Handle button press."""
        if self.entity_description.key == "restart":
            try:
                await self._api_client.restart_system()
                _LOGGER.info(f"Restart initiated for {self._host}")
            except Exception as e:
                _LOGGER.error(f"Failed to restart {self._host}: {e}")
                raise
