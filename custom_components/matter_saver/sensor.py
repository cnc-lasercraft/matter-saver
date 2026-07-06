"""Sensor platform for Matter Saver."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import MatterSaverCoordinator
from .const import DOMAIN, get_integration_version, get_repository_url

ROLE_TO_CODE = {
    "leader": "l",
    "router": "r",
    "reed": "re",
    "end_device": "e",
    "sed": "s",
    "unassigned": "ua",
    "unspecified": "us",
    "unknown": "u",
}

POWER_TO_CODE = {
    "battery": "b",
    "wired": "w",
    "unknown": "u",
}


def _node_name(node: dict[str, Any]) -> str:
    """Return the preferred display name for a Matter node."""
    return (
        node.get("device_name")
        or node.get("node_label")
        or node.get("product_name")
        or f"Node {node['node_id']}"
    )


def _encode_route_path(route_path: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact route path payload for Lovelace cards."""
    compact_path: list[dict[str, Any]] = []
    for hop in route_path:
        compact_hop = {"i": hop.get("node_id")}
        if hop.get("rssi") is not None:
            compact_hop["rs"] = hop["rssi"]
        if hop.get("lqi") is not None:
            compact_hop["lq"] = hop["lqi"]
        compact_path.append(compact_hop)
    return compact_path


def _encode_device(node: dict[str, Any]) -> dict[str, Any]:
    """Compact device payload to keep state attributes small."""
    encoded: dict[str, Any] = {
        "i": node["node_id"],
        "n": _node_name(node),
        "av": node.get("available", False),
        "r": ROLE_TO_CODE.get(node.get("thread_role", "unknown"), "u"),
    }

    optional_fields = (
        ("a", node.get("area")),
        ("fl", node.get("floor")),
        ("p", node.get("product_name")),
        ("v", node.get("vendor_name")),
        ("nl", node.get("node_label")),
        ("sn", node.get("serial_number")),
        ("f", node.get("software_version_string")),
        ("m", node.get("error_comment")),
        ("mc", node.get("error_comment_codes")),
        ("pn", node.get("parent_name")),
        ("ls", node.get("last_seen")),
        ("dc", node.get("date_commissioned")),
        ("li", node.get("last_interview")),
    )
    for key, value in optional_fields:
        if value:
            encoded[key] = value

    if node.get("power_source"):
        encoded["w"] = POWER_TO_CODE.get(node["power_source"], "u")
    if node.get("update_available"):
        encoded["u"] = True
    if node.get("neighbors"):
        encoded["k"] = node["neighbors"]
    if node.get("children"):
        encoded["ch"] = node["children"]
    if node.get("errors"):
        encoded["e"] = node["errors"]
    if node.get("parent_node_id") is not None:
        encoded["pi"] = node["parent_node_id"]
    if node.get("route_path"):
        encoded["rt"] = _encode_route_path(node["route_path"])
    if node.get("tx_retries"):
        encoded["tr"] = node["tx_retries"]
    if node.get("offline_24h_count"):
        encoded["c24"] = node["offline_24h_count"]
    if node.get("offline_24h_minutes"):
        encoded["m24"] = node["offline_24h_minutes"]
    if node.get("offline_7d_count"):
        encoded["c7"] = node["offline_7d_count"]
    if node.get("offline_7d_minutes"):
        encoded["m7"] = node["offline_7d_minutes"]
    if node.get("offline_30d_count"):
        encoded["c30"] = node["offline_30d_count"]
    if node.get("offline_30d_minutes"):
        encoded["m30"] = node["offline_30d_minutes"]
    if node.get("battery_percent") is not None:
        encoded["b"] = round(node["battery_percent"], 1)
    if node.get("signal_rssi") is not None:
        encoded["sr"] = node["signal_rssi"]
    if node.get("signal_lqi") is not None:
        encoded["sq"] = node["signal_lqi"]
    if node.get("device_type_ids"):
        encoded["dt"] = node["device_type_ids"]

    return encoded


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

    # Per-node diagnostic sensors are created dynamically as nodes appear and
    # are mapped to their core Matter device. Track which nodes already have
    # entities so refreshes only add the newly seen ones.
    known_nodes: set[int] = set()

    @callback
    def _async_add_node_sensors() -> None:
        """Add per-node diagnostic sensors for newly seen Matter nodes."""
        if coordinator.data is None:
            return
        new_entities: list[SensorEntity] = []
        for node in coordinator.data.get("nodes", []):
            node_id = node.get("node_id")
            if node_id is None or node_id in known_nodes:
                continue
            matter_identifier = node.get("matter_identifier")
            if not matter_identifier:
                # Not yet mapped to a core Matter device (e.g. startup light
                # parse). Skip for now; a later refresh will pick it up.
                continue
            known_nodes.add(node_id)
            new_entities.append(
                MatterNodeLastInterviewSensor(
                    coordinator, entry, node_id, matter_identifier
                )
            )
            new_entities.append(
                MatterNodeInterviewVersionSensor(
                    coordinator, entry, node_id, matter_identifier
                )
            )
        if new_entities:
            async_add_entities(new_entities)

    _async_add_node_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_node_sensors))


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
            "sw_version": get_integration_version(),
            "configuration_url": get_repository_url(),
        }


class MatterDeviceCountSensor(MatterSaverBaseSensor):
    """Sensor showing total Matter device count with details as attributes."""

    _attr_name = "Devices"
    _attr_icon = "mdi:devices"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "devices"
    _unrecorded_attributes = frozenset({"devices", "border_routers"})

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

        return {
            "online": data.get("online", 0),
            "offline": data.get("offline", 0),
            "devices": [_encode_device(node) for node in nodes],
            "border_routers": data.get("border_routers", []),
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
    # Exclude high-cardinality device names from recorder history.
    _unrecorded_attributes = frozenset({"device_names"})

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

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return offline device names for notifications/automations."""
        if self.coordinator.data is None:
            return {"device_names": []}

        nodes = self.coordinator.data.get("nodes", [])
        return {
            "device_names": [
                _node_name(node) for node in nodes if not node.get("available", False)
            ],
        }


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


class MatterNodeDiagnosticSensor(
    CoordinatorEntity[MatterSaverCoordinator], SensorEntity
):
    """Base class for per-node diagnostic sensors.

    Unlike the aggregate hub sensors, each of these binds to the node's own
    core Matter device (via the Matter integration's device identifier) so the
    entity is grouped under the real device and inherits its friendly name.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: MatterSaverCoordinator,
        entry: ConfigEntry,
        node_id: int,
        matter_identifier: tuple[str, str],
    ) -> None:
        """Initialize the per-node sensor bound to its core Matter device."""
        super().__init__(coordinator)
        self._entry = entry
        self._node_id = node_id
        # Link to the existing Matter device; do not set name/manufacturer so
        # we attach to it rather than trying to redefine it.
        self._attr_device_info = {"identifiers": {tuple(matter_identifier)}}

    def _node(self) -> dict[str, Any] | None:
        """Return this node's current coordinator dict, if still present."""
        if self.coordinator.data is None:
            return None
        for node in self.coordinator.data.get("nodes", []):
            if node.get("node_id") == self._node_id:
                return node
        return None


class MatterNodeLastInterviewSensor(MatterNodeDiagnosticSensor):
    """Timestamp of the node's last completed Matter interview."""

    _attr_name = "Last Interview"
    _attr_icon = "mdi:calendar-clock"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: MatterSaverCoordinator,
        entry: ConfigEntry,
        node_id: int,
        matter_identifier: tuple[str, str],
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, entry, node_id, matter_identifier)
        self._attr_unique_id = f"{entry.entry_id}_{node_id}_last_interview"

    @property
    def native_value(self) -> datetime | None:
        """Return the last-interview time as a timezone-aware datetime."""
        node = self._node()
        if node is None:
            return None
        raw = node.get("last_interview")
        if not raw:
            return None
        parsed = raw if isinstance(raw, datetime) else dt_util.parse_datetime(str(raw))
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            # Matter Server reports naive UTC timestamps; make them tz-aware
            # so Home Assistant can do time-math in templates/automations.
            parsed = parsed.replace(tzinfo=dt_util.UTC)
        return parsed


class MatterNodeInterviewVersionSensor(MatterNodeDiagnosticSensor):
    """Interview schema version the node was last interviewed under."""

    _attr_name = "Interview Version"
    _attr_icon = "mdi:counter"

    def __init__(
        self,
        coordinator: MatterSaverCoordinator,
        entry: ConfigEntry,
        node_id: int,
        matter_identifier: tuple[str, str],
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, entry, node_id, matter_identifier)
        self._attr_unique_id = f"{entry.entry_id}_{node_id}_interview_version"

    @property
    def native_value(self) -> int | None:
        """Return the node's interview schema version."""
        node = self._node()
        if node is None:
            return None
        version = node.get("interview_version")
        if version is None:
            return None
        try:
            return int(version)
        except (TypeError, ValueError):
            return None
