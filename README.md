# Matter Saver

Matter Saver is a Home Assistant custom integration for monitoring and managing Matter and Thread devices.

This fork is maintained at `https://github.com/hellosamblack/matter-saver` and focuses on keeping the integration, bundled Lovelace cards, and installation flow working reliably for HACS and manual installs.

## Why use Matter Saver?

Home Assistant already exposes Matter devices, but Matter Saver brings the troubleshooting and network context together in one place.

- See which devices are online, offline, battery-powered, or updateable at a glance
- Inspect Thread-specific details such as role, neighbors, children, and error counters
- Open route and topology views when a device is behaving like a tiny radio gremlin
- Run repair actions directly from the dashboard instead of hopping through multiple menus
- Keep a lightweight history of activity and offline behavior for recurring issues

## Highlights

- One main card for day-to-day device status, signal strength, tabbed diagnostics, and repair actions
- Dedicated log, topology, and mesh cards for deeper visibility
- Client-side English/German localization for card text, diagnostics, and activity log messages
- Offline history and activity tracking for recurring problems

## Requirements

- Home Assistant `2024.1.0` or newer
- A Matter Server reachable over WebSocket
  - Default URL: `ws://core-matter-server:5580/ws`
- Matter or Thread devices already commissioned into your environment

## Quick start

If you want the shortest path from install to a useful dashboard:

1. Install the integration through HACS.
2. Add the **Matter Saver** integration and enter your Matter Server WebSocket URL.
3. Open a dashboard and add the `matter-saver-card` from the Lovelace card picker.
4. Optionally add `matter-saver-log-card`, `matter-saver-topology-card`, or `matter-saver-mesh-card` for deeper visibility.

The main card is the best place to start because it combines device status, signal quality, route access, tabbed device details, and repair actions.

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant.
2. Open the three-dots menu and choose **Custom repositories**.
3. Add `https://github.com/hellosamblack/matter-saver` as an **Integration** repository.
4. Search for **Matter Saver** and install it.
5. Restart Home Assistant.
6. Go to **Settings → Devices & Services → Add Integration**.
7. Search for **Matter Saver**.
8. Enter your Matter Server WebSocket URL.

The Lovelace card resources are registered automatically after setup.

### Manual installation

1. Copy `custom_components/matter_saver/` into `/config/custom_components/`.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration**.
4. Search for **Matter Saver** and complete the setup flow.

The Lovelace card resources are registered automatically after setup.

## After installation

Once the integration is configured, you can add the included cards to a dashboard through the Lovelace card picker.

Matter Saver asks for one setting during setup:

- **Matter Server WebSocket URL** — the WebSocket endpoint used to connect to Matter Server

If you prefer editing a dashboard in YAML, this is a simple starting point:

```yaml
type: custom:matter-saver-card
entity: sensor.matter_saver_devices
title: Matter Devices
```

## Included cards

| Card | Purpose |
| --- | --- |
| `matter-saver-card` | Main device table with sorting, grouping, search, signal strength, route popup, tabbed device details, and visual editor support |
| `matter-saver-log-card` | Activity log with filtering, relative timestamps, and visual editor support |
| `matter-saver-topology-card` | Thread topology tree grouped by routers and their child devices |
| `matter-saver-mesh-card` | Interactive Thread mesh visualization with device-type icons, discovered Thread border routers, logical/floor/area/dollhouse layouts, and optional room-name trimming in labels |

The visual editor exposes card-specific options such as title overrides, default sorting and filters, topology or legend visibility, log entry limits, mesh layout mode, room-name trimming, floor/area ordering, and graph height, while preserving Home Assistant's built-in `Visibility` and `Layout` controls.

## Services

| Service | Description |
| --- | --- |
| `matter_saver.ping_node` | Ping a Matter node to check reachability |
| `matter_saver.interview_node` | Re-interview a Matter node to refresh its attributes |
| `matter_saver.reset_counters` | Reset Thread diagnostic error counters for a node |

## Data sources

| Source | Used for |
| --- | --- |
| Matter Server WebSocket API | Device availability, node attributes, and Thread diagnostics |
| Home Assistant device registry | Friendly names and areas |
| Home Assistant entity registry | Matter firmware update status |
| Matter cluster 40 | Basic device information |
| Matter cluster 47 | Battery level |
| Matter cluster 53 | Thread role, neighbors, routing, and error counters |
| Matter node metadata (`last_interview`, `interview_version`) | Per-node **Last Interview** (timestamp) and **Interview Version** diagnostic sensors, bound to each core Matter device |

## Roadmap

- **Auto-Recovery** — Periodically ping and re-interview offline nodes automatically once the background task is wired into startup
- **Help View** — Add a dedicated dashboard or help card that documents table columns, Thread roles, and color codes

## Releasing

- The installed integration version is read from `custom_components/matter_saver/manifest.json`.
- GitHub release detection compares that manifest version to the latest published GitHub release.
- Use the VS Code task `Matter Saver: Release next version` to:
  - bump the manifest version,
  - prompt for release notes,
  - commit the manifest change,
  - create and push a Git tag,
  - publish the GitHub release.
- Requirements: `git` and the GitHub CLI `gh` must be installed and authenticated.

## License

MIT
