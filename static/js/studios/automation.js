/**
 * Clawzd — AutomationStudio
 * Extracted from app.js for modular architecture.
 * Uses window globals for shared utilities (el, $, $$, toast, escHtml, icon, ICONS).
 */
/* global $, $$, el, toast, escHtml, icon, ICONS, OC */

// ---- Automation Studio ----
class AutomationStudio {
  constructor() {
    this.layout = $('#automation-layout');
    this.canvas = $('#auto-canvas');
    this.nodesLayer = $('#auto-nodes-layer');
    this.connsLayer = $('#auto-connections-layer');
    this.wfList = $('#auto-wf-list');
    this.propsBody = $('#auto-props-body');
    this.propsPanel = $('#auto-props-panel');
    this.propsEmpty = $('#auto-props-empty');
    this.nameInput = $('#auto-wf-name');
    this.descInput = $('#auto-wf-desc');
    this.activeToggle = $('#auto-wf-active');
    this.nodes = []; this.connections = [];
    this._allWorkflows = [];
    this.currentWf = null; this.selectedNode = null;
    this.nodeTypes = {}; this.dragNode = null;
    this.pan = { x: 0, y: 0 }; this.isPanning = false;
    this.connecting = null; this.tempLine = null;
    this.selectedConnection = null;
    this._nextId = 1;
    this._init();
  }
  async _init() {
    // Load node types
    try { const r = await fetch('/automation/node-types'); const d = await r.json(); this.nodeTypes = d.types || {}; this.modelsByProvider = d.models_by_provider || {}; } catch (e) { }
    // Buttons
    $('#auto-btn-new')?.addEventListener('click', () => this.createWorkflow());
    $('#auto-btn-globals')?.addEventListener('click', () => this.openGlobalsModal());
    $('#auto-btn-save')?.addEventListener('click', () => this.saveWorkflow());
    $('#auto-btn-execute')?.addEventListener('click', () => this.executeWorkflow(false));
    $('#auto-btn-test')?.addEventListener('click', () => this.executeWorkflow(true));
    $('#auto-props-delete')?.addEventListener('click', () => this.deleteSelectedNode());
    $('#auto-exec-log-close')?.addEventListener('click', () => { $('#auto-exec-log').style.display = 'none'; });
    $('#auto-btn-ai-generate')?.addEventListener('click', () => this.generateWorkflowAI());
    $('#auto-ai-prompt')?.addEventListener('keypress', (e) => { if (e.key === 'Enter') this.generateWorkflowAI(); });
    $('#auto-btn-delete-wf')?.addEventListener('click', () => this.deleteCurrentWorkflow());

    // Globals UI
    $('#auto-btn-globals-cancel')?.addEventListener('click', () => { $('#auto-globals-modal').style.display = 'none'; });
    $('#auto-btn-globals-save')?.addEventListener('click', () => this.saveGlobals());
    $('#auto-btn-add-global')?.addEventListener('click', () => this.addGlobalRow());

    // Palette drag and icons
    $$('.auto-palette-node').forEach(n => {
      n.addEventListener('dragstart', e => { e.dataTransfer.setData('text/plain', n.dataset.type); });
    });
    $$('.auto-icon').forEach(n => {
      if (window.icon && n.dataset.icon) {
        n.innerHTML = window.icon(n.dataset.icon, 14);
        n.style.marginRight = '8px';
        n.style.display = 'inline-flex';
        n.style.alignItems = 'center';
      }
    });
    // Search: Workflows
    $('#auto-wf-search')?.addEventListener('input', e => this._filterWorkflows(e.target.value));
    $('#auto-wf-search-clear')?.addEventListener('click', () => { const s = $('#auto-wf-search'); if (s) { s.value = ''; this._filterWorkflows(''); } });
    // Search: Palette
    $('#auto-palette-search')?.addEventListener('input', e => this._filterPalette(e.target.value));
    $('#auto-palette-search-clear')?.addEventListener('click', () => { const s = $('#auto-palette-search'); if (s) { s.value = ''; this._filterPalette(''); } });
    // Canvas drop
    const wrap = $('#auto-canvas-wrap');
    wrap?.addEventListener('dragover', e => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
    wrap?.addEventListener('drop', e => {
      e.preventDefault();
      const type = e.dataTransfer.getData('text/plain');
      if (!type || !this.nodeTypes[type]) return;
      const rect = this.canvas.getBoundingClientRect();
      const x = (e.clientX - rect.left - this.pan.x);
      const y = (e.clientY - rect.top - this.pan.y);
      this.addNode(type, x, y);
    });
    // Canvas pan
    this.canvas?.addEventListener('mousedown', e => {
      if (e.target === this.canvas || e.target.tagName === 'rect' && !e.target.classList.contains('auto-node-body')) {
        this.isPanning = true; this._panStart = { x: e.clientX - this.pan.x, y: e.clientY - this.pan.y };
        this.selectedConnection = null;
        this.deselectNode();
      }
    });
    window.addEventListener('mousemove', e => {
      if (this.isPanning) {
        this.pan.x = e.clientX - this._panStart.x;
        this.pan.y = e.clientY - this._panStart.y;
        this.nodesLayer.setAttribute('transform', `translate(${this.pan.x},${this.pan.y})`);
        this.connsLayer.setAttribute('transform', `translate(${this.pan.x},${this.pan.y})`);
      }
      if (this.connecting && this.tempLine) {
        const rect = this.canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left - this.pan.x;
        const my = e.clientY - rect.top - this.pan.y;
        const sx = this.connecting.portX, sy = this.connecting.portY;
        this.tempLine.setAttribute('d', `M${sx},${sy} C${sx + 80},${sy} ${mx - 80},${my} ${mx},${my}`);
      }
      if (this.dragNode) {
        const rect = this.canvas.getBoundingClientRect();
        this.dragNode.node.x = e.clientX - rect.left - this.pan.x - this.dragNode.ox;
        this.dragNode.node.y = e.clientY - rect.top - this.pan.y - this.dragNode.oy;
        this.renderNodes(); this.renderConnections();
      }
    });
    window.addEventListener('mouseup', () => {
      this.isPanning = false; this.dragNode = null;
      if (this.connecting) { this._cancelConnect(); }
    });
    // Keyboard: Delete / Backspace to remove selected node or connection
    window.addEventListener('keydown', e => {
      if (e.key !== 'Delete' && e.key !== 'Backspace') return;
      // Don't intercept when typing in inputs
      const tag = document.activeElement?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      // Only when automation mode is visible
      if (!this.layout || this.layout.style.display === 'none') return;
      e.preventDefault();
      if (this.selectedNode) {
        this.deleteSelectedNode();
      } else if (this.selectedConnection !== null && this.selectedConnection !== undefined) {
        this.connections.splice(this.selectedConnection, 1);
        this.selectedConnection = null;
        this.renderConnections();
      }
    });
    // Load workflows
    this.loadWorkflows();
  }
  toggle(show) {
    if (this.layout) this.layout.style.display = show ? 'flex' : 'none';
    if (show) this.loadWorkflows();
  }
  // ── Globals Management ──
  async openGlobalsModal() {
    const modal = $('#auto-globals-modal');
    if (!modal) return;
    modal.style.display = 'flex';
    $('#auto-globals-list').innerHTML = '<div style="color:var(--text-muted)">Loading...</div>';
    try {
      const r = await fetch('/automation/globals');
      const d = await r.json();
      this.globalsData = d.globals || {};
      this.renderGlobalsList();
    } catch (e) {
      toast(ICONS.x(14) + ' Failed to load globals');
    }
  }
  renderGlobalsList() {
    const list = $('#auto-globals-list');
    if (!list) return;
    list.innerHTML = '';
    const keys = Object.keys(this.globalsData);
    if (keys.length === 0) {
      list.innerHTML = '<div style="color:var(--text-muted); font-size:12px; margin-bottom:10px;">No global variables yet.</div>';
    }
    keys.forEach(k => {
      this.addGlobalRow(k, this.globalsData[k]);
    });
  }
  addGlobalRow(key = '', val = '') {
    const list = $('#auto-globals-list');
    if (!list) return;
    const row = document.createElement('div');
    row.style.display = 'flex';
    row.style.gap = '8px';

    const keyInp = document.createElement('input');
    keyInp.className = 'auto-prop-input global-key';
    keyInp.placeholder = 'Key (e.g. API_KEY)';
    keyInp.value = key;
    keyInp.style.flex = '1';

    const valInp = document.createElement('input');
    valInp.className = 'auto-prop-input global-val';
    valInp.placeholder = 'Value';
    valInp.value = val;
    valInp.style.flex = '2';

    const delBtn = document.createElement('button');
    delBtn.className = 'icon-btn';
    delBtn.style.color = '#ff5555';
    delBtn.innerHTML = window.icon ? window.icon('trash', 14) : '';
    delBtn.onclick = () => row.remove();

    row.appendChild(keyInp);
    row.appendChild(valInp);
    row.appendChild(delBtn);
    list.appendChild(row);
  }
  async saveGlobals() {
    const modal = $('#auto-globals-modal');
    const list = $('#auto-globals-list');
    if (!modal || !list) return;

    const newGlobals = {};
    Array.from(list.children).forEach(row => {
      const k = row.querySelector('.global-key')?.value.trim();
      const v = row.querySelector('.global-val')?.value.trim();
      if (k) newGlobals[k] = v || '';
    });

    try {
      const r = await fetch('/automation/globals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ globals: newGlobals })
      });
      if (r.ok) {
        toast(ICONS.check(14) + ' Global variables saved');
        modal.style.display = 'none';
      } else {
        toast(ICONS.x(14) + ' Failed to save globals');
      }
    } catch (e) {
      toast(ICONS.x(14) + ' Error saving globals');
    }
  }
  // ── Node Management ──
  addNode(type, x, y) {
    const nt = this.nodeTypes[type];
    if (!nt) return;
    const id = 'n' + (this._nextId++);
    const node = { id, type, label: nt.label, x: Math.round(x), y: Math.round(y), params: {} };
    // Set default params
    (nt.params || []).forEach(p => { node.params[p.key] = p.default ?? ''; });
    this.nodes.push(node);
    this.renderNodes(); this.renderConnections();
    this.selectNode(id);
    return node;
  }
  selectNode(id) {
    this.selectedNode = id;
    this.selectedConnection = null;
    this.renderNodes();
    this.renderConnections();
    this.renderProps();
  }
  deselectNode() {
    this.selectedNode = null;
    this.renderNodes();
    if (this.propsPanel) this.propsPanel.style.display = 'none';
    if (this.propsEmpty) this.propsEmpty.style.display = '';
  }
  deleteSelectedNode() {
    if (!this.selectedNode) return;
    this.nodes = this.nodes.filter(n => n.id !== this.selectedNode);
    this.connections = this.connections.filter(c => c.source !== this.selectedNode && c.target !== this.selectedNode);
    this.deselectNode(); this.renderNodes(); this.renderConnections();
  }
  // ── SVG Rendering ──
  renderNodes() {
    if (!this.nodesLayer) return;
    this.nodesLayer.innerHTML = '';
    const NW = 180, NH = 60, HH = 28;
    this.nodes.forEach(node => {
      const nt = this.nodeTypes[node.type] || {};
      const color = nt.color || '#666';
      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.setAttribute('class', 'auto-node-group' + (this.selectedNode === node.id ? ' selected' : ''));
      g.setAttribute('transform', `translate(${node.x},${node.y})`);
      // Body
      const body = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      body.setAttribute('class', 'auto-node-body');
      body.setAttribute('width', NW); body.setAttribute('height', NH);
      body.setAttribute('rx', 8); body.setAttribute('ry', 8);
      g.appendChild(body);
      // Header
      const hdr = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      hdr.setAttribute('width', NW); hdr.setAttribute('height', HH);
      hdr.setAttribute('rx', 8); hdr.setAttribute('ry', 8);
      hdr.setAttribute('fill', color); hdr.setAttribute('fill-opacity', '0.9');
      g.appendChild(hdr);
      // Header bottom (square corners)
      const hdr2 = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      hdr2.setAttribute('x', 0); hdr2.setAttribute('y', HH - 8);
      hdr2.setAttribute('width', NW); hdr2.setAttribute('height', 8);
      hdr2.setAttribute('fill', color); hdr2.setAttribute('fill-opacity', '0.9');
      g.appendChild(hdr2);
      // Icon
      const iconName = nt.icon || 'bolt';
      const iconWrapper = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      iconWrapper.setAttribute('transform', `translate(8, ${HH / 2 - 9})`);
      iconWrapper.style.color = '#ffffff';
      if (window.icon) {
        iconWrapper.innerHTML = window.icon(iconName, 18);
      }
      g.appendChild(iconWrapper);

      // Title
      const ttl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      ttl.setAttribute('class', 'auto-node-title');
      ttl.setAttribute('x', 32); ttl.setAttribute('y', HH / 2 + 4);
      ttl.textContent = (node.label || nt.label || node.type).substring(0, 18);
      g.appendChild(ttl);
      // Subtitle (type)
      const sub = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      sub.setAttribute('class', 'auto-node-subtitle');
      sub.setAttribute('x', 10); sub.setAttribute('y', NH - 8);
      sub.textContent = node.type;
      g.appendChild(sub);
      // Input ports
      const inputs = nt.inputs || [];
      inputs.forEach((inp, i) => {
        const py = HH + (NH - HH) / (inputs.length + 1) * (i + 1);
        const port = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        port.setAttribute('class', 'auto-node-port');
        port.setAttribute('cx', 0); port.setAttribute('cy', py);
        port.setAttribute('r', 6);
        port.setAttribute('data-node', node.id); port.setAttribute('data-port', inp);
        port.setAttribute('data-dir', 'input');
        port.addEventListener('mouseup', e => { e.stopPropagation(); this._finishConnect(node.id, inp); });
        g.appendChild(port);
      });
      // Output ports
      const outputs = nt.outputs || [];
      outputs.forEach((out, i) => {
        const py = HH + (NH - HH) / (outputs.length + 1) * (i + 1);
        const port = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        port.setAttribute('class', 'auto-node-port');
        port.setAttribute('cx', NW); port.setAttribute('cy', py);
        port.setAttribute('r', 6);
        port.setAttribute('data-node', node.id); port.setAttribute('data-port', out);
        port.setAttribute('data-dir', 'output');
        port.addEventListener('mousedown', e => {
          e.stopPropagation();
          this._startConnect(node.id, out, node.x + NW, node.y + py);
        });
        g.appendChild(port);
        if (outputs.length > 1) {
          const lbl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
          lbl.setAttribute('class', 'auto-node-port-label');
          lbl.setAttribute('x', NW + 10); lbl.setAttribute('y', py + 3);
          lbl.textContent = out;
          g.appendChild(lbl);
        }
      });
      // Drag
      g.addEventListener('mousedown', e => {
        if (e.target.classList.contains('auto-node-port')) return;
        e.stopPropagation();
        this.selectNode(node.id);
        const rect = this.canvas.getBoundingClientRect();
        this.dragNode = { node, ox: e.clientX - rect.left - this.pan.x - node.x, oy: e.clientY - rect.top - this.pan.y - node.y };
      });
      this.nodesLayer.appendChild(g);
    });
  }
  renderConnections() {
    if (!this.connsLayer) return;
    this.connsLayer.innerHTML = '';
    const NW = 180, NH = 60, HH = 28;
    this.connections.forEach((conn, idx) => {
      const src = this.nodes.find(n => n.id === conn.source);
      const tgt = this.nodes.find(n => n.id === conn.target);
      if (!src || !tgt) return;
      const srcNt = this.nodeTypes[src.type] || {};
      const tgtNt = this.nodeTypes[tgt.type] || {};
      const srcOutputs = srcNt.outputs || ['main'];
      const srcIdx = Math.max(0, srcOutputs.indexOf(conn.sourceOutput || 'main'));
      const sx = src.x + NW;
      const sy = src.y + HH + (NH - HH) / (srcOutputs.length + 1) * (srcIdx + 1);
      const tgtInputs = tgtNt.inputs || ['main'];
      const tgtIdx = Math.max(0, tgtInputs.indexOf(conn.targetInput || 'main'));
      const tx = tgt.x;
      const ty = tgt.y + HH + (NH - HH) / (tgtInputs.length + 1) * (tgtIdx + 1);
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      const dx = Math.abs(tx - sx) * 0.5;
      path.setAttribute('d', `M${sx},${sy} C${sx + dx},${sy} ${tx - dx},${ty} ${tx},${ty}`);
      path.setAttribute('class', 'auto-connection' + (this.selectedConnection === idx ? ' selected' : ''));
      if (this.selectedConnection === idx) {
        path.setAttribute('stroke', 'var(--accent)'); path.setAttribute('stroke-width', '3');
      }
      path.addEventListener('click', (e) => {
        e.stopPropagation();
        this.deselectNode();
        this.selectedConnection = idx;
        this.renderConnections();
      });
      path.addEventListener('dblclick', () => {
        this.connections = this.connections.filter(c => c !== conn);
        this.selectedConnection = null;
        this.renderConnections();
      });
      this.connsLayer.appendChild(path);
    });
  }
  // ── Connection drawing ──
  _startConnect(nodeId, output, px, py) {
    this.connecting = { nodeId, output, portX: px, portY: py };
    this.tempLine = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    this.tempLine.setAttribute('class', 'auto-connection-temp');
    this.tempLine.setAttribute('d', `M${px},${py} C${px},${py} ${px},${py} ${px},${py}`);
    this.connsLayer.appendChild(this.tempLine);
  }
  _finishConnect(targetId, targetInput) {
    if (!this.connecting || this.connecting.nodeId === targetId) { this._cancelConnect(); return; }
    // Check for duplicate
    const exists = this.connections.some(c => c.source === this.connecting.nodeId && c.sourceOutput === this.connecting.output && c.target === targetId && c.targetInput === targetInput);
    if (!exists) {
      this.connections.push({ source: this.connecting.nodeId, sourceOutput: this.connecting.output, target: targetId, targetInput: targetInput });
    }
    this._cancelConnect();
    this.renderConnections();
  }
  _cancelConnect() {
    this.connecting = null;
    if (this.tempLine) { this.tempLine.remove(); this.tempLine = null; }
  }
  // ── Properties Panel ──
  renderProps() {
    const node = this.nodes.find(n => n.id === this.selectedNode);
    if (!node) { this.deselectNode(); return; }
    const nt = this.nodeTypes[node.type] || {};
    if (this.propsEmpty) this.propsEmpty.style.display = 'none';
    if (this.propsPanel) this.propsPanel.style.display = '';
    const title = $('#auto-props-title');
    if (title) title.textContent = `${nt.icon || ''} ${nt.label || node.type}`;
    if (!this.propsBody) return;
    this.propsBody.innerHTML = '';
    // Label edit
    const labelGrp = document.createElement('div'); labelGrp.className = 'auto-prop-group';
    labelGrp.innerHTML = `<label class="auto-prop-label">Label</label>`;
    const labelInp = document.createElement('input'); labelInp.className = 'auto-prop-input';
    labelInp.value = node.label || nt.label || ''; labelInp.addEventListener('input', () => { node.label = labelInp.value; this.renderNodes(); });
    labelGrp.appendChild(labelInp); this.propsBody.appendChild(labelGrp);
    // Params
    const inputsByKey = {};
    (nt.params || []).forEach(p => {
      const grp = document.createElement('div'); grp.className = 'auto-prop-group';
      grp.innerHTML = `<label class="auto-prop-label">${p.label}</label>`;
      let inp;
      if (p.type === 'textarea') {
        inp = document.createElement('textarea'); inp.className = 'auto-prop-textarea';
        inp.value = node.params[p.key] ?? p.default ?? '';
        inp.rows = 4;
      } else if (p.type === 'select') {
        inp = document.createElement('select'); inp.className = 'auto-prop-select';
        (p.options || []).forEach(o => { const opt = document.createElement('option'); opt.value = o; opt.textContent = o; inp.appendChild(opt); });
        inp.value = node.params[p.key] ?? p.default ?? '';
      } else if (p.type === 'number') {
        inp = document.createElement('input'); inp.className = 'auto-prop-input';
        inp.type = 'number'; inp.value = node.params[p.key] ?? p.default ?? 0;
      } else {
        inp = document.createElement('input'); inp.className = 'auto-prop-input';
        inp.type = 'text'; inp.value = node.params[p.key] ?? p.default ?? '';
      }
      inp.addEventListener('input', () => { node.params[p.key] = inp.value; });
      inp.addEventListener('change', () => { node.params[p.key] = inp.value; });
      inputsByKey[p.key] = inp;
      grp.appendChild(inp); this.propsBody.appendChild(grp);
    });

    // Provider -> Model linking
    if (inputsByKey['provider'] && inputsByKey['model']) {
      const provInp = inputsByKey['provider'];
      const modInp = inputsByKey['model'];

      let selectMod = modInp;
      if (modInp.tagName !== 'SELECT') {
        selectMod = document.createElement('select');
        selectMod.className = 'auto-prop-select';
        modInp.parentNode.replaceChild(selectMod, modInp);
        inputsByKey['model'] = selectMod;
        selectMod.addEventListener('change', () => { node.params['model'] = selectMod.value; });
      }

      const updateModels = () => {
        const prov = provInp.value;
        const models = this.modelsByProvider[prov] || [];
        const currentMod = node.params['model'];

        selectMod.innerHTML = '';
        models.forEach(m => {
          const opt = document.createElement('option');
          opt.value = m;
          opt.textContent = m;
          selectMod.appendChild(opt);
        });

        if (models.includes(currentMod)) {
          selectMod.value = currentMod;
        } else if (models.length > 0) {
          selectMod.value = models[0];
          node.params['model'] = models[0];
        } else {
          node.params['model'] = '';
        }
      };

      provInp.addEventListener('change', updateModels);
      updateModels(); // Initialize options for the currently selected provider
    }
  }
  // ── Workflow CRUD ──
  async loadWorkflows() {
    try {
      const r = await fetch('/automation/workflows'); const d = await r.json();
      this._allWorkflows = d.workflows || [];
      this._renderWorkflowList();
    } catch (e) { console.error('Failed to load workflows', e); }
  }
  _renderWorkflowList(filter = '') {
    const wfs = this._allWorkflows;
    if (!this.wfList) return;
    const q = filter.toLowerCase().trim();
    const filtered = q ? wfs.filter(wf => {
      const name = (wf.name || '').toLowerCase();
      const desc = (wf.description || '').toLowerCase();
      const nodeTypes = (wf.nodes || []).map(n => (n.type || '') + ' ' + (n.label || '')).join(' ').toLowerCase();
      return name.includes(q) || desc.includes(q) || nodeTypes.includes(q);
    }) : wfs;
    if (!filtered.length) {
      this.wfList.innerHTML = q
        ? '<div class="auto-wf-empty">No matching workflows.</div>'
        : '<div class="auto-wf-empty">No workflows yet.<br>Click + to create one.</div>';
      return;
    }
    this.wfList.innerHTML = '';
    filtered.forEach(wf => {
      const item = document.createElement('div');
      item.className = 'auto-wf-item' + (this.currentWf?.id === wf.id ? ' active' : '');
      const descHint = wf.description ? `<span class="auto-wf-item-desc">${escHtml(wf.description.substring(0, 40))}</span>` : '';
      item.innerHTML = `<div class="auto-wf-item-info"><span class="auto-wf-item-name">${escHtml(wf.name)}</span>${descHint}</div>` +
        `<span class="auto-wf-item-badge ${wf.active ? 'active' : 'inactive'}">${wf.active ? 'ON' : 'OFF'}</span>` +
        `<button class="auto-wf-item-delete icon-btn" title="Delete" style="color:var(--red); margin-left: 8px;">${window.icon ? window.icon('trash', 14) : '🗑️'}</button>`;
      item.querySelector('.auto-wf-item-info').addEventListener('click', () => this.loadWorkflow(wf.id));
      item.querySelector('.auto-wf-item-delete').addEventListener('click', async e => {
        e.stopPropagation();
        await fetch(`/automation/workflows/${wf.id}`, { method: 'DELETE' });
        if (this.currentWf?.id === wf.id) { this.currentWf = null; this.nodes = []; this.connections = []; this.renderNodes(); this.renderConnections(); this.deselectNode(); }
        this.loadWorkflows(); toast(ICONS.circle(14) + ' ️ Workflow deleted');
      });
      this.wfList.appendChild(item);
    });
  }
  _filterWorkflows(q) { this._renderWorkflowList(q); }
  _filterPalette(q) {
    const palette = $('#auto-palette');
    if (!palette) return;
    const term = q.toLowerCase().trim();
    palette.querySelectorAll('.auto-palette-group').forEach(group => {
      let anyVisible = false;
      group.querySelectorAll('.auto-palette-node').forEach(node => {
        const text = node.textContent.toLowerCase();
        const type = (node.dataset.type || '').toLowerCase();
        const match = !term || text.includes(term) || type.includes(term);
        node.style.display = match ? '' : 'none';
        if (match) anyVisible = true;
      });
      group.style.display = anyVisible ? '' : 'none';
    });
  }
  async loadWorkflow(id) {
    try {
      const r = await fetch(`/automation/workflows/${id}`); const d = await r.json();
      const wf = d.workflow;
      this.currentWf = wf; this.nodes = wf.nodes || []; this.connections = wf.connections || [];
      if (this.nameInput) this.nameInput.value = wf.name || '';
      if (this.descInput) this.descInput.value = wf.description || '';
      if (this.activeToggle) this.activeToggle.checked = wf.active || false;
      // Recalculate next id
      this._nextId = 1;
      this.nodes.forEach(n => { const num = parseInt(n.id.replace('n', '')); if (num >= this._nextId) this._nextId = num + 1; });
      this.deselectNode(); this.renderNodes(); this.renderConnections(); this.loadWorkflows();
      if ($('#auto-btn-delete-wf')) $('#auto-btn-delete-wf').style.display = 'inline-flex';
      toast(`${ICONS.folderOpen(14)} Loaded: ${wf.name}`);
    } catch (e) { toast(ICONS.x(14) + ' Failed to load workflow'); }
  }
  async createWorkflow() {
    const name = prompt('Workflow name:', 'New Workflow');
    if (!name?.trim()) return;
    try {
      const r = await fetch('/automation/workflows', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name.trim() }) });
      const d = await r.json();
      this.currentWf = d.workflow; this.nodes = []; this.connections = [];
      if (this.nameInput) this.nameInput.value = name.trim();
      if (this.descInput) this.descInput.value = '';
      if (this.activeToggle) this.activeToggle.checked = false;
      this.deselectNode(); this.renderNodes(); this.renderConnections(); this.loadWorkflows();
      if ($('#auto-btn-delete-wf')) $('#auto-btn-delete-wf').style.display = 'none';
      toast(`${ICONS.check(14)} Workflow created: ${name.trim()}`);
    } catch (e) { toast(ICONS.x(14) + ' Failed to create workflow'); }
  }
  async saveWorkflow() {
    if (!this.currentWf) { toast(ICONS.circle(14) + ' ️ Create a workflow first'); return; }
    const name = this.nameInput?.value || this.currentWf.name;
    const description = this.descInput?.value || '';
    const active = this.activeToggle?.checked || false;
    try {
      await fetch(`/automation/workflows/${this.currentWf.id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description, nodes: this.nodes, connections: this.connections, active })
      });
      this.currentWf.name = name; this.currentWf.description = description; this.currentWf.active = active;
      this.loadWorkflows(); toast(ICONS.download(14) + ' Workflow saved!');
      if ($('#auto-btn-delete-wf') && this.currentWf && !this.currentWf.id.startsWith('temp_')) {
        $('#auto-btn-delete-wf').style.display = 'inline-flex';
      }
    } catch (e) { toast(ICONS.x(14) + ' Failed to save workflow'); }
  }
  
  async deleteCurrentWorkflow() {
    if (!this.currentWf || this.currentWf.id.startsWith('temp_')) return;
    if (!confirm(`Are you sure you want to delete workflow "${this.currentWf.name}"?`)) return;
    try {
      await fetch(`/automation/workflows/${this.currentWf.id}`, { method: 'DELETE' });
      this.currentWf = null; this.nodes = []; this.connections = [];
      this.renderNodes(); this.renderConnections(); this.deselectNode();
      this.loadWorkflows();
      if (this.nameInput) this.nameInput.value = 'New Workflow';
      if (this.descInput) this.descInput.value = '';
      if ($('#auto-btn-delete-wf')) $('#auto-btn-delete-wf').style.display = 'none';
      toast(ICONS.circle(14) + ' ️ Workflow deleted');
    } catch (e) {
      toast(ICONS.x(14) + ' Failed to delete workflow');
    }
  }

  async executeWorkflow(testingMode = false) {
    if (!this.currentWf) { toast(ICONS.circle(14) + ' ️ No workflow loaded'); return; }
    // Save first
    await this.saveWorkflow();
    toast(testingMode ? ' Testing workflow (no real sends)...' : ICONS.play(14) + ' Executing workflow...');
    const logEl = $('#auto-exec-log'); const logBody = $('#auto-exec-log-body');
    if (logEl) logEl.style.display = '';
    if (logBody) logBody.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted)">⏳ Running...</div>';
    try {
      const r = await fetch(`/automation/workflows/${this.currentWf.id}/execute`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ testing_mode: testingMode })
      });
      const result = await r.json();
      if (logBody) {
        logBody.innerHTML = '';
        // Testing mode header
        if (testingMode) {
          const banner = document.createElement('div');
          banner.className = 'auto-test-banner';
          banner.innerHTML = ' <strong>TESTING MODE</strong> — Communication nodes were simulated, no real messages sent.';
          logBody.appendChild(banner);
        }
        (result.log || []).forEach(entry => {
          const div = document.createElement('div'); div.className = 'auto-log-entry';
          div.style.cursor = 'pointer';
          div.style.flexDirection = 'column';
          div.style.alignItems = 'stretch';

          const header = document.createElement('div');
          header.style.display = 'flex';
          header.style.alignItems = 'center';
          header.style.gap = '10px';
          const simBadge = entry.simulated ? '<span class="auto-test-badge"> SIM</span>' : '';
          header.innerHTML = `<div class="auto-log-status ${entry.status}"></div>` +
            `<span class="auto-log-node" style="min-width:120px;"><strong>${entry.node_label || entry.node_type}</strong></span>` +
            simBadge +
            `<span class="auto-log-duration" style="font-size:12px;opacity:0.7;">${Math.round(entry.duration_ms)}ms</span>` +
            `<span class="auto-log-preview" style="flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${(entry.output_preview || '').substring(0, 80)}</span>`;

          const details = document.createElement('div');
          details.style.display = 'none';
          details.style.marginTop = '8px';
          details.style.padding = '8px';
          details.style.background = 'var(--bg-elevated)';
          details.style.borderRadius = '4px';
          details.style.fontSize = '12px';
          details.style.whiteSpace = 'pre-wrap';
          details.style.wordBreak = 'break-word';
          details.style.borderLeft = entry.status === 'error' ? '3px solid var(--red)' : entry.simulated ? '3px solid #f59e0b' : '3px solid var(--accent)';
          const fullRes = result.results ? result.results[entry.node_id] : entry.output_preview;
          details.textContent = fullRes || 'No details';

          div.appendChild(header);
          div.appendChild(details);

          div.onclick = () => {
            details.style.display = details.style.display === 'none' ? 'block' : 'none';
          };

          logBody.appendChild(div);
        });
      }
      const isTest = result.testing_mode;
      if (isTest) {
        toast(result.status.includes('error') ? ' Test completed with errors' : ' Test completed successfully!');
      } else {
        toast(result.status === 'success' ? ' Workflow completed!' : '️ Workflow completed with errors');
      }
    } catch (e) { toast(' Execution failed: ' + e.message); }
  }

  async generateWorkflowAI() {
    const input = $('#auto-ai-prompt');
    const prompt = input?.value.trim();
    if (!prompt) { toast('Please enter a description for the workflow.'); return; }
    const btn = $('#auto-btn-ai-generate');
    if (btn) { btn.disabled = true; btn.classList.add('loading'); }
    toast(ICONS.sparkles(14) + ' AI is generating/updating your workflow...');

    try {
      const res = await fetch('/automation/workflows/ai-generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: prompt,
          current_workflow: this.currentWf ? { nodes: this.nodes, connections: this.connections, name: this.nameInput?.value } : null
        })
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      if (data.nodes) {
        this.nodes = data.nodes;
        this.connections = data.connections || [];
        if (data.name && this.nameInput) this.nameInput.value = data.name;
        if (!this.currentWf) {
          // Create a new local unsaved workflow context if not loaded
          this.currentWf = { id: 'temp_' + Date.now(), name: data.name || 'AI Workflow', active: false };
          if (this.nameInput) this.nameInput.value = this.currentWf.name;
        }
        // Recalculate nextId
        this._nextId = 1;
        this.nodes.forEach(n => { const num = parseInt(n.id.replace('n', '')); if (num >= this._nextId) this._nextId = num + 1; });

        this.renderNodes();
        this.renderConnections();
        this.deselectNode();
        toast(ICONS.check(14) + ' Workflow updated by AI! Remember to Save.');
      } else {
        throw new Error('Invalid AI response');
      }
    } catch (e) {
      toast(' AI Generation failed: ' + e.message);
    } finally {
      if (btn) { btn.disabled = false; btn.classList.remove('loading'); }
    }
  }
}

// Backward compatibility
window.AutomationStudio = AutomationStudio;
