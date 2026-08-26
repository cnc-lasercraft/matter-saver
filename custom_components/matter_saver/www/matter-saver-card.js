class MatterSaverCard extends HTMLElement {
  constructor() {
    super();
    this._sortField = "status";
    this._sortAsc = true;
    this._filter = "";
    this._lastDataJson = "";
    this._initialized = false;
    this._devices = [];
  }

  setConfig(config) {
    this.config = config;
    this._entityId = config.entity || "sensor.matter_saver_devices";
  }

  set hass(hass) {
    this._hass = hass;
    const state = hass.states[this._entityId];
    const dataJson = state ? JSON.stringify(state.attributes) : "";
    if (!this._initialized) {
      this._fullRender();
      this._initialized = true;
    } else if (dataJson !== this._lastDataJson) {
      this._lastDataJson = dataJson;
      this._updateTable();
    }
  }

  _fullRender() {
    const state = this._hass.states[this._entityId];
    if (!state) {
      this.innerHTML = `<ha-card header="Matter Saver"><div class="card-content">Entity not found</div></ha-card>`;
      return;
    }
    this._lastDataJson = JSON.stringify(state.attributes);
    const CC = 14;

    this.innerHTML = `
      <ha-card>
        <style>
          .ms-header { padding: 16px 16px 8px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
          .ms-title { font-size: 1.2em; font-weight: 500; }
          .ms-stats { display: flex; gap: 12px; font-size: 0.9em; }
          .ms-stat { display: flex; align-items: center; gap: 4px; }
          .ms-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
          .ms-dot.online { background: #4caf50; }
          .ms-dot.offline { background: #f44336; }
          .ms-search-wrap { padding: 0 16px 8px; }
          .ms-search {
            width: 100%; padding: 8px 12px; box-sizing: border-box;
            border: 1px solid var(--divider-color, #333);
            border-radius: 8px; font-size: 0.9em;
            background: var(--card-background-color, #1c1c1c);
            color: var(--primary-text-color, #fff); outline: none;
          }
          .ms-search:focus { border-color: var(--primary-color, #03a9f4); }
          .ms-search::placeholder { color: var(--secondary-text-color, #999); }
          .ms-table { width: 100%; border-collapse: collapse; font-size: 0.85em; }
          .ms-table th {
            text-align: left; padding: 8px 12px; cursor: pointer; user-select: none;
            border-bottom: 2px solid var(--divider-color, #333);
            color: var(--secondary-text-color, #999);
            font-weight: 500; font-size: 0.85em; text-transform: uppercase; white-space: nowrap;
          }
          .ms-table th:hover { color: var(--primary-color, #03a9f4); }
          .ms-table th.sorted { color: var(--primary-color, #03a9f4); }
          .ms-table th .arrow { font-size: 0.7em; margin-left: 2px; }
          .ms-table td { padding: 6px 12px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.05)); }
          .ms-table tr:last-child td { border-bottom: none; }
          .ms-group-header td {
            padding: 16px 12px 8px; font-weight: 700; font-size: 1.1em;
            color: var(--primary-color, #03a9f4);
            border-bottom: 2px solid var(--primary-color, #03a9f4);
            background: var(--card-background-color, transparent); letter-spacing: 0.02em;
          }
          .ms-status { display: flex; align-items: center; gap: 6px; }
          .ms-battery { display: flex; align-items: center; gap: 4px; }
          .ms-battery.low { color: #ff9800; }
          .ms-battery.critical { color: #f44336; }
          .ms-lastseen { color: var(--secondary-text-color, #999); font-size: 0.9em; }
          .ms-offline-row { opacity: 0.7; }
          .ms-errors { display: flex; align-items: center; gap: 6px; }
          .ms-errors .count { font-weight: 500; }
          .ms-errors .comment { font-size: 0.85em; color: var(--secondary-text-color, #999); font-style: italic; }
          .ms-no-results td { text-align: center; padding: 20px; color: var(--secondary-text-color, #999); }
          .ms-parent-link { cursor: pointer; color: var(--primary-color, #03a9f4); text-decoration: underline; }
          .ms-parent-link:hover { opacity: 0.8; }
          .ms-name-link { cursor: pointer; }
          .ms-name-link:hover { color: var(--primary-color, #03a9f4); }

          /* Action Modal */
          .ms-action-details { margin-bottom: 16px; }
          .ms-action-details table { width: 100%; font-size: 0.9em; }
          .ms-action-details td { padding: 4px 8px; }
          .ms-action-details td:first-child { color: var(--secondary-text-color, #999); width: 100px; }
          .ms-action-buttons { display: flex; gap: 10px; flex-wrap: wrap; }
          .ms-action-btn {
            padding: 10px 18px; border: none; border-radius: 10px; cursor: pointer;
            font-size: 0.9em; font-weight: 500; display: flex; align-items: center; gap: 6px;
            transition: opacity 0.2s;
          }
          .ms-action-btn:hover { opacity: 0.85; }
          .ms-action-btn:disabled { opacity: 0.4; cursor: not-allowed; }
          .ms-action-btn.ping { background: #1b5e20; color: #fff; }
          .ms-action-btn.interview { background: #0d47a1; color: #fff; }
          .ms-action-btn.reset { background: #e65100; color: #fff; }
          .ms-action-status {
            margin-top: 12px; padding: 10px; border-radius: 8px; font-size: 0.85em; display: none;
          }
          .ms-action-status.show { display: block; }
          .ms-action-status.success { background: #1b5e2033; color: #4caf50; }
          .ms-action-status.error { background: #b7140033; color: #f44336; }
          .ms-action-status.loading { background: #01579b33; color: #03a9f4; }
          .ms-suggestion {
            margin: 12px 0; padding: 12px; border-radius: 10px; font-size: 0.85em; line-height: 1.5;
            background: #01579b22; border-left: 3px solid #03a9f4;
          }
          .ms-suggestion.warn {
            background: #e6510022; border-left-color: #ff9800;
          }

          /* Route Modal */
          .ms-modal-overlay {
            display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0,0,0,0.6); z-index: 9999; justify-content: center; align-items: center;
          }
          .ms-modal-overlay.open { display: flex; }
          .ms-modal {
            background: var(--ha-card-background, var(--card-background-color, #1c1c1c));
            border-radius: 16px; padding: 24px; max-width: 500px; width: 90%;
            box-shadow: 0 8px 32px rgba(0,0,0,0.5); color: var(--primary-text-color, #fff);
          }
          .ms-modal-title { font-size: 1.2em; font-weight: 600; margin-bottom: 16px; }
          .ms-modal-close {
            float: right; cursor: pointer; font-size: 1.5em; line-height: 1;
            color: var(--secondary-text-color, #999); background: none; border: none;
          }
          .ms-modal-close:hover { color: var(--primary-text-color, #fff); }
          .ms-route { display: flex; flex-direction: column; gap: 0; }
          .ms-route-hop {
            display: flex; align-items: center; gap: 12px; padding: 10px 0;
          }
          .ms-route-icon {
            width: 40px; height: 40px; border-radius: 50%; display: flex;
            align-items: center; justify-content: center; font-size: 1.2em; flex-shrink: 0;
          }
          .ms-route-info { flex: 1; }
          .ms-route-name { font-weight: 600; font-size: 0.95em; }
          .ms-route-detail { font-size: 0.8em; color: var(--secondary-text-color, #999); }
          .ms-route-connector {
            width: 40px; display: flex; justify-content: center; flex-shrink: 0;
          }
          .ms-route-connector .line {
            width: 2px; height: 24px;
            background: linear-gradient(to bottom, var(--primary-color, #03a9f4), var(--primary-color, #03a9f4));
          }
          .ms-route-signal { text-align: right; min-width: 70px; }
          .ms-route-signal .rssi { font-weight: 500; font-size: 0.9em; }
          .ms-route-signal .lqi { font-size: 0.8em; color: var(--secondary-text-color, #999); }
        </style>
        <div class="ms-header">
          <span class="ms-title">Matter Devices</span>
          <div class="ms-stats" id="ms-stats"></div>
        </div>
        <div class="ms-search-wrap">
          <input type="text" class="ms-search" id="ms-search" placeholder="Filter devices..." />
        </div>
        <div class="card-content" style="padding: 0 8px 16px; overflow-x: auto;">
          <table class="ms-table">
            <thead id="ms-thead"></thead>
            <tbody id="ms-tbody"></tbody>
          </table>
        </div>
        <div class="ms-modal-overlay" id="ms-modal">
          <div class="ms-modal">
            <button class="ms-modal-close" id="ms-modal-close">&times;</button>
            <div class="ms-modal-title" id="ms-modal-title"></div>
            <div class="ms-route" id="ms-route"></div>
          </div>
        </div>
        <div class="ms-modal-overlay" id="ms-action-modal">
          <div class="ms-modal">
            <button class="ms-modal-close" id="ms-action-modal-close">&times;</button>
            <div class="ms-modal-title" id="ms-action-title"></div>
            <div class="ms-action-details" id="ms-action-details"></div>
            <div class="ms-action-buttons" id="ms-action-buttons"></div>
            <div class="ms-action-status" id="ms-action-status"></div>
          </div>
        </div>
      </ha-card>
    `;

    // Sort header clicks
    this.querySelector("#ms-thead").addEventListener("click", (e) => {
      const th = e.target.closest("th[data-field]");
      if (!th) return;
      const field = th.dataset.field;
      if (this._sortField === field) { this._sortAsc = !this._sortAsc; }
      else { this._sortField = field; this._sortAsc = true; }
      this._updateTable();
    });

    // Search
    this.querySelector("#ms-search").addEventListener("input", (e) => {
      this._filter = e.target.value.toLowerCase();
      this._updateTable();
    });

    // Table click delegation
    this.querySelector("#ms-tbody").addEventListener("click", (e) => {
      const parentLink = e.target.closest(".ms-parent-link");
      if (parentLink) {
        this._showRoutePopup(parseInt(parentLink.dataset.nodeId));
        return;
      }
      const nameLink = e.target.closest(".ms-name-link");
      if (nameLink) {
        this._showActionPopup(parseInt(nameLink.dataset.nodeId));
        return;
      }
    });

    // Close modals
    const modal = this.querySelector("#ms-modal");
    this.querySelector("#ms-modal-close").addEventListener("click", () => modal.classList.remove("open"));
    modal.addEventListener("click", (e) => { if (e.target === modal) modal.classList.remove("open"); });

    const actionModal = this.querySelector("#ms-action-modal");
    this.querySelector("#ms-action-modal-close").addEventListener("click", () => actionModal.classList.remove("open"));
    actionModal.addEventListener("click", (e) => { if (e.target === actionModal) actionModal.classList.remove("open"); });

    this._updateTable();
  }

  _showRoutePopup(nodeId) {
    const device = this._devices.find(d => d.node_id === nodeId);
    if (!device || !device.route_path) return;

    const titleEl = this.querySelector("#ms-modal-title");
    const routeEl = this.querySelector("#ms-route");
    const modal = this.querySelector("#ms-modal");

    titleEl.textContent = `Route: ${device.name}`;

    const roleIcons = {
      "sed": "\uD83D\uDD0B", "end_device": "\uD83D\uDD0C", "reed": "\uD83D\uDD00",
      "router": "\uD83D\uDCE1", "leader": "\u2B50", "ha": "\uD83C\uDFE0",
      "unknown": "\u2753",
    };
    const roleColors = {
      "sed": "#78909c", "end_device": "#78909c", "reed": "#8bc34a",
      "router": "#4caf50", "leader": "#ffb300", "ha": "#03a9f4",
    };

    let html = "";
    const path = device.route_path;
    for (let i = 0; i < path.length; i++) {
      const hop = path[i];
      const icon = roleIcons[hop.role] || "\u2753";
      const color = roleColors[hop.role] || "#999";
      const roleLabel = this._threadRoleLabel(hop.role === "ha" ? "" : hop.role);

      // Signal quality
      let signalHtml = "";
      if (hop.rssi != null) {
        const rssiColor = hop.rssi > -70 ? "#4caf50" : hop.rssi > -85 ? "#ff9800" : "#f44336";
        const lqiLabel = hop.lqi != null ? `LQI ${hop.lqi}/3` : "";
        signalHtml = `<div class="ms-route-signal"><div class="rssi" style="color:${rssiColor}">${hop.rssi} dBm</div><div class="lqi">${lqiLabel}</div></div>`;
      }

      html += `<div class="ms-route-hop">
        <div class="ms-route-icon" style="background:${color}22;color:${color}">${icon}</div>
        <div class="ms-route-info">
          <div class="ms-route-name">${this._escHtml(hop.name || "Unknown")}</div>
          <div class="ms-route-detail">${hop.node_id != null ? `Node ${hop.node_id} \u2022 ` : ""}${hop.role === "ha" ? "Border Router Gateway" : roleLabel}</div>
        </div>
        ${signalHtml}
      </div>`;

      if (i < path.length - 1) {
        html += `<div class="ms-route-hop"><div class="ms-route-connector"><div class="line"></div></div></div>`;
      }
    }

    routeEl.innerHTML = html;
    modal.classList.add("open");
  }

  _showActionPopup(nodeId) {
    const device = this._devices.find(d => d.node_id === nodeId);
    if (!device) return;

    const titleEl = this.querySelector("#ms-action-title");
    const detailsEl = this.querySelector("#ms-action-details");
    const buttonsEl = this.querySelector("#ms-action-buttons");
    const statusEl = this.querySelector("#ms-action-status");
    const modal = this.querySelector("#ms-action-modal");

    titleEl.textContent = device.name || `Node ${nodeId}`;
    // Preserve status message during refresh
    if (!this._keepStatus) {
      statusEl.className = "ms-action-status";
      statusEl.textContent = "";
    }
    this._keepStatus = false;

    // Device details table
    const rows = [
      ["Node ID", device.node_id],
      ["Product", device.product],
      ["Area", device.area || "-"],
      ["Status", device.status],
      ["Thread", this._threadRoleLabel(device.thread_role)],
      ["Parent", device.parent || "-"],
      ["Power", device.power],
      ["Battery", device.battery != null ? `${Math.round(device.battery)}%` : "-"],
      ["Firmware", device.firmware || "-"],
      ["Errors", device.errors ? device.errors.toLocaleString() : "0"],
    ];
    if (device.error_comment) rows.push(["Diagnose", device.error_comment]);

    // Offline history stats
    if (device.offline_7d_count > 0 || device.offline_30d_count > 0) {
      const fmt = (min) => min < 60 ? `${min}m` : min < 1440 ? `${Math.round(min/60)}h` : `${(min/1440).toFixed(1)}d`;
      if (device.offline_7d_count > 0)
        rows.push(["Offline 7d", `${device.offline_7d_count}x, total ${fmt(device.offline_7d_minutes)}`]);
      if (device.offline_30d_count > 0)
        rows.push(["Offline 30d", `${device.offline_30d_count}x, total ${fmt(device.offline_30d_minutes)}`]);
    }

    // Get repair history for this node from activity log
    const logState = this._hass.states["sensor.matter_saver_activity_log"];
    const allEntries = logState ? (logState.attributes.entries || []) : [];
    const nodeHistory = allEntries.filter(e => e.node_id === nodeId);

    // Analyze what was already tried
    const triedPing = nodeHistory.some(e => e.message && e.message.includes("Ping"));
    const pingOk = nodeHistory.some(e => e.level === "success" && e.message && e.message.includes("Ping"));
    const pingFail = nodeHistory.some(e => e.level === "error" && e.message && e.message.includes("Ping"));
    const triedInterview = nodeHistory.some(e => e.message && e.message.includes("Interview"));
    const interviewOk = nodeHistory.some(e => e.level === "success" && e.message && e.message.includes("Interview"));
    const interviewFail = nodeHistory.some(e => e.level === "error" && e.message && e.message.includes("Interview"));
    const triedReset = nodeHistory.some(e => e.message && e.message.includes("Reset"));

    // Build smart suggestion
    let suggestion = "";
    if (device.status === "offline") {
      if (!triedPing) {
        suggestion = `<div class="ms-suggestion">\uD83D\uDCA1 <strong>Empfehlung:</strong> Zuerst Ping versuchen um zu prüfen ob das Gerät auf Thread-Ebene erreichbar ist.</div>`;
      } else if (pingOk && !triedInterview) {
        suggestion = `<div class="ms-suggestion">\uD83D\uDCA1 <strong>Empfehlung:</strong> Ping war erfolgreich - das Gerät ist auf Thread-Ebene erreichbar. Re-Interview versuchen um die Matter-Verbindung neu aufzubauen.</div>`;
      } else if (pingOk && interviewFail) {
        suggestion = `<div class="ms-suggestion warn">\u26A0\uFE0F <strong>Empfehlung:</strong> Ping OK aber Re-Interview gescheitert - die Matter-Application reagiert nicht.<br><br>1. Matter Server Addon neustarten: <button class="ms-action-btn" id="ms-restart-addon" style="background:#b71c1c;color:#fff;display:inline-flex;padding:6px 14px;font-size:0.85em;margin:4px 0">\u26A1 Matter Server Restart</button><br>2. Falls das nicht hilft: Gerät physisch vom Strom trennen (5 Sek) und wieder einstecken</div>`;
      } else if (pingFail) {
        suggestion = `<div class="ms-suggestion warn">\u26A0\uFE0F <strong>Empfehlung:</strong> Ping fehlgeschlagen - das Gerät ist nicht erreichbar. Mögliche Ursachen:<br>1. Kein Strom \u2192 Stecker/Sicherung prüfen<br>2. Ausserhalb Thread-Reichweite \u2192 näher an einen Router stellen<br>3. Hardware-Defekt</div>`;
      }
    } else if (device.errors > 10000) {
      if (!triedReset) {
        suggestion = `<div class="ms-suggestion">\uD83D\uDCA1 <strong>Empfehlung:</strong> Hohe Error-Zähler. Reset Counters ausführen und beobachten ob die Fehler wiederkommen. Falls ja, Gerät umplatzieren.</div>`;
      } else {
        suggestion = `<div class="ms-suggestion warn">\u26A0\uFE0F <strong>Empfehlung:</strong> Counter wurden bereits zurückgesetzt. Falls Fehler weiter steigen: Gerät steht vermutlich in einem Bereich mit starken Funkstörungen (WLAN, Mikrowelle). Umplatzieren oder Thread-Kanal prüfen.</div>`;
      }
    }

    // Repair history HTML
    let historyHtml = "";
    if (nodeHistory.length > 0) {
      const histIcons = {"action": "\u26A1", "success": "\u2705", "error": "\u274C", "info": "\uD83D\uDFE2", "warning": "\u26A0\uFE0F"};
      historyHtml = `<div class="ms-repair-history">
        <div style="font-weight:600;font-size:0.85em;margin:12px 0 6px;color:var(--secondary-text-color,#999)">REPAIR HISTORY</div>
        ${nodeHistory.slice(0, 10).map(e => {
          const ts = new Date(e.timestamp);
          const time = ts.toLocaleTimeString("de-CH", {hour:"2-digit",minute:"2-digit"});
          const date = ts.toLocaleDateString("de-CH");
          const icon = histIcons[e.level] || "\u2139\uFE0F";
          const color = e.level === "success" ? "#4caf50" : e.level === "error" ? "#f44336" : e.level === "action" ? "#ce93d8" : "#999";
          return `<div style="display:flex;gap:8px;padding:3px 0;font-size:0.8em"><span>${icon}</span><span style="color:${color}">${this._escHtml(e.message)}</span><span style="color:var(--secondary-text-color,#666);margin-left:auto;white-space:nowrap">${date} ${time}</span></div>`;
        }).join("")}
      </div>`;
    }

    detailsEl.innerHTML = `<table>${rows.map(([k, v]) =>
      `<tr><td>${k}</td><td>${this._escHtml(String(v))}</td></tr>`
    ).join("")}</table>${suggestion}${historyHtml}`;

    // Action buttons
    buttonsEl.innerHTML = `
      <button class="ms-action-btn ping" data-action="ping" data-node="${nodeId}">\uD83C\uDFD3 Ping</button>
      <button class="ms-action-btn interview" data-action="interview" data-node="${nodeId}">\uD83D\uDD04 Re-Interview</button>
      <button class="ms-action-btn reset" data-action="reset" data-node="${nodeId}">\uD83D\uDDD1 Reset Counters</button>
    `;

    // Attach button handlers
    buttonsEl.querySelectorAll(".ms-action-btn").forEach(btn => {
      btn.addEventListener("click", () => this._executeAction(btn.dataset.action, parseInt(btn.dataset.node)));
    });

    modal.classList.add("open");

    // Restart addon button (in suggestion)
    const restartBtn = this.querySelector("#ms-restart-addon");
    if (restartBtn) {
      restartBtn.addEventListener("click", () => this._restartMatterAddon(nodeId));
    }
  }

  async _executeAction(action, nodeId) {
    const statusEl = this.querySelector("#ms-action-status");
    const buttons = this.querySelectorAll(".ms-action-btn");

    // Disable buttons during execution
    buttons.forEach(b => b.disabled = true);
    statusEl.className = "ms-action-status show loading";

    const serviceMap = {
      "ping": "ping_node",
      "interview": "interview_node",
      "reset": "reset_counters",
    };
    const labels = {
      "ping": "Ping",
      "interview": "Re-Interview",
      "reset": "Reset Counters",
    };

    const hints = {
      "ping": "Ping wird ausgeführt...",
      "interview": "Re-Interview läuft, das kann bis zu 30 Sekunden dauern...",
      "reset": "Error Counter werden zurückgesetzt...",
    };
    statusEl.textContent = hints[action] || `${labels[action]} wird ausgeführt...`;

    try {
      await this._hass.callService("matter_saver", serviceMap[action], { node_id: nodeId });
      statusEl.className = "ms-action-status show success";
      statusEl.textContent = `${labels[action]} erfolgreich für Node ${nodeId}`;
    } catch (err) {
      statusEl.className = "ms-action-status show error";
      statusEl.textContent = `Fehler: ${err.message || err}`;
    }

    buttons.forEach(b => b.disabled = false);

    // Wait for log sensor to update, then refresh history + suggestion (keep status)
    const refreshPopup = () => {
      const modal = this.querySelector("#ms-action-modal");
      if (modal && modal.classList.contains("open")) {
        this._keepStatus = true;
        this._showActionPopup(nodeId);
      }
    };
    setTimeout(refreshPopup, 2000);
    setTimeout(refreshPopup, 5000);
  }

  async _restartMatterAddon(nodeId) {
    const statusEl = this.querySelector("#ms-action-status");
    if (!confirm("Matter Server Addon neustarten?\n\nAlle Matter-Geräte werden kurzzeitig offline sein (30-60 Sek).")) return;

    statusEl.className = "ms-action-status show loading";
    statusEl.textContent = "Matter Server Addon wird neu gestartet, alle Geräte werden kurzzeitig offline...";

    try {
      await this._hass.callService("hassio", "addon_restart", { addon: "core_matter_server" });
      statusEl.className = "ms-action-status show success";
      statusEl.textContent = "Matter Server Addon neu gestartet. Geräte kommen in 1-5 Minuten zurück.";
    } catch (err) {
      statusEl.className = "ms-action-status show error";
      statusEl.textContent = `Fehler: ${err.message || err}`;
    }
  }

  _updateTable() {
    const state = this._hass.states[this._entityId];
    if (!state) return;

    let devices = state.attributes.devices || [];
    const online = state.attributes.online || 0;
    const offline = state.attributes.offline || 0;
    const CC = 14;

    const statsEl = this.querySelector("#ms-stats");
    if (statsEl) {
      statsEl.innerHTML = `
        <span class="ms-stat"><span class="ms-dot online"></span> ${online} online</span>
        <span class="ms-stat"><span class="ms-dot offline"></span> ${offline} offline</span>
      `;
    }

    const theadEl = this.querySelector("#ms-thead");
    if (theadEl) {
      theadEl.innerHTML = `<tr>
        ${this._th("node_id", "Node")}
        ${this._th("name", "Name")}
        ${this._th("area", "Area")}
        ${this._th("product", "Product")}
        ${this._th("status", "Status")}
        ${this._th("thread_role", "Thread")}
        ${this._th("neighbors", "Neighbors")}
        ${this._th("children", "Children")}
        ${this._th("parent", "Parent")}
        ${this._th("power", "Power")}
        ${this._th("battery", "Battery")}
        ${this._th("firmware", "Firmware")}
        ${this._th("errors", "Errors")}
        ${this._th("last_seen", "Last Seen")}
      </tr>`;
    }

    if (this._filter) {
      devices = devices.filter((d) => {
        const searchable = [
          d.name, d.area, d.product, d.status, d.power,
          d.firmware, d.thread_role, d.parent, String(d.node_id),
        ].join(" ").toLowerCase();
        return searchable.includes(this._filter);
      });
    }

    this._devices = devices;

    const tbodyEl = this.querySelector("#ms-tbody");
    if (tbodyEl) {
      if (devices.length === 0) {
        tbodyEl.innerHTML = `<tr class="ms-no-results"><td colspan="${CC}">No devices found</td></tr>`;
      } else {
        const sorted = this._sortDevices(devices);
        tbodyEl.innerHTML = this._groupDevices(sorted, CC);
      }
    }
  }

  _th(field, label) {
    const sorted = this._sortField === field;
    const arrow = sorted ? (this._sortAsc ? " \u25B2" : " \u25BC") : "";
    return `<th data-field="${field}" class="${sorted ? "sorted" : ""}">${label}<span class="arrow">${arrow}</span></th>`;
  }

  _sortDevices(devices) {
    const field = this._sortField;
    const asc = this._sortAsc;
    return [...devices].sort((a, b) => {
      let va = a[field]; let vb = b[field];
      if (va == null) va = field === "battery" ? 999 : "";
      if (vb == null) vb = field === "battery" ? 999 : "";
      if (field === "node_id" || field === "battery" || field === "neighbors" || field === "children" || field === "errors") {
        va = Number(va) || 0; vb = Number(vb) || 0;
      } else { va = String(va).toLowerCase(); vb = String(vb).toLowerCase(); }
      if (va < vb) return asc ? -1 : 1;
      if (va > vb) return asc ? 1 : -1;
      return 0;
    });
  }

  _groupDevices(devices, CC) {
    const field = this._sortField;
    let html = ""; let lastGroup = null;
    for (const d of devices) {
      let groupVal = this._groupValue(d, field);
      if (groupVal !== lastGroup) {
        html += `<tr class="ms-group-header"><td colspan="${CC}">${this._escHtml(groupVal)}</td></tr>`;
        lastGroup = groupVal;
      }
      html += this._deviceRow(d);
    }
    return html;
  }

  _groupValue(device, field) {
    switch (field) {
      case "status": return device.status === "online" ? "Online" : "Offline";
      case "power": return device.power === "battery" ? "Battery" : "Wired";
      case "product": return device.product || "Unknown";
      case "area": return device.area || "No Area";
      case "firmware": return device.firmware || "Unknown";
      case "thread_role": return this._threadRoleLabel(device.thread_role);
      case "parent": return device.parent || "No Parent (Router)";
      case "battery":
        if (device.battery == null) return "No Battery";
        if (device.battery < 20) return "Critical (< 20%)";
        if (device.battery < 50) return "Low (< 50%)";
        return "Good (50%+)";
      case "errors":
        if (!device.errors || device.errors === 0) return "No Errors";
        if (device.errors > 100000) return "Critical";
        if (device.errors > 10000) return "High";
        if (device.errors > 1000) return "Moderate";
        return "Low";
      case "last_seen":
        if (!device.last_seen) return "Never seen";
        return "Seen";
      default: return "";
    }
  }

  _deviceRow(d) {
    const statusIcon = d.status === "online" ? "\uD83D\uDFE2" : "\uD83D\uDD34";
    const rowClass = d.status === "offline" ? "ms-offline-row" : "";
    const parentHtml = d.parent
      ? `<span class="ms-parent-link" data-node-id="${d.node_id}">${this._escHtml(d.parent)}</span>`
      : (d.thread_role === "router" || d.thread_role === "leader" || d.thread_role === "reed")
        ? `<span class="ms-parent-link" data-node-id="${d.node_id}">Router</span>`
        : "-";

    return `<tr class="${rowClass}">
      <td>${d.node_id}</td>
      <td><span class="ms-name-link" data-node-id="${d.node_id}">${this._escHtml(d.name)}</span></td>
      <td>${this._escHtml(d.area)}</td>
      <td>${this._escHtml(d.product)}</td>
      <td><span class="ms-status">${statusIcon} ${d.status}</span></td>
      <td>${this._threadRoleHtml(d.thread_role)}</td>
      <td>${d.neighbors || "-"}</td>
      <td>${d.children || "-"}</td>
      <td>${parentHtml}</td>
      <td>${d.power}</td>
      <td>${this._batteryHtml(d.battery)}</td>
      <td>${this._firmwareHtml(d.firmware, d.update_available)}</td>
      <td>${this._errorsHtml(d.errors, d.error_comment)}</td>
      <td>${this._lastSeenHtml(d.last_seen)}</td>
    </tr>`;
  }

  _threadRoleLabel(role) {
    const labels = {
      "leader": "Leader", "router": "Router", "reed": "REED",
      "end_device": "End Device", "sed": "Sleepy End Device",
      "unassigned": "Unassigned", "unspecified": "Unspecified",
    };
    return labels[role] || role || "Unknown";
  }

  _threadRoleHtml(role) {
    const label = this._threadRoleLabel(role);
    let color = "var(--secondary-text-color, #999)";
    if (role === "leader") color = "#ffb300";
    else if (role === "router") color = "#4caf50";
    else if (role === "reed") color = "#8bc34a";
    return `<span style="color:${color};font-weight:${role === "leader" ? 700 : 400}">${label}</span>`;
  }

  _errorsHtml(errors, comment) {
    if (!errors || errors === 0) return `<span style="color:#4caf50">0</span>`;
    let color = "#4caf50";
    if (errors > 100000) color = "#f44336";
    else if (errors > 10000) color = "#ff9800";
    else if (errors > 1000) color = "#ffb300";
    const countStr = errors > 999999 ? `${(errors / 1000000).toFixed(1)}M` : errors > 999 ? `${(errors / 1000).toFixed(1)}k` : String(errors);
    let html = `<span class="ms-errors"><span class="count" style="color:${color}">${countStr}</span>`;
    if (comment) html += `<span class="comment">${this._escHtml(comment)}</span>`;
    html += `</span>`;
    return html;
  }

  _firmwareHtml(firmware, updateAvailable) {
    if (!firmware) return "-";
    const dot = updateAvailable
      ? `<span class="ms-dot offline" style="width:8px;height:8px;display:inline-block;vertical-align:middle;margin-right:4px" title="Update available"></span>`
      : `<span class="ms-dot online" style="width:8px;height:8px;display:inline-block;vertical-align:middle;margin-right:4px" title="Up to date"></span>`;
    return `${dot}${this._escHtml(firmware)}`;
  }

  _batteryHtml(battery) {
    if (battery == null) return "-";
    let cls = "";
    if (battery < 20) cls = "critical";
    else if (battery < 50) cls = "low";
    return `<span class="ms-battery ${cls}">${Math.round(battery)}%</span>`;
  }

  _lastSeenHtml(isoStr) {
    if (!isoStr) return `<span class="ms-lastseen">-</span>`;
    const then = new Date(isoStr);
    const now = new Date();
    const diffMin = Math.floor((now - then) / 60000);
    let text;
    if (diffMin < 1) text = "just now";
    else if (diffMin < 60) text = `${diffMin}m ago`;
    else if (diffMin < 1440) text = `${Math.floor(diffMin / 60)}h ago`;
    else text = `${Math.floor(diffMin / 1440)}d ago`;
    return `<span class="ms-lastseen">${text}</span>`;
  }

  _escHtml(str) {
    const div = document.createElement("div");
    div.textContent = str || "";
    return div.innerHTML;
  }

  getCardSize() { return 8; }
}

customElements.define("matter-saver-card", MatterSaverCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "matter-saver-card",
  name: "Matter Saver Card",
  description: "Sortable Matter device table with route visualization",
});

/* ── Sidebar Badge: show offline device count ── */
(function initSidebarBadge() {
  const LABEL = "Matter Saver";
  const ENTITY = "sensor.matter_saver_offline";
  const BADGE_ID = "ms-sidebar-badge";

  function getHass() {
    const el = document.querySelector("home-assistant");
    return el && (el.hass || el.__hass);
  }

  function findSidebarItem() {
    try {
      const sidebar = document.querySelector("home-assistant")
        ?.shadowRoot?.querySelector("home-assistant-main")
        ?.shadowRoot?.querySelector("ha-drawer")
        ?.querySelector("ha-sidebar")
        ?.shadowRoot;
      if (!sidebar) return null;
      const items = sidebar.querySelectorAll("ha-md-list-item");
      for (const item of items) {
        const headline = item.querySelector('.item-text[slot="headline"]');
        if (headline && headline.textContent.trim() === LABEL) return item;
      }
      return null;
    } catch { return null; }
  }

  function updateBadge(count) {
    const item = findSidebarItem();
    if (!item) return;
    let badge = item.querySelector(`#${BADGE_ID}`);
    if (count > 0) {
      if (!badge) {
        badge = document.createElement("span");
        badge.id = BADGE_ID;
        badge.slot = "end";
        badge.className = "badge";
        badge.style.cssText =
          "min-width:20px;height:20px;border-radius:10px;" +
          "background:#f5a623;color:#fff;font-size:12px;font-weight:700;" +
          "display:inline-flex;align-items:center;justify-content:center;" +
          "padding:0 5px;box-sizing:border-box;line-height:1;";
        item.appendChild(badge);
      }
      badge.textContent = count;
    } else if (badge) {
      badge.remove();
    }
  }

  function poll() {
    const hass = getHass();
    if (!hass) { setTimeout(poll, 2000); return; }
    const state = hass.states[ENTITY];
    updateBadge(state ? parseInt(state.state, 10) || 0 : 0);

    // Subscribe to state changes
    hass.connection.subscribeEvents((ev) => {
      if (ev.data.entity_id === ENTITY) {
        const val = parseInt(ev.data.new_state?.state, 10) || 0;
        updateBadge(val);
      }
    }, "state_changed");

    // Re-check periodically (sidebar may re-render)
    setInterval(() => {
      const h = getHass();
      if (!h) return;
      const s = h.states[ENTITY];
      updateBadge(s ? parseInt(s.state, 10) || 0 : 0);
    }, 30000);
  }

  if (document.readyState === "complete") poll();
  else window.addEventListener("load", poll);
})();
