"""Number entities for Bitaxe/NerdAxe integration."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ASIC_OVERHEAT_THRESHOLD_C,
    CONF_DEVICE_NAME,
    CONF_DEVICE_SLUG,
    CONF_GOLDSHELL_ALEO_OVERHEAT_THRESHOLD_C,
    CONF_GOLDSHELL_LTC_OVERHEAT_THRESHOLD_C,
    CONF_GOLDSHELL_TEMP1_OVERHEAT_THRESHOLD_C,
    CONF_GOLDSHELL_TEMP2_OVERHEAT_THRESHOLD_C,
    CONF_HOST,
    CONF_MINER_TYPE,
    CONF_OVERHEAT_THRESHOLD_C,
    CONF_VR_OVERHEAT_THRESHOLD_C,
    DOMAIN,
    MINER_TYPE_GOLDSHELL,
    overheat_threshold_profile,
)
from .utils import normalize_identifier


def _cleanup_legacy_goldshell_number_entities(hass: HomeAssistant, entry_id: str) -> None:
    """Remove stale Goldshell number entities using legacy Temp1/Temp2 keys."""
    entity_registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(entity_registry, entry_id):
        if registry_entry.domain != "number":
            continue
        unique_id = registry_entry.unique_id or ""
        if unique_id.endswith(f"_{CONF_GOLDSHELL_TEMP1_OVERHEAT_THRESHOLD_C}") or unique_id.endswith(
            f"_{CONF_GOLDSHELL_TEMP2_OVERHEAT_THRESHOLD_C}"
        ):
            entity_registry.async_remove(registry_entry.entity_id)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities for Bitaxe/NerdAxe."""
    host = config_entry.data[CONF_HOST]
    miner_type = config_entry.data[CONF_MINER_TYPE]
    device_name = config_entry.data.get(
        CONF_DEVICE_NAME, f"{miner_type.capitalize()} {host}"
    )
    device_slug = config_entry.data.get(CONF_DEVICE_SLUG, normalize_identifier(host))

    min_value, max_value, default_value = overheat_threshold_profile(miner_type)
    entities: list[BitaxeOverheatThresholdNumber] = []

    if miner_type == MINER_TYPE_GOLDSHELL:
        _cleanup_legacy_goldshell_number_entities(hass, config_entry.entry_id)

        current_temp1_value = float(
            config_entry.options.get(
                CONF_GOLDSHELL_ALEO_OVERHEAT_THRESHOLD_C,
                config_entry.options.get(
                    CONF_GOLDSHELL_TEMP1_OVERHEAT_THRESHOLD_C,
                    config_entry.options.get(
                        CONF_ASIC_OVERHEAT_THRESHOLD_C,
                        config_entry.options.get(
                            CONF_OVERHEAT_THRESHOLD_C,
                            default_value,
                        ),
                    ),
                ),
            )
        )
        current_temp2_value = float(
            config_entry.options.get(
                CONF_GOLDSHELL_LTC_OVERHEAT_THRESHOLD_C,
                config_entry.options.get(
                    CONF_GOLDSHELL_TEMP2_OVERHEAT_THRESHOLD_C,
                    config_entry.options.get(
                        CONF_VR_OVERHEAT_THRESHOLD_C,
                        default_value,
                    ),
                ),
            )
        )

        entities.extend(
            [
                BitaxeOverheatThresholdNumber(
                    hass,
                    config_entry,
                    miner_type,
                    device_name,
                    device_slug,
                    CONF_GOLDSHELL_ALEO_OVERHEAT_THRESHOLD_C,
                    "ALEO Overheat Alert Threshold",
                    current_temp1_value,
                    min_value,
                    max_value,
                    "mdi:thermometer-high",
                ),
                BitaxeOverheatThresholdNumber(
                    hass,
                    config_entry,
                    miner_type,
                    device_name,
                    device_slug,
                    CONF_GOLDSHELL_LTC_OVERHEAT_THRESHOLD_C,
                    "LTC Overheat Alert Threshold",
                    current_temp2_value,
                    min_value,
                    max_value,
                    "mdi:thermometer",
                ),
            ]
        )
    else:
        current_asic_value = float(
            config_entry.options.get(
                CONF_ASIC_OVERHEAT_THRESHOLD_C,
                config_entry.options.get(
                    CONF_OVERHEAT_THRESHOLD_C,
                    default_value,
                ),
            )
        )
        current_vr_value = float(
            config_entry.options.get(
                CONF_VR_OVERHEAT_THRESHOLD_C,
                default_value,
            )
        )

        entities.extend(
            [
                BitaxeOverheatThresholdNumber(
                    hass,
                    config_entry,
                    miner_type,
                    device_name,
                    device_slug,
                    CONF_ASIC_OVERHEAT_THRESHOLD_C,
                    "ASIC Overheat Alert Threshold",
                    current_asic_value,
                    min_value,
                    max_value,
                    "mdi:chip",
                ),
                BitaxeOverheatThresholdNumber(
                    hass,
                    config_entry,
                    miner_type,
                    device_name,
                    device_slug,
                    CONF_VR_OVERHEAT_THRESHOLD_C,
                    "VR Overheat Alert Threshold",
                    current_vr_value,
                    min_value,
                    max_value,
                    "mdi:thermometer-lines",
                ),
            ]
        )

    async_add_entities(entities)


class BitaxeOverheatThresholdNumber(NumberEntity):
    """Per-miner overheat threshold slider (Celsius)."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "°C"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        miner_type: str,
        device_name: str,
        device_slug: str,
        threshold_key: str,
        display_name: str,
        current_value: float,
        min_value: float,
        max_value: float,
        icon: str,
    ) -> None:
        """Initialize the threshold number entity."""
        self.hass = hass
        self._config_entry = config_entry
        self._entry_id = config_entry.entry_id
        self._miner_type = miner_type
        self._device_name = device_name
        self._device_slug = device_slug
        self._threshold_key = threshold_key
        self._attr_name = display_name
        self._attr_icon = icon
        self._attr_native_min_value = float(min_value)
        self._attr_native_max_value = float(max_value)
        self._attr_native_value = float(
            max(self._attr_native_min_value, min(self._attr_native_max_value, current_value))
        )
        self._attr_unique_id = f"{miner_type}_{self._device_slug}_{threshold_key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{miner_type}_{self._device_slug}")},
            "name": self._device_name,
            "manufacturer": "Bitaxe Project",
            "model": miner_type.capitalize(),
        }

    async def async_set_native_value(self, value: float) -> None:
        """Set the overheat threshold and persist it in entry options."""
        clamped = max(self._attr_native_min_value, min(self._attr_native_max_value, value))
        self._attr_native_value = float(clamped)

        current_options = dict(self._config_entry.options)
        current_options[self._threshold_key] = self._attr_native_value
        if self._threshold_key == CONF_ASIC_OVERHEAT_THRESHOLD_C:
            # Keep legacy option key synchronized for backward compatibility.
            current_options[CONF_OVERHEAT_THRESHOLD_C] = self._attr_native_value
        if self._threshold_key == CONF_GOLDSHELL_ALEO_OVERHEAT_THRESHOLD_C:
            current_options[CONF_GOLDSHELL_TEMP1_OVERHEAT_THRESHOLD_C] = self._attr_native_value
        if self._threshold_key == CONF_GOLDSHELL_LTC_OVERHEAT_THRESHOLD_C:
            current_options[CONF_GOLDSHELL_TEMP2_OVERHEAT_THRESHOLD_C] = self._attr_native_value
        self.hass.config_entries.async_update_entry(self._config_entry, options=current_options)

        runtime_entry = self.hass.data.get(DOMAIN, {}).get(self._entry_id)
        if isinstance(runtime_entry, dict):
            runtime_entry[self._threshold_key] = self._attr_native_value
            if self._threshold_key == CONF_ASIC_OVERHEAT_THRESHOLD_C:
                runtime_entry[CONF_OVERHEAT_THRESHOLD_C] = self._attr_native_value
            if self._threshold_key == CONF_GOLDSHELL_ALEO_OVERHEAT_THRESHOLD_C:
                runtime_entry[CONF_GOLDSHELL_TEMP1_OVERHEAT_THRESHOLD_C] = self._attr_native_value
            if self._threshold_key == CONF_GOLDSHELL_LTC_OVERHEAT_THRESHOLD_C:
                runtime_entry[CONF_GOLDSHELL_TEMP2_OVERHEAT_THRESHOLD_C] = self._attr_native_value

        self.async_write_ha_state()
