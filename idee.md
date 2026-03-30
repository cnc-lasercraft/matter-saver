# Matter Monitor - Custom Component für Home Assistant

## Problem

Matter/Thread-Geräte in Home Assistant haben keine zentrale Übersicht. Bei 43+ Geräten ist es unmöglich schnell zu sehen welches Gerät offline ist, welche Node-ID zu welchem Gerät gehört, oder wie das Thread-Mesh aufgebaut ist. Nach Neustarts fehlt jede Diagnose-Möglichkeit.

## Kernfeatures

### 1. Geräte-Übersicht Sensor
- Sensor mit allen Matter-Geräten als Attribute
- Pro Gerät: Name, Node-ID, Status (online/offline), letzter Kontakt
- Gruppierung nach: Batterie vs. Strombetrieben, Thread-Rolle (Router/Enddevice/Leader)
- Batterie-Level wenn verfügbar

### 2. Dashboard Card (Custom Lovelace Card)
- Tabelle aller Matter-Geräte sortierbar nach Status/Typ/Batterie
- Untertitel-Gruppierung: "Router (strombetrieben)" / "Enddevice (Batterie)"
- Farbcodierung: grün=online, rot=offline, gelb=kürzlich ausgefallen
- Node-ID prominent angezeigt (für Troubleshooting)
- Letzter Kontakt als relative Zeit ("vor 5 Min" / "vor 2 Std")

### 3. Auto-Recovery
- Erkennt wenn Geräte länger als X Minuten offline sind
- Versucht automatisch Re-Subscribe über Matter Server
- Konfigurierbare Wartezeit und Retry-Anzahl

### 4. Benachrichtigungen
- Push-Notification wenn mehr als X Geräte gleichzeitig offline gehen
- Zusammenfassende Meldung ("12 Matter-Geräte offline seit 10:30")
- Einzelmeldung wenn kritische Geräte (z.B. Wasserleck-Sensoren) ausfallen

### 5. Thread-Netzwerk Info (optional, via OTBR API)
- Thread-Netzwerk-Status (Channel, PAN ID, Network Name)
- Router-Topology (welches Gerät routet für welche Enddevices)
- Integration mit bestehender thread-topology CC oder eigene Implementation

## Technische Basis

- **Datenquelle:** Matter Server WebSocket API (ws://core-matter-server:5580/ws)
- **Thread-Info:** OTBR REST API (http://core-openthread-border-router:8081)
- **Node-ID Mapping:** Matter Server liefert Node-ID + Geräteinfo, HA Device Registry liefert friendly_name
- **Custom Card:** JavaScript, ähnlich Pattern wie andere HA Custom Cards

## Bestehendes Ökosystem

- **thread-topology** (jjtortosa/thread-topology) - Visualisiert Thread-Mesh, könnte als Referenz dienen
- **Matter Server Addon** - liefert die Daten via WebSocket
- **HA Matter Integration** - built-in, aber ohne Monitoring-Features

## Scope

**MVP (v0.1):**
- Sensor mit Geräteliste + Status + Node-ID Mapping
- Einfache Entities-Card oder Markdown-Card als Dashboard

**v0.2:**
- Custom Lovelace Card mit Sortierung/Gruppierung
- Offline-Benachrichtigungen

**v0.3:**
- Auto-Recovery
- Thread-Topology Integration
- HACS-kompatibel zum Teilen

## Entstanden aus

Reales Problem: Nach mehreren HA-Neustarts waren 34 von 43 Matter-Geräten (alle IKEA, Thread) offline. Keine Möglichkeit schnell zu sehen welche fehlen, welche Node-IDs betroffen sind, oder das Mesh zu diagnostizieren. Manuelles Durchklicken von 43 Geräten im Matter Server UI war die einzige Option.
