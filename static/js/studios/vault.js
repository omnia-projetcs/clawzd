/**
 * Clawzd — VaultStudio
 * Knowledge Vault: import documents, vectorize them into the global RAG,
 * browse/search indexed sources, and visualize the knowledge graph.
 */
/* global $, $$, toast, escHtml, ICONS */

class VaultStudio {
  constructor() {
    this.layout = $('#vault-layout');
    this._graphNodes = [];
    this._graphEdges = [];
    this._init();
  }

  _init() {
    // Upload zone
    const zone = $('#vault-upload-zone');
    const fileInput = $('#vault-file-input');
    if (zone && fileInput) {
      zone.addEventListener('click', () => fileInput.click());
      zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
      zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
      zone.addEventListener('drop', e => {
        e.preventDefault();
        zone.classList.remove('dragover');
        if (e.dataTransfer.files.length) this.uploadFiles(e.dataTransfer.files);
      });
      fileInput.addEventListener('change', () => {
        if (fileInput.files.length) this.uploadFiles(fileInput.files);
        fileInput.value = '';
      });
    }
    // Search
    $('#vault-search-btn')?.addEventListener('click', () => this.search());
    $('#vault-search-input')?.addEventListener('keydown', e => {
      if (e.key === 'Enter') this.search();
    });
    $('#vault-search-close')?.addEventListener('click', () => {
      const r = $('#vault-search-results');
      if (r) r.style.display = 'none';
    });
    // Actions
    $('#vault-btn-scan')?.addEventListener('click', () => this.scanFolder());
    $('#vault-btn-clear')?.addEventListener('click', () => this.clearAll());
    $('#vault-sources-refresh')?.addEventListener('click', () => this.loadSources());
    $('#vault-graph-refresh')?.addEventListener('click', () => this.loadGraph());
  }

  toggle(show) {
    if (this.layout) this.layout.style.display = show ? 'grid' : 'none';
    if (show) this._load();
  }

  async _load() {
    await Promise.all([this.loadStats(), this.loadSources(), this.loadGraph()]);
  }

  // ── Stats ──
  async loadStats() {
    try {
      const r = await fetch('/clone/vault/stats');
      const d = await r.json();
      const docs = $('#vault-stat-docs');
      const chunks = $('#vault-stat-chunks');
      if (docs) docs.textContent = d.source_count || 0;
      if (chunks) chunks.textContent = d.total_chunks || 0;
    } catch (e) { console.error('Vault: loadStats failed', e); }
  }

  // ── Sources ──
  async loadSources() {
    try {
      const r = await fetch('/clone/vault/sources');
      const d = await r.json();
      const list = $('#vault-sources-list');
      if (!list) return;
      const sources = d.sources || [];
      if (!sources.length) {
        list.innerHTML = '<div class="vault-empty">No documents indexed yet.<br>Upload files to get started.</div>';
        return;
      }
      list.innerHTML = '';
      const typeColors = {
        PDF: '#ef4444', Word: '#3b82f6', Excel: '#10b981', CSV: '#06b6d4',
        Markdown: '#8b5cf6', Text: '#6b7280', PowerPoint: '#f59e0b', Archive: '#78716c',
      };
      sources.forEach(s => {
        const color = s.file_type?.startsWith('Code') ? '#22d3ee' : (typeColors[s.file_type] || '#a855f7');
        const div = document.createElement('div');
        div.className = 'vault-source-item';
        div.innerHTML = `
          <span class="vault-source-badge" style="background:${color}">${escHtml(s.file_type || '?')}</span>
          <span class="vault-source-name" title="${escHtml(s.name)}">${escHtml(s.name)}</span>
          <span class="vault-source-chunks">${s.chunks} chunks</span>
          <button class="icon-btn vault-source-delete" title="Delete" style="color:#ef4444">
            <svg class="ic" width="12" height="12"><use href="#icon-x"></use></svg>
          </button>`;
        div.querySelector('.vault-source-delete')?.addEventListener('click', e => {
          e.stopPropagation();
          this.deleteSource(s.name);
        });
        list.appendChild(div);
      });
    } catch (e) { console.error('Vault: loadSources failed', e); }
  }

  // ── Upload ──
  async uploadFiles(fileList) {
    const progress = $('#vault-upload-progress');
    const fill = $('#vault-progress-fill');
    const text = $('#vault-progress-text');
    if (progress) progress.style.display = 'block';
    if (fill) fill.style.width = '10%';
    if (text) text.textContent = `Indexing ${fileList.length} file(s)...`;

    const formData = new FormData();
    for (const f of fileList) formData.append('files', f);

    try {
      if (fill) fill.style.width = '40%';
      const r = await fetch('/clone/vault/upload', { method: 'POST', body: formData });
      const d = await r.json();
      if (fill) fill.style.width = '100%';
      const indexed = d.indexed || 0;
      if (text) text.textContent = `✓ ${indexed} file(s) indexed`;
      toast(ICONS.check(14) + ` ${indexed} file(s) vectorized`);
      await this._load();
    } catch (e) {
      if (text) text.textContent = '✗ Upload failed';
      toast('Upload failed: ' + e.message);
    }
    setTimeout(() => { if (progress) progress.style.display = 'none'; }, 2000);
  }

  // ── Delete ──
  async deleteSource(name) {
    if (!confirm(`Delete "${name}" from the knowledge base?`)) return;
    try {
      const r = await fetch(`/clone/vault/source/${encodeURIComponent(name)}`, { method: 'DELETE' });
      const d = await r.json();
      toast(ICONS.check(14) + ` Removed ${d.chunks_removed || 0} chunks`);
      await this._load();
    } catch (e) { toast('Delete failed'); }
  }

  // ── Search ──
  async search() {
    const input = $('#vault-search-input');
    const query = input?.value?.trim();
    if (!query) { toast('Enter a search query'); return; }
    const results = $('#vault-search-results');
    const body = $('#vault-results-body');
    if (results) results.style.display = 'block';
    if (body) body.innerHTML = '<div class="vault-empty">Searching...</div>';

    try {
      const r = await fetch(`/clone/vault/search?query=${encodeURIComponent(query)}&k=8`);
      const d = await r.json();
      const docs = d.documents || [];
      const metas = d.metadatas || [];
      const scores = d.scores || [];
      if (!docs.length) {
        if (body) body.innerHTML = '<div class="vault-empty">No results found.</div>';
        return;
      }
      if (body) {
        body.innerHTML = '';
        docs.forEach((doc, i) => {
          const meta = metas[i] || {};
          const score = scores[i] || 0;
          const div = document.createElement('div');
          div.className = 'vault-result-item';
          div.innerHTML = `
            <div class="vault-result-header">
              <span class="vault-result-source">${escHtml(meta.source || '?')} · ${escHtml(meta.file_type || '')}</span>
              <span class="vault-result-score">${score}%</span>
            </div>
            <div class="vault-result-text">${escHtml(doc.substring(0, 300))}${doc.length > 300 ? '…' : ''}</div>`;
          body.appendChild(div);
        });
      }
    } catch (e) {
      if (body) body.innerHTML = '<div class="vault-empty">Search failed.</div>';
    }
  }

  // ── Scan RAG Folder ──
  async scanFolder() {
    toast('Scanning data/rag/ folder...');
    try {
      const r = await fetch('/rag/scan', { method: 'POST' });
      const d = await r.json();
      const added = (d.added || []).length;
      const updated = (d.updated || []).length;
      toast(ICONS.check(14) + ` Scan complete: ${added} new, ${updated} updated`);
      await this._load();
    } catch (e) { toast('Scan failed: ' + e.message); }
  }

  // ── Clear All ──
  async clearAll() {
    if (!confirm('Clear the ENTIRE knowledge base? This affects both Vault and global RAG.')) return;
    try {
      await fetch('/clone/vault/clear', { method: 'DELETE' });
      toast(ICONS.check(14) + ' Knowledge base cleared');
      await this._load();
    } catch (e) { toast('Clear failed'); }
  }

  // ── Knowledge Graph ──
  async loadGraph() {
    try {
      const r = await fetch('/clone/vault/graph');
      const d = await r.json();
      this._graphNodes = d.nodes || [];
      this._graphEdges = d.edges || [];
      this._renderGraph();
    } catch (e) { console.error('Vault: loadGraph failed', e); }
  }

  _renderGraph() {
    const svg = $('#vault-graph-svg');
    const empty = $('#vault-graph-empty');
    if (!svg) return;

    const nodes = this._graphNodes;
    const edges = this._graphEdges;

    if (!nodes.length) {
      svg.innerHTML = '';
      if (empty) empty.style.display = 'flex';
      return;
    }
    if (empty) empty.style.display = 'none';

    const w = svg.clientWidth || 320;
    const h = svg.clientHeight || 400;
    const cx = w / 2, cy = h / 2;

    // Position nodes in a circle or force layout
    const nodeMap = {};
    nodes.forEach((n, i) => {
      const angle = (2 * Math.PI * i) / nodes.length;
      const radius = Math.min(w, h) * 0.35;
      n._x = cx + radius * Math.cos(angle);
      n._y = cy + radius * Math.sin(angle);
      n._vx = 0; n._vy = 0;
      nodeMap[n.id] = n;
    });

    // Simple force simulation (30 iterations)
    for (let iter = 0; iter < 40; iter++) {
      // Repulsion
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          let dx = nodes[j]._x - nodes[i]._x;
          let dy = nodes[j]._y - nodes[i]._y;
          let dist = Math.sqrt(dx * dx + dy * dy) || 1;
          let force = 800 / (dist * dist);
          nodes[i]._vx -= dx / dist * force;
          nodes[i]._vy -= dy / dist * force;
          nodes[j]._vx += dx / dist * force;
          nodes[j]._vy += dy / dist * force;
        }
      }
      // Attraction (edges)
      edges.forEach(e => {
        const s = nodeMap[e.source], t = nodeMap[e.target];
        if (!s || !t) return;
        let dx = t._x - s._x, dy = t._y - s._y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        let force = (dist - 80) * 0.02 * (e.weight || 0.5);
        s._vx += dx / dist * force;
        s._vy += dy / dist * force;
        t._vx -= dx / dist * force;
        t._vy -= dy / dist * force;
      });
      // Center gravity
      nodes.forEach(n => {
        n._vx += (cx - n._x) * 0.005;
        n._vy += (cy - n._y) * 0.005;
        n._x += n._vx * 0.3;
        n._y += n._vy * 0.3;
        n._vx *= 0.8; n._vy *= 0.8;
        // Clamp
        n._x = Math.max(30, Math.min(w - 30, n._x));
        n._y = Math.max(30, Math.min(h - 30, n._y));
      });
    }

    // Render
    let html = '';
    // Edges
    edges.forEach(e => {
      const s = nodeMap[e.source], t = nodeMap[e.target];
      if (!s || !t) return;
      const opacity = Math.min(1, (e.weight || 0.5) * 1.5);
      html += `<line class="vault-edge" x1="${s._x}" y1="${s._y}" x2="${t._x}" y2="${t._y}" style="opacity:${opacity}"/>`;
    });
    // Nodes
    const tooltip = $('#vault-tooltip');
    nodes.forEach(n => {
      const r = 6 + Math.min(n.chunks || 1, 20) * 0.8;
      html += `<g class="vault-node" data-id="${escHtml(n.id)}">
        <circle cx="${n._x}" cy="${n._y}" r="${r}" fill="${n.color}" opacity="0.85"/>
        <circle cx="${n._x}" cy="${n._y}" r="${r + 3}" fill="${n.color}" opacity="0.15"/>
        <text class="vault-node-label" x="${n._x}" y="${n._y + r + 12}">${escHtml(n.label.length > 18 ? n.label.substring(0, 16) + '…' : n.label)}</text>
      </g>`;
    });
    svg.innerHTML = html;

    // Tooltip events
    svg.querySelectorAll('.vault-node').forEach(g => {
      g.addEventListener('mouseenter', e => {
        const id = g.dataset.id;
        const node = nodes.find(n => n.id === id);
        if (!node || !tooltip) return;
        tooltip.innerHTML = `<strong>${escHtml(node.id)}</strong><br>${node.file_type} · ${node.chunks} chunks`;
        tooltip.style.display = 'block';
      });
      g.addEventListener('mousemove', e => {
        if (!tooltip) return;
        const rect = svg.closest('.vault-graph-container').getBoundingClientRect();
        tooltip.style.left = (e.clientX - rect.left + 12) + 'px';
        tooltip.style.top = (e.clientY - rect.top - 10) + 'px';
      });
      g.addEventListener('mouseleave', () => {
        if (tooltip) tooltip.style.display = 'none';
      });
    });
  }
}

window.VaultStudio = VaultStudio;
