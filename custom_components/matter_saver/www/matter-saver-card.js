// Keep this in sync with the rendered device-table header/body column count.
const TABLE_COLUMN_COUNT = 17;
const NUMERIC_SORT_FIELDS = new Set([
  "node_id",
  "battery",
  "neighbors",
  "children",
  "errors",
  "offline_24h_minutes",
  "offline_7d_minutes",
  "signal_rssi",
]);

class MatterSaverCard extends HTMLElement {
  constructor() {
    super();
    this._sortField = "status";
    this._sortAsc = true;
    this._filter = "";
    this._lastDataJson = "";
    this._initialized = false;
    this._devices = [];
    this._deviceDataError = "";
    this._handleExternalDeviceSelect = (event) => {
      const nodeId = Number(event?.detail?.nodeId);
      if (!Number.isFinite(nodeId)) return;
      if (event?.detail?.entityId && event.detail.entityId !== this._entityId) return;
      this._showActionPopup(nodeId);
    };
  }

  connectedCallback() {
    window.addEventListener("matter-saver-open-device-details", this._handleExternalDeviceSelect);
  }

  disconnectedCallback() {
    window.removeEventListener("matter-saver-open-device-details", this._handleExternalDeviceSelect);
  }

  setConfig(config) {
    this.config = config;
    this._entityId = config.entity || "sensor.matter_saver_devices";
    this._title = config.title || "Matter Devices";
    this._sortField = config.sort_by || "status";
    this._sortAsc = config.sort_ascending !== false;
    this._filter = (config.filter || "").toLowerCase();
    this._showSearch = config.show_search !== false;
    this._showStats = config.show_stats !== false;
    if (this._initialized && this._hass) {
      this._fullRender();
    }
  }

  set hass(hass) {
    this._hass = hass;
    const state = hass.states[this._entityId];
    const dataJson = state ? JSON.stringify(state.attributes) : "";
    if (!this._initialized || !this.querySelector("#ms-tbody")) {
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
      this.innerHTML = `<ha-card header="${this._escHtml(this._title || "Matter Saver")}"><div class="card-content">${this._escHtml(this._t("entityNotFound"))}</div></ha-card>`;
      return;
    }
    this._lastDataJson = JSON.stringify(state.attributes);
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
          .ms-signal { font-weight: 500; white-space: nowrap; }
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
          .ms-modal.wide { max-width: 760px; }
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
          .ms-tab-bar {
            display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px;
            border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.08)); padding-bottom: 12px;
          }
          .ms-tab {
            border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
            background: transparent; color: var(--secondary-text-color, #999);
            border-radius: 999px; padding: 7px 12px; cursor: pointer; font-size: 0.85em;
          }
          .ms-tab.active {
            color: var(--primary-text-color, #fff);
            background: color-mix(in srgb, var(--primary-color, #03a9f4) 16%, transparent);
            border-color: color-mix(in srgb, var(--primary-color, #03a9f4) 45%, transparent);
          }
          .ms-tab-panel { display: none; }
          .ms-tab-panel.active { display: block; }
          .ms-tab-content { max-height: min(60vh, 520px); overflow: auto; padding-right: 4px; }
          .ms-detail-table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
          .ms-detail-table td { padding: 7px 8px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.06)); vertical-align: top; }
          .ms-detail-table tr:last-child td { border-bottom: none; }
          .ms-detail-table td:first-child { width: 180px; color: var(--secondary-text-color, #999); }
          .ms-detail-table td:last-child { white-space: pre-wrap; word-break: break-word; }
          .ms-actions-pane { display: flex; flex-direction: column; gap: 14px; }
          .ms-history-empty { color: var(--secondary-text-color, #999); font-size: 0.9em; }
        </style>
        <div class="ms-header">
          <span class="ms-title">${this._escHtml(this._title)}</span>
          <div class="ms-stats" id="ms-stats"></div>
        </div>
        ${this._showSearch ? `<div class="ms-search-wrap">
          <input type="text" class="ms-search" id="ms-search" placeholder="${this._escHtml(this._t("filterDevicesPlaceholder"))}" value="${this._escHtml(this.config.filter || "")}" />
        </div>` : ""}
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
          <div class="ms-modal wide">
            <button class="ms-modal-close" id="ms-action-modal-close">&times;</button>
            <div class="ms-modal-title" id="ms-action-title"></div>
            <div class="ms-tab-bar" id="ms-action-tabs"></div>
            <div class="ms-tab-content" id="ms-action-content"></div>
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
    const searchInput = this.querySelector("#ms-search");
    if (searchInput) {
      searchInput.addEventListener("input", (e) => {
        this._filter = e.target.value.toLowerCase();
        this._updateTable();
      });
    }

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
    if (!device || !this._hasRoutePath(device)) return;

    const titleEl = this.querySelector("#ms-modal-title");
    const routeEl = this.querySelector("#ms-route");
    const modal = this.querySelector("#ms-modal");

    titleEl.textContent = this._t("routeTitle", { name: device.name });

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
      const roleLabel = hop.role === "ha"
        ? this._t("borderRouterGateway")
        : this._threadRoleLabel(hop.role);

      // Signal quality
      let signalHtml = "";
      if (hop.rssi != null) {
        const rssiColor = this._signalInfo(hop.rssi).color;
        const lqiLabel = hop.lqi != null ? `LQI ${hop.lqi}/3` : "";
        signalHtml = `<div class="ms-route-signal"><div class="rssi" style="color:${rssiColor}">${hop.rssi} dBm</div><div class="lqi">${lqiLabel}</div></div>`;
      }

      html += `<div class="ms-route-hop">
        <div class="ms-route-icon" style="background:${color}22;color:${color}">${icon}</div>
        <div class="ms-route-info">
          <div class="ms-route-name">${this._escHtml(hop.name || this._t("unknown"))}</div>
          <div class="ms-route-detail">${hop.node_id != null ? `${this._t("node")} ${hop.node_id} \u2022 ` : ""}${roleLabel}</div>
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
    const tabsEl = this.querySelector("#ms-action-tabs");
    const contentEl = this.querySelector("#ms-action-content");
    const statusEl = this.querySelector("#ms-action-status");
    const modal = this.querySelector("#ms-action-modal");

    titleEl.textContent = device.name || `Node ${nodeId}`;
    // Preserve status message during refresh
    if (!this._keepStatus) {
      statusEl.className = "ms-action-status";
      statusEl.textContent = "";
    }
    this._keepStatus = false;

    const localizedComment = this._localizeIssueComment(device.error_comment, device.error_comment_codes);

    // Get repair history for this node from activity log
    const logState = this._hass.states["sensor.matter_saver_activity_log"];
    const allEntries = logState ? (logState.attributes.entries || []) : [];
    const nodeHistory = allEntries.filter(e => e.node_id === nodeId);

    // Analyze what was already tried
    const triedPing = nodeHistory.some(e => this._entryMatchesAction(e, "ping"));
    const pingOk = nodeHistory.some(e => e.level === "success" && this._entryMatchesAction(e, "ping"));
    const pingFail = nodeHistory.some(e => e.level === "error" && this._entryMatchesAction(e, "ping"));
    const triedInterview = nodeHistory.some(e => this._entryMatchesAction(e, "interview"));
    const interviewOk = nodeHistory.some(e => e.level === "success" && this._entryMatchesAction(e, "interview"));
    const interviewFail = nodeHistory.some(e => e.level === "error" && this._entryMatchesAction(e, "interview"));
    const triedReset = nodeHistory.some(e => this._entryMatchesAction(e, "reset"));

    // Build smart suggestion
    let suggestion = "";
    if (device.status === "offline") {
      if (!triedPing) {
        suggestion = `<div class="ms-suggestion">${this._t("suggestionPingFirst")}</div>`;
      } else if (pingOk && !triedInterview) {
        suggestion = `<div class="ms-suggestion">${this._t("suggestionInterviewNext")}</div>`;
      } else if (pingOk && interviewFail) {
        suggestion = `<div class="ms-suggestion warn">${this._t("suggestionRestartAddon")}</div>`;
      } else if (pingFail) {
        suggestion = `<div class="ms-suggestion warn">${this._t("suggestionPingFailed")}</div>`;
      }
    } else if (device.errors > 10000) {
      if (!triedReset) {
        suggestion = `<div class="ms-suggestion">${this._t("suggestionResetCounters")}</div>`;
      } else {
        suggestion = `<div class="ms-suggestion warn">${this._t("suggestionMoveDevice")}</div>`;
      }
    }

    // Repair history HTML
    let historyHtml = "";
    if (nodeHistory.length > 0) {
      const histIcons = {"action": "\u26A1", "success": "\u2705", "error": "\u274C", "info": "\uD83D\uDFE2", "warning": "\u26A0\uFE0F"};
      historyHtml = `<div class="ms-repair-history">
        ${nodeHistory.slice(0, 10).map(e => {
          const ts = new Date(e.timestamp);
          const time = this._formatDate(ts, {hour:"2-digit",minute:"2-digit"});
          const date = this._formatDate(ts, {year:"numeric",month:"2-digit",day:"2-digit"});
          const icon = histIcons[e.level] || "\u2139\uFE0F";
          const color = e.level === "success" ? "#4caf50" : e.level === "error" ? "#f44336" : e.level === "action" ? "#ce93d8" : "#999";
          return `<div style="display:flex;gap:8px;padding:3px 0;font-size:0.8em"><span>${icon}</span><span style="color:${color}">${this._escHtml(this._localizeLogMessage(e))}</span><span style="color:var(--secondary-text-color,#666);margin-left:auto;white-space:nowrap">${date} ${time}</span></div>`;
        }).join("")}
      </div>`;
    } else {
      historyHtml = `<div class="ms-history-empty">${this._escHtml(this._t("noHistory"))}</div>`;
    }

    const diagnosticsSummary = localizedComment || this._t("noErrors");
    const tabs = [
      {
        id: "overview",
        label: this._t("overviewTab"),
        html: this._detailTable([
          [this._t("nodeId"), device.node_id],
          [this._t("name"), device.name || `Node ${device.node_id}`],
          [this._t("label"), this._textOrFallback(device.node_label)],
          [this._t("vendor"), this._textOrFallback(device.vendor)],
          [this._t("product"), this._textOrFallback(device.product)],
          [this._t("serialNumber"), this._textOrFallback(device.serial_number)],
          [this._t("area"), this._textOrFallback(device.area)],
          [this._t("status"), this._statusLabel(device.status)],
          [this._t("power"), this._powerLabel(device.power)],
          [this._t("battery"), this._formatBatteryValue(device.battery)],
          [this._t("firmware"), this._textOrFallback(device.firmware)],
          [this._t("update"), device.update_available ? this._t("updateAvailable") : this._t("upToDate")],
        ]),
      },
      {
        id: "thread",
        label: this._t("threadTab"),
        html: this._detailTable([
          [this._t("thread"), this._threadRoleLabel(device.thread_role)],
          [this._t("parent"), this._textOrFallback(device.parent)],
          [this._t("parentNodeId"), this._numberOrFallback(device.parent_node_id)],
          [this._t("signalQuality"), this._signalLabel(device.signal_rssi)],
          [this._t("signal"), this._formatSignal(device.signal_rssi, device.signal_lqi)],
          [this._t("signalRssi"), this._numberWithUnit(device.signal_rssi, "dBm")],
          [this._t("signalLqi"), this._numberWithUnit(device.signal_lqi, "/3")],
          [this._t("neighbors"), this._numberOrFallback(device.neighbors, 0)],
          [this._t("children"), this._numberOrFallback(device.children, 0)],
          [this._t("routeHopCount"), this._routeHopCount(device)],
          [this._t("routePath"), this._routePathText(device)],
          [this._t("routeDetails"), this._routeDetailsText(device)],
        ]),
      },
      {
        id: "diagnostics",
        label: this._t("diagnosticsTab"),
        html: this._detailTable([
          [this._t("errors"), this._countValue(device.errors)],
          [this._t("txRetries"), this._countValue(device.tx_retries)],
          [this._t("diagnostics"), diagnosticsSummary],
          [this._t("issueCodes"), this._formatIssueCodes(device.error_comment_codes)],
          [this._t("offline24hCount"), this._countValue(device.offline_24h_count)],
          [this._t("offline24hDuration"), this._formatDowntime(device.offline_24h_minutes)],
          [this._t("offline7dCount"), this._countValue(device.offline_7d_count)],
          [this._t("offline7dDuration"), this._formatDowntime(device.offline_7d_minutes)],
          [this._t("offline30dCount"), this._countValue(device.offline_30d_count)],
          [this._t("offline30dDuration"), this._formatDowntime(device.offline_30d_minutes)],
        ]),
      },
      {
        id: "history",
        label: this._t("historyTab"),
        html: `${this._detailTable([
          [this._t("lastSeen"), this._formatTimestamp(device.last_seen, true)],
          [this._t("lastInterview"), this._formatTimestamp(device.last_interview)],
          [this._t("commissioned"), this._formatTimestamp(device.date_commissioned)],
        ])}${historyHtml}`,
      },
      {
        id: "actions",
        label: this._t("actionsTab"),
        html: `<div class="ms-actions-pane">
          ${suggestion}
          <div class="ms-action-details">${this._detailTable([
            [this._t("status"), this._statusLabel(device.status)],
            [this._t("thread"), this._threadRoleLabel(device.thread_role)],
            [this._t("parent"), this._textOrFallback(device.parent)],
            [this._t("signalQuality"), this._signalLabel(device.signal_rssi)],
            [this._t("signal"), this._formatSignal(device.signal_rssi, device.signal_lqi)],
            [this._t("diagnostics"), diagnosticsSummary],
          ])}</div>
          <div class="ms-action-buttons" id="ms-action-buttons">
            <button class="ms-action-btn ping" data-action="ping" data-node="${nodeId}">\uD83C\uDFD3 ${this._escHtml(this._actionLabel("ping"))}</button>
            <button class="ms-action-btn interview" data-action="interview" data-node="${nodeId}">\uD83D\uDD04 ${this._escHtml(this._actionLabel("interview"))}</button>
            <button class="ms-action-btn reset" data-action="reset" data-node="${nodeId}">\uD83D\uDDD1 ${this._escHtml(this._actionLabel("reset"))}</button>
          </div>
        </div>`,
      },
    ];

    tabsEl.innerHTML = tabs.map((tab) =>
      `<button class="ms-tab" data-tab="${tab.id}">${this._escHtml(tab.label)}</button>`
    ).join("");
    contentEl.innerHTML = tabs.map((tab) =>
      `<div class="ms-tab-panel" data-tab="${tab.id}">${tab.html}</div>`
    ).join("");

    tabsEl.querySelectorAll(".ms-tab").forEach((btn) => {
      btn.addEventListener("click", () => this._setActionTab(btn.dataset.tab));
    });
    this._setActionTab(this._activeDeviceTab || "overview");

    contentEl.querySelectorAll(".ms-action-btn[data-action][data-node]").forEach((btn) => {
      btn.addEventListener("click", () => this._executeAction(btn.dataset.action, parseInt(btn.dataset.node)));
    });

    modal.classList.add("open");

    // Restart addon button (in suggestion)
    const restartBtn = this.querySelector("#ms-restart-addon");
    if (restartBtn) {
      restartBtn.addEventListener("click", () => this._restartMatterAddon(nodeId));
    }
  }

  _setActionTab(tabId) {
    this._activeDeviceTab = tabId;
    this.querySelectorAll("#ms-action-tabs .ms-tab").forEach((tab) => {
      tab.classList.toggle("active", tab.dataset.tab === tabId);
    });
    this.querySelectorAll("#ms-action-content .ms-tab-panel").forEach((panel) => {
      panel.classList.toggle("active", panel.dataset.tab === tabId);
    });
  }

  _detailTable(rows) {
    return `<table class="ms-detail-table">${rows.map(([key, value]) =>
      `<tr><td>${this._escHtml(String(key))}</td><td>${this._escHtml(String(value))}</td></tr>`
    ).join("")}</table>`;
  }

  _textOrFallback(value) {
    return value ? String(value) : this._t("notAvailable");
  }

  _countValue(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return this._t("notAvailable");
    return numeric.toLocaleString();
  }

  _numberOrFallback(value, fallback = null) {
    if (value === null || value === undefined || value === "") {
      return fallback !== null ? Number(fallback).toLocaleString() : this._t("notAvailable");
    }
    const numeric = Number(value);
    if (Number.isFinite(numeric)) return numeric.toLocaleString();
    if (fallback !== null) return Number(fallback).toLocaleString();
    return this._t("notAvailable");
  }

  _numberWithUnit(value, unit) {
    if (value === null || value === undefined || value === "") return this._t("notAvailable");
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return this._t("notAvailable");
    return unit.startsWith("/") ? `${numeric}${unit}` : `${numeric} ${unit}`;
  }

  _formatBatteryValue(battery) {
    if (battery == null || Number.isNaN(Number(battery))) return this._t("notAvailable");
    return `${Math.round(Number(battery))}%`;
  }

  _formatIssueCodes(codes) {
    if (!Array.isArray(codes) || codes.length === 0) return this._t("notAvailable");
    return codes.map((code) => {
      const localized = this._localizeIssueComment("", [code]) || code;
      return `${localized} (${code})`;
    }).join("\n");
  }

  _signalInfo(rssi) {
    return window.MatterSaverCardUtils?.signalInfo(rssi) || { level: "unknown", color: "rgba(255,255,255,0.25)" };
  }

  _signalLabel(rssi) {
    const level = this._signalInfo(rssi).level;
    if (level === "strong") return this._t("strongSignal");
    if (level === "fair") return this._t("fairSignal");
    if (level === "weak") return this._t("weakSignal");
    return this._t("unknownSignal");
  }

  _formatSignal(rssi, lqi) {
    return window.MatterSaverCardUtils?.formatSignal(this._hass, rssi, lqi)
      || this._t("unknownSignal");
  }

  _signalHtml(rssi, lqi) {
    const info = this._signalInfo(rssi);
    return `<span class="ms-signal" style="color:${info.color}">${this._escHtml(this._formatSignal(rssi, lqi))}</span>`;
  }

  _formatTimestamp(value, useRelative = false) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    if (useRelative) {
      return `${this._relativeTime(date)} • ${this._formatDate(date, {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })}`;
    }
    return this._formatDate(date, {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  _hasRoutePath(device) {
    return Array.isArray(device?.route_path) && device.route_path.length > 1;
  }

  _routeHopCount(device) {
    return this._hasRoutePath(device)
      ? String(Math.max(device.route_path.length - 1, 0))
      : this._t("notAvailable");
  }

  _routePathText(device) {
    if (!this._hasRoutePath(device)) return this._t("notAvailable");
    return device.route_path.map((hop) => (
      hop?.name
      || (hop?.node_id == null ? this._t("homeAssistant") : `Node ${hop.node_id}`)
    )).join(" → ");
  }

  _routeDetailsText(device) {
    if (!this._hasRoutePath(device)) return this._t("notAvailable");
    return device.route_path.map((hop, index) => {
      const name = hop?.name
        || (hop?.node_id == null ? this._t("homeAssistant") : `Node ${hop.node_id}`);
      const nodeId = hop?.node_id == null ? this._t("homeAssistant") : `${this._t("node")} ${hop.node_id}`;
      const role = hop?.role === "ha"
        ? this._t("homeAssistant")
        : this._threadRoleLabel(hop?.role);
      const signal = this._formatSignal(hop?.rssi, hop?.lqi);
      return `${index + 1}. ${name} (${nodeId}) — ${role} — ${signal}`;
    }).join("\n");
  }

  async _executeAction(action, nodeId) {
    const statusEl = this.querySelector("#ms-action-status");
    const buttons = this.querySelectorAll(".ms-action-btn[data-action][data-node]");

    // Disable buttons during execution
    buttons.forEach(b => b.disabled = true);
    statusEl.className = "ms-action-status show loading";

    const serviceMap = {
      "ping": "ping_node",
      "interview": "interview_node",
      "reset": "reset_counters",
    };
    const labels = {
      "ping": this._actionLabel("ping"),
      "interview": this._actionLabel("interview"),
      "reset": this._actionLabel("reset"),
    };

    const hints = {
      "ping": this._t("pingRunning"),
      "interview": this._t("interviewRunning"),
      "reset": this._t("resetRunning"),
    };
    if (!serviceMap[action]) {
      statusEl.className = "ms-action-status show error";
      statusEl.textContent = this._t("errorPrefix", { error: `Unsupported action: ${action}` });
      buttons.forEach(b => b.disabled = false);
      return;
    }
    statusEl.textContent = hints[action] || `${labels[action]}...`;

    try {
      await this._hass.callService("matter_saver", serviceMap[action], { node_id: nodeId });
      statusEl.className = "ms-action-status show success";
      statusEl.textContent = this._t("actionSuccessForNode", { action: labels[action], nodeId });
    } catch (err) {
      statusEl.className = "ms-action-status show error";
      statusEl.textContent = this._t("errorPrefix", { error: err.message || err });
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
    if (!confirm(this._t("restartAddonConfirm"))) return;

    statusEl.className = "ms-action-status show loading";
    statusEl.textContent = this._t("restartAddonLoading");

    try {
      await this._hass.callService("hassio", "addon_restart", { addon: "core_matter_server" });
      statusEl.className = "ms-action-status show success";
      statusEl.textContent = this._t("restartAddonSuccess");
    } catch (err) {
      statusEl.className = "ms-action-status show error";
      statusEl.textContent = this._t("errorPrefix", { error: err.message || err });
    }
  }

  _updateTable() {
    const state = this._hass.states[this._entityId];
    if (!state) return;

    let devices = this._getDevices(state);
    const online = state.attributes.online || 0;
    const offline = state.attributes.offline || 0;

    const statsEl = this.querySelector("#ms-stats");
    if (statsEl) {
      if (this._showStats) {
        statsEl.innerHTML = `
          <span class="ms-stat"><span class="ms-dot online"></span> ${online} ${this._escHtml(this._t("online"))}</span>
          <span class="ms-stat"><span class="ms-dot offline"></span> ${offline} ${this._escHtml(this._t("offline"))}</span>
        `;
      } else {
        statsEl.innerHTML = "";
      }
    }

    const theadEl = this.querySelector("#ms-thead");
    if (theadEl) {
        theadEl.innerHTML = `<tr>
          ${this._th("node_id", this._t("node"))}
          ${this._th("name", this._t("name"))}
          ${this._th("area", this._t("area"))}
          ${this._th("product", this._t("product"))}
        ${this._th("status", this._t("status"))}
        ${this._th("thread_role", this._t("thread"))}
          ${this._th("neighbors", this._t("neighbors"))}
          ${this._th("children", this._t("children"))}
          ${this._th("parent", this._t("parent"))}
          ${this._th("signal_rssi", this._t("signal"))}
          ${this._th("power", this._t("power"))}
          ${this._th("battery", this._t("battery"))}
          ${this._th("firmware", this._t("firmware"))}
        ${this._th("errors", this._t("errors"))}
        ${this._th("offline_24h_minutes", this._t("downtime24h"))}
        ${this._th("offline_7d_minutes", this._t("downtime7d"))}
        ${this._th("last_seen", this._t("lastSeen"))}
      </tr>`;
    }

    if (this._filter) {
      devices = devices.filter((d) => {
        const searchable = [
          d.name, d.area, d.product, d.status, d.power,
          d.firmware, d.thread_role, d.parent, this._formatSignal(d.signal_rssi, d.signal_lqi), String(d.node_id),
        ].join(" ").toLowerCase();
        return searchable.includes(this._filter);
      });
    }

    this._devices = devices;

    const tbodyEl = this.querySelector("#ms-tbody");
    if (tbodyEl) {
      if (devices.length === 0) {
        tbodyEl.innerHTML = `<tr class="ms-no-results"><td colspan="${TABLE_COLUMN_COUNT}">${this._escHtml(this._deviceDataError || this._t("noDevicesFound"))}</td></tr>`;
      } else {
        const sorted = this._sortDevices(devices);
        tbodyEl.innerHTML = this._groupDevices(sorted, TABLE_COLUMN_COUNT);
      }
    }
  }

  _th(field, label) {
    const sorted = this._sortField === field;
    const arrow = sorted ? (this._sortAsc ? " \u25B2" : " \u25BC") : "";
    return `<th data-field="${field}" class="${sorted ? "sorted" : ""}">${label}<span class="arrow">${arrow}</span></th>`;
  }

  _getDevices(state) {
    const result = window.MatterSaverCardUtils?.getDevices(state, "matter-saver-card", this._hass);
    if (result) {
      this._deviceDataError = result.error;
      return result.devices;
    }

    this._deviceDataError = this._t("sharedDeviceDecoderUnavailable");
    console.warn("matter-saver-card: shared card utilities unavailable; returning no devices to avoid mis-rendering.");
    return [];
  }

  _sortDevices(devices) {
    const field = this._sortField;
    const asc = this._sortAsc;
    return [...devices].sort((a, b) => {
      let va = a[field]; let vb = b[field];
      if (va == null) va = field === "battery" ? 999 : "";
      if (vb == null) vb = field === "battery" ? 999 : "";
      if (NUMERIC_SORT_FIELDS.has(field)) {
        va = Number(va) || 0; vb = Number(vb) || 0;
      } else { va = String(va).toLowerCase(); vb = String(vb).toLowerCase(); }
      if (va < vb) return asc ? -1 : 1;
      if (va > vb) return asc ? 1 : -1;
      return 0;
    });
  }

  _groupDevices(devices, columnCount) {
    const field = this._sortField;
    let html = ""; let lastGroup = null;
    for (const d of devices) {
      let groupVal = this._groupValue(d, field);
      if (groupVal !== lastGroup) {
        html += `<tr class="ms-group-header"><td colspan="${columnCount}">${this._escHtml(groupVal)}</td></tr>`;
        lastGroup = groupVal;
      }
      html += this._deviceRow(d);
    }
    return html;
  }

  _groupValue(device, field) {
    switch (field) {
      case "status": return device.status === "online" ? this._t("onlineGroup") : this._t("offlineGroup");
      case "power": return device.power === "battery" ? this._t("batteryPower") : this._t("wiredPower");
      case "product": return device.product || this._t("unknown");
      case "area": return device.area || this._t("noArea");
      case "firmware": return device.firmware || this._t("unknown");
      case "thread_role": return this._threadRoleLabel(device.thread_role);
      case "parent": return device.parent || this._t("noParentRouter");
      case "signal_rssi": return this._signalLabel(device.signal_rssi);
      case "battery":
        if (device.battery == null) return this._t("noBattery");
        if (device.battery < 20) return this._t("criticalBattery");
        if (device.battery < 50) return this._t("lowBattery");
        return this._t("goodBattery");
      case "errors":
        if (!device.errors || device.errors === 0) return this._t("noErrors");
        if (device.errors > 100000) return this._t("critical");
        if (device.errors > 10000) return this._t("high");
        if (device.errors > 1000) return this._t("moderate");
        return this._t("low");
      case "last_seen":
        if (!device.last_seen) return this._t("neverSeen");
        return this._t("seen");
      case "offline_24h_minutes":
        return this._t("downtime24h");
      case "offline_7d_minutes":
        return this._t("downtime7d");
      default: return "";
    }
  }

  _deviceRow(d) {
    const statusIcon = d.status === "online" ? "\uD83D\uDFE2" : "\uD83D\uDD34";
    const rowClass = d.status === "offline" ? "ms-offline-row" : "";
    const parentText = d.parent
      ? d.parent
      : (d.thread_role === "router" || d.thread_role === "leader" || d.thread_role === "reed")
        ? this._t("routerFallback")
        : "";
    const parentHtml = parentText
      ? (this._hasRoutePath(d)
        ? `<span class="ms-parent-link" data-node-id="${d.node_id}">${this._escHtml(parentText)}</span>`
        : this._escHtml(parentText))
        : "-";

    return `<tr class="${rowClass}">
      <td>${d.node_id}</td>
      <td><span class="ms-name-link" data-node-id="${d.node_id}">${this._escHtml(d.name)}</span></td>
      <td>${this._escHtml(d.area)}</td>
      <td>${this._escHtml(d.product)}</td>
      <td><span class="ms-status">${statusIcon} ${this._statusLabel(d.status)}</span></td>
      <td>${this._threadRoleHtml(d.thread_role)}</td>
      <td>${d.neighbors || "-"}</td>
      <td>${d.children || "-"}</td>
      <td>${parentHtml}</td>
      <td>${this._signalHtml(d.signal_rssi, d.signal_lqi)}</td>
      <td>${this._escHtml(this._powerLabel(d.power))}</td>
      <td>${this._batteryHtml(d.battery)}</td>
      <td>${this._firmwareHtml(d.firmware, d.update_available)}</td>
      <td>${this._errorsHtml(d.errors, this._localizeIssueComment(d.error_comment, d.error_comment_codes))}</td>
      <td>${this._downtimeHtml(d.offline_24h_minutes)}</td>
      <td>${this._downtimeHtml(d.offline_7d_minutes)}</td>
      <td>${this._lastSeenHtml(d.last_seen)}</td>
    </tr>`;
  }

  _threadRoleLabel(role) {
    return window.MatterSaverCardUtils?.roleLabel(this._hass, role) || role || this._t("unknown");
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
    return `<span class="ms-lastseen">${this._escHtml(this._relativeTime(isoStr))}</span>`;
  }

  _formatDowntime(minutes) {
    const value = Number(minutes) || 0;
    if (value < 60) return `${value}m`;
    if (value < 1440) return `${Math.round(value / 60)}h`;
    return `${(value / 1440).toFixed(1)}d`;
  }

  _downtimeHtml(minutes) {
    const value = Number(minutes) || 0;
    if (value <= 0) return "-";
    return this._escHtml(this._formatDowntime(value));
  }

  _t(key, vars) {
    return window.MatterSaverCardUtils?.t(this._hass, key, vars) || key;
  }

  _actionLabel(action) {
    return window.MatterSaverCardUtils?.actionLabel(this._hass, action) || action;
  }

  _formatDate(value, options) {
    return window.MatterSaverCardUtils?.formatDate(this._hass, value, options) || "";
  }

  _relativeTime(value) {
    return window.MatterSaverCardUtils?.formatRelativeTime(this._hass, value) || "";
  }

  _localizeIssueComment(message, codes) {
    return window.MatterSaverCardUtils?.localizeIssueComment(this._hass, message, codes) || message || "";
  }

  _localizeLogMessage(entry) {
    return window.MatterSaverCardUtils?.localizeLogMessage(this._hass, entry) || entry?.message || "";
  }

  _powerLabel(power) {
    if (power === "battery") return this._t("batteryPower");
    if (power === "wired") return this._t("wiredPower");
    return power || "-";
  }

  _statusLabel(status) {
    return status === "offline" ? this._t("offline") : this._t("online");
  }

  _entryMatchesAction(entry, action) {
    if (entry?.action === action) return true;
    const text = String(entry?.message || "");
    if (action === "ping") return text.includes("Ping");
    if (action === "interview") return text.includes("Interview");
    if (action === "reset") return text.includes("Reset");
    return false;
  }

  _escHtml(str) {
    const div = document.createElement("div");
    div.textContent = str || "";
    return div.innerHTML;
  }

  static async getConfigElement() {
    const editor = document.createElement("matter-saver-card-editor");
    editor.cardType = "matter-saver-card";
    return editor;
  }

  static getStubConfig() {
    return {
      type: window.MatterSaverCardEditor?.buildCardType("matter-saver-card") || "custom:matter-saver-card",
      entity: "sensor.matter_saver_devices",
    };
  }

  getGridOptions() {
    return {
      columns: 12,
      rows: 8,
      min_columns: 6,
    };
  }

  getCardSize() { return 8; }
}

customElements.define("matter-saver-card", MatterSaverCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "matter-saver-card",
  name: "Matter Saver Card",
  description: "Sortable Matter device table with route visualization",
  preview: true,
  documentationURL: "https://github.com/hellosamblack/matter-saver",
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
