"""Sensor platform for Matter Saver."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MatterSaverCoordinator
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Matter Saver sensors."""
    coordinator: MatterSaverCoordinator = entry.runtime_data
    async_add_entities([
        MatterDeviceCountSensor(coordinator, entry),
        MatterOnlineSensor(coordinator, entry),
        MatterOfflineSensor(coordinator, entry),
        MatterActivityLogSensor(coordinator, entry),
    ])


class MatterSaverBaseSensor(CoordinatorEntity[MatterSaverCoordinator], SensorEntity):
    """Base class for Matter Saver sensors."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: MatterSaverCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Matter Saver",
            "manufacturer": "Matter Saver",
            "model": "Matter Device Monitor",
            "sw_version": "0.1.0",
        }


class MatterDeviceCountSensor(MatterSaverBaseSensor):
    """Sensor showing total Matter device count with details as attributes."""

    _attr_name = "Devices"
    _attr_icon = "mdi:devices"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "devices"
    _unrecorded_attributes = frozenset({"devices"})

    def __init__(
        self, coordinator: MatterSaverCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_device_count"

    @property
    def native_value(self) -> int:
        """Return total device count."""
        if self.coordinator.data is None:
            return 0
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
                "name": node.get("device_name") or node.get("node_label") or node.get("product_name") or f"Node {node['node_id']}",
                "area": node.get("area", ""),
                "product": node.get("product_name", ""),
                "status": "online" if node["available"] else "offline",
                "power": node.get("power_source", "unknown"),
                "firmware": node.get("software_version_string", ""),
                "update_available": node.get("update_available", False),
                "thread_role": node.get("thread_role", "unknown"),
                "neighbors": node.get("neighbors", 0),
                "children": node.get("children", 0),
                "errors": node.get("errors", 0),
                "error_comment": node.get("error_comment", ""),
                "parent": node.get("parent_name", ""),
                "parent_node_id": node.get("parent_node_id"),
                "route_path": node.get("route_path", []),
                "offline_7d_count": node.get("offline_7d_count", 0),
                "offline_7d_minutes": node.get("offline_7d_minutes", 0),
                "offline_30d_count": node.get("offline_30d_count", 0),
                "offline_30d_minutes": node.get("offline_30d_minutes", 0),
                "last_seen": node.get("last_seen", ""),
            }
            if node.get("battery_percent") is not None:
                entry["battery"] = node["battery_percent"]
            device_list.append(entry)

        return {
            "online": data.get("online", 0),
            "offline": data.get("offline", 0),
            "devices": device_list,
        }


class MatterOnlineSensor(MatterSaverBaseSensor):
    """Sensor showing online Matter device count."""

    _attr_name = "Online"
    _attr_icon = "mdi:check-network"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "devices"

    def __init__(
        self, coordinator: MatterSaverCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_online"

    @property
    def native_value(self) -> int:
        """Return online device count."""
        if self.coordinator.data is None:
            return 0
        return self.coordinator.data.get("online", 0)


class MatterOfflineSensor(MatterSaverBaseSensor):
    """Sensor showing offline Matter device count."""

    _attr_name = "Offline"
    _attr_icon = "mdi:close-network"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "devices"

    def __init__(
        self, coordinator: MatterSaverCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_offline"

    @property
    def native_value(self) -> int:
        """Return offline device count."""
        if self.coordinator.data is None:
            return 0
        return self.coordinator.data.get("offline", 0)


class MatterActivityLogSensor(MatterSaverBaseSensor):
    """Sensor providing the activity log."""

    _attr_name = "Activity Log"
    _attr_icon = "mdi:text-box-outline"
    _unrecorded_attributes = frozenset({"entries"})

    def __init__(
        self, coordinator: MatterSaverCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_activity_log"

    @property
    def native_value(self) -> int:
        """Return number of log entries."""
        return len(self.coordinator.activity_log)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return log entries."""
        return {
            "entries": self.coordinator.activity_log,
        }
