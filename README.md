# Matter Saver

Custom Component for Home Assistant to monitor and manage Matter/Thread devices.

## Features

- **Device Overview** - All Matter devices in one sortable, filterable table
- **Thread Diagnostics** - Role (Router/Leader/SED), neighbors, children, error counters with analysis
- **Route Visualization** - Click any device to see its mesh path to Home Assistant with RSSI/LQI per hop
- **Thread Topology** - Visual tree of routers and their connected end devices
- **Action Popup** - Ping, Re-Interview, Reset Error Counters per device
- **Smart Recommendations** - Context-aware repair suggestions based on what was already tried
- **Auto-Recovery** - Automatically pings and re-interviews offline nodes every 5 minutes
- **Activity Log** - Persistent log of all status changes and actions with timestamps
- **Offline History** - Track how often and how long each device was offline (7d/30d stats)
- **Matter Server Restart** - One-click restart of the Matter Server addon when needed

## Dashboard Views

| View | Description |
|------|-------------|
| **Status** | Device table with 14 columns, sortable with group headers and search |
| **Activity** | Chronological log of all events, filterable |
| **Topology** | Thread mesh tree: routers and their children |
| **Help** | Documentation of all columns, thread roles, and color codes |

## Screenshots

*Coming soon*

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → **Custom repositories**
3. Add `https://github.com/cnc-lasercraft/matter-saver` as **Integration**
4. Search for "Matter Saver" and install
5. Restart Home Assistant
6. Go to **Settings → Integrations → Add Integration → Matter Saver**
7. Enter your Matter Server WebSocket URL (default: `ws://core-matter-server:5580/ws`)

### Manual

1. Copy `custom_components/matter_saver/` to your `/config/custom_components/` directory
2. Copy `www/matter-saver-card.js`, `www/matter-saver-log-card.js`, and `www/matter-saver-topology-card.js` to your `/config/www/` directory
3. Add the cards as dashboard resources (type: module):
   - `/local/matter-saver-card.js`
   - `/local/matter-saver-log-card.js`
   - `/local/matter-saver-topology-card.js`
4. Restart Home Assistant
5. Add the integration via UI

## Requirements

- Home Assistant 2024.1.0 or newer
- Matter Server addon running
- Matter/Thread devices commissioned

## Data Sources

| Source | Data |
|--------|------|
| Matter Server WebSocket API | Device status, node attributes, Thread diagnostics |
| HA Device Registry | Device names, areas |
| HA Entity Registry | Firmware update status |
| Matter Cluster 40 | Basic device information |
| Matter Cluster 47 | Battery level |
| Matter Cluster 53 | Thread role, neighbors, routing, error counters |

## Custom Cards

Three custom Lovelace cards are included:

- **`matter-saver-card`** - Main device table with sorting, grouping, search, action popup, and route popup
- **`matter-saver-log-card`** - Activity log with filtering and relative timestamps
- **`matter-saver-topology-card`** - Thread mesh topology tree

## Services

| Service | Description |
|---------|-------------|
| `matter_saver.ping_node` | Ping a Matter node to check reachability |
| `matter_saver.interview_node` | Re-interview a node to refresh its data |
| `matter_saver.reset_counters` | Reset Thread diagnostic error counters |

## License

MIT
