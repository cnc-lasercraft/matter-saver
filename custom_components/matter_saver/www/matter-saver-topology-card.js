class MatterSaverTopologyCard extends HTMLElement {
  constructor() {
    super();
    this._lastDataJson = "";
    this._initialized = false;
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
      this._updateTopology();
    }
  }

  _fullRender() {
    this._lastDataJson = JSON.stringify((this._hass.states[this._entityId] || {}).attributes || {});
    this.innerHTML = `
      <ha-card>
        <style>
          .mt-header { padding: 16px 16px 8px; }
          .mt-title { font-size: 1.2em; font-weight: 500; }
          .mt-content { padding: 0 16px 16px; }
          .mt-router {
            margin-bottom: 16px; border-radius: 12px;
            border: 1px solid var(--divider-color, rgba(255,255,255,0.1));
            overflow: hidden;
          }
          .mt-router-header {
            display: flex; justify-content: space-between; align-items: center;
            padding: 12px 16px;
            background: var(--card-background-color, rgba(255,255,255,0.03));
          }
          .mt-router-name { font-weight: 600; font-size: 0.95em; }
          .mt-router-meta { display: flex; gap: 12px; font-size: 0.8em; color: var(--secondary-text-color, #999); }
          .mt-router-role {
            padding: 2px 8px; border-radius: 4px; font-size: 0.75em; font-weight: 600;
            text-transform: uppercase;
          }
          .mt-role-leader { background: #ffb30033; color: #ffb300; }
          .mt-role-router { background: #4caf5033; color: #4caf50; }
          .mt-role-reed { background: #8bc34a33; color: #8bc34a; }
          .mt-children { padding: 0; }
          .mt-child {
            display: flex; justify-content: space-between; align-items: center;
            padding: 8px 16px 8px 32px;
            border-top: 1px solid var(--divider-color, rgba(255,255,255,0.05));
            font-size: 0.85em;
          }
          .mt-child-name { display: flex; align-items: center; gap: 8px; }
          .mt-child-indicator {
            width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0;
          }
          .mt-child-indicator.online { background: #4caf50; }
          .mt-child-indicator.offline { background: #f44336; }
          .mt-child-meta { display: flex; gap: 12px; font-size: 0.8em; color: var(--secondary-text-color, #999); }
          .mt-no-children { padding: 8px 16px 8px 32px; font-size: 0.8em; color: var(--secondary-text-color, #666); font-style: italic; }
          .mt-stats {
            display: flex; gap: 16px; padding: 8px 16px 16px; font-size: 0.85em;
            color: var(--secondary-text-color, #999);
          }
          .mt-stat-value { font-weight: 600; color: var(--primary-text-color, #fff); }
          .mt-unassigned { margin-top: 8px; }
          .mt-unassigned-title { font-size: 0.85em; font-weight: 600; color: var(--secondary-text-color, #999); padding: 8px 0; }
        </style>
        <div class="mt-header">
          <span class="mt-title">Thread Topology</span>
        </div>
        <div class="mt-stats" id="mt-stats"></div>
        <div class="mt-content" id="mt-content"></div>
      </ha-card>
    `;
    this._updateTopology();
  }

  _updateTopology() {
    const state = this._hass.states[this._entityId];
    if (!state) return;

    const devices = state.attributes.devices || [];
    const routers = devices.filter(d => ["router", "leader", "reed"].includes(d.thread_role));
    const endDevices = devices.filter(d => ["sed", "end_device"].includes(d.thread_role));

    // Stats
    const statsEl = this.querySelector("#mt-stats");
    if (statsEl) {
      const leaderCount = routers.filter(d => d.thread_role === "leader").length;
      const routerCount = routers.filter(d => d.thread_role === "router").length;
      const reedCount = routers.filter(d => d.thread_role === "reed").length;
      const sedCount = endDevices.length;
      statsEl.innerHTML = `
        <span><span class="mt-stat-value">${leaderCount}</span> Leader</span>
        <span><span class="mt-stat-value">${routerCount}</span> Router</span>
        <span><span class="mt-stat-value">${reedCount}</span> REED</span>
        <span><span class="mt-stat-value">${sedCount}</span> End Devices</span>
      `;
    }

    // Build parent_node_id -> children mapping
    const childrenMap = {};
    const assignedChildren = new Set();
    for (const d of endDevices) {
      if (d.parent_node_id != null) {
        if (!childrenMap[d.parent_node_id]) childrenMap[d.parent_node_id] = [];
        childrenMap[d.parent_node_id].push(d);
        assignedChildren.add(d.node_id);
      }
    }
    const unassigned = endDevices.filter(d => !assignedChildren.has(d.node_id));

    // Sort routers: leader first, then by children count desc
    const sortedRouters = [...routers].sort((a, b) => {
      if (a.thread_role === "leader") return -1;
      if (b.thread_role === "leader") return 1;
      const ac = (childrenMap[a.node_id] || []).length;
      const bc = (childrenMap[b.node_id] || []).length;
      return bc - ac;
    });

    const contentEl = this.querySelector("#mt-content");
    if (!contentEl) return;

    let html = "";
    for (const router of sortedRouters) {
      const children = childrenMap[router.node_id] || [];
      const roleClass = router.thread_role === "leader" ? "mt-role-leader" : router.thread_role === "reed" ? "mt-role-reed" : "mt-role-router";
      const roleLabel = router.thread_role === "leader" ? "Leader" : router.thread_role === "reed" ? "REED" : "Router";
      const statusDot = router.status === "online"
        ? '<span class="mt-child-indicator online"></span>'
        : '<span class="mt-child-indicator offline"></span>';

      html += `<div class="mt-router">
        <div class="mt-router-header">
          <span class="mt-router-name">${statusDot} ${this._esc(router.name)}</span>
          <div class="mt-router-meta">
            <span class="mt-router-role ${roleClass}">${roleLabel}</span>
            <span>Node ${router.node_id}</span>
            <span>${router.neighbors || 0} neighbors</span>
            <span>${children.length} children</span>
            ${router.area ? `<span>${this._esc(router.area)}</span>` : ""}
          </div>
        </div>
        <div class="mt-children">`;

      if (children.length === 0) {
        html += `<div class="mt-no-children">Keine End Devices angebunden</div>`;
      } else {
        for (const child of children) {
          const cDot = child.status === "online"
            ? '<span class="mt-child-indicator online"></span>'
            : '<span class="mt-child-indicator offline"></span>';
          const bat = child.battery != null ? `${Math.round(child.battery)}%` : "";
          html += `<div class="mt-child">
            <span class="mt-child-name">${cDot} ${this._esc(child.name)}</span>
            <div class="mt-child-meta">
              <span>Node ${child.node_id}</span>
              <span>${this._esc(child.product)}</span>
              ${bat ? `<span>${bat}</span>` : ""}
              ${child.area ? `<span>${this._esc(child.area)}</span>` : ""}
            </div>
          </div>`;
        }
      }
      html += `</div></div>`;
    }

    // Unassigned end devices
    if (unassigned.length > 0) {
      html += `<div class="mt-unassigned">
        <div class="mt-unassigned-title">Nicht zugeordnete End Devices</div>`;
      for (const d of unassigned) {
        const dot = d.status === "online"
          ? '<span class="mt-child-indicator online"></span>'
          : '<span class="mt-child-indicator offline"></span>';
        html += `<div class="mt-child">
          <span class="mt-child-name">${dot} ${this._esc(d.name)}</span>
          <div class="mt-child-meta"><span>Node ${d.node_id}</span><span>${this._esc(d.product)}</span></div>
        </div>`;
      }
      html += `</div>`;
    }

    contentEl.innerHTML = html;
  }

  _esc(str) {
    const div = document.createElement("div");
    div.textContent = str || "";
    return div.innerHTML;
  }

  getCardSize() { return 8; }
}

customElements.define("matter-saver-topology-card", MatterSaverTopologyCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "matter-saver-topology-card",
  name: "Matter Saver Topology Card",
  description: "Thread mesh topology - routers and their children",
});
