/**
 * Clawzd — ModelManager
 * Extracted from app.js for modular architecture.
 * Uses window globals for shared utilities (el, $, $$, toast, escHtml, icon, ICONS).
 */
/* global $, $$, el, toast, escHtml, icon, ICONS, OC */

// ---- Model Manager ----
class ModelManager {
  constructor() {
    this.overlay = $('#models-overlay');
    this.grid = $('#models-grid');
    this.hwInfo = $('#models-hw-info');
    this.dlBar = $('#models-download-bar');
    this.catalog = [];
    this.hardware = {};
    this.activeVendor = 'all';
    this.pollInterval = null;

    // Close modal
    $('#models-close').addEventListener('click', () => this.close());
    this.overlay.addEventListener('click', e => { if (e.target === this.overlay) this.close(); });

    // Cancel download
    $('#dl-cancel').addEventListener('click', () => this.cancelDownload());
  }

  _bindTabs() {
    $$('#models-tabs .models-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        $$('#models-tabs .models-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        this.activeVendor = tab.dataset.vendor;
        this.render();
      });
    });
  }

  renderTabs() {
    // Build dynamic vendor tabs from catalog
    const tabsEl = $('#models-tabs');
    const vendors = [...new Set(this.catalog.map(m => m.vendor))].sort();
    tabsEl.innerHTML = '<button class="models-tab active" data-vendor="all">All</button>';
    vendors.forEach(v => {
      tabsEl.innerHTML += `<button class="models-tab" data-vendor="${escHtml(v)}">${escHtml(v)}</button>`;
    });
    this.activeVendor = 'all';
    this._bindTabs();
  }

  async open() {
    this.overlay.classList.add('open');
    await Promise.all([this.loadCatalog(), this.loadHardware()]);
    this.renderTabs();
    this.render();
    this.startPollDownload();
  }

  close() {
    this.overlay.classList.remove('open');
    this.stopPollDownload();
  }

  async loadCatalog() {
    try {
      const r = await fetch('/models/catalog');
      const d = await r.json();
      this.catalog = d.catalog || [];
    } catch (e) { console.error('Failed to load model catalog:', e); }
  }

  async loadHardware() {
    try {
      const r = await fetch('/models/hardware');
      this.hardware = await r.json();
      const gpu = this.hardware.gpu_name || 'No GPU';
      const vram = this.hardware.vram_total_mib ? `${(this.hardware.vram_total_mib / 1024).toFixed(0)} Go VRAM` : 'VRAM ?';
      const vramFree = this.hardware.vram_free_mib ? `(${(this.hardware.vram_free_mib / 1024).toFixed(1)} Go libre)` : '';
      const ram = this.hardware.ram_total_mib ? `${(this.hardware.ram_total_mib / 1024).toFixed(0)} Go RAM` : '';
      this.hwInfo.textContent = `${gpu} — ${vram} ${vramFree} • ${ram}`;
    } catch (e) {
      this.hwInfo.textContent = 'Hardware info unavailable';
    }
  }

  render() {
    const filtered = this.activeVendor === 'all'
      ? this.catalog
      : this.catalog.filter(m => m.vendor === this.activeVendor);

    if (!filtered.length) {
      this.grid.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-muted);font-size:13px;">No models in this category</div>';
      return;
    }

    const vramTotal = this.hardware.vram_total_mib || 0;
    const CAP_ICONS = { txt: '', image: '️', video: '', mcp: '', code: ICONS.monitor(14) };

    this.grid.innerHTML = filtered.map(m => {
      const canFit = vramTotal > 0 ? (m.vram_min_gb * 1024) <= vramTotal : true;
      const fitClass = canFit ? '' : ' style="opacity:.7"';
      const fitBadge = !canFit ? '<span class="model-meta-tag" style="color:var(--red)"> VRAM insuffisant</span>' : '';
      const downloadedClass = m.downloaded ? ' downloaded' : '';
      const recClass = m.recommended ? ' recommended' : '';
      const activeClass = m.active ? ' active-model' : '';

      // Capability tags
      const caps = (m.capabilities || []).map(c =>
        `<span class="model-cap-tag cap-${escHtml(c)}" title="${escHtml(c)}">${CAP_ICONS[c] || '•'} ${escHtml(c)}</span>`
      ).join('');

      let actions = '';
      const modelRef = m.ollama_id || m.id;
      if (m.downloaded) {
        if (m.active) {
          actions = `
            <button class="btn btn-active-indicator" disabled> Active</button>
            <button class="btn btn-danger" onclick="OC.deleteModel('${escHtml(modelRef)}','${escHtml(m.name)}')"> Delete</button>`;
        } else {
          actions = `
            <button class="btn btn-success" onclick="OC.activateModel('${escHtml(modelRef)}')"> Activate</button>
            <button class="btn btn-danger" onclick="OC.deleteModel('${escHtml(modelRef)}','${escHtml(m.name)}')"> Delete</button>`;
        }
      } else {
        actions = `
          <button class="btn btn-download" onclick="OC.downloadModel('${escHtml(m.id)}')">⬇ Download</button>`;
      }

      const statusHtml = m.active
        ? `<div class="model-card-status active-status"> Active${m.local_size_gb ? ` (${m.local_size_gb} GB)` : ''}</div>`
        : m.downloaded
          ? `<div class="model-card-status downloaded"> Downloaded${m.local_size_gb ? ` (${m.local_size_gb} GB)` : ''}</div>`
          : `<div class="model-card-status not-downloaded">○ Not downloaded</div>`;

      return `
        <div class="model-card${downloadedClass}${recClass}${activeClass}"${fitClass}>
          <div class="model-card-header">
            <span class="model-card-vendor vendor-${m.vendor}">${escHtml(m.vendor)}</span>
            <span class="model-card-name">${escHtml(m.name)}</span>
          </div>
          <div class="model-card-desc">${escHtml(m.description)}</div>
          <div class="model-card-caps">${caps}</div>
          <div class="model-card-meta">
            <span class="model-meta-tag params">${m.params}</span>
            <span class="model-meta-tag size">${m.size_gb} Go</span>
            <span class="model-meta-tag vram">≥ ${m.vram_min_gb} Go VRAM</span>
            <span class="model-meta-tag">${m.quant}</span>
            ${m.release_date ? `<span class="model-meta-tag date"> ${m.release_date}</span>` : ''}
            ${fitBadge}
          </div>
          ${statusHtml}
          <div class="model-card-actions">${actions}</div>
        </div>`;
    }).join('');
  }

  async downloadModel(modelId) {
    try {
      const r = await fetch('/models/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_id: modelId }),
      });
      const d = await r.json();
      if (!r.ok) { toast(' ' + (d.detail || 'Download failed')); return; }
      toast('⬇ Download started: ' + (d.ollama_id || d.model_id || d.filename));
      this.dlBar.style.display = 'flex';
      this.startPollDownload();
    } catch (e) { toast('${ICONS.x(14)} Error: ' + e.message); }
  }

  async cancelDownload() {
    try {
      await fetch('/models/download/cancel', { method: 'POST' });
      toast('Download cancelled');
      this.dlBar.style.display = 'none';
    } catch (e) { /* ignore */ }
  }

  startPollDownload() {
    this.stopPollDownload();
    this.pollInterval = setInterval(() => this.pollDownload(), 1000);
  }

  stopPollDownload() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
  }

  async pollDownload() {
    try {
      const r = await fetch('/models/download/status');
      const d = await r.json();

      // Check for errors first — even if download already stopped
      if (d.error) {
        toast(' Download error: ' + d.error);
        this.dlBar.style.display = 'none';
        this.stopPollDownload();
        return;
      }

      if (d.active || d.completed) {
        this.dlBar.style.display = 'flex';
        $('#dl-filename').textContent = d.ollama_id || d.model_id || d.status_text || '—';
        $('#dl-fill').style.width = d.progress + '%';
        $('#dl-stats').textContent = `${d.downloaded_mb || 0} / ${d.total_mb || '?'} MB — ${d.speed_mbps || 0} MB/s — ${Math.round(d.progress || 0)}%`;

        if (d.completed) {
          toast(' Model downloaded: ' + (d.ollama_id || d.model_id));
          this.dlBar.style.display = 'none';
          this.stopPollDownload();
          await this.loadCatalog();
          this.render();
        }
      } else {
        this.dlBar.style.display = 'none';
        this.stopPollDownload();
      }
    } catch (e) { /* ignore */ }
  }

  async deleteModel(filename, name) {
    if (!confirm(`Delete model "${name}" (${filename})?`)) return;
    try {
      const r = await fetch('/models/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename }),
      });
      if (r.ok) {
        const d = await r.json();
        if (d.was_active && d.fallback_model) {
          toast(`${ICONS.circle(14)} Deleted active model. Switched to: ${d.fallback_model}`);
        } else if (d.was_active) {
          toast(ICONS.circle(14) + ' Active model deleted — no fallback available');
        } else {
          toast(' Model deleted: ' + filename);
        }
        await this.loadCatalog();
        this.render();
        loadProviders();
      } else {
        const d = await r.json();
        toast(' ' + (d.detail || 'Delete failed'));
      }
    } catch (e) { toast('${ICONS.x(14)} Error: ' + e.message); }
  }

  async activateModel(filename) {
    try {
      const r = await fetch('/models/activate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename }),
      });
      const d = await r.json();
      if (r.ok) {
        toast(' ' + d.message);
        await this.loadCatalog();
        this.render();
        // Refresh provider/model picker to show the new active model
        loadProviders();
      } else {
        toast(' ' + (d.detail || 'Activation failed'));
      }
    } catch (e) { toast('${ICONS.x(14)} Error: ' + e.message); }
  }
}

// Backward compatibility
window.ModelManager = ModelManager;
