"""Sensor platform for Matter Monitor."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MatterMonitorCoordinator
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Matter Monitor sensors."""
    coordinator: MatterMonitorCoordinator = entry.runtime_data
    async_add_entities([
        MatterDeviceCountSensor(coordinator, entry),
        MatterOnlineSensor(coordinator, entry),
        MatterOfflineSensor(coordinator, entry),
    ])


class MatterMonitorBaseSensor(CoordinatorEntity[MatterMonitorCoordinator], SensorEntity):
    """Base class for Matter Monitor sensors."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: MatterMonitorCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Matter Monitor",
            "manufacturer": "Matter Monitor",
            "model": "Matter Device Monitor",
            "sw_version": "0.1.0",
        }


class MatterDeviceCountSensor(MatterMonitorBaseSensor):
    """Sensor showing total Matter device count with details as attributes."""

    _attr_name = "Devices"
    _attr_icon = "mdi:devices"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "devices"

    def __init__(
        self, coordinator: MatterMonitorCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_device_count"

    @property
    def native_value(self) -> int | None:
        """Return total device count."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("total", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return device details as attributes."""
        if self.coordinator.data is None:
            return {}

        data = self.coordinator.data
        nodes = data.get("nodes", [])

        # Build a summary list for attributes
        device_list = []
        for node in nodes:
            entry = {
                "node_id": node["node_id"],
                "name": node.get("node_label") or node.get("product_name") or f"Node {node['node_id']}",
                "status": "online" if node["available"] else "offline",
                "vendor": node.get("vendor_name", ""),
                "product": node.get("product_name", ""),
                "power": node.get("power_source", "unknown"),
            }
            if node.get("battery_percent") is not None:
                entry["battery"] = node["battery_percent"]
            device_list.append(entry)

        return {
            "online": data.get("online", 0),
            "offline": data.get("offline", 0),
            "devices": device_list,
        }


class MatterOnlineSensor(MatterMonitorBaseSensor):
    """Sensor showing online Matter device count."""

    _attr_name = "Online"
    _attr_icon = "mdi:check-network"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "devices"

    def __init__(
        self, coordinator: MatterMonitorCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_online"

    @property
    def native_value(self) -> int | None:
        """Return online device count."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("online", 0)


class MatterOfflineSensor(MatterMonitorBaseSensor):
    """Sensor showing offline Matter device count."""

    _attr_name = "Offline"
    _attr_icon = "mdi:close-network"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "devices"

    def __init__(
        self, coordinator: MatterMonitorCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_offline"

    @property
    def native_value(self) -> int | None:
        """Return offline device count."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("offline", 0)
