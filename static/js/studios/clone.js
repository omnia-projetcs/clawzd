/**
 * Clawzd — CloneStudio
 * Manages the "My Clone" AI agent: profile, knowledge base,
 * connectors, auto-reply settings, test sandbox, and activity feed.
 */
/* global $, $$, toast, escHtml, icon, ICONS */

class CloneStudio {
  constructor() {
    this.layout = $('#clone-layout');
    this._editingFile = null;
    this._connectors = {};
    this._init();
  }

  async _init() {
    // Test sandbox
    $('#clone-test-send')?.addEventListener('click', () => this.sendTest());
    $('#clone-test-input')?.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.sendTest(); }
    });
    // Confidence slider
    const slider = $('#clone-confidence-slider');
    const valEl = $('#clone-confidence-val');
    if (slider && valEl) {
      slider.addEventListener('input', () => {
        valEl.textContent = (slider.value / 100).toFixed(2);
      });
    }
    // Save all settings
    $('#clone-btn-save-all')?.addEventListener('click', () => this.saveSettings());
    // Feed refresh
    $('#clone-feed-refresh')?.addEventListener('click', () => this.loadFeed());
    // Knowledge tree
    $('#clone-kb-add')?.addEventListener('click', () => this.createFile());
    $('#clone-kb-upload')?.addEventListener('click', () => this._uploadFiles());
    // Profile edit buttons
    $('#clone-btn-edit-profile')?.addEventListener('click', () => this.editFile('profile.md'));
    $('#clone-btn-edit-rules')?.addEventListener('click', () => this.editFile('rules.md'));
    // Editor modal
    $('#clone-editor-close')?.addEventListener('click', () => this._closeEditor());
    $('#clone-editor-cancel')?.addEventListener('click', () => this._closeEditor());
    $('#clone-editor-save')?.addEventListener('click', () => this._saveEditor());
    // Onboarding
    $('#clone-ob-skip')?.addEventListener('click', () => this._closeOnboarding());
    $('#clone-ob-next')?.addEventListener('click', () => this._advanceOnboarding());
  }

  toggle(show) {
    if (this.layout) this.layout.style.display = show ? 'grid' : 'none';
    if (show) this._load();
  }

  async _load() {
    await Promise.all([
      this.loadProfile(),
      this.loadKnowledgeTree(),
      this.loadConnectors(),
      this.loadSettings(),
      this.loadFeed(),
      this.loadStats(),
    ]);
    this._checkOnboarding();
  }

  // ── Profile ──
  async loadProfile() {
    try {
      const r = await fetch('/clone/profile');
      const d = await r.json();
      // Parse name from profile.md
      const nameMatch = (d.profile || '').match(/^##\s*Name\s*\n+(.+)/m);
      const roleMatch = (d.profile || '').match(/^##\s*Role\s*\n+(.+)/m);
      const name = nameMatch ? nameMatch[1].trim() : 'My Clone';
      const role = roleMatch ? roleMatch[1].trim() : 'Not configured';
      const nameEl = $('#clone-name');
      const roleEl = $('#clone-role');
      const avatarEl = $('#clone-avatar');
      if (nameEl) nameEl.textContent = name;
      if (roleEl) roleEl.textContent = role;
      if (avatarEl) avatarEl.textContent = name.charAt(0).toUpperCase() || '?';
    } catch (e) { console.error('Clone: loadProfile failed', e); }
  }

  // ── Knowledge Tree ──
  async loadKnowledgeTree() {
    try {
      const r = await fetch('/clone/knowledge');
      const d = await r.json();
      const container = $('#clone-knowledge-tree');
      if (!container) return;
      container.innerHTML = '';
      this._renderTree(d.tree || [], container, 0);
    } catch (e) { console.error('Clone: loadKnowledgeTree failed', e); }
  }

  _renderTree(items, parent, depth) {
    items.forEach(item => {
      const div = document.createElement('div');
      div.className = `clone-tree-item ${item.type === 'dir' ? 'clone-tree-dir' : 'clone-tree-file'}`;
      div.style.paddingLeft = (12 + depth * 16) + 'px';
      const iconName = item.type === 'dir' ? 'folder' : 'file';
      div.innerHTML = `<svg class="ic" width="12" height="12"><use href="#icon-${iconName}"></use></svg>
        <span>${escHtml(item.name)}</span>
        ${item.type === 'file' ? `<div class="clone-tree-actions">
          <button class="icon-btn" title="Edit" data-path="${escHtml(item.path)}">
            <svg class="ic" width="10" height="10"><use href="#icon-pen"></use></svg>
          </button>
          <button class="icon-btn" title="Delete" data-del="${escHtml(item.path)}" style="color:#ef4444">
            <svg class="ic" width="10" height="10"><use href="#icon-x"></use></svg>
          </button>
        </div>` : ''}`;
      if (item.type === 'file') {
        div.querySelector('[data-path]')?.addEventListener('click', e => {
          e.stopPropagation();
          this.editFile(item.path);
        });
        div.querySelector('[data-del]')?.addEventListener('click', e => {
          e.stopPropagation();
          this.deleteFile(item.path);
        });
      }
      parent.appendChild(div);
      if (item.type === 'dir' && item.children) {
        this._renderTree(item.children, parent, depth + 1);
      }
    });
  }

  async editFile(path) {
    try {
      const r = await fetch(`/clone/knowledge/${path}`);
      const d = await r.json();
      this._editingFile = path;
      const title = $('#clone-editor-title');
      const textarea = $('#clone-editor-textarea');
      if (title) title.textContent = `Edit: ${path}`;
      if (textarea) textarea.value = d.content || '';
      $('#clone-editor-overlay')?.classList.add('open');
    } catch (e) { toast('Failed to load file'); }
  }

  async _saveEditor() {
    if (!this._editingFile) return;
    const content = $('#clone-editor-textarea')?.value || '';
    try {
      await fetch(`/clone/knowledge/${this._editingFile}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content })
      });
      toast(ICONS.check(14) + ' File saved');
      this._closeEditor();
      this.loadKnowledgeTree();
      this.loadProfile();
    } catch (e) { toast('Failed to save file'); }
  }

  _closeEditor() {
    $('#clone-editor-overlay')?.classList.remove('open');
    this._editingFile = null;
  }

  async createFile() {
    const name = prompt('File name (e.g. expertise/cybersecurity.md):');
    if (!name?.trim()) return;
    const path = name.trim().endsWith('.md') ? name.trim() : name.trim() + '.md';
    try {
      await fetch(`/clone/knowledge/${path}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: `# ${path.split('/').pop().replace('.md', '')}\n\n` })
      });
      toast(ICONS.check(14) + ' File created');
      this.loadKnowledgeTree();
      this.editFile(path);
    } catch (e) { toast('Failed to create file'); }
  }

  async deleteFile(path) {
    if (!confirm(`Delete ${path}?`)) return;
    try {
      const r = await fetch(`/clone/knowledge/${path}`, { method: 'DELETE' });
      const d = await r.json();
      if (r.ok) {
        toast(ICONS.check(14) + ' File deleted');
        this.loadKnowledgeTree();
      } else {
        toast(d.detail || 'Cannot delete this file');
      }
    } catch (e) { toast('Failed to delete file'); }
  }

  _uploadFiles() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.md';
    input.multiple = true;
    input.onchange = async () => {
      for (const file of input.files) {
        const text = await file.text();
        await fetch(`/clone/knowledge/${file.name}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: text })
        });
      }
      toast(ICONS.check(14) + ` ${input.files.length} file(s) uploaded`);
      this.loadKnowledgeTree();
    };
    input.click();
  }

  // ── Connectors ──
  async loadConnectors() {
    try {
      const r = await fetch('/clone/connectors');
      const d = await r.json();
      this._connectors = d.connectors || {};
      this._renderConnectors();
      this._renderConnectorStatus();
    } catch (e) { console.error('Clone: loadConnectors failed', e); }
  }

  _renderConnectors() {
    const list = $('#clone-connectors-list');
    if (!list) return;
    list.innerHTML = '';
    const channels = [
      { key: 'email', label: 'Email', icon: '📧' },
      { key: 'whatsapp', label: 'WhatsApp', icon: '💬' },
      { key: 'signal', label: 'Signal', icon: '🔒' },
      { key: 'telegram', label: 'Telegram', icon: '✈️' },
      { key: 'webhook', label: 'Webhook', icon: '🔗' },
    ];
    channels.forEach(ch => {
      const cfg = this._connectors[ch.key] || {};
      const div = document.createElement('div');
      div.className = 'clone-connector';
      div.innerHTML = `
        <div class="clone-connector-icon ${ch.key}">${ch.icon}</div>
        <div class="clone-connector-info">
          <div class="clone-connector-name">${ch.label}</div>
          <div class="clone-connector-status">${cfg.enabled ? 'Connected' : 'Disabled'}</div>
        </div>
        <label class="clone-toggle">
          <input type="checkbox" data-channel="${ch.key}" ${cfg.enabled ? 'checked' : ''}>
          <span class="clone-toggle-track"></span>
        </label>`;
      div.querySelector('input')?.addEventListener('change', e => {
        if (!this._connectors[ch.key]) this._connectors[ch.key] = {};
        this._connectors[ch.key].enabled = e.target.checked;
        this._renderConnectorStatus();
      });
      list.appendChild(div);
    });
  }

  _renderConnectorStatus() {
    const dots = $('#clone-connectors-status');
    if (!dots) return;
    dots.innerHTML = '';
    Object.entries(this._connectors).forEach(([key, cfg]) => {
      const dot = document.createElement('span');
      dot.className = `clone-status-dot${cfg.enabled ? ' active' : ''}`;
      dot.textContent = key;
      dots.appendChild(dot);
    });
  }

  // ── Settings ──
  async loadSettings() {
    try {
      const r = await fetch('/clone/settings');
      const d = await r.json();
      const s = d.settings || {};
      const toggle = $('#clone-auto-toggle');
      const slider = $('#clone-confidence-slider');
      const valEl = $('#clone-confidence-val');
      const mode = $('#clone-review-mode');
      const limit = $('#clone-daily-limit');
      if (toggle) toggle.checked = s.auto_mode || false;
      if (slider) slider.value = Math.round((s.confidence_threshold || 0.85) * 100);
      if (valEl) valEl.textContent = (s.confidence_threshold || 0.85).toFixed(2);
      if (mode) mode.value = s.review_mode || 'human-in-loop';
      if (limit) limit.value = s.daily_limit || 50;
    } catch (e) { console.error('Clone: loadSettings failed', e); }
  }

  async saveSettings() {
    const settings = {
      auto_mode: $('#clone-auto-toggle')?.checked || false,
      confidence_threshold: ($('#clone-confidence-slider')?.value || 85) / 100,
      review_mode: $('#clone-review-mode')?.value || 'human-in-loop',
      daily_limit: parseInt($('#clone-daily-limit')?.value || '50'),
    };
    try {
      await fetch('/clone/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
      });
      // Save connectors too
      await fetch('/clone/connectors', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ connectors: this._connectors })
      });
      toast(ICONS.check(14) + ' All settings saved');
    } catch (e) { toast('Failed to save settings'); }
  }

  // ── Test Sandbox ──
  async sendTest() {
    const input = $('#clone-test-input');
    const message = input?.value.trim();
    if (!message) { toast('Enter a test message'); return; }
    const channel = $('#clone-test-channel')?.value || 'test';
    const btn = $('#clone-test-send');
    const result = $('#clone-test-result');
    const meta = $('#clone-test-meta');
    if (btn) { btn.disabled = true; btn.textContent = 'Generating...'; }
    if (result) { result.style.display = 'block'; result.textContent = '⏳ Generating clone reply...'; }
    if (meta) meta.style.display = 'none';
    try {
      const r = await fetch('/clone/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, channel })
      });
      const d = await r.json();
      if (result) result.textContent = d.reply || 'No reply generated';
      if (meta) {
        meta.style.display = 'flex';
        $('#clone-test-intent').textContent = `Intent: ${d.intent || '—'}`;
        const conf = d.confidence || 0;
        const confEl = $('#clone-test-conf');
        if (confEl) {
          confEl.textContent = `Confidence: ${conf.toFixed(2)}`;
          confEl.className = `clone-feed-badge ${conf >= 0.85 ? 'high' : conf >= 0.6 ? 'medium' : 'low'}`;
        }
        const flag = $('#clone-test-flag');
        if (flag) flag.style.display = d.flagged ? '' : 'none';
      }
      this.loadFeed();
      this.loadStats();
    } catch (e) {
      if (result) result.textContent = '❌ Failed: ' + e.message;
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = `<svg class="ic" width="14" height="14"><use href="#icon-play"></use></svg> Send Test`; }
    }
  }

  // ── Activity Feed ──
  async loadFeed() {
    try {
      const r = await fetch('/clone/logs?limit=30');
      const d = await r.json();
      const feed = $('#clone-activity-feed');
      if (!feed) return;
      const logs = d.logs || [];
      if (!logs.length) {
        feed.innerHTML = '<div style="color:var(--text-muted);font-size:12px;text-align:center;padding:20px">No activity yet.</div>';
        return;
      }
      feed.innerHTML = '';
      logs.forEach(entry => {
        const div = document.createElement('div');
        div.className = 'clone-feed-item';
        const conf = entry.confidence || 0;
        const badge = conf >= 0.85 ? 'high' : conf >= 0.6 ? 'medium' : 'low';
        const time = entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString() : '';
        div.innerHTML = `
          <span class="clone-feed-channel">${escHtml(entry.channel || '—')}</span>
          <span class="clone-feed-msg" title="${escHtml(entry.message || '')}">${escHtml((entry.message || '').substring(0, 60))}</span>
          <span class="clone-feed-badge ${badge}">${conf.toFixed(2)}</span>
          <span class="clone-feed-time">${time}</span>`;
        feed.appendChild(div);
      });
    } catch (e) { console.error('Clone: loadFeed failed', e); }
  }

  // ── Stats ──
  async loadStats() {
    try {
      const r = await fetch('/clone/stats');
      const d = await r.json();
      const rep = $('#clone-stat-replies');
      const conf = $('#clone-stat-confidence');
      const inter = $('#clone-stat-interactions');
      if (rep) rep.textContent = d.replies_today || 0;
      if (conf) conf.textContent = d.avg_confidence ? d.avg_confidence.toFixed(2) : '—';
      if (inter) inter.textContent = d.interactions_today || 0;
    } catch (e) { console.error('Clone: loadStats failed', e); }
  }

  // ── Onboarding ──
  async _checkOnboarding() {
    try {
      const r = await fetch('/clone/onboarding');
      const d = await r.json();
      const ob = d.onboarding || {};
      if (!ob.completed) this._showOnboarding(ob.current_step || 1, ob.steps_done || []);
    } catch (e) { /* ignore */ }
  }

  _showOnboarding(step, done) {
    const steps = [
      { title: 'Write Your Profile', desc: 'Tell your clone who you are — name, role, bio, and personality traits.' },
      { title: 'Add Knowledge Files', desc: 'Upload or create .md files with your expertise, FAQs, and project details.' },
      { title: 'Connect a Channel', desc: 'Enable at least one connector (Email, Telegram, WhatsApp, etc.).' },
      { title: 'Run Test Messages', desc: 'Send 5 test messages to calibrate your clone\'s voice and accuracy.' },
      { title: 'Set Auto Mode', desc: 'Configure confidence threshold and activate autonomous replies.' },
    ];
    this._obStep = step;
    this._obDone = done;
    const overlay = $('#clone-onboarding');
    if (!overlay || step > 5) return;
    const s = steps[step - 1];
    $('#clone-ob-step').textContent = `Step ${step} of 5`;
    $('#clone-ob-title').textContent = s.title;
    $('#clone-ob-desc').textContent = s.desc;
    const dots = $('#clone-ob-dots');
    if (dots) {
      dots.innerHTML = '';
      for (let i = 1; i <= 5; i++) {
        const dot = document.createElement('div');
        dot.className = `clone-onboarding-dot${done.includes(i) ? ' done' : i === step ? ' current' : ''}`;
        dots.appendChild(dot);
      }
    }
    overlay.classList.add('open');
  }

  async _advanceOnboarding() {
    const step = this._obStep || 1;
    try {
      await fetch('/clone/onboarding', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ step_done: step, current_step: step + 1 })
      });
    } catch (e) { /* ignore */ }
    this._closeOnboarding();
    // Open relevant UI
    if (step === 1) this.editFile('profile.md');
    else if (step === 2) this.createFile();
    else if (step === 5) $('#clone-auto-toggle')?.focus();
  }

  _closeOnboarding() {
    $('#clone-onboarding')?.classList.remove('open');
  }
}

window.CloneStudio = CloneStudio;
