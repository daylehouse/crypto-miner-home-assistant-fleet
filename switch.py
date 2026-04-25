"""Switch entities for Bitaxe/NerdAxe integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities for Bitaxe/NerdAxe.

    No writable switches are exposed. Remove legacy mining_active switches.
    """
    entity_registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(entity_registry, config_entry.entry_id):
        if registry_entry.domain != "switch":
            continue
        unique_id = registry_entry.unique_id or ""
        if unique_id.endswith("_mining_active"):
            entity_registry.async_remove(registry_entry.entity_id)
