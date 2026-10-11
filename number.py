"""Number entities for Bitaxe/NerdAxe integration."""

from __future__ import annotations

from typing import Any, Callable

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api_client import BitaxeAPIClient
from .coordinator import BitaxeDataUpdateCoordinator
from .const import (
    CONNECTION_TIMEOUT,
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
    CONF_TARGET_TEMP_C,
    CONF_VR_OVERHEAT_THRESHOLD_C,
    DOMAIN,
    MINER_TYPE_BITAXE,
    MINER_TYPE_GOLDSHELL,
    MINER_TYPE_NERDAXE,
    overheat_threshold_profile,
)
from .utils import normalize_identifier


def _api_first_numeric(info: dict[str, Any], keys: tuple[str, ...]) -> float | None:
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


def _api_bitaxe_temperature_target_c(info: dict[str, Any]) -> float | None:
    """Return Bitaxe target temperature from API payload when available."""
    return _api_first_numeric(info, ("temptarget", "tempTarget", "temp_target"))


def _api_nerdaxe_asic_shutdown_temp_c(info: dict[str, Any]) -> float | None:
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


def _api_nerdaxe_vr_shutdown_temp_c(info: dict[str, Any]) -> float | None:
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


def _is_bitaxe_miner(miner_type: str) -> bool:
    """Return True for Bitaxe miners."""
    return miner_type == MINER_TYPE_BITAXE


def _is_nerdaxe_miner(miner_type: str) -> bool:
    """Return True for NerdAxe miners."""
    return miner_type == MINER_TYPE_NERDAXE


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
    runtime_entry = hass.data.get(DOMAIN, {}).get(config_entry.entry_id, {})
    coordinator = runtime_entry.get("coordinator") if isinstance(runtime_entry, dict) else None
    if not isinstance(coordinator, BitaxeDataUpdateCoordinator):
        coordinator = None
    api_client = runtime_entry.get("api_client") if isinstance(runtime_entry, dict) else None
    if not isinstance(api_client, BitaxeAPIClient):
        api_client = None

    bitaxe_target: float | None = None
    nerdaxe_asic_target: float | None = None
    nerdaxe_vr_target: float | None = None
    if (_is_bitaxe_miner(miner_type) or _is_nerdaxe_miner(miner_type)) and coordinator and isinstance(coordinator.data, dict):
        info = coordinator.data.get("info", {})
        if isinstance(info, dict):
            if _is_bitaxe_miner(miner_type):
                bitaxe_target = _api_bitaxe_temperature_target_c(info)
            if _is_nerdaxe_miner(miner_type):
                nerdaxe_asic_target = _api_nerdaxe_asic_shutdown_temp_c(info)
                nerdaxe_vr_target = _api_nerdaxe_vr_shutdown_temp_c(info)

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
                    coordinator,
                    api_client,
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
                    coordinator,
                    api_client,
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
        current_target_value = float(
            config_entry.options.get(
                CONF_TARGET_TEMP_C,
                bitaxe_target if bitaxe_target is not None else default_value,
            )
        )
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

        if nerdaxe_asic_target is not None:
            current_asic_value = float(nerdaxe_asic_target)
        if nerdaxe_vr_target is not None:
            current_vr_value = float(nerdaxe_vr_target)

        if _is_bitaxe_miner(miner_type):
            entities.append(
                BitaxeTargetTemperatureNumber(
                    hass,
                    config_entry,
                    coordinator,
                    api_client,
                    miner_type,
                    device_name,
                    device_slug,
                    CONF_TARGET_TEMP_C,
                    "Target Temperature",
                    current_target_value,
                    min_value,
                    max_value,
                    "mdi:thermometer-check",
                )
            )

        entities.extend(
            [
                BitaxeOverheatThresholdNumber(
                    hass,
                    config_entry,
                    coordinator,
                    api_client,
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
                    coordinator,
                    api_client,
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
        coordinator: BitaxeDataUpdateCoordinator | None,
        api_client: BitaxeAPIClient | None,
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
        self._coordinator = coordinator
        self._api_client = api_client
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
        self._remove_coordinator_listener: Callable[[], None] | None = None

    @property
    def _is_api_backed_target(self) -> bool:
        """Return True when this slider should mirror the miner API target."""
        return (
            _is_nerdaxe_miner(self._miner_type)
            and self._threshold_key in {
            CONF_ASIC_OVERHEAT_THRESHOLD_C,
            CONF_VR_OVERHEAT_THRESHOLD_C,
            }
        )

    def _api_target_from_coordinator(self) -> float | None:
        """Read current target temperature from coordinator cache."""
        if not self._coordinator or not isinstance(self._coordinator.data, dict):
            return None
        info = self._coordinator.data.get("info", {})
        if not isinstance(info, dict):
            return None

        if _is_bitaxe_miner(self._miner_type):
            value = _api_bitaxe_temperature_target_c(info)
        elif _is_nerdaxe_miner(self._miner_type):
            if self._threshold_key == CONF_ASIC_OVERHEAT_THRESHOLD_C:
                value = _api_nerdaxe_asic_shutdown_temp_c(info)
            else:
                value = _api_nerdaxe_vr_shutdown_temp_c(info)
        else:
            value = None

        if value is None:
            return None
        return float(max(self._attr_native_min_value, min(self._attr_native_max_value, value)))

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator updates so API-backed values stay current."""
        await super().async_added_to_hass()
        if not self._coordinator:
            return

        self._remove_coordinator_listener = self._coordinator.async_add_listener(
            self._handle_coordinator_update
        )
        self.async_on_remove(self._remove_coordinator_listener)

    def _handle_coordinator_update(self) -> None:
        """Refresh number state when coordinator data changes."""
        if self._is_api_backed_target:
            api_value = self._api_target_from_coordinator()
            if api_value is not None:
                self._attr_native_value = float(api_value)
        self.async_write_ha_state()


class BitaxeTargetTemperatureNumber(NumberEntity):
    """Bitaxe target temperature slider (Celsius)."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "°C"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        coordinator: BitaxeDataUpdateCoordinator | None,
        api_client: BitaxeAPIClient | None,
        miner_type: str,
        device_name: str,
        device_slug: str,
        target_key: str,
        display_name: str,
        current_value: float,
        min_value: float,
        max_value: float,
        icon: str,
    ) -> None:
        """Initialize the target number entity."""
        self.hass = hass
        self._config_entry = config_entry
        self._entry_id = config_entry.entry_id
        self._coordinator = coordinator
        self._api_client = api_client
        self._miner_type = miner_type
        self._device_name = device_name
        self._device_slug = device_slug
        self._target_key = target_key
        self._attr_name = display_name
        self._attr_icon = icon
        self._attr_native_min_value = float(min_value)
        self._attr_native_max_value = float(max_value)
        self._attr_native_value = float(
            max(self._attr_native_min_value, min(self._attr_native_max_value, current_value))
        )
        self._attr_unique_id = f"{miner_type}_{self._device_slug}_{target_key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{miner_type}_{self._device_slug}")},
            "name": self._device_name,
            "manufacturer": "Bitaxe Project",
            "model": miner_type.capitalize(),
        }
        self._remove_coordinator_listener: Callable[[], None] | None = None

    def _api_target_from_coordinator(self) -> float | None:
        """Read current target temperature from coordinator cache."""
        if not self._coordinator or not isinstance(self._coordinator.data, dict):
            return None
        info = self._coordinator.data.get("info", {})
        if not isinstance(info, dict):
            return None

        value = _api_bitaxe_temperature_target_c(info)
        if value is None:
            return None
        return float(max(self._attr_native_min_value, min(self._attr_native_max_value, value)))

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator updates so API-backed values stay current."""
        await super().async_added_to_hass()
        if not self._coordinator:
            return

        self._remove_coordinator_listener = self._coordinator.async_add_listener(
            self._handle_coordinator_update
        )
        self.async_on_remove(self._remove_coordinator_listener)

    def _handle_coordinator_update(self) -> None:
        """Refresh number state when coordinator data changes."""
        api_value = self._api_target_from_coordinator()
        if api_value is not None:
            self._attr_native_value = float(api_value)
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Set Bitaxe target temperature and persist it in entry options."""
        clamped = max(self._attr_native_min_value, min(self._attr_native_max_value, value))
        self._attr_native_value = float(clamped)

        api_client = self._api_client
        if not isinstance(api_client, BitaxeAPIClient):
            runtime_entry = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
            if isinstance(runtime_entry, dict):
                candidate = runtime_entry.get("api_client")
                if isinstance(candidate, BitaxeAPIClient):
                    api_client = candidate

        if not isinstance(api_client, BitaxeAPIClient):
            raise HomeAssistantError("Miner API client is unavailable")

        try:
            await api_client.set_temperature_target(
                self._attr_native_value,
                timeout=CONNECTION_TIMEOUT,
            )
        except (TimeoutError, ConnectionError, ValueError) as err:
            raise HomeAssistantError(f"Failed to update miner target temperature: {err}") from err

        if self._coordinator and isinstance(self._coordinator.data, dict):
            current_data = dict(self._coordinator.data)
            info = dict(current_data.get("info") or {})
            info["temptarget"] = self._attr_native_value
            current_data["info"] = info
            self._coordinator.async_set_updated_data(current_data)

        current_options = dict(self._config_entry.options)
        current_options[self._target_key] = self._attr_native_value
        self.hass.config_entries.async_update_entry(self._config_entry, options=current_options)

        runtime_entry = self.hass.data.get(DOMAIN, {}).get(self._entry_id)
        if isinstance(runtime_entry, dict):
            runtime_entry[self._target_key] = self._attr_native_value

        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Set the overheat threshold and persist it in entry options."""
        clamped = max(self._attr_native_min_value, min(self._attr_native_max_value, value))
        self._attr_native_value = float(clamped)

        if self._is_api_backed_target:
            api_client = self._api_client
            if not isinstance(api_client, BitaxeAPIClient):
                runtime_entry = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
                if isinstance(runtime_entry, dict):
                    candidate = runtime_entry.get("api_client")
                    if isinstance(candidate, BitaxeAPIClient):
                        api_client = candidate

            if not isinstance(api_client, BitaxeAPIClient):
                raise HomeAssistantError("Miner API client is unavailable")

            try:
                if _is_bitaxe_miner(self._miner_type):
                    await api_client.set_temperature_target(
                        self._attr_native_value,
                        timeout=CONNECTION_TIMEOUT,
                    )
                elif _is_nerdaxe_miner(self._miner_type):
                    if self._threshold_key == CONF_ASIC_OVERHEAT_THRESHOLD_C:
                        await api_client.set_nerdaxe_shutdown_temperatures(
                            asic_shutdown_c=self._attr_native_value,
                            timeout=CONNECTION_TIMEOUT,
                        )
                    else:
                        await api_client.set_nerdaxe_shutdown_temperatures(
                            vr_shutdown_c=self._attr_native_value,
                            timeout=CONNECTION_TIMEOUT,
                        )
                else:
                    raise HomeAssistantError("Unsupported miner type for API-backed threshold")
            except (TimeoutError, ConnectionError, ValueError) as err:
                raise HomeAssistantError(
                    f"Failed to update miner temperature target: {err}"
                ) from err

            if self._coordinator and isinstance(self._coordinator.data, dict):
                current_data = dict(self._coordinator.data)
                info = dict(current_data.get("info") or {})
                if _is_bitaxe_miner(self._miner_type):
                    info["temptarget"] = self._attr_native_value
                elif _is_nerdaxe_miner(self._miner_type):
                    if self._threshold_key == CONF_ASIC_OVERHEAT_THRESHOLD_C:
                        info["overheat_temp"] = self._attr_native_value
                        fans = list(info.get("fans") or [])
                        while len(fans) < 1:
                            fans.append({})
                        if isinstance(fans[0], dict):
                            fan0 = dict(fans[0])
                            fan0["overheatTemp"] = self._attr_native_value
                            fans[0] = fan0
                        info["fans"] = fans
                    else:
                        fans = list(info.get("fans") or [])
                        while len(fans) < 2:
                            fans.append({})
                        if isinstance(fans[1], dict):
                            fan1 = dict(fans[1])
                            fan1["overheatTemp"] = self._attr_native_value
                            fans[1] = fan1
                        info["fans"] = fans
                current_data["info"] = info
                self._coordinator.async_set_updated_data(current_data)

        current_options = dict(self._config_entry.options)
        if self._is_api_backed_target:
            if _is_bitaxe_miner(self._miner_type):
                current_options[CONF_ASIC_OVERHEAT_THRESHOLD_C] = self._attr_native_value
                current_options[CONF_VR_OVERHEAT_THRESHOLD_C] = self._attr_native_value
                current_options[CONF_OVERHEAT_THRESHOLD_C] = self._attr_native_value
            else:
                current_options[self._threshold_key] = self._attr_native_value
                if self._threshold_key == CONF_ASIC_OVERHEAT_THRESHOLD_C:
                    current_options[CONF_OVERHEAT_THRESHOLD_C] = self._attr_native_value
        else:
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
            if self._is_api_backed_target:
                if _is_bitaxe_miner(self._miner_type):
                    runtime_entry[CONF_ASIC_OVERHEAT_THRESHOLD_C] = self._attr_native_value
                    runtime_entry[CONF_VR_OVERHEAT_THRESHOLD_C] = self._attr_native_value
                    runtime_entry[CONF_OVERHEAT_THRESHOLD_C] = self._attr_native_value
                else:
                    runtime_entry[self._threshold_key] = self._attr_native_value
                    if self._threshold_key == CONF_ASIC_OVERHEAT_THRESHOLD_C:
                        runtime_entry[CONF_OVERHEAT_THRESHOLD_C] = self._attr_native_value
            else:
                runtime_entry[self._threshold_key] = self._attr_native_value
                if self._threshold_key == CONF_ASIC_OVERHEAT_THRESHOLD_C:
                    runtime_entry[CONF_OVERHEAT_THRESHOLD_C] = self._attr_native_value
                if self._threshold_key == CONF_GOLDSHELL_ALEO_OVERHEAT_THRESHOLD_C:
                    runtime_entry[CONF_GOLDSHELL_TEMP1_OVERHEAT_THRESHOLD_C] = self._attr_native_value
                if self._threshold_key == CONF_GOLDSHELL_LTC_OVERHEAT_THRESHOLD_C:
                    runtime_entry[CONF_GOLDSHELL_TEMP2_OVERHEAT_THRESHOLD_C] = self._attr_native_value

        self.async_write_ha_state()
