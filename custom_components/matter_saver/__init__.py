"""Matter Saver - Custom Component for Home Assistant."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_MATTER_URL,
    DEFAULT_MATTER_URL,
    DOMAIN,
    SCAN_INTERVAL_SECONDS,
)

from datetime import datetime, timedelta, timezone

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

type MatterSaverConfigEntry = ConfigEntry[MatterSaverCoordinator]


class MatterSaverCoordinator(DataUpdateCoordinator[dict[str, Any]]):
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
        self._last_seen: dict[int, str] = {}  # node_id -> ISO timestamp
        self._previous_status: dict[int, bool] = {}  # node_id -> available
        self.activity_log: list[dict[str, Any]] = []
        self.max_log_entries = 200
        self._store = Store(hass, 1, f"{DOMAIN}_data")
        self._store_loaded = False
        # Offline history: node_id -> list of {"start": iso, "end": iso|None, "duration_min": int}
        self.offline_history: dict[int, list[dict[str, Any]]] = {}
        # Auto-recovery
        self.auto_recovery_enabled = True
        self._recovery_task: asyncio.Task | None = None
        self._recovery_interval = 300  # 5 minutes

    async def async_load_log(self) -> None:
        """Load persistent data from storage."""
        data = await self._store.async_load()
        if data and isinstance(data, dict):
            self.activity_log = data.get("entries", [])
            self._last_seen = data.get("last_seen", {})
            self.offline_history = {
                int(k): v for k, v in data.get("offline_history", {}).items()
            }
            self.auto_recovery_enabled = data.get("auto_recovery", True)
        self._store_loaded = True

    async def _async_save_log(self) -> None:
        """Save persistent data to storage."""
        await self._store.async_save({
            "entries": self.activity_log,
            "last_seen": self._last_seen,
            "offline_history": {str(k): v for k, v in self.offline_history.items()},
            "auto_recovery": self.auto_recovery_enabled,
        })

    def add_log(self, level: str, node_id: int | None, name: str,
                message: str) -> None:
        """Add an entry to the activity log."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "node_id": node_id,
            "name": name,
            "message": message,
        }
        self.activity_log.insert(0, entry)
        if len(self.activity_log) > self.max_log_entries:
            self.activity_log = self.activity_log[:self.max_log_entries]
        # Trigger immediate update so log sensor refreshes
        if self.data is not None:
            self.data["activity_log"] = self.activity_log
            self.async_set_updated_data(self.data)
        # Persist to disk
        self.hass.async_create_task(self._async_save_log())

    async def start_auto_recovery(self) -> None:
        """Start the auto-recovery background task."""
        if self._recovery_task is not None:
            self._recovery_task.cancel()
        self._recovery_task = self.hass.async_create_task(self._auto_recovery_loop())

    async def stop_auto_recovery(self) -> None:
        """Stop the auto-recovery background task."""
        if self._recovery_task is not None:
            self._recovery_task.cancel()
            self._recovery_task = None

    async def _auto_recovery_loop(self) -> None:
        """Periodically try to recover offline nodes."""
        while True:
            await asyncio.sleep(self._recovery_interval)
            if not self.auto_recovery_enabled or self.data is None:
                continue
            offline_nodes = [
                n for n in self.data.get("nodes", [])
                if not n["available"]
            ]
            for node in offline_nodes:
                nid = node["node_id"]
                name = node.get("device_name") or f"Node {nid}"
                try:
                    # Try ping first
                    result = await self.send_matter_command(
                        "ping_node", {"node_id": nid}
                    )
                    if isinstance(result, dict) and "error" in result:
                        self.add_log("action", nid, name,
                                     f"Auto-Recovery: Ping fehlgeschlagen")
                        continue
                    self.add_log("action", nid, name,
                                 "Auto-Recovery: Ping OK, starte Re-Interview")
                    # Ping worked, try interview
                    result = await self.send_matter_command(
                        "interview_node", {"node_id": nid}
                    )
                    if isinstance(result, dict) and "error" in result:
                        self.add_log("error", nid, name,
                                     f"Auto-Recovery: Re-Interview fehlgeschlagen")
                    else:
                        self.add_log("success", nid, name,
                                     "Auto-Recovery: Re-Interview erfolgreich")
                        await self.async_request_refresh()
                except Exception:
                    pass  # Don't crash the loop

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Matter Server."""
        try:
            data = await self._fetch_matter_nodes()
        except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError) as err:
            raise UpdateFailed(f"Error communicating with Matter Server: {err}") from err

        # Track status changes + offline history
        now = datetime.now(timezone.utc).isoformat()
        for node in data.get("nodes", []):
            nid = node["node_id"]
            available = node["available"]
            name = node.get("device_name") or f"Node {nid}"
            prev = self._previous_status.get(nid)

            if prev is not None and prev != available:
                if available:
                    self.add_log("info", nid, name, "online")
                    # Close open offline period
                    if nid in self.offline_history:
                        for period in self.offline_history[nid]:
                            if period.get("end") is None:
                                period["end"] = now
                                start = datetime.fromisoformat(period["start"])
                                end = datetime.fromisoformat(now)
                                period["duration_min"] = int((end - start).total_seconds() / 60)
                                break
                else:
                    self.add_log("warning", nid, name, "offline")
                    # Start new offline period
                    if nid not in self.offline_history:
                        self.offline_history[nid] = []
                    self.offline_history[nid].insert(0, {
                        "start": now, "end": None, "duration_min": 0,
                    })
                    # Keep max 50 entries per node
                    self.offline_history[nid] = self.offline_history[nid][:50]

            self._previous_status[nid] = available

        # Build offline stats per node
        for node in data.get("nodes", []):
            nid = node["node_id"]
            history = self.offline_history.get(nid, [])
            now_dt = datetime.now(timezone.utc)
            week_ago = (now_dt - timedelta(days=7)).isoformat()
            month_ago = (now_dt - timedelta(days=30)).isoformat()

            week_events = [h for h in history if h["start"] >= week_ago]
            month_events = [h for h in history if h["start"] >= month_ago]
            week_dur = sum(h.get("duration_min", 0) for h in week_events)
            month_dur = sum(h.get("duration_min", 0) for h in month_events)

            # Check if currently in an open offline period
            if history and history[0].get("end") is None:
                start = datetime.fromisoformat(history[0]["start"])
                week_dur += int((now_dt - start).total_seconds() / 60)
                month_dur += int((now_dt - start).total_seconds() / 60)

            node["offline_7d_count"] = len(week_events)
            node["offline_7d_minutes"] = week_dur
            node["offline_30d_count"] = len(month_events)
            node["offline_30d_minutes"] = month_dur

        data["activity_log"] = self.activity_log
        return data

    async def _fetch_matter_nodes(self) -> dict[str, Any]:
        """Connect to Matter Server WebSocket and get all nodes."""
        session = aiohttp.ClientSession()
        try:
            async with session.ws_connect(self.url, timeout=10) as ws:
                # Matter Server sends server info on connect - read and discard
                await asyncio.wait_for(ws.receive(), timeout=5)

                # Send get_nodes command
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

    def _build_node_device_map(self) -> dict[int, dict[str, str]]:
        """Build a mapping of Matter node_id to HA device info.

        The Matter integration uses identifiers like:
        ("matter", "deviceid_<fabric>-<node_id_hex>-MatterNodeDevice")
        """
        node_map: dict[int, dict[str, Any]] = {}
        dev_reg = dr.async_get(self.hass)
        ent_reg = er.async_get(self.hass)
        area_reg = ar.async_get(self.hass)

        # Build area_id -> area_name lookup
        area_names: dict[str, str] = {}
        for area in area_reg.async_list_areas():
            area_names[area.id] = area.name

        # Build device_id -> update_available lookup
        update_available: dict[str, bool] = {}
        for entity in ent_reg.entities.values():
            if entity.domain == "update" and entity.platform == "matter":
                state = self.hass.states.get(entity.entity_id)
                if state:
                    update_available[entity.device_id] = state.state == "on"

        for device in dev_reg.devices.values():
            for domain, identifier in device.identifiers:
                if domain != "matter":
                    continue
                # Extract node_id hex from identifier string
                # Format: "deviceid_<fabric_hex>-<node_id_hex>-MatterNodeDevice"
                parts = identifier.split("-")
                if len(parts) >= 2:
                    try:
                        node_id = int(parts[1], 16)
                        node_map[node_id] = {
                            "name": device.name_by_user or device.name or "",
                            "area": area_names.get(device.area_id, "") if device.area_id else "",
                            "update_available": update_available.get(device.id, False),
                        }
                    except (ValueError, IndexError):
                        continue
        return node_map

    def _parse_nodes(self, data: Any) -> dict[str, Any]:
        """Parse the Matter Server response into structured data."""
        node_device_map = self._build_node_device_map()
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
            # Matter Server uses "endpoint/cluster/attribute" keys
            # Cluster 40 = BasicInformation: 1=VendorName, 3=ProductName,
            #   5=NodeLabel, 15=SerialNumber, 10=SoftwareVersionString
            # Cluster 47 = PowerSource: 12=BatPercentRemaining
            attributes = node.get("attributes", {})
            device_info = node_device_map.get(node_id, {})
            node_info = {
                "node_id": node_id,
                "device_name": device_info.get("name", ""),
                "area": device_info.get("area", ""),
                "update_available": device_info.get("update_available", False),
                "available": available,
                "vendor_name": self._get_matter_attr(attributes, 40, 1, ""),
                "product_name": self._get_matter_attr(attributes, 40, 3, ""),
                "node_label": self._get_matter_attr(attributes, 40, 5, ""),
                "serial_number": self._get_matter_attr(attributes, 40, 15, ""),
                "software_version_string": self._get_matter_attr(attributes, 40, 10, ""),
                "date_commissioned": node.get("date_commissioned", ""),
                "last_interview": node.get("last_interview", ""),
            }

            # Thread role (cluster 53, attr 1 = RoutingRole)
            # 0=Unspecified, 1=Unassigned, 2=SleepyEndDevice,
            # 3=EndDevice, 4=REED, 5=Router, 6=Leader
            thread_role_map = {
                0: "unspecified", 1: "unassigned", 2: "sed",
                3: "end_device", 4: "reed", 5: "router", 6: "leader",
            }
            thread_role_val = self._get_matter_attr(attributes, 53, 1, None)
            node_info["thread_role"] = thread_role_map.get(thread_role_val, "unknown")

            # Thread neighbor/children count (cluster 53, attr 7 = NeighborTable)
            # Each entry with field '13' = True is a child
            neighbor_table = self._get_matter_attr(attributes, 53, 7, [])
            if isinstance(neighbor_table, list):
                node_info["neighbors"] = len(neighbor_table)
                node_info["children"] = sum(
                    1 for nb in neighbor_table
                    if isinstance(nb, dict) and nb.get("13", False)
                )
            else:
                node_info["neighbors"] = 0
                node_info["children"] = 0

            # Thread error counters (cluster 53)
            tx_retry = self._get_matter_attr(attributes, 53, 25, 0) or 0
            tx_err_cca = self._get_matter_attr(attributes, 53, 28, 0) or 0
            tx_err_abort = self._get_matter_attr(attributes, 53, 29, 0) or 0
            tx_err_busy = self._get_matter_attr(attributes, 53, 30, 0) or 0
            rx_err_no_frame = self._get_matter_attr(attributes, 53, 42, 0) or 0
            rx_err_unknown = self._get_matter_attr(attributes, 53, 43, 0) or 0
            rx_err_invalid = self._get_matter_attr(attributes, 53, 44, 0) or 0
            rx_err_sec = self._get_matter_attr(attributes, 53, 45, 0) or 0
            rx_err_fcs = self._get_matter_attr(attributes, 53, 46, 0) or 0

            total_errors = (tx_err_cca + tx_err_abort + tx_err_busy
                            + rx_err_no_frame + rx_err_unknown
                            + rx_err_invalid + rx_err_sec + rx_err_fcs)
            node_info["errors"] = total_errors
            node_info["tx_retries"] = tx_retry

            # Build error comment
            comments = []
            if tx_err_cca > 10000:
                comments.append("starke Kanalstörungen")
            elif tx_err_cca > 1000:
                comments.append("Kanalstörungen")
            if tx_err_abort > 10000:
                comments.append("viele Sendeabbrüche")
            elif tx_err_abort > 1000:
                comments.append("Sendeabbrüche")
            if rx_err_no_frame > 10000:
                comments.append("Empfangsprobleme")
            elif rx_err_no_frame > 1000:
                comments.append("leichte Empfangsprobleme")
            if rx_err_unknown > 1000:
                comments.append("unbekannte Nachbarn")
            if rx_err_invalid > 1000:
                comments.append("ungültige Quellen")
            if tx_retry > 100000:
                comments.append("sehr schlechte Verbindung")
            elif tx_retry > 10000:
                comments.append("schlechte Verbindung")
            node_info["error_comment"] = ", ".join(comments) if comments else ""

            # Try to get battery level (cluster 47, attr 12)
            battery_percent = self._get_matter_attr(attributes, 47, 12, None)
            if battery_percent is not None:
                # Matter reports battery as 0-200 (2x percentage)
                node_info["battery_percent"] = battery_percent / 2
                node_info["power_source"] = "battery"
            else:
                node_info["battery_percent"] = None
                node_info["power_source"] = "wired"

            # Track last_seen: update when device is available,
            # fallback to last_interview from Matter Server
            if available:
                self._last_seen[node_id] = datetime.now(timezone.utc).isoformat()
                online_count += 1
            else:
                if node_id not in self._last_seen:
                    last_interview = node.get("last_interview", "")
                    if last_interview:
                        self._last_seen[node_id] = last_interview
                offline_count += 1

            # Store Thread topology info for path resolution
            node_info["_parent_rloc_base"] = None
            node_info["_parent_rssi"] = None
            node_info["_parent_lqi"] = None
            if thread_role_val in (2, 3) and isinstance(neighbor_table, list):
                for nb in neighbor_table:
                    if isinstance(nb, dict):
                        rloc = nb.get("2", 0)
                        if rloc:
                            node_info["_parent_rloc_base"] = (rloc >> 10) * 1024
                            node_info["_parent_rssi"] = nb.get("7")  # LastRssi
                            node_info["_parent_lqi"] = nb.get("5")   # LQI
                        break

            # Store RLOC base for routers
            node_info["_rloc_base"] = None
            if thread_role_val in (5, 6):
                route_table = self._get_matter_attr(attributes, 53, 8, [])
                if isinstance(route_table, list):
                    # Method 1: own entry has ExtAddr!=0, Allocated, !LinkEstablished
                    for entry in route_table:
                        if (isinstance(entry, dict)
                                and entry.get("0", 0) != 0
                                and entry.get("8", False)
                                and not entry.get("9", False)):
                            rloc = entry.get("1", 0)
                            if rloc:
                                node_info["_rloc_base"] = (rloc >> 10) * 1024
                            break
                    # Method 2: find the Allocated+!LinkEstablished entry
                    # that is NOT a known linked neighbor
                    if node_info["_rloc_base"] is None:
                        linked_rids = set()
                        candidates = []
                        for entry in route_table:
                            if not isinstance(entry, dict):
                                continue
                            rid = entry.get("2", -1)
                            if entry.get("8", False) and entry.get("9", False):
                                linked_rids.add(rid)
                            elif entry.get("8", False) and not entry.get("9", False):
                                candidates.append(entry)
                        for c in candidates:
                            rid = c.get("2", -1)
                            if rid not in linked_rids:
                                rloc = c.get("1", 0)
                                if rloc:
                                    node_info["_rloc_base"] = (rloc >> 10) * 1024
                                break
                # Method 3 fallback: infer from children RLOC
                if node_info["_rloc_base"] is None and isinstance(neighbor_table, list):
                    for nb in neighbor_table:
                        if isinstance(nb, dict) and nb.get("13", False):
                            child_rloc = nb.get("2", 0)
                            if child_rloc:
                                node_info["_rloc_base"] = (child_rloc >> 10) * 1024
                            break

            # Store router neighbor info (RSSI to other routers)
            node_info["_router_neighbors"] = {}
            if thread_role_val in (5, 6) and isinstance(neighbor_table, list):
                for nb in neighbor_table:
                    if isinstance(nb, dict) and not nb.get("13", False):
                        nb_rloc = nb.get("2", 0)
                        nb_base = (nb_rloc >> 10) * 1024 if nb_rloc else None
                        if nb_base is not None:
                            node_info["_router_neighbors"][nb_base] = {
                                "rssi": nb.get("7"),
                                "lqi": nb.get("5"),
                            }

            node_info["last_seen"] = self._last_seen.get(node_id, "")
            nodes.append(node_info)

        # Build RLOC base -> node info mapping
        rloc_to_node: dict[int, dict[str, Any]] = {}
        for n in nodes:
            if n["_rloc_base"] is not None:
                rloc_to_node[n["_rloc_base"]] = n

        # Find the leader node (border router path ends here)
        leader_rloc_base = None
        for n in nodes:
            if n.get("thread_role") == "leader" and n["_rloc_base"] is not None:
                leader_rloc_base = n["_rloc_base"]
                break

        # Resolve parent and build route_path for each node
        for n in nodes:
            parent_rloc = n.pop("_parent_rloc_base", None)
            parent_rssi = n.pop("_parent_rssi", None)
            parent_lqi = n.pop("_parent_lqi", None)
            rloc_base = n.pop("_rloc_base", None)
            router_neighbors = n.pop("_router_neighbors", {})

            if parent_rloc is not None and parent_rloc in rloc_to_node:
                parent = rloc_to_node[parent_rloc]
                n["parent_node_id"] = parent["node_id"]
                n["parent_name"] = parent["device_name"]
            else:
                n["parent_node_id"] = None
                n["parent_name"] = ""

            # Build route_path: list of hops from device to HA
            path = []
            # Hop 0: the device itself
            path.append({
                "node_id": n["node_id"],
                "name": n["device_name"],
                "role": n["thread_role"],
                "rssi": None, "lqi": None,
            })

            if n["thread_role"] in ("sed", "end_device"):
                # Hop 1: parent router
                if parent_rloc is not None and parent_rloc in rloc_to_node:
                    pr = rloc_to_node[parent_rloc]
                    path.append({
                        "node_id": pr["node_id"],
                        "name": pr["device_name"],
                        "role": pr["thread_role"],
                        "rssi": parent_rssi, "lqi": parent_lqi,
                    })
                    # Trace from parent router toward leader (max 5 hops)
                    current_rloc = parent_rloc
                    visited = {parent_rloc}
                    for _ in range(5):
                        if current_rloc == leader_rloc_base:
                            break
                        cur = rloc_to_node.get(current_rloc)
                        if not cur:
                            break
                        cur_neighbors = cur.get("_router_neighbors", {})
                        if not cur_neighbors:
                            break
                        # Find neighbor closest to leader (prefer leader directly)
                        if leader_rloc_base in cur_neighbors:
                            hop = cur_neighbors[leader_rloc_base]
                            lr = rloc_to_node[leader_rloc_base]
                            path.append({
                                "node_id": lr["node_id"],
                                "name": lr["device_name"],
                                "role": lr["thread_role"],
                                "rssi": hop.get("rssi"),
                                "lqi": hop.get("lqi"),
                            })
                            break
                        # Otherwise pick best LQI neighbor not yet visited
                        best_rloc = None
                        best_lqi = -1
                        for nb_rloc, nb_info in cur_neighbors.items():
                            if nb_rloc not in visited and (nb_info.get("lqi") or 0) > best_lqi:
                                best_lqi = nb_info.get("lqi") or 0
                                best_rloc = nb_rloc
                        if best_rloc and best_rloc in rloc_to_node:
                            visited.add(best_rloc)
                            nr = rloc_to_node[best_rloc]
                            hop_info = cur_neighbors[best_rloc]
                            path.append({
                                "node_id": nr["node_id"],
                                "name": nr["device_name"],
                                "role": nr["thread_role"],
                                "rssi": hop_info.get("rssi"),
                                "lqi": hop_info.get("lqi"),
                            })
                            current_rloc = best_rloc
                        else:
                            break

            elif n["thread_role"] in ("router", "reed"):
                # Trace router path toward leader (max 5 hops)
                if rloc_base and rloc_base != leader_rloc_base:
                    current_rloc = rloc_base
                    current_neighbors = router_neighbors
                    visited = {rloc_base}
                    for _ in range(5):
                        if current_rloc == leader_rloc_base:
                            break
                        # Direct link to leader?
                        if leader_rloc_base in current_neighbors:
                            hop = current_neighbors[leader_rloc_base]
                            lr = rloc_to_node[leader_rloc_base]
                            path.append({
                                "node_id": lr["node_id"],
                                "name": lr["device_name"],
                                "role": lr["thread_role"],
                                "rssi": hop.get("rssi"),
                                "lqi": hop.get("lqi"),
                            })
                            break
                        # Pick best LQI neighbor not yet visited
                        best_rloc = None
                        best_lqi = -1
                        for nb_rloc, nb_info in current_neighbors.items():
                            if nb_rloc not in visited and (nb_info.get("lqi") or 0) > best_lqi:
                                best_lqi = nb_info.get("lqi") or 0
                                best_rloc = nb_rloc
                        if best_rloc and best_rloc in rloc_to_node:
                            visited.add(best_rloc)
                            nr = rloc_to_node[best_rloc]
                            hop_info = current_neighbors[best_rloc]
                            path.append({
                                "node_id": nr["node_id"],
                                "name": nr["device_name"],
                                "role": nr["thread_role"],
                                "rssi": hop_info.get("rssi"),
                                "lqi": hop_info.get("lqi"),
                            })
                            current_rloc = best_rloc
                            current_neighbors = nr.get("_router_neighbors", {})
                        else:
                            break

            # Final hop: HA
            path.append({"node_id": None, "name": "Home Assistant", "role": "ha", "rssi": None, "lqi": None})
            n["route_path"] = path

        # Sort: offline first, then by node_id
        nodes.sort(key=lambda n: (n["available"], n["node_id"] or 0))

        return {
            "nodes": nodes,
            "total": len(nodes),
            "online": online_count,
            "offline": offline_count,
        }

    async def send_matter_command(
        self, command: str, args: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a command to the Matter Server and return the response."""
        session = aiohttp.ClientSession()
        try:
            async with session.ws_connect(self.url, timeout=10) as ws:
                await asyncio.wait_for(ws.receive(), timeout=5)  # server info
                request: dict[str, Any] = {
                    "message_id": "cmd",
                    "command": command,
                }
                if args:
                    request["args"] = args
                await ws.send_json(request)
                msg = await asyncio.wait_for(ws.receive(), timeout=30)
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    # Matter Server error responses
                    if isinstance(data, dict) and "error_code" in data:
                        return {"error": data.get("details", data.get("error_code", "Unknown error"))}
                    return data
                return {"error": f"Unexpected message type: {msg.type}"}
        except asyncio.TimeoutError:
            return {"error": "Timeout - Gerät antwortet nicht"}
        except (aiohttp.ClientError, ConnectionError) as err:
            return {"error": f"Verbindungsfehler: {err}"}
        finally:
            await session.close()

    @staticmethod
    def _get_matter_attr(
        attributes: dict, cluster_id: int, attr_id: int, default: Any
    ) -> Any:
        """Extract a Matter attribute from endpoint/cluster/attribute keyed dict.

        Matter Server uses keys like "0/40/1" meaning endpoint 0, cluster 40,
        attribute 1. We search all endpoints for the given cluster/attribute.
        """
        for key, value in attributes.items():
            parts = str(key).split("/")
            if len(parts) == 3:
                try:
                    if int(parts[1]) == cluster_id and int(parts[2]) == attr_id:
                        return value
                except (ValueError, IndexError):
                    continue
        return default


SERVICE_SCHEMA_NODE = vol.Schema({
    vol.Required("node_id"): int,
})


async def async_setup_entry(hass: HomeAssistant, entry: MatterSaverConfigEntry) -> bool:
    """Set up Matter Saver from a config entry."""
    url = entry.data.get(CONF_MATTER_URL, DEFAULT_MATTER_URL)

    coordinator = MatterSaverCoordinator(hass, url)
    await coordinator.async_load_log()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await coordinator.start_auto_recovery()

    def _node_name(nid: int) -> str:
        """Get device name for a node_id from coordinator data."""
        if coordinator.data:
            for n in coordinator.data.get("nodes", []):
                if n["node_id"] == nid:
                    return n.get("device_name") or f"Node {nid}"
        return f"Node {nid}"

    async def _run_action(
        node_id: int, action_name: str, command: str,
        args: dict[str, Any], success_msg: str,
    ) -> None:
        """Run a Matter command with logging and error propagation."""
        from homeassistant.exceptions import HomeAssistantError
        name = _node_name(node_id)
        coordinator.add_log("action", node_id, name, f"{action_name} gestartet")
        result = await coordinator.send_matter_command(command, args)
        if isinstance(result, dict) and "error" in result:
            error_msg = result["error"]
            coordinator.add_log("error", node_id, name, f"{action_name} fehlgeschlagen: {error_msg}")
            raise HomeAssistantError(f"{action_name} fehlgeschlagen: {error_msg}")
        coordinator.add_log("success", node_id, name, success_msg)

    async def handle_ping_node(call: ServiceCall) -> None:
        """Ping a Matter node."""
        node_id = call.data["node_id"]
        await _run_action(node_id, "Ping", "ping_node",
                          {"node_id": node_id}, "Ping erfolgreich")

    async def handle_interview_node(call: ServiceCall) -> None:
        """Re-interview a Matter node."""
        node_id = call.data["node_id"]
        await _run_action(node_id, "Re-Interview", "interview_node",
                          {"node_id": node_id}, "Re-Interview erfolgreich")
        await coordinator.async_request_refresh()

    async def handle_reset_counters(call: ServiceCall) -> None:
        """Reset Thread diagnostic counters for a node."""
        node_id = call.data["node_id"]
        await _run_action(node_id, "Error Counter Reset", "send_command", {
            "node_id": node_id, "endpoint_id": 0,
            "cluster_id": 53, "command_name": "ResetCounts", "payload": {},
        }, "Error Counter zurückgesetzt")
        await coordinator.async_request_refresh()
        hass.bus.async_fire(f"{DOMAIN}_action_result", {
            "action": "reset_counters", "node_id": node_id,
            "result": result,
        })
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, "ping_node", handle_ping_node, schema=SERVICE_SCHEMA_NODE,
    )
    hass.services.async_register(
        DOMAIN, "interview_node", handle_interview_node, schema=SERVICE_SCHEMA_NODE,
    )
    hass.services.async_register(
        DOMAIN, "reset_counters", handle_reset_counters, schema=SERVICE_SCHEMA_NODE,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MatterSaverConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: MatterSaverCoordinator = entry.runtime_data
    await coordinator.stop_auto_recovery()
    hass.services.async_remove(DOMAIN, "ping_node")
    hass.services.async_remove(DOMAIN, "interview_node")
    hass.services.async_remove(DOMAIN, "reset_counters")
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
