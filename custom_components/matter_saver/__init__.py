"""Matter Saver - Custom Component for Home Assistant."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
try:
    from homeassistant.helpers import floor_registry as fr
except ImportError:  # pragma: no cover - compatibility for older HA versions
    fr = None
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
LOVELACE_CARD_FILENAMES = (
    "matter-saver-card-utils.js",
    "matter-saver-device-data.js",
    "matter-saver-card-editor.js",
    "matter-saver-card.js",
    "matter-saver-log-card.js",
    "matter-saver-topology-card.js",
    "matter-saver-mesh-card.js",
)
LOVELACE_RESOURCE_KEY = "lovelace_resources_registered"

type MatterSaverConfigEntry = ConfigEntry[MatterSaverCoordinator]

ERROR_COMMENT_LABELS_EN = {
    "thread_noise_severe": "severe channel interference",
    "thread_noise_moderate": "channel interference",
    "tx_abort_severe": "many aborted transmissions",
    "tx_abort_moderate": "aborted transmissions",
    "rx_no_frame_severe": "reception problems",
    "rx_no_frame_moderate": "minor reception problems",
    "rx_unknown_neighbors": "unknown neighbors",
    "rx_invalid_source": "invalid sources",
    "tx_retry_severe": "very poor connection",
    "tx_retry_moderate": "poor connection",
}

ACTION_LABELS_EN = {
    "ping": "Ping",
    "interview": "Re-Interview",
    "reset": "Reset Counters",
}


def _render_error_comment_en(codes: list[str]) -> str:
    """Render an English fallback error comment from diagnostic codes."""
    return ", ".join(
        ERROR_COMMENT_LABELS_EN[code]
        for code in codes
        if code in ERROR_COMMENT_LABELS_EN
    )


def _action_label_en(action: str | None) -> str:
    """Return the English action label for log entries."""
    if not action:
        return "Action"
    return ACTION_LABELS_EN.get(action, action.replace("_", " ").title())


def _preferred_node_name(node: dict[str, Any]) -> str:
    """Return the best available display name for a parsed node."""
    return (
        node.get("device_name")
        or node.get("node_label")
        or node.get("product_name")
        or f"Node {node['node_id']}"
    )


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
        self._previous_problem: dict[int, tuple[str, ...]] = {}
        self._recent_parents: dict[int, dict[str, Any]] = {}
        self._recent_parents_dirty = False
        self.activity_log: list[dict[str, Any]] = []
        self.max_log_entries = 200
        self._store = Store(hass, 1, f"{DOMAIN}_data")
        self._store_loaded = False
        self._first_refresh_done = False
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
            self._recent_parents = {
                int(k): normalized
                for k, value in data.get("recent_parents", {}).items()
                if (normalized := self._normalize_recent_parent(value)) is not None
            }
            self.auto_recovery_enabled = data.get("auto_recovery", True)
        self._recent_parents_dirty = False
        self._store_loaded = True

    async def _async_save_log(self) -> None:
        """Save persistent data to storage."""
        await self._store.async_save({
            "entries": self.activity_log,
            "last_seen": self._last_seen,
            "offline_history": {str(k): v for k, v in self.offline_history.items()},
            "recent_parents": {str(k): v for k, v in self._recent_parents.items()},
            "auto_recovery": self.auto_recovery_enabled,
        })

    def add_log(
        self,
        level: str,
        node_id: int | None,
        name: str,
        message: str,
        **extra: Any,
    ) -> None:
        """Add an entry to the activity log."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "node_id": node_id,
            "name": name,
            "message": message,
        }
        entry.update(extra)
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
        # Wait for startup to complete before first recovery attempt
        await asyncio.sleep(self._recovery_interval)
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
                        self.add_log(
                            "action",
                            nid,
                            name,
                            "Auto-Recovery: ping failed",
                            message_key="auto_recovery_ping_failed",
                            action="ping",
                        )
                        continue
                    self.add_log(
                        "action",
                        nid,
                        name,
                        "Auto-Recovery: ping ok, starting re-interview",
                        message_key="auto_recovery_ping_ok",
                        action="interview",
                    )
                    # Ping worked, try interview
                    result = await self.send_matter_command(
                        "interview_node", {"node_id": nid}
                    )
                    if isinstance(result, dict) and "error" in result:
                        self.add_log(
                            "error",
                            nid,
                            name,
                            "Auto-Recovery: re-interview failed",
                            message_key="auto_recovery_interview_failed",
                            action="interview",
                        )
                    else:
                        self.add_log(
                            "success",
                            nid,
                            name,
                            "Auto-Recovery: re-interview succeeded",
                            message_key="auto_recovery_interview_succeeded",
                            action="interview",
                        )
                        await self.async_request_refresh()
                except Exception:
                    pass  # Don't crash the loop

    @staticmethod
    def _get_open_offline_period(
        history: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Return the currently open offline period for a node."""
        for period in history:
            if isinstance(period, dict) and period.get("end") is None:
                return period
        return None

    @staticmethod
    def _parse_period_timestamp(value: Any) -> datetime | None:
        """Parse a stored offline-history timestamp.

        Naive timestamps are treated as UTC so historical data can still be
        compared with the coordinator's timezone-aware timestamps.
        """
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    @classmethod
    def _period_start(cls, period: dict[str, Any]) -> datetime | None:
        """Return the parsed start timestamp for an offline period."""
        return cls._parse_period_timestamp(period.get("start"))

    @classmethod
    def _period_end(
        cls, period: dict[str, Any], now_dt: datetime
    ) -> datetime:
        """Return the parsed end timestamp for an offline period."""
        end = cls._parse_period_timestamp(period.get("end"))
        return end or now_dt

    @staticmethod
    def _seconds_to_minutes(total_seconds: float) -> int:
        """Convert seconds to rounded minutes for display."""
        if total_seconds <= 0:
            return 0
        return round(total_seconds / 60)

    @classmethod
    def _close_offline_period(
        cls,
        period: dict[str, Any],
        end_dt: datetime,
    ) -> None:
        """Close an offline period at a specific timestamp."""
        start = cls._period_start(period)
        if start is not None and end_dt < start:
            end_dt = start
        period["end"] = end_dt.isoformat()
        if start is None:
            period["duration_min"] = 0
            return
        period["duration_min"] = cls._seconds_to_minutes(
            (end_dt - start).total_seconds()
        )

    @classmethod
    def _stale_offline_period_end(
        cls,
        period: dict[str, Any],
        now_dt: datetime,
    ) -> datetime:
        """Return the best known end for a stale open offline period.

        Older persisted data may contain an open period from a previous Home
        Assistant session. Reconstruct the last observed end by adding the
        previously tracked observed duration to the stored start time so the
        restart gap is not counted as device downtime. If the stored start is
        invalid, fall back to ``now_dt`` so the caller can safely close the
        malformed period without raising.
        """
        start = cls._period_start(period)
        if start is None:
            return now_dt
        # Keep supporting historical periods saved before stale-open migration
        # so existing persisted data is closed at the last known observed point.
        observed_minutes_int = cls._stored_observed_minutes(period)
        return start + timedelta(minutes=observed_minutes_int)

    @staticmethod
    def _start_offline_period(now: str) -> dict[str, Any]:
        """Create a new open offline period starting now."""
        return {
            "start": now,
            "end": None,
            "duration_min": 0,
        }

    @staticmethod
    def _stored_observed_minutes(period: dict[str, Any]) -> int:
        """Return the best known observed minutes from persisted history."""
        # Historical data may contain `observed_minutes` from the old
        # per-refresh tracking logic. Fall back to `duration_min` for older
        # closed periods that never stored the observed field explicitly.
        observed_minutes = period.get("observed_minutes")
        if observed_minutes is None:
            observed_minutes = period.get("duration_min", 0)
        try:
            return max(0, int(observed_minutes))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _offline_window_stats(
        history: list[dict[str, Any]],
        window_start: datetime,
        now_dt: datetime,
    ) -> tuple[int, int]:
        """Calculate downtime event count and attributed minutes for a time window."""
        count = 0
        overlap_seconds_total = 0.0
        for period in history:
            if not isinstance(period, dict):
                continue
            start = MatterSaverCoordinator._period_start(period)
            if start is None:
                continue
            end = MatterSaverCoordinator._period_end(period, now_dt)

            overlap_start = max(start, window_start)
            overlap_end = min(end, now_dt)
            overlap_seconds = max((overlap_end - overlap_start).total_seconds(), 0)
            if overlap_seconds <= 0:
                continue

            count += 1
            overlap_seconds_total += overlap_seconds

        return count, MatterSaverCoordinator._seconds_to_minutes(
            overlap_seconds_total
        )

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        """Return an integer when possible."""
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_thread_ext_address(value: Any) -> str:
        """Return a normalized 16-character uppercase Thread extended address."""
        if value is None or value == "":
            return ""
        if isinstance(value, str):
            normalized = value.strip().replace(":", "").replace("-", "").upper()
            if normalized.startswith("0X"):
                normalized = normalized[2:]
            if not normalized:
                return ""
            try:
                return f"{int(normalized, 16):016X}"
            except ValueError:
                return ""
        coerced = MatterSaverCoordinator._coerce_int(value)
        if coerced is None:
            return ""
        return f"{coerced & 0xFFFFFFFFFFFFFFFF:016X}"

    @classmethod
    def _extract_device_type_ids(cls, attributes: dict[str, Any]) -> list[int]:
        """Extract Descriptor cluster device type IDs."""
        raw_device_types = cls._get_matter_attr(attributes, 29, 0, [])
        if not isinstance(raw_device_types, list):
            return []

        device_type_ids: list[int] = []
        for entry in raw_device_types:
            if isinstance(entry, dict):
                candidate = entry.get("0", entry.get("deviceType"))
            else:
                candidate = entry
            coerced = cls._coerce_int(candidate)
            if coerced is not None and coerced not in device_type_ids:
                device_type_ids.append(coerced)
        return device_type_ids

    @staticmethod
    def _signal_candidate(rssi: Any, lqi: Any) -> dict[str, int | None]:
        """Normalize RSSI/LQI values for comparisons and payloads."""
        return {
            "rssi": MatterSaverCoordinator._coerce_int(rssi),
            "lqi": MatterSaverCoordinator._coerce_int(lqi),
        }

    @staticmethod
    def _better_signal(
        current: dict[str, int | None] | None,
        candidate: dict[str, int | None],
    ) -> bool:
        """Return True when the candidate signal is more useful."""
        if current is None:
            return candidate.get("rssi") is not None or candidate.get("lqi") is not None

        current_lqi = current.get("lqi")
        candidate_lqi = candidate.get("lqi")
        if current_lqi is None and candidate_lqi is not None:
            return True
        if current_lqi is not None and candidate_lqi is not None and candidate_lqi > current_lqi:
            return True

        current_rssi = current.get("rssi")
        candidate_rssi = candidate.get("rssi")
        if current_rssi is None and candidate_rssi is not None:
            return True
        if current_rssi is not None and candidate_rssi is not None and candidate_rssi > current_rssi:
            return True
        return False

    @staticmethod
    def _border_router_name(entry: dict[str, Any]) -> str:
        """Return the best available label for a discovered border router."""
        model_name = str(entry.get("modelName") or "").strip()
        vendor_name = str(entry.get("vendorName") or "").strip()
        hostname = str(entry.get("hostname") or "").strip().rstrip(".")
        network_name = str(entry.get("networkName") or "").strip()
        if vendor_name and model_name:
            return f"{vendor_name} {model_name}"
        if model_name:
            return model_name
        if hostname:
            return hostname
        if network_name:
            return f"{network_name} Border Router"
        return "Thread Border Router"

    @classmethod
    def _normalize_border_routers(
        cls,
        raw_entries: Any,
        nodes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Normalize discovered Thread border routers for Lovelace cards."""
        if not isinstance(raw_entries, list):
            return []

        known_ext_addresses = {
            ext_address: node["node_id"]
            for node in nodes
            if (ext_address := node.get("thread_ext_address"))
        }
        discovered_links: dict[str, list[dict[str, Any]]] = {}
        for node in nodes:
            for ext_address, signal in node.get("_external_thread_neighbors", {}).items():
                if ext_address in known_ext_addresses:
                    continue
                links = discovered_links.setdefault(ext_address, [])
                links.append({
                    "node_id": node["node_id"],
                    "rssi": signal.get("rssi"),
                    "lqi": signal.get("lqi"),
                })

        normalized_entries: list[dict[str, Any]] = []
        seen_addresses: set[str] = set()
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            ext_address = cls._format_thread_ext_address(
                entry.get("extAddressHex")
                or entry.get("ext_address")
                or entry.get("extAddress")
            )
            if not ext_address or ext_address in seen_addresses or ext_address in known_ext_addresses:
                continue
            seen_addresses.add(ext_address)

            addresses = entry.get("addresses", [])
            normalized_entries.append({
                "ext_address": ext_address,
                "name": cls._border_router_name(entry),
                "vendor_name": str(entry.get("vendorName") or ""),
                "model_name": str(entry.get("modelName") or ""),
                "hostname": str(entry.get("hostname") or "").rstrip("."),
                "network_name": str(entry.get("networkName") or ""),
                "last_seen": cls._coerce_int(entry.get("lastSeen")),
                "addresses": [str(address) for address in addresses] if isinstance(addresses, list) else [],
                "links": discovered_links.get(ext_address, []),
            })

        normalized_entries.sort(key=lambda item: item["name"].lower())
        return normalized_entries

    @classmethod
    def _normalize_recent_parent(cls, value: Any) -> dict[str, Any] | None:
        """Normalize persisted recent-parent metadata."""
        if not isinstance(value, dict):
            return None
        parent_node_id = cls._coerce_int(value.get("parent_node_id"))
        if parent_node_id is None:
            return None
        return {
            "parent_node_id": parent_node_id,
            "parent_name": str(value.get("parent_name") or ""),
            "rssi": cls._coerce_int(value.get("rssi")),
            "lqi": cls._coerce_int(value.get("lqi")),
        }

    def _remember_recent_parent(
        self,
        node_id: int,
        parent_node_id: int,
        parent_name: str,
        rssi: Any,
        lqi: Any,
    ) -> None:
        """Persist the most recently known parent for a node."""
        payload = {
            "parent_node_id": parent_node_id,
            "parent_name": parent_name,
            "rssi": self._coerce_int(rssi),
            "lqi": self._coerce_int(lqi),
        }
        if self._recent_parents.get(node_id) != payload:
            self._recent_parents[node_id] = payload
            self._recent_parents_dirty = True

    @staticmethod
    def _is_child_device_role(role: str) -> bool:
        """Return True when the role belongs to a child/end-device."""
        return role not in ("router", "leader", "reed")

    @staticmethod
    def _extend_route_to_leader(
        path: list[dict[str, Any]],
        start_rloc_base: int | None,
        leader_rloc_base: int | None,
        rloc_to_node: dict[int, dict[str, Any]],
    ) -> None:
        """Append router hops from the starting router toward the leader."""
        if (
            start_rloc_base is None
            or leader_rloc_base is None
            or start_rloc_base == leader_rloc_base
        ):
            return

        current_rloc = start_rloc_base
        visited = {start_rloc_base}
        for _ in range(5):
            if current_rloc == leader_rloc_base:
                break
            current = rloc_to_node.get(current_rloc)
            if not current:
                break
            current_neighbors = current.get("_router_neighbors", {})
            if not current_neighbors:
                break

            if leader_rloc_base in current_neighbors:
                hop = current_neighbors[leader_rloc_base]
                leader = rloc_to_node.get(leader_rloc_base)
                if leader:
                    path.append({
                        "node_id": leader["node_id"],
                        "name": _preferred_node_name(leader),
                        "role": leader["thread_role"],
                        "rssi": hop.get("rssi"),
                        "lqi": hop.get("lqi"),
                    })
                break

            best_rloc = None
            best_lqi = -1
            for neighbor_rloc, neighbor_info in current_neighbors.items():
                neighbor_lqi = neighbor_info.get("lqi") or 0
                if neighbor_rloc not in visited and neighbor_lqi > best_lqi:
                    best_lqi = neighbor_lqi
                    best_rloc = neighbor_rloc

            if best_rloc is None or best_rloc not in rloc_to_node:
                break

            visited.add(best_rloc)
            next_router = rloc_to_node[best_rloc]
            hop_info = current_neighbors[best_rloc]
            path.append({
                "node_id": next_router["node_id"],
                "name": _preferred_node_name(next_router),
                "role": next_router["thread_role"],
                "rssi": hop_info.get("rssi"),
                "lqi": hop_info.get("lqi"),
            })
            current_rloc = best_rloc

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Matter Server."""
        try:
            data = await self._fetch_matter_nodes(light=not self._first_refresh_done)
            self._first_refresh_done = True
        except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError) as err:
            raise UpdateFailed(f"Error communicating with Matter Server: {err}") from err

        # Track status changes + offline history
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        history_changed = False
        for node in data.get("nodes", []):
            nid = node["node_id"]
            available = node["available"]
            name = node.get("device_name") or f"Node {nid}"
            prev = self._previous_status.get(nid)
            problem_codes = tuple(node.get("error_comment_codes", []))
            prev_problem = self._previous_problem.get(nid)
            history = self.offline_history.setdefault(nid, [])
            open_period = self._get_open_offline_period(history)

            if prev is None:
                if open_period is not None:
                    # This open period was persisted by an earlier Home
                    # Assistant session. Close it at the last observed point so
                    # the restart gap is not attributed as new downtime.
                    stale_end = self._stale_offline_period_end(open_period, now_dt)
                    self._close_offline_period(open_period, stale_end)
                    history_changed = True
                if not available:
                    # If the node is still offline after startup, begin a new
                    # runtime-local open period that only tracks downtime we can
                    # observe in this Home Assistant session.
                    history.insert(0, self._start_offline_period(now))
                    self.offline_history[nid] = history[:50]
                    open_period = self.offline_history[nid][0]
                    history_changed = True

            if prev is not None and prev != available:
                if available:
                    self.add_log(
                        "info",
                        nid,
                        name,
                        "online",
                        message_key="node_online",
                    )
                    # Close open offline period
                    if open_period is not None:
                        self._close_offline_period(open_period, now_dt)
                        history_changed = True
                else:
                    self.add_log(
                        "warning",
                        nid,
                        name,
                        "offline",
                        message_key="node_offline",
                    )
                    # Start new offline period
                    history.insert(0, self._start_offline_period(now))
                    # Keep max 50 entries per node
                    self.offline_history[nid] = history[:50]
                    history_changed = True

            if prev_problem is not None and prev_problem != problem_codes:
                problem_text = _render_error_comment_en(list(problem_codes))
                if not prev_problem and problem_codes:
                    self.add_log(
                        "warning",
                        nid,
                        name,
                        f"problem detected: {problem_text}",
                        message_key="problem_detected",
                        problem_codes=list(problem_codes),
                    )
                elif prev_problem and not problem_codes:
                    self.add_log(
                        "success",
                        nid,
                        name,
                        "problem cleared",
                        message_key="problem_cleared",
                    )
                elif prev_problem and problem_codes:
                    self.add_log(
                        "warning",
                        nid,
                        name,
                        f"problem updated: {problem_text}",
                        message_key="problem_updated",
                        problem_codes=list(problem_codes),
                    )

            self._previous_status[nid] = available
            self._previous_problem[nid] = problem_codes

        # Build offline stats per node
        for node in data.get("nodes", []):
            nid = node["node_id"]
            history = self.offline_history.get(nid, [])
            day_count, day_minutes = self._offline_window_stats(
                history, now_dt - timedelta(days=1), now_dt
            )
            week_count, week_minutes = self._offline_window_stats(
                history, now_dt - timedelta(days=7), now_dt
            )
            month_count, month_minutes = self._offline_window_stats(
                history, now_dt - timedelta(days=30), now_dt
            )

            node["offline_24h_count"] = day_count
            node["offline_24h_minutes"] = day_minutes
            node["offline_7d_count"] = week_count
            node["offline_7d_minutes"] = week_minutes
            node["offline_30d_count"] = month_count
            node["offline_30d_minutes"] = month_minutes

        if history_changed or self._recent_parents_dirty:
            self._recent_parents_dirty = False
            self.hass.async_create_task(self._async_save_log())
        data["activity_log"] = self.activity_log
        return data

    async def _fetch_matter_nodes(self, light: bool = False) -> dict[str, Any]:
        """Connect to Matter Server WebSocket and get all nodes."""
        session = aiohttp.ClientSession()
        try:
            async with session.ws_connect(self.url, timeout=10) as ws:
                # Matter Server sends server info on connect - read and discard
                await asyncio.wait_for(ws.receive(), timeout=5)

                async def _ws_command(
                    message_id: str,
                    command: str,
                    args: dict[str, Any] | None = None,
                    timeout: int = 15,
                ) -> Any:
                    request: dict[str, Any] = {
                        "message_id": message_id,
                        "command": command,
                    }
                    if args:
                        request["args"] = args
                    await ws.send_json(request)
                    msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        raise UpdateFailed(
                            f"Unexpected WebSocket message type: {msg.type}"
                        )
                    payload = json.loads(msg.data)
                    if isinstance(payload, dict) and "result" in payload:
                        return payload["result"]
                    return payload

                node_payload = await _ws_command("1", "get_nodes")
                if light:
                    # Quick parse for startup - no registry lookups
                    return self._parse_nodes_light(node_payload)

                border_router_payload: Any = []
                try:
                    border_router_payload = await _ws_command(
                        "2",
                        "get_thread_border_routers",
                        timeout=10,
                    )
                except (UpdateFailed, asyncio.TimeoutError, ValueError, TypeError):
                    border_router_payload = []

                return self._parse_nodes(node_payload, border_router_payload)
        finally:
            await session.close()

    def _parse_nodes_light(self, data: Any) -> dict[str, Any]:
        """Quick parse for startup - basic info only, no registry lookups."""
        raw_nodes = []
        if isinstance(data, dict):
            raw_nodes = data.get("result", data.get("nodes", []))
        elif isinstance(data, list):
            raw_nodes = data
        if not isinstance(raw_nodes, list):
            raw_nodes = []

        nodes = []
        online_count = 0
        offline_count = 0
        for node in raw_nodes:
            if not isinstance(node, dict):
                continue
            node_id = node.get("node_id")
            available = node.get("available", False)
            attributes = node.get("attributes", {})
            if available:
                online_count += 1
            else:
                offline_count += 1
            nodes.append({
                "node_id": node_id,
                "device_name": self._get_matter_attr(attributes, 40, 3, ""),
                "area": "",
                "floor": "",
                "available": available,
                "product_name": self._get_matter_attr(attributes, 40, 3, ""),
                "vendor_name": self._get_matter_attr(attributes, 40, 1, ""),
                "node_label": self._get_matter_attr(attributes, 40, 5, ""),
                "serial_number": self._get_matter_attr(attributes, 40, 15, ""),
                "software_version_string": self._get_matter_attr(attributes, 40, 10, ""),
                "date_commissioned": node.get("date_commissioned", ""),
                "last_interview": node.get("last_interview", ""),
                "interview_version": node.get("interview_version"),
                "device_type_ids": self._extract_device_type_ids(attributes),
                "update_available": False,
                "thread_role": "unknown",
                "neighbors": 0, "children": 0,
                "errors": 0, "tx_retries": 0,
                "error_comment": "",
                "error_comment_codes": [],
                "battery_percent": None, "power_source": "unknown",
                "parent_node_id": None, "parent_name": "",
                "signal_rssi": None, "signal_lqi": None,
                "route_path": [], "last_seen": self._last_seen.get(node_id, ""),
                "offline_24h_count": 0, "offline_24h_minutes": 0,
                "offline_7d_count": 0, "offline_7d_minutes": 0,
                "offline_30d_count": 0, "offline_30d_minutes": 0,
            })

        nodes.sort(key=lambda n: (n["available"], n["node_id"] or 0))
        return {
            "nodes": nodes, "total": len(nodes),
            "online": online_count, "offline": offline_count,
            "activity_log": self.activity_log,
            "border_routers": [],
        }

    def _build_node_device_map(self) -> dict[int, dict[str, str]]:
        """Build a mapping of Matter node_id to HA device info.

        The Matter integration uses identifiers like:
        ("matter", "deviceid_<fabric>-<node_id_hex>-MatterNodeDevice")
        """
        node_map: dict[int, dict[str, Any]] = {}
        dev_reg = dr.async_get(self.hass)
        ent_reg = er.async_get(self.hass)
        area_reg = ar.async_get(self.hass)
        floor_reg = fr.async_get(self.hass) if fr is not None else None

        floor_names: dict[str, str] = {}
        if floor_reg is not None:
            for floor in floor_reg.async_list_floors():
                floor_id = getattr(floor, "floor_id", "")
                if floor_id:
                    floor_names[floor_id] = floor.name

        # Build area_id -> area details lookup
        area_details: dict[str, dict[str, str]] = {}
        for area in area_reg.async_list_areas():
            area_details[area.id] = {
                "name": area.name,
                "floor": floor_names.get(getattr(area, "floor_id", ""), ""),
            }

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
                        area_info = area_details.get(device.area_id, {}) if device.area_id else {}
                        node_map[node_id] = {
                            "name": device.name_by_user or device.name or "",
                            "area": area_info.get("name", ""),
                            "floor": area_info.get("floor", ""),
                            "update_available": update_available.get(device.id, False),
                            # Reuse the core Matter device identifier so our
                            # per-node diagnostic entities bind to that device.
                            "matter_identifier": (domain, identifier),
                        }
                    except (ValueError, IndexError):
                        continue
        return node_map

    def _parse_nodes(
        self,
        data: Any,
        border_router_entries: Any = None,
    ) -> dict[str, Any]:
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
                "floor": device_info.get("floor", ""),
                "update_available": device_info.get("update_available", False),
                "available": available,
                "vendor_name": self._get_matter_attr(attributes, 40, 1, ""),
                "product_name": self._get_matter_attr(attributes, 40, 3, ""),
                "node_label": self._get_matter_attr(attributes, 40, 5, ""),
                "serial_number": self._get_matter_attr(attributes, 40, 15, ""),
                "software_version_string": self._get_matter_attr(attributes, 40, 10, ""),
                "date_commissioned": node.get("date_commissioned", ""),
                "last_interview": node.get("last_interview", ""),
                "interview_version": node.get("interview_version"),
                "matter_identifier": device_info.get("matter_identifier"),
                "device_type_ids": self._extract_device_type_ids(attributes),
                "thread_ext_address": self._format_thread_ext_address(
                    self._get_matter_attr(attributes, 53, 63, None)
                ),
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
            comment_codes = []
            if tx_err_cca > 10000:
                comment_codes.append("thread_noise_severe")
            elif tx_err_cca > 1000:
                comment_codes.append("thread_noise_moderate")
            if tx_err_abort > 10000:
                comment_codes.append("tx_abort_severe")
            elif tx_err_abort > 1000:
                comment_codes.append("tx_abort_moderate")
            if rx_err_no_frame > 10000:
                comment_codes.append("rx_no_frame_severe")
            elif rx_err_no_frame > 1000:
                comment_codes.append("rx_no_frame_moderate")
            if rx_err_unknown > 1000:
                comment_codes.append("rx_unknown_neighbors")
            if rx_err_invalid > 1000:
                comment_codes.append("rx_invalid_source")
            if tx_retry > 100000:
                comment_codes.append("tx_retry_severe")
            elif tx_retry > 10000:
                comment_codes.append("tx_retry_moderate")
            node_info["error_comment_codes"] = comment_codes
            node_info["error_comment"] = _render_error_comment_en(comment_codes)

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
            last_interview = node.get("last_interview", "")
            existing_last_seen = self._last_seen.get(node_id, "")
            previous_available = self._previous_status.get(node_id)
            if available:
                if (previous_available is not None and not previous_available) or not existing_last_seen:
                    self._last_seen[node_id] = datetime.now(timezone.utc).isoformat()
                elif last_interview and last_interview > existing_last_seen:
                    self._last_seen[node_id] = last_interview
                online_count += 1
            else:
                # Always update from last_interview if it's more recent
                if last_interview:
                    if not existing_last_seen or last_interview > existing_last_seen:
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
            if thread_role_val in (4, 5, 6):  # 4=REED, 5=Router, 6=Leader
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
            node_info["_external_thread_neighbors"] = {}
            best_neighbor_signal: dict[str, int | None] | None = None
            if thread_role_val in (4, 5, 6) and isinstance(neighbor_table, list):
                for nb in neighbor_table:
                    if isinstance(nb, dict) and not nb.get("13", False):
                        signal_candidate = self._signal_candidate(nb.get("7"), nb.get("5"))
                        if self._better_signal(best_neighbor_signal, signal_candidate):
                            best_neighbor_signal = signal_candidate
                        nb_rloc = nb.get("2", 0)
                        nb_base = (nb_rloc >> 10) * 1024 if nb_rloc else None
                        if nb_base is not None:
                            node_info["_router_neighbors"][nb_base] = {
                                **signal_candidate,
                            }
                        ext_address = self._format_thread_ext_address(nb.get("0"))
                        if ext_address:
                            node_info["_external_thread_neighbors"][ext_address] = {
                                **signal_candidate,
                            }
            node_info["_best_neighbor_signal"] = best_neighbor_signal

            node_info["last_seen"] = self._last_seen.get(node_id, "")
            nodes.append(node_info)

        # Build RLOC base -> node info mapping
        rloc_to_node: dict[int, dict[str, Any]] = {}
        for n in nodes:
            if n["_rloc_base"] is not None:
                rloc_to_node[n["_rloc_base"]] = n
        nodes_by_id = {n["node_id"]: n for n in nodes if n.get("node_id") is not None}

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
            fallback_signal = n.pop("_best_neighbor_signal", None)
            recent_parent = self._recent_parents.get(n["node_id"])
            resolved_parent = None
            resolved_parent_rssi = parent_rssi
            resolved_parent_lqi = parent_lqi
            used_recent_parent = False
            can_use_recent_parent = (
                self._is_child_device_role(n["thread_role"])
                and recent_parent is not None
                and recent_parent["parent_node_id"] in nodes_by_id
            )

            if parent_rloc is not None and parent_rloc in rloc_to_node:
                resolved_parent = rloc_to_node[parent_rloc]
            elif can_use_recent_parent:
                resolved_parent = nodes_by_id[recent_parent["parent_node_id"]]
                resolved_parent_rssi = recent_parent.get("rssi")
                resolved_parent_lqi = recent_parent.get("lqi")
                used_recent_parent = True

            if resolved_parent is not None:
                resolved_parent_name = _preferred_node_name(resolved_parent)
                n["parent_node_id"] = resolved_parent["node_id"]
                n["parent_name"] = resolved_parent_name
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

            if (
                self._is_child_device_role(n["thread_role"])
                and resolved_parent is not None
            ):
                # Hop 1: parent router
                pr = resolved_parent
                path.append({
                    "node_id": pr["node_id"],
                    "name": pr["device_name"],
                    "role": pr["thread_role"],
                    "rssi": resolved_parent_rssi,
                    "lqi": resolved_parent_lqi,
                })
                self._extend_route_to_leader(
                    path,
                    pr.get("_rloc_base"),
                    leader_rloc_base,
                    rloc_to_node,
                )

            elif n["thread_role"] in ("router", "reed"):
                self._extend_route_to_leader(
                    path,
                    rloc_base,
                    leader_rloc_base,
                    rloc_to_node,
                )

            # Final hop: HA
            path.append({"node_id": None, "name": "Home Assistant", "role": "ha", "rssi": None, "lqi": None})
            n["route_path"] = path
            signal_hop = next(
                (
                    hop for hop in path[1:]
                    # Skip the device itself and inspect the upstream link.
                    if hop.get("rssi") is not None or hop.get("lqi") is not None
                ),
                None,
            )
            signal_source = signal_hop or fallback_signal or {}
            n["signal_rssi"] = signal_source.get("rssi")
            n["signal_lqi"] = signal_source.get("lqi")

            if (
                self._is_child_device_role(n["thread_role"])
                and resolved_parent is not None
                and not used_recent_parent
            ):
                self._remember_recent_parent(
                    n["node_id"],
                    resolved_parent["node_id"],
                    resolved_parent_name,
                    resolved_parent_rssi,
                    resolved_parent_lqi,
                )

        # Sort: offline first, then by node_id
        nodes.sort(key=lambda n: (n["available"], n["node_id"] or 0))

        return {
            "nodes": nodes,
            "total": len(nodes),
            "online": online_count,
            "offline": offline_count,
            "border_routers": self._normalize_border_routers(
                border_router_entries,
                nodes,
            ),
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
            return {"error": "Timeout - device did not respond"}
        except (aiohttp.ClientError, ConnectionError) as err:
            return {"error": f"Connection error: {err}"}
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


async def _async_register_lovelace_resources(hass: HomeAssistant) -> None:
    """Serve and preload the bundled Lovelace card modules."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(LOVELACE_RESOURCE_KEY):
        return

    static_paths: list[StaticPathConfig] = []
    resource_urls: list[str] = []
    cards_path = Path(__file__).parent / "www"

    for filename in LOVELACE_CARD_FILENAMES:
        asset_path = cards_path / filename
        if not asset_path.is_file():
            _LOGGER.warning("Missing Lovelace card asset: %s", asset_path)
            continue

        url = f"/api/{DOMAIN}/{filename}"
        version = str(asset_path.stat().st_mtime_ns)
        static_paths.append(
            StaticPathConfig(url, str(asset_path), cache_headers=True)
        )
        resource_urls.append(f"{url}?v={version}")

    if static_paths:
        await hass.http.async_register_static_paths(static_paths)
        for url in resource_urls:
            add_extra_js_url(hass, url)
        domain_data[LOVELACE_RESOURCE_KEY] = True


async def async_setup_entry(hass: HomeAssistant, entry: MatterSaverConfigEntry) -> bool:
    """Set up Matter Saver from a config entry."""
    url = entry.data.get(CONF_MATTER_URL, DEFAULT_MATTER_URL)

    await _async_register_lovelace_resources(hass)

    coordinator = MatterSaverCoordinator(hass, url)
    await coordinator.async_load_log()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    def _node_name(nid: int) -> str:
        """Get device name for a node_id from coordinator data."""
        if coordinator.data:
            for n in coordinator.data.get("nodes", []):
                if n["node_id"] == nid:
                    return n.get("device_name") or f"Node {nid}"
        return f"Node {nid}"

    async def _run_action(
        node_id: int,
        action: str,
        command: str,
        args: dict[str, Any],
        fallback_args: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run a Matter command with logging and error propagation."""
        from homeassistant.exceptions import HomeAssistantError
        name = _node_name(node_id)
        action_label = _action_label_en(action)
        coordinator.add_log(
            "action",
            node_id,
            name,
            f"{action_label} started",
            message_key="action_started",
            action=action,
        )
        result = await coordinator.send_matter_command(command, args)
        if isinstance(result, dict) and "error" in result and fallback_args:
            for candidate_args in fallback_args:
                fallback_result = await coordinator.send_matter_command(
                    command,
                    candidate_args,
                )
                if not (isinstance(fallback_result, dict) and "error" in fallback_result):
                    result = fallback_result
                    break
        if isinstance(result, dict) and "error" in result:
            error_msg = result["error"]
            coordinator.add_log(
                "error",
                node_id,
                name,
                f"{action_label} failed: {error_msg}",
                message_key="action_failed",
                action=action,
                error=error_msg,
            )
            raise HomeAssistantError(f"{action_label} failed: {error_msg}")
        coordinator.add_log(
            "success",
            node_id,
            name,
            f"{action_label} succeeded",
            message_key="action_succeeded",
            action=action,
        )
        return result

    async def handle_ping_node(call: ServiceCall) -> None:
        """Ping a Matter node."""
        node_id = call.data["node_id"]
        await _run_action(node_id, "ping", "ping_node", {"node_id": node_id})

    async def handle_interview_node(call: ServiceCall) -> None:
        """Re-interview a Matter node."""
        node_id = call.data["node_id"]
        await _run_action(
            node_id,
            "interview",
            "interview_node",
            {"node_id": node_id},
        )
        await coordinator.async_request_refresh()

    async def handle_reset_counters(call: ServiceCall) -> None:
        """Reset Thread diagnostic counters for a node."""
        node_id = call.data["node_id"]
        primary_args = {
            "node_id": node_id,
            "endpoint_id": 0,
            "cluster_id": 53,
            "command_name": "resetCounts",
            "payload": {},
        }
        result = await _run_action(
            node_id,
            "reset",
            "device_command",
            primary_args,
            fallback_args=[{
                "node_id": node_id,
                "endpoint_id": 0,
                "cluster_id": 53,
                "command_name": "ResetCounts",
                "payload": {},
            }],
        )
        await asyncio.sleep(1)
        await coordinator.send_matter_command("read_attribute", {
            "node_id": node_id,
            "attribute_path": "0/53/*",
            "fabric_filtered": False,
        })
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
