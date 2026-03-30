class MatterSaverMeshCard extends HTMLElement {
  constructor() {
    super();
    this._lastDataJson = "";
    this._initialized = false;
    this._nodes = [];
    this._links = [];
    this._dragging = null;
    this._offsetX = 0;
    this._offsetY = 0;
    this._scale = 1;
    this._panX = 0;
    this._panY = 0;
    this._isPanning = false;
    this._panStartX = 0;
    this._panStartY = 0;
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
      this._buildGraph();
      this._renderGraph();
    }
  }

  _fullRender() {
    this._lastDataJson = JSON.stringify((this._hass.states[this._entityId] || {}).attributes || {});
    this.innerHTML = `
      <ha-card>
        <style>
          .mm-header { padding: 16px 16px 8px; display: flex; justify-content: space-between; align-items: center; }
          .mm-title { font-size: 1.2em; font-weight: 500; }
          .mm-controls { display: flex; gap: 8px; }
          .mm-btn {
            background: var(--card-background-color, #333); border: 2px solid var(--divider-color, #555);
            color: var(--primary-text-color, #fff); padding: 8px 16px; border-radius: 10px;
            cursor: pointer; font-size: 1.1em; font-weight: 600; min-width: 40px;
          }
          .mm-btn:hover { border-color: var(--primary-color, #03a9f4); background: var(--primary-color, #03a9f4)22; }
          .mm-legend { padding: 0 16px 8px; display: flex; gap: 16px; font-size: 0.8em; flex-wrap: wrap; }
          .mm-legend-item { display: flex; align-items: center; gap: 4px; }
          .mm-legend-dot { width: 12px; height: 12px; border-radius: 50%; }
          .mm-svg-wrap {
            width: 100%; height: calc(100vh - 180px); min-height: 400px;
            position: relative; overflow: hidden;
            cursor: grab; user-select: none;
          }
          .mm-svg-wrap.grabbing { cursor: grabbing; }
          .mm-svg { width: 100%; height: 100%; }
          .mm-tooltip {
            display: none; position: absolute; background: var(--ha-card-background, #1c1c1c);
            border: 1px solid var(--divider-color, #555); border-radius: 8px;
            padding: 10px 14px; font-size: 0.8em; pointer-events: none; z-index: 10;
            box-shadow: 0 4px 12px rgba(0,0,0,0.4); max-width: 250px;
          }
          .mm-tooltip.show { display: block; }
          .mm-tooltip-name { font-weight: 600; margin-bottom: 4px; }
          .mm-tooltip-detail { color: var(--secondary-text-color, #999); line-height: 1.4; }
        </style>
        <div class="mm-header">
          <span class="mm-title">Thread Mesh</span>
          <div class="mm-controls">
            <button class="mm-btn" id="mm-zoom-in">+</button>
            <button class="mm-btn" id="mm-zoom-out">-</button>
            <button class="mm-btn" id="mm-reset">Reset</button>
          </div>
        </div>
        <div class="mm-legend">
          <span class="mm-legend-item"><span class="mm-legend-dot" style="background:#ffb300"></span> Leader</span>
          <span class="mm-legend-item"><span class="mm-legend-dot" style="background:#4caf50"></span> Router</span>
          <span class="mm-legend-item"><span class="mm-legend-dot" style="background:#8bc34a"></span> REED</span>
          <span class="mm-legend-item"><span class="mm-legend-dot" style="background:#78909c"></span> End Device</span>
          <span class="mm-legend-item"><span class="mm-legend-dot" style="background:#03a9f4"></span> Home Assistant</span>
          <span class="mm-legend-item"><span style="width:20px;height:2px;background:#4caf50;display:inline-block"></span> Parent</span>
          <span class="mm-legend-item"><span style="width:20px;height:1px;background:rgba(255,255,255,0.15);display:inline-block"></span> Neighbor</span>
        </div>
        <div class="mm-svg-wrap" id="mm-wrap">
          <svg class="mm-svg" id="mm-svg"></svg>
          <div class="mm-tooltip" id="mm-tooltip">
            <div class="mm-tooltip-name" id="mm-tt-name"></div>
            <div class="mm-tooltip-detail" id="mm-tt-detail"></div>
          </div>
        </div>
      </ha-card>
    `;

    // Controls
    this.querySelector("#mm-zoom-in").addEventListener("click", () => { this._scale *= 1.2; this._renderGraph(); });
    this.querySelector("#mm-zoom-out").addEventListener("click", () => { this._scale /= 1.2; this._renderGraph(); });
    this.querySelector("#mm-reset").addEventListener("click", () => { this._scale = 1; this._panX = 0; this._panY = 0; this._layoutNodes(); this._renderGraph(); });

    // Pan
    const wrap = this.querySelector("#mm-wrap");
    wrap.addEventListener("mousedown", (e) => {
      if (e.target.closest(".mm-node")) return;
      this._isPanning = true;
      this._panStartX = e.clientX - this._panX;
      this._panStartY = e.clientY - this._panY;
      wrap.classList.add("grabbing");
    });
    wrap.addEventListener("mousemove", (e) => {
      if (this._isPanning) {
        this._panX = e.clientX - this._panStartX;
        this._panY = e.clientY - this._panStartY;
        this._renderGraph();
      }
      if (this._dragging) {
        const svg = this.querySelector("#mm-svg");
        const rect = svg.getBoundingClientRect();
        this._dragging.x = (e.clientX - rect.left - this._panX) / this._scale;
        this._dragging.y = (e.clientY - rect.top - this._panY) / this._scale;
        this._dragging.fixed = true;
        this._renderGraph();
      }
    });
    wrap.addEventListener("mouseup", () => {
      this._isPanning = false;
      this._dragging = null;
      wrap.classList.remove("grabbing");
    });
    wrap.addEventListener("mouseleave", () => {
      this._isPanning = false;
      this._dragging = null;
      wrap.classList.remove("grabbing");
    });
    wrap.addEventListener("wheel", (e) => {
      e.preventDefault();
      this._scale *= e.deltaY < 0 ? 1.1 : 0.9;
      this._scale = Math.max(0.3, Math.min(3, this._scale));
      this._renderGraph();
    });

    this._buildGraph();
    this._layoutNodes();
    this._renderGraph();
  }

  _buildGraph() {
    const state = this._hass.states[this._entityId];
    if (!state) return;
    const devices = state.attributes.devices || [];

    // Keep existing positions if available
    const oldPos = {};
    for (const n of this._nodes) {
      oldPos[n.id] = { x: n.x, y: n.y, fixed: n.fixed };
    }

    this._nodes = [];
    this._links = [];

    // HA node
    this._nodes.push({
      id: "ha", name: "Home Assistant", role: "ha", status: "online",
      radius: 20, x: 0, y: 0, fixed: false,
      children: 0, neighbors: 0, area: "", product: "Border Router",
    });

    for (const d of devices) {
      const isRouter = ["router", "leader", "reed"].includes(d.thread_role);
      this._nodes.push({
        id: d.node_id, name: d.name, role: d.thread_role, status: d.status,
        radius: isRouter ? 16 : 10,
        x: 0, y: 0, fixed: false,
        children: d.children || 0, neighbors: d.neighbors || 0,
        area: d.area || "", product: d.product || "",
        battery: d.battery, errors: d.errors || 0,
        parent_node_id: d.parent_node_id,
      });
    }

    // Restore positions
    for (const n of this._nodes) {
      if (oldPos[n.id]) {
        n.x = oldPos[n.id].x;
        n.y = oldPos[n.id].y;
        n.fixed = oldPos[n.id].fixed;
      }
    }

    // Links: parent -> child
    for (const d of devices) {
      if (d.parent_node_id != null) {
        this._links.push({ source: d.parent_node_id, target: d.node_id, type: "parent" });
      }
    }

    // Links: routers/leader -> HA
    for (const d of devices) {
      if (d.thread_role === "leader") {
        this._links.push({ source: "ha", target: d.node_id, type: "parent" });
      }
    }

    // If no leader, connect all routers to HA
    if (!devices.some(d => d.thread_role === "leader")) {
      for (const d of devices) {
        if (d.thread_role === "router") {
          this._links.push({ source: "ha", target: d.node_id, type: "parent" });
        }
      }
    }
  }

  _layoutNodes() {
    const svg = this.querySelector("#mm-svg");
    if (!svg) return;
    const w = svg.clientWidth || 800;
    const h = svg.clientHeight || 600;
    const cx = w / 2;
    const cy = h / 2;

    // Place HA in center
    const ha = this._nodes.find(n => n.id === "ha");
    if (ha) { ha.x = cx; ha.y = cy; }

    // Place routers in circle around HA
    const routers = this._nodes.filter(n => ["router", "leader", "reed"].includes(n.role));
    const rRadius = Math.min(w, h) * 0.3;
    routers.forEach((r, i) => {
      if (r.fixed) return;
      const angle = (2 * Math.PI * i) / routers.length - Math.PI / 2;
      r.x = cx + rRadius * Math.cos(angle);
      r.y = cy + rRadius * Math.sin(angle);
    });

    // Place end devices around their parent
    const endDevices = this._nodes.filter(n => ["sed", "end_device"].includes(n.role));
    for (const ed of endDevices) {
      if (ed.fixed) continue;
      const parent = this._nodes.find(n => n.id === ed.parent_node_id);
      if (parent) {
        const siblings = endDevices.filter(e => e.parent_node_id === ed.parent_node_id);
        const idx = siblings.indexOf(ed);
        const count = siblings.length;
        const spread = Math.min(count * 25, 120);
        const baseAngle = Math.atan2(parent.y - cy, parent.x - cx);
        const angle = baseAngle + ((idx - (count - 1) / 2) * 0.4);
        const dist = rRadius * 0.45;
        ed.x = parent.x + dist * Math.cos(angle);
        ed.y = parent.y + dist * Math.sin(angle);
      } else {
        // Unassigned - place at bottom
        ed.x = cx + (Math.random() - 0.5) * w * 0.5;
        ed.y = h * 0.85 + (Math.random() - 0.5) * 40;
      }
    }
  }

  _renderGraph() {
    const svg = this.querySelector("#mm-svg");
    if (!svg) return;

    const roleColors = {
      "leader": "#ffb300", "router": "#4caf50", "reed": "#8bc34a",
      "sed": "#78909c", "end_device": "#78909c", "ha": "#03a9f4",
    };

    const nodeMap = {};
    for (const n of this._nodes) nodeMap[n.id] = n;

    let html = `<g transform="translate(${this._panX},${this._panY}) scale(${this._scale})">`;

    // Links
    for (const link of this._links) {
      const s = nodeMap[link.source];
      const t = nodeMap[link.target];
      if (!s || !t) continue;
      const isParent = link.type === "parent";
      const color = isParent ? "rgba(76,175,80,0.4)" : "rgba(255,255,255,0.08)";
      const width = isParent ? 2 : 1;
      html += `<line x1="${s.x}" y1="${s.y}" x2="${t.x}" y2="${t.y}" stroke="${color}" stroke-width="${width}" />`;
    }

    // Nodes
    for (const node of this._nodes) {
      const color = roleColors[node.role] || "#999";
      const offline = node.status === "offline";
      const opacity = offline ? 0.4 : 1;
      const strokeColor = offline ? "#f44336" : "rgba(255,255,255,0.15)";
      const strokeWidth = offline ? 2 : 1;

      // Error glow
      let glow = "";
      if (node.errors > 10000) {
        glow = `<circle cx="${node.x}" cy="${node.y}" r="${node.radius + 4}" fill="none" stroke="#f4433655" stroke-width="3" />`;
      }

      // Label
      const label = node.name.length > 18 ? node.name.substring(0, 16) + ".." : node.name;
      const fontSize = node.role === "ha" ? 11 : node.radius > 12 ? 9 : 8;

      html += `${glow}
        <g class="mm-node" data-id="${node.id}" style="cursor:pointer;opacity:${opacity}">
          <circle cx="${node.x}" cy="${node.y}" r="${node.radius}" fill="${color}" stroke="${strokeColor}" stroke-width="${strokeWidth}" />
          <text x="${node.x}" y="${node.y + node.radius + fontSize + 2}" text-anchor="middle" fill="var(--primary-text-color, #fff)" font-size="${fontSize}" font-family="inherit">${this._esc(label)}</text>
        </g>`;
    }

    html += `</g>`;
    svg.innerHTML = html;

    // Event handlers for nodes
    svg.querySelectorAll(".mm-node").forEach(g => {
      const id = g.dataset.id;
      const node = nodeMap[id === "ha" ? "ha" : parseInt(id)] || nodeMap[id];

      g.addEventListener("mousedown", (e) => {
        if (node && node.id !== "ha") {
          this._dragging = node;
          e.stopPropagation();
        }
      });

      g.addEventListener("mouseenter", (e) => {
        if (node) this._showTooltip(e, node);
      });
      g.addEventListener("mouseleave", () => this._hideTooltip());
    });
  }

  _showTooltip(e, node) {
    const tt = this.querySelector("#mm-tooltip");
    const nameEl = this.querySelector("#mm-tt-name");
    const detailEl = this.querySelector("#mm-tt-detail");
    if (!tt) return;

    nameEl.textContent = node.name;
    let detail = `Node ${node.id} | ${this._roleLabel(node.role)}`;
    if (node.area) detail += `\n${node.area}`;
    if (node.product) detail += `\n${node.product}`;
    if (node.neighbors) detail += `\n${node.neighbors} neighbors`;
    if (node.children) detail += `, ${node.children} children`;
    if (node.battery != null) detail += `\nBatterie: ${Math.round(node.battery)}%`;
    if (node.errors > 0) detail += `\nErrors: ${node.errors.toLocaleString()}`;
    if (node.status === "offline") detail += `\nOFFLINE`;
    detailEl.textContent = detail;

    const wrap = this.querySelector("#mm-wrap");
    const rect = wrap.getBoundingClientRect();
    tt.style.left = `${e.clientX - rect.left + 12}px`;
    tt.style.top = `${e.clientY - rect.top - 10}px`;
    tt.classList.add("show");
  }

  _hideTooltip() {
    const tt = this.querySelector("#mm-tooltip");
    if (tt) tt.classList.remove("show");
  }

  _roleLabel(role) {
    return {"leader":"Leader","router":"Router","reed":"REED","sed":"Sleepy End Device","end_device":"End Device","ha":"Home Assistant"}[role] || role;
  }

  _esc(str) {
    return (str || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }

  getCardSize() { return 8; }
}

customElements.define("matter-saver-mesh-card", MatterSaverMeshCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "matter-saver-mesh-card",
  name: "Matter Saver Mesh Card",
  description: "Interactive Thread mesh network visualization",
});
