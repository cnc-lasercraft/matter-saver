"""Matter Monitor - Custom Component for Home Assistant."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_MATTER_URL,
    DEFAULT_MATTER_URL,
    DOMAIN,
    SCAN_INTERVAL_SECONDS,
)

from datetime import timedelta

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

type MatterMonitorConfigEntry = ConfigEntry[MatterMonitorCoordinator]


class MatterMonitorCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to fetch data from Matter Server WebSocket API."""

    def __init__(self, hass: HomeAssistant, url: str) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.url = url

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Matter Server."""
        try:
            return await self._fetch_matter_nodes()
        except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError) as err:
            raise UpdateFailed(f"Error communicating with Matter Server: {err}") from err

    async def _fetch_matter_nodes(self) -> dict[str, Any]:
        """Connect to Matter Server WebSocket and get all nodes."""
        session = aiohttp.ClientSession()
        try:
            async with session.ws_connect(self.url, timeout=10) as ws:
                # Matter Server expects JSON-RPC messages
                # First, get all nodes
                request = {
                    "message_id": "1",
                    "command": "get_nodes",
                }
                await ws.send_json(request)

                # Read response
                msg = await asyncio.wait_for(ws.receive(), timeout=15)
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    return self._parse_nodes(data)

                raise UpdateFailed(f"Unexpected WebSocket message type: {msg.type}")
        finally:
            await session.close()

    def _parse_nodes(self, data: Any) -> dict[str, Any]:
        """Parse the Matter Server response into structured data."""
        nodes = []
        raw_nodes = []

        # Matter Server returns result in different formats depending on version
        if isinstance(data, dict):
            raw_nodes = data.get("result", data.get("nodes", []))
        elif isinstance(data, list):
            raw_nodes = data

        if not isinstance(raw_nodes, list):
            raw_nodes = []

        online_count = 0
        offline_count = 0

        for node in raw_nodes:
            if not isinstance(node, dict):
                continue

            node_id = node.get("node_id")
            available = node.get("available", False)

            # Extract basic info from node attributes
            attributes = node.get("attributes", {})
            node_info = {
                "node_id": node_id,
                "available": available,
                "vendor_name": self._get_attribute(attributes, "basicInformation", "vendorName", ""),
                "product_name": self._get_attribute(attributes, "basicInformation", "productName", ""),
                "node_label": self._get_attribute(attributes, "basicInformation", "nodeLabel", ""),
                "serial_number": self._get_attribute(attributes, "basicInformation", "serialNumber", ""),
                "software_version_string": self._get_attribute(
                    attributes, "basicInformation", "softwareVersionString", ""
                ),
                "date_commissioned": node.get("date_commissioned", ""),
                "last_interview": node.get("last_interview", ""),
            }

            # Try to get battery level
            battery_percent = self._get_attribute(
                attributes, "powerSource", "batPercentRemaining", None
            )
            if battery_percent is not None:
                # Matter reports battery as 0-200 (2x percentage)
                node_info["battery_percent"] = battery_percent / 2
                node_info["power_source"] = "battery"
            else:
                node_info["battery_percent"] = None
                node_info["power_source"] = "wired"

            if available:
                online_count += 1
            else:
                offline_count += 1

            nodes.append(node_info)

        # Sort: offline first, then by node_id
        nodes.sort(key=lambda n: (n["available"], n["node_id"] or 0))

        return {
            "nodes": nodes,
            "total": len(nodes),
            "online": online_count,
            "offline": offline_count,
        }

    @staticmethod
    def _get_attribute(
        attributes: dict, cluster: str, attribute: str, default: Any
    ) -> Any:
        """Extract a Matter attribute value from the attributes dict.

        Matter Server stores attributes in various formats. This tries
        common patterns to find the value.
        """
        # Pattern 1: flat dict with "cluster/attribute" keys
        for key, value in attributes.items():
            key_str = str(key)
            if cluster.lower() in key_str.lower() and attribute.lower() in key_str.lower():
                return value

        # Pattern 2: nested dict
        if cluster in attributes:
            cluster_data = attributes[cluster]
            if isinstance(cluster_data, dict) and attribute in cluster_data:
                return cluster_data[attribute]

        return default


async def async_setup_entry(hass: HomeAssistant, entry: MatterMonitorConfigEntry) -> bool:
    """Set up Matter Monitor from a config entry."""
    url = entry.data.get(CONF_MATTER_URL, DEFAULT_MATTER_URL)

    coordinator = MatterMonitorCoordinator(hass, url)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MatterMonitorConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
