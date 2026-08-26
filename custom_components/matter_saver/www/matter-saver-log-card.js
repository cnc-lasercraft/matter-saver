class MatterSaverLogCard extends HTMLElement {
  constructor() {
    super();
    this._lastDataJson = "";
    this._initialized = false;
    this._filter = "";
  }

  setConfig(config) {
    this.config = config;
    this._entityId = config.entity || "sensor.matter_saver_activity_log";
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
      this._updateLog();
    }
  }

  _fullRender() {
    const state = this._hass.states[this._entityId];
    this._lastDataJson = state ? JSON.stringify(state.attributes) : "";

    this.innerHTML = `
      <ha-card>
        <style>
          .ml-header { padding: 16px 16px 8px; display: flex; justify-content: space-between; align-items: center; }
          .ml-title { font-size: 1.2em; font-weight: 500; }
          .ml-count { font-size: 0.9em; color: var(--secondary-text-color, #999); }
          .ml-search-wrap { padding: 0 16px 12px; }
          .ml-search {
            width: 100%; padding: 8px 12px; box-sizing: border-box;
            border: 1px solid var(--divider-color, #333);
            border-radius: 8px; font-size: 0.9em;
            background: var(--card-background-color, #1c1c1c);
            color: var(--primary-text-color, #fff); outline: none;
          }
          .ml-search:focus { border-color: var(--primary-color, #03a9f4); }
          .ml-search::placeholder { color: var(--secondary-text-color, #999); }
          .ml-entries { padding: 0 16px 16px; }
          .ml-entry {
            display: flex; gap: 12px; padding: 10px 0;
            border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.05));
          }
          .ml-entry:last-child { border-bottom: none; }
          .ml-icon {
            width: 32px; height: 32px; border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            font-size: 0.9em; flex-shrink: 0;
          }
          .ml-icon.info { background: #01579b33; color: #03a9f4; }
          .ml-icon.warning { background: #e6510033; color: #ff9800; }
          .ml-icon.error { background: #b7140033; color: #f44336; }
          .ml-icon.success { background: #1b5e2033; color: #4caf50; }
          .ml-icon.action { background: #4a148c33; color: #ce93d8; }
          .ml-body { flex: 1; min-width: 0; }
          .ml-top { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
          .ml-name { font-weight: 600; font-size: 0.9em; }
          .ml-node { color: var(--secondary-text-color, #999); font-size: 0.8em; }
          .ml-time { font-size: 0.8em; color: var(--secondary-text-color, #999); white-space: nowrap; }
          .ml-msg { font-size: 0.85em; margin-top: 2px; }
          .ml-msg.info { color: #03a9f4; }
          .ml-msg.warning { color: #ff9800; }
          .ml-msg.error { color: #f44336; }
          .ml-msg.success { color: #4caf50; }
          .ml-msg.action { color: #ce93d8; }
          .ml-empty { text-align: center; padding: 40px 0; color: var(--secondary-text-color, #999); }
        </style>
        <div class="ml-header">
          <span class="ml-title">Activity Log</span>
          <span class="ml-count" id="ml-count"></span>
        </div>
        <div class="ml-search-wrap">
          <input type="text" class="ml-search" id="ml-search" placeholder="Filter log..." />
        </div>
        <div class="ml-entries" id="ml-entries"></div>
      </ha-card>
    `;

    this.querySelector("#ml-search").addEventListener("input", (e) => {
      this._filter = e.target.value.toLowerCase();
      this._updateLog();
    });

    this._updateLog();
  }

  _updateLog() {
    const state = this._hass.states[this._entityId];
    if (!state) return;

    let entries = state.attributes.entries || [];

    if (this._filter) {
      entries = entries.filter(e => {
        const searchable = [e.name, e.message, String(e.node_id)].join(" ").toLowerCase();
        return searchable.includes(this._filter);
      });
    }

    const countEl = this.querySelector("#ml-count");
    if (countEl) countEl.textContent = `${entries.length} Einträge`;

    const container = this.querySelector("#ml-entries");
    if (!container) return;

    if (entries.length === 0) {
      container.innerHTML = `<div class="ml-empty">Noch keine Aktivitäten</div>`;
      return;
    }

    const icons = {
      "info": "\uD83D\uDFE2",
      "warning": "\u26A0\uFE0F",
      "error": "\u274C",
      "success": "\u2705",
      "action": "\u26A1",
    };

    let html = "";
    let lastDate = "";

    for (const e of entries) {
      const ts = new Date(e.timestamp);
      const dateStr = ts.toLocaleDateString("de-CH");
      const timeStr = ts.toLocaleTimeString("de-CH", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      const relTime = this._relativeTime(ts);

      // Date separator
      if (dateStr !== lastDate) {
        html += `<div style="padding:12px 0 4px;font-weight:600;font-size:0.85em;color:var(--primary-color,#03a9f4);border-bottom:1px solid var(--primary-color,#03a9f4)">${dateStr}</div>`;
        lastDate = dateStr;
      }

      const level = e.level || "info";
      const icon = icons[level] || "\u2139\uFE0F";

      html += `<div class="ml-entry">
        <div class="ml-icon ${level}">${icon}</div>
        <div class="ml-body">
          <div class="ml-top">
            <span><span class="ml-name">${this._escHtml(e.name)}</span> <span class="ml-node">Node ${e.node_id || "?"}</span></span>
            <span class="ml-time" title="${timeStr}">${relTime}</span>
          </div>
          <div class="ml-msg ${level}">${this._escHtml(e.message)}</div>
        </div>
      </div>`;
    }

    container.innerHTML = html;
  }

  _relativeTime(date) {
    const now = new Date();
    const diffMin = Math.floor((now - date) / 60000);
    if (diffMin < 1) return "gerade eben";
    if (diffMin < 60) return `vor ${diffMin}m`;
    if (diffMin < 1440) return `vor ${Math.floor(diffMin / 60)}h`;
    return `vor ${Math.floor(diffMin / 1440)}d`;
  }

  _escHtml(str) {
    const div = document.createElement("div");
    div.textContent = str || "";
    return div.innerHTML;
  }

  getCardSize() { return 6; }
}

customElements.define("matter-saver-log-card", MatterSaverLogCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "matter-saver-log-card",
  name: "Matter Saver Log Card",
  description: "Activity log for Matter Saver",
});
