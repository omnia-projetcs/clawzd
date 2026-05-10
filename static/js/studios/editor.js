/**
 * Clawzd — EditorMode (Claude Code-style IDE)
 * Extracted from app.js for modular architecture.
 * Uses window globals for shared utilities (el, $, $$, toast, escHtml, icon, ICONS).
 */
/* global $, $$, el, toast, escHtml, icon, ICONS, OC, renderMd, highlightAll, Zip */

// ---- Editor Mode (Claude Code-style IDE) ----
class EditorMode {
  constructor() {
    this.active = false;
    this.files = [];
    this.openTabs = []; // [{path, content, modified}]
    this.activeTab = null;
    this.cmView = null;
    this.collapsed = new Set();
    this.editorSessionId = null;
    this.editorES = null;
    this.editorStreaming = false;
    this.editorText = '';
    this.editorBubble = null;
    // --- OpenCode features ---
    this.agentMode = 'build'; // 'build' | 'plan'
    this.changeHistory = []; // [{path, oldContent, newContent, timestamp}]
    this.changeHistoryIdx = -1;
    this.todoItems = JSON.parse(localStorage.getItem('hoc-todo') || '[]');
    this.attachedFiles = []; // [{path, content}]
    this.fileRefIndex = -1;
    this.editorTokenCount = 0; // approximate context token count
    this.TOKEN_LIMIT = 30000;
  }

  toggle(on) {
    this.active = on;
    const editorLayout = $('#editor-layout');
    if (on) {
      editorLayout.classList.add('active');
      this.loadTree();
    } else {
      editorLayout.classList.remove('active');
    }
  }

  // ---- File Tree ----
  async loadTree() {
    try {
      const r = await fetch('/workspace/tree');
      const d = await r.json();
      this.files = d.files || [];
      this.renderTree();
    } catch (e) { toast(ICONS.x(14) + ' Failed to load workspace'); }
  }

  _fileIcon(name) {
    const ext = name.split('.').pop().toLowerCase();
    // Language-specific SVG icons
    const pyIcon = '<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#3572A5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>';
    const jsIcon = '<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#F7DF1E" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>';
    const htmlIcon = '<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#E34F26" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>';
    const cssIcon = '<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#1572B6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="13.5" cy="6.5" r="1.5"/><circle cx="17.5" cy="10.5" r="1.5"/><circle cx="8.5" cy="7.5" r="1.5"/><circle cx="6.5" cy="12.5" r="1.5"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.93 0 1.5-.67 1.5-1.5 0-.38-.14-.74-.39-1.02-.24-.27-.37-.63-.37-1.01 0-.83.67-1.5 1.5-1.5H16c3.31 0 6-2.69 6-6 0-5.5-4.5-9.97-10-9.97z"/></svg>';
    const mdIcon = '<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>';
    const configIcon = '<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4"/></svg>';
    const defaultIcon = '<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
    const jsonIcon = '<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#F5A623" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
    const map = { py: pyIcon, js: jsIcon, jsx: jsIcon, ts: jsIcon, tsx: jsIcon, html: htmlIcon, htm: htmlIcon, css: cssIcon, scss: cssIcon, json: jsonIcon, md: mdIcon, sh: configIcon, yml: configIcon, yaml: configIcon, toml: configIcon, sql: configIcon, txt: mdIcon, csv: mdIcon, xml: htmlIcon, svg: cssIcon, java: jsIcon, go: jsIcon, rs: jsIcon, rb: jsIcon, php: jsIcon };
    return map[ext] || defaultIcon;
  }

  _buildDirTree() {
    const tree = {};
    this.files.sort((a, b) => a.path.localeCompare(b.path)).forEach(f => {
      const parts = f.path.split('/');
      let node = tree;
      for (let i = 0; i < parts.length - 1; i++) {
        if (!node[parts[i]]) node[parts[i]] = {};
        node = node[parts[i]];
      }
      node['__f__' + parts[parts.length - 1]] = f;
    });
    return tree;
  }

  _renderTreeNode(node, parentPath, depth, container) {
    const entries = Object.entries(node).sort(([a, va], [b, vb]) => {
      const aD = typeof va === 'object' && !a.startsWith('__f__');
      const bD = typeof vb === 'object' && !b.startsWith('__f__');
      if (aD !== bD) return aD ? -1 : 1;
      return a.localeCompare(b);
    });
    entries.forEach(([key, val]) => {
      if (key.startsWith('__f__')) {
        const f = val;
        const name = key.slice(5);
        const indent = depth * 14;
        const isActive = this.activeTab === f.path;
        const div = el('div', {
          class: 'eft-file' + (isActive ? ' active' : ''),
          style: `padding-left:${20 + indent}px`,
          onclick: () => this.openFile(f.path)
        }, [
          el('span', { class: 'eft-file-icon', html: this._fileIcon(name) }),
          el('span', { class: 'eft-file-name', text: name }),
          el('span', { class: 'eft-file-size', text: f.size > 1024 ? (f.size / 1024).toFixed(0) + 'K' : f.size + 'B' }),
          el('div', { class: 'eft-file-actions' }, [
            el('button', { class: 'eft-file-btn rename', html: ICONS.pen(12), title: 'Rename', onclick: e => { e.stopPropagation(); this.renameFile(f.path); } }),
            el('button', { class: 'eft-file-btn delete', html: ICONS.trash(12), title: 'Delete', onclick: e => { e.stopPropagation(); this.deleteFile(f.path); } })
          ])
        ]);
        container.appendChild(div);
      } else {
        const dirPath = parentPath ? parentPath + '/' + key : key;
        const isOpen = !this.collapsed.has(dirPath);
        const indent = depth * 14;
        const div = el('div', {
          class: 'eft-dir' + (isOpen ? ' open' : ''),
          style: `padding-left:${8 + indent}px`,
        }, [
          el('span', { class: 'eft-dir-arrow', text: '►', onclick: e => { e.stopPropagation(); if (this.collapsed.has(dirPath)) this.collapsed.delete(dirPath); else this.collapsed.add(dirPath); this.renderTree(); } }),
          el('span', { text: isOpen ? '' : '', style: 'font-size:13px', onclick: () => { if (this.collapsed.has(dirPath)) this.collapsed.delete(dirPath); else this.collapsed.add(dirPath); this.renderTree(); } }),
          el('span', { text: key, style: 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer', onclick: () => { if (this.collapsed.has(dirPath)) this.collapsed.delete(dirPath); else this.collapsed.add(dirPath); this.renderTree(); } }),
          el('div', { class: 'eft-file-actions' }, [
            el('button', { class: 'eft-file-btn rename', html: ICONS.pen(12), title: 'Rename folder', onclick: e => { e.stopPropagation(); this.renameFile(dirPath); } }),
            el('button', { class: 'eft-file-btn delete', html: ICONS.trash(12), title: 'Delete folder', onclick: e => { e.stopPropagation(); this.deleteDir(dirPath); } })
          ])
        ]);
        container.appendChild(div);
        if (isOpen) this._renderTreeNode(val, dirPath, depth + 1, container);
      }
    });
  }

  renderTree() {
    const list = $('#eft-list');
    list.innerHTML = '';
    if (!this.files.length) { list.innerHTML = '<div class="eft-empty">Workspace is empty.<br>Create a file or ask the AI to generate code.</div>'; return; }
    const tree = this._buildDirTree();
    this._renderTreeNode(tree, '', 0, list);
  }

  // ---- File Operations ----
  _isBinaryExt(path) {
    const ext = path.split('.').pop().toLowerCase();
    const binaryExts = new Set(['png', 'jpg', 'jpeg', 'gif', 'bmp', 'ico', 'svg', 'webp', 'mp4', 'webm', 'mp3', 'wav', 'ogg', 'pdf', 'zip', 'tar', 'gz', '7z', 'rar', 'woff', 'woff2', 'ttf', 'otf', 'eot', 'exe', 'dll', 'so', 'dylib', 'pyc', 'pyo', 'class', 'o', 'obj']);
    return binaryExts.has(ext);
  }

  _isImageExt(path) {
    const ext = path.split('.').pop().toLowerCase();
    return ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'ico', 'svg', 'webp'].includes(ext);
  }

  async openFile(path) {
    // Handle binary files — show preview instead of editor
    if (this._isBinaryExt(path)) {
      this.activeTab = path;
      this.renderTabs();
      this.renderTree();
      const area = $('#editor-code-area');
      const welcome = $('#editor-welcome');
      if (welcome) welcome.style.display = 'none';
      if (this._isImageExt(path)) {
        area.innerHTML = `
          <div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:24px;gap:16px;overflow:auto;">
            <div style="font-size:12px;color:var(--text-muted);font-weight:600;">${escHtml(path)}</div>
            <img src="/workspace/file-raw?path=${encodeURIComponent(path)}"
                 alt="${escHtml(path)}"
                 style="max-width:90%;max-height:70vh;border-radius:8px;border:1px solid var(--border);box-shadow:0 4px 20px rgba(0,0,0,.3);object-fit:contain;">
            <div style="font-size:11px;color:var(--text-muted);">Image preview</div>
          </div>`;
      } else {
        const ext = path.split('.').pop().toUpperCase();
        area.innerHTML = `
          <div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;color:var(--text-muted);padding:40px;">
            <div style="font-size:48px;opacity:.4;"></div>
            <div style="font-size:14px;font-weight:600;">${escHtml(path.split('/').pop())}</div>
            <div style="font-size:12px;">Binary file (.${ext.toLowerCase()}) — cannot be edited</div>
          </div>`;
      }
      return;
    }

    let tab = this.openTabs.find(t => t.path === path);
    if (!tab) {
      try {
        const r = await fetch('/workspace/file?path=' + encodeURIComponent(path));
        if (!r.ok) { toast(ICONS.x(14) + ' Cannot read file'); return; }
        const d = await r.json();
        tab = { path, content: d.content, original: d.content, modified: false };
        this.openTabs.push(tab);
      } catch (e) { toast(ICONS.x(14) + ' Read error'); return; }
    }
    this.activeTab = path;
    this.renderTabs();
    this.renderTree();
    this.loadIntoEditor(tab);
  }

  async saveFile(path) {
    const tab = this.openTabs.find(t => t.path === path);
    if (!tab) return;
    try {
      await fetch('/workspace/file', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: tab.path, content: tab.content })
      });
      tab.original = tab.content;
      tab.modified = false;
      this.renderTabs();
      toast(icon('save') + ' Saved: ' + path.split('/').pop());
      this.addActivity(icon('save'), 'File saved', path);
    } catch (e) { toast(ICONS.x(14) + ' Save error'); }
  }

  async createFile() {
    const name = prompt('File name (e.g. src/main.py):');
    if (!name || !name.trim()) return;

    const project = $('#project-select') ? $('#project-select').value : '.';
    let fullPath = name.trim();
    if (project && project !== '.' && !fullPath.startsWith(project + '/')) {
      fullPath = project + '/' + fullPath;
    }

    try {
      await fetch('/workspace/file', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: fullPath, content: '' })
      });
      await this.loadTree();
      this.openFile(fullPath);
      this.addActivity(icon('filePlus'), 'File created', fullPath);
    } catch (e) { toast(ICONS.x(14) + ' Create error'); }
  }

  async deleteFile(path) {
    if (!confirm('Delete ' + path + '?')) return;
    try {
      await fetch('/workspace/file?path=' + encodeURIComponent(path), { method: 'DELETE' });
      this.openTabs = this.openTabs.filter(t => t.path !== path);
      if (this.activeTab === path) {
        this.activeTab = this.openTabs.length ? this.openTabs[this.openTabs.length - 1].path : null;
      }
      await this.loadTree();
      if (this.activeTab) this.openFile(this.activeTab);
      else { this.renderTabs(); this.showWelcome(); }
      this.addActivity(icon('trash'), 'File deleted', path);
    } catch (e) { toast(ICONS.x(14) + ' Delete error'); }
  }

  async deleteDir(dirPath) {
    if (!confirm('Delete folder "' + dirPath + '" and all its contents?')) return;
    try {
      const resp = await fetch('/workspace/dir?path=' + encodeURIComponent(dirPath), { method: 'DELETE' });
      if (!resp.ok) {
        const d = await resp.json();
        toast(' ' + (d.detail || 'Delete failed'));
        return;
      }
      // Close any open tabs inside the deleted directory
      this.openTabs = this.openTabs.filter(t => !t.path.startsWith(dirPath + '/') && t.path !== dirPath);
      if (this.activeTab && (this.activeTab.startsWith(dirPath + '/') || this.activeTab === dirPath)) {
        this.activeTab = this.openTabs.length ? this.openTabs[this.openTabs.length - 1].path : null;
      }
      await this.loadTree();
      if (this.activeTab) this.openFile(this.activeTab);
      else { this.renderTabs(); this.showWelcome(); }
      this.addActivity(icon('trash'), 'Folder deleted', dirPath);
    } catch (e) { toast(' Delete error: ' + e.message); }
  }

  closeTab(path) {
    const tab = this.openTabs.find(t => t.path === path);
    if (tab && tab.modified && !confirm('Discard unsaved changes?')) return;
    this.openTabs = this.openTabs.filter(t => t.path !== path);
    if (this.activeTab === path) {
      this.activeTab = this.openTabs.length ? this.openTabs[this.openTabs.length - 1].path : null;
    }
    this.renderTabs();
    this.renderTree();
    if (this.activeTab) { const t = this.openTabs.find(t2 => t2.path === this.activeTab); if (t) this.loadIntoEditor(t); }
    else this.showWelcome();
  }

  closeAllTabs() {
    const hasUnsaved = this.openTabs.some(t => t.modified);
    if (hasUnsaved && !confirm('Discard all unsaved changes?')) return;
    this.openTabs = [];
    this.activeTab = null;
    this.renderTabs();
    this.renderTree();
    this.showWelcome();
  }


  renderTabs() {
    const tabsEl = $('#editor-tabs');
    tabsEl.innerHTML = '';
    this.openTabs.forEach((tab, tabIndex) => {
      const name = tab.path.split('/').pop();
      const tabEl = el('div', {
        class: 'editor-tab' + (tab.path === this.activeTab ? ' active' : '') + (tab.modified ? ' modified' : ''),
        onclick: () => { this.activeTab = tab.path; this.renderTabs(); this.renderTree(); this.loadIntoEditor(tab); }
      }, [
        el('span', { class: 'editor-tab-icon', html: this._fileIcon(name) }),
        el('span', { class: 'editor-tab-name', text: name }),
        el('span', { class: 'editor-tab-modified' }),
        el('button', { class: 'editor-tab-close', text: '', onclick: e => { e.stopPropagation(); this.closeTab(tab.path); } })
      ]);
      // Right-click context menu
      tabEl.addEventListener('contextmenu', e => {
        e.preventDefault();
        this._showTabContextMenu(e, tab.path, tabIndex);
      });
      tabsEl.appendChild(tabEl);
    });
    // Update breadcrumb
    const bc = $('#editor-breadcrumb');
    if (this.activeTab) {
      const parts = this.activeTab.split('/');
      bc.innerHTML = '<span>workspace</span>' + parts.map(p => '<span class="editor-breadcrumb-sep">›</span><span>' + escHtml(p) + '</span>').join('');
    } else {
      bc.innerHTML = '<span>workspace</span>';
    }

    // Scroll active tab into view & update scroll buttons
    requestAnimationFrame(() => {
      const activeEl = tabsEl.querySelector('.editor-tab.active');
      if (activeEl) activeEl.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
      this._updateTabScrollButtons();
    });

    // Wire up scroll buttons once
    if (!this._tabScrollWired) {
      this._tabScrollWired = true;
      const leftBtn = $('#editor-tabs-scroll-left');
      const rightBtn = $('#editor-tabs-scroll-right');
      const closeAllBtn = $('#editor-tabs-close-all');
      if (leftBtn) leftBtn.addEventListener('click', (e) => {
        e.preventDefault(); e.stopPropagation();
        const t = $('#editor-tabs');
        if (t) { t.scrollLeft -= 150; }
        setTimeout(() => this._updateTabScrollButtons(), 250);
      });
      if (rightBtn) rightBtn.addEventListener('click', (e) => {
        e.preventDefault(); e.stopPropagation();
        const t = $('#editor-tabs');
        if (t) { t.scrollLeft += 150; }
        setTimeout(() => this._updateTabScrollButtons(), 250);
      });
      if (closeAllBtn) closeAllBtn.addEventListener('click', () => this.closeAllTabs());
      // Update buttons on scroll and resize
      const tabsContainer = $('#editor-tabs');
      if (tabsContainer) {
        tabsContainer.addEventListener('scroll', () => this._updateTabScrollButtons());
        if (window.ResizeObserver) {
          new ResizeObserver(() => this._updateTabScrollButtons()).observe(tabsContainer);
        }
      }
    }
  }

  _updateTabScrollButtons() {
    const tabsEl = $('#editor-tabs');
    const leftBtn = $('#editor-tabs-scroll-left');
    const rightBtn = $('#editor-tabs-scroll-right');
    if (!tabsEl || !leftBtn || !rightBtn) return;
    const atLeft = tabsEl.scrollLeft <= 1;
    const atRight = tabsEl.scrollLeft + tabsEl.clientWidth >= tabsEl.scrollWidth - 1;
    leftBtn.disabled = atLeft;
    rightBtn.disabled = atRight;
  }

  _showTabContextMenu(e, path, index) {
    // Remove any existing menu
    const old = document.querySelector('.editor-tab-context');
    if (old) old.remove();

    const isFirst = index === 0;
    const isLast = index === this.openTabs.length - 1;
    const name = path.split('/').pop();

    const menu = document.createElement('div');
    menu.className = 'editor-tab-context';
    menu.style.left = e.clientX + 'px';
    menu.style.top = e.clientY + 'px';

    const items = [
      { label: '◄ Move Left', icon: '◄', action: () => this._moveTab(index, -1), disabled: isFirst },
      { label: '► Move Right', icon: '►', action: () => this._moveTab(index, 1), disabled: isLast },
      { sep: true },
      { label: ' Close', action: () => this.closeTab(path) },
      {
        label: ' Close Others', action: () => {
          const hasUnsaved = this.openTabs.some(t => t.path !== path && t.modified);
          if (hasUnsaved && !confirm('Discard unsaved changes in other tabs?')) return;
          this.openTabs = this.openTabs.filter(t => t.path === path);
          this.activeTab = path;
          this.renderTabs(); this.renderTree();
          const t = this.openTabs.find(t2 => t2.path === path);
          if (t) this.loadIntoEditor(t);
        }
      },
      { label: ' Close All', action: () => this.closeAllTabs(), cls: 'danger' },
    ];

    items.forEach(item => {
      if (item.sep) {
        const sep = document.createElement('div');
        sep.className = 'editor-tab-context-sep';
        menu.appendChild(sep);
        return;
      }
      const row = document.createElement('div');
      row.className = 'editor-tab-context-item' + (item.cls ? ' ' + item.cls : '');
      row.textContent = item.label;
      if (item.disabled) {
        row.style.opacity = '0.3';
        row.style.pointerEvents = 'none';
      } else {
        row.addEventListener('click', () => { menu.remove(); item.action(); });
      }
      menu.appendChild(row);
    });

    document.body.appendChild(menu);

    // Keep menu in viewport
    requestAnimationFrame(() => {
      const rect = menu.getBoundingClientRect();
      if (rect.right > window.innerWidth) menu.style.left = (window.innerWidth - rect.width - 8) + 'px';
      if (rect.bottom > window.innerHeight) menu.style.top = (window.innerHeight - rect.height - 8) + 'px';
    });

    // Dismiss on click outside
    const dismiss = (ev) => {
      if (!menu.contains(ev.target)) { menu.remove(); document.removeEventListener('mousedown', dismiss); }
    };
    setTimeout(() => document.addEventListener('mousedown', dismiss), 10);
  }

  _moveTab(index, direction) {
    const newIndex = index + direction;
    if (newIndex < 0 || newIndex >= this.openTabs.length) return;
    const temp = this.openTabs[index];
    this.openTabs[index] = this.openTabs[newIndex];
    this.openTabs[newIndex] = temp;
    this.renderTabs();
  }

  // ---- CodeMirror 6 Editor ----
  loadIntoEditor(tab) {
    const area = $('#editor-code-area');
    const welcome = $('#editor-welcome');
    if (welcome) welcome.style.display = 'none';

    // Try CodeMirror 6 first, fallback to textarea
    if (window.cm6) {
      this._loadCM6Editor(tab, area);
    } else {
      this._loadTextareaEditor(tab, area);
    }

    // Update breadcrumb
    const bc = $('#editor-breadcrumb');
    if (bc) bc.innerHTML = tab.path.split('/').map((p, i, arr) =>
      i === arr.length - 1 ? `<span class="bc-file">${escHtml(p)}</span>` : `<span>${escHtml(p)}</span><span class="bc-sep">/</span>`
    ).join('');
  }

  _loadCM6Editor(tab, area) {
    // Destroy previous CM6 view if switching tabs
    if (this._cmView && this._cmActiveTab !== tab.path) {
      this._cmView.destroy();
      this._cmView = null;
      clearInterval(this._cmChangeInterval);
      this._cmClearGhost();
    }

    if (!this._cmView) {
      area.innerHTML = '';
      const container = document.createElement('div');
      container.className = 'code-editor-wrap cm6-editor-wrap';
      container.style.cssText = 'flex:1;display:flex;flex-direction:column;overflow:hidden;position:relative;';
      area.appendChild(container);

      // Ghost text overlay for CM6
      const ghostOverlay = document.createElement('div');
      ghostOverlay.className = 'cm6-ghost-overlay';
      ghostOverlay.id = 'cm6-ghost';
      container.appendChild(ghostOverlay);

      const builder = cm6.load();
      const view = builder.newEditor(container, tab.content, {
        dark: true,
        lineWrapping: true,
        focus: { value: tab.content },
      });

      this._cmView = view;
      this._cmActiveTab = tab.path;
      this._currentLang = this._extToLang(tab.path);
      this._cmGhostText = '';
      this._cmGhostCursorPos = -1;
      this._cmLastContent = tab.content;

      const editorInstance = this;

      // Track changes + trigger autocomplete
      this._cmChangeInterval = setInterval(() => {
        if (!editorInstance._cmView || !editorInstance.activeTab) return;
        const currentContent = editorInstance._cmView.state.doc.toString();
        const t = editorInstance.openTabs.find(t2 => t2.path === editorInstance.activeTab);
        if (t && t.content !== currentContent) {
          t.content = currentContent;
          t.modified = t.content !== t.original;
          editorInstance.renderTabs();
          // Content changed — clear ghost and schedule autocomplete
          editorInstance._cmClearGhost();
          clearTimeout(editorInstance._autoSaveTimer);
          editorInstance._autoSaveTimer = setTimeout(() => {
            const tab2 = editorInstance.openTabs.find(t2 => t2.path === editorInstance.activeTab);
            if (tab2 && tab2.modified) {
              editorInstance.saveFile(tab2.path);
              editorInstance._showAutoSaveIndicator();
            }
          }, 2000);
          // Debounced AI autocomplete (500ms after last change)
          clearTimeout(editorInstance._cmAcTimer);
          if (editorInstance._acEnabled) {
            editorInstance._cmAcTimer = setTimeout(() => editorInstance._cmTriggerAutocomplete(), 500);
          }
          editorInstance._cmLastContent = currentContent;
        }
      }, 200);

      // Key handlers for ghost text + save
      container.addEventListener('keydown', e => {
        // Ctrl+S save
        if (e.ctrlKey && e.key === 's') {
          e.preventDefault();
          editorInstance.saveFile(editorInstance.activeTab);
          return;
        }
        // Tab: accept full ghost text
        if (e.key === 'Tab' && !e.shiftKey && editorInstance._cmGhostText) {
          e.preventDefault();
          editorInstance._cmAcceptGhost();
          return;
        }
        // Ctrl+Right: accept next word of ghost text
        if (e.ctrlKey && e.key === 'ArrowRight' && editorInstance._cmGhostText) {
          e.preventDefault();
          editorInstance._cmAcceptGhostWord();
          return;
        }
        // Escape: dismiss ghost
        if (e.key === 'Escape' && editorInstance._cmGhostText) {
          editorInstance._cmClearGhost();
          return;
        }
        // Any other key that isn't a modifier — dismiss ghost
        if (editorInstance._cmGhostText && !['Shift', 'Control', 'Alt', 'Meta'].includes(e.key)) {
          editorInstance._cmClearGhost();
        }
      });

      // Click dismisses ghost
      container.addEventListener('mousedown', () => {
        if (editorInstance._cmGhostText) editorInstance._cmClearGhost();
      });

    } else {
      // Same tab reload — just update content if different
      const currentContent = this._cmView.state.doc.toString();
      if (currentContent !== tab.content) {
        this._cmView.dispatch({
          changes: { from: 0, to: currentContent.length, insert: tab.content }
        });
      }
    }
  }

  // ---- CM6 Ghost Text Autocomplete ----
  _cmGhostText = '';
  _cmGhostCursorPos = -1;
  _cmAcTimer = null;
  _cmAcAbort = null;

  _cmClearGhost() {
    this._cmGhostText = '';
    this._cmGhostCursorPos = -1;
    const ghost = document.getElementById('cm6-ghost');
    if (ghost) { ghost.innerHTML = ''; ghost.style.display = 'none'; }
  }

  _cmAcceptGhost() {
    if (!this._cmView || !this._cmGhostText) return;
    const cursor = this._cmView.state.selection.main.head;
    this._cmView.dispatch({
      changes: { from: cursor, insert: this._cmGhostText }
    });
    // Move cursor to end of inserted text
    const newPos = cursor + this._cmGhostText.length;
    this._cmView.dispatch({ selection: { anchor: newPos } });
    this._cmClearGhost();
  }

  _cmAcceptGhostWord() {
    if (!this._cmView || !this._cmGhostText) return;
    const wordMatch = this._cmGhostText.match(/^(\S+\s?)/);
    if (!wordMatch) return;
    const word = wordMatch[1];
    const cursor = this._cmView.state.selection.main.head;
    this._cmView.dispatch({
      changes: { from: cursor, insert: word }
    });
    const newPos = cursor + word.length;
    this._cmView.dispatch({ selection: { anchor: newPos } });
    this._cmGhostText = this._cmGhostText.substring(word.length);
    if (!this._cmGhostText.trim()) {
      this._cmClearGhost();
    } else {
      this._cmGhostCursorPos = newPos;
      this._cmRenderGhost();
    }
  }

  async _cmTriggerAutocomplete() {
    if (!this._cmView || !this._acEnabled) return;
    const doc = this._cmView.state.doc.toString();
    if (!doc.trim()) return;
    const cursor = this._cmView.state.selection.main.head;
    // Don't trigger if selection
    if (this._cmView.state.selection.main.anchor !== cursor) return;

    const prefix = doc.substring(Math.max(0, cursor - 1500), cursor);
    const suffix = doc.substring(cursor, Math.min(doc.length, cursor + 500));
    const lastLine = prefix.split('\n').pop();
    if (!lastLine.trim() && prefix.trim().length < 20) return;

    const intent = this._detectCompletionIntent(prefix, suffix);
    const maxTokens = intent === 'comment_generate' ? 250 : 120;

    if (this._cmAcAbort) { this._cmAcAbort.abort(); this._cmAcAbort = null; }
    const controller = new AbortController();
    this._cmAcAbort = controller;
    this._cmGhostCursorPos = cursor;

    try {
      const r = await fetch('/api/autocomplete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prefix, suffix, intent,
          language: this._currentLang || 'plaintext',
          file_path: this.activeTab || '',
          provider: $('#provider-select').value,
          model: $('#model-select').value,
          max_tokens: maxTokens
        }),
        signal: controller.signal
      });
      if (!r.ok) return;
      const d = await r.json();
      let completion = (d.completion || '').trimEnd();
      if (!completion || completion.length < 2) return;
      // Don't show if cursor has moved
      if (this._cmView.state.selection.main.head !== cursor) return;

      this._cmGhostText = completion;
      this._cmRenderGhost();
    } catch (e) {
      if (e.name === 'AbortError') return;
    }
  }

  _cmRenderGhost() {
    const ghost = document.getElementById('cm6-ghost');
    if (!ghost || !this._cmView || !this._cmGhostText) return;
    const cursor = this._cmView.state.selection.main.head;
    const coords = this._cmView.coordsAtPos(cursor);
    if (!coords) return;
    // Position relative to editor container
    const cmEditor = this._cmView.dom;
    const cmRect = cmEditor.getBoundingClientRect();
    const wrapRect = ghost.parentElement.getBoundingClientRect();
    ghost.innerHTML = '';
    ghost.style.display = 'block';
    ghost.style.position = 'absolute';
    ghost.style.left = (coords.left - wrapRect.left) + 'px';
    ghost.style.top = (coords.top - wrapRect.top) + 'px';
    ghost.style.pointerEvents = 'none';
    ghost.style.zIndex = '10';
    // Render the ghost text with matching font
    const span = document.createElement('span');
    span.className = 'cm6-ghost-text';
    span.textContent = this._cmGhostText;
    ghost.appendChild(span);
  }

  _loadTextareaEditor(tab, area) {
    // Fallback: original textarea-based editor
    let editorWrap = area.querySelector('.code-editor-wrap');
    if (!editorWrap) {
      area.innerHTML = '';
      editorWrap = document.createElement('div');
      editorWrap.className = 'code-editor-wrap';
      editorWrap.innerHTML = `
        <div class="code-editor-gutter" id="code-gutter"></div>
        <div class="code-editor-content">
          <textarea class="code-editor-textarea" id="code-textarea" spellcheck="false" autocomplete="off" autocorrect="off" autocapitalize="off"></textarea>
          <pre class="code-editor-search-hl" id="code-search-hl" aria-hidden="true"></pre>
          <pre class="code-editor-highlight" id="code-highlight" aria-hidden="true"><code></code></pre>
          <pre class="code-editor-ghost" id="code-ghost" aria-hidden="true"></pre>
        </div>`;
      area.appendChild(editorWrap);

      const textarea = editorWrap.querySelector('#code-textarea');
      const pre = editorWrap.querySelector('#code-highlight');
      const gutter = editorWrap.querySelector('#code-gutter');

      // Sync scroll
      textarea.addEventListener('scroll', () => {
        pre.scrollTop = textarea.scrollTop;
        pre.scrollLeft = textarea.scrollLeft;
        gutter.scrollTop = textarea.scrollTop;
        const ghost = document.querySelector('#code-ghost');
        if (ghost) { ghost.scrollTop = textarea.scrollTop; ghost.scrollLeft = textarea.scrollLeft; }
        const diffBg = document.querySelector('#code-diff-bg');
        if (diffBg) { diffBg.scrollTop = textarea.scrollTop; diffBg.scrollLeft = textarea.scrollLeft; }
      });

      // Input handler
      textarea.addEventListener('input', () => {
        const t = this.openTabs.find(t2 => t2.path === this.activeTab);
        if (t) { t.content = textarea.value; t.modified = t.content !== t.original; this.renderTabs(); }
        clearTimeout(this._hlTimer);
        this._hlTimer = setTimeout(() => {
          this._updateHighlight(textarea.value);
          this._updateSearchHighlight();
        }, 50);
        this._clearGhost();
        const currentTabPath = this.activeTab;
        clearTimeout(this._autoSaveTimer);
        this._autoSaveTimer = setTimeout(() => {
          const tab = this.openTabs.find(t2 => t2.path === currentTabPath);
          if (tab && tab.modified) { this.saveFile(tab.path); this._showAutoSaveIndicator(); }
        }, 2000);
        clearTimeout(this._acTimer);
        if (this._acEnabled) {
          this._acTimer = setTimeout(() => this._triggerAutocomplete(textarea), 500);
        }
      });

      // Key handlers
      textarea.addEventListener('keydown', e => {
        if (e.key === 'Tab' && !e.shiftKey) {
          if (this._ghostText) { e.preventDefault(); this._insertText(textarea, this._ghostText); this._clearGhost(); return; }
          e.preventDefault(); this._insertText(textarea, '  ');
        }
        if (e.ctrlKey && e.key === 'ArrowRight' && this._ghostText) {
          e.preventDefault();
          const wordMatch = this._ghostText.match(/^(\S+\s?)/);
          if (wordMatch) {
            const word = wordMatch[1];
            this._insertText(textarea, word);
            const t = this.openTabs.find(t2 => t2.path === this.activeTab);
            if (t) { t.content = textarea.value; t.modified = t.content !== t.original; this.renderTabs(); }
            this._updateHighlight(textarea.value);
            this._ghostText = this._ghostText.substring(word.length);
            this._ghostLines = this._ghostText.split('\n');
            if (!this._ghostText.trim()) { this._clearGhost(); }
            else { this._acCursorPos = textarea.selectionStart; this._renderGhost(textarea, this._acCursorPos); }
          }
          return;
        }
        if (e.ctrlKey && (e.key === 'z' || e.key === 'Z')) { if (this._ghostText) this._clearGhost(); return; }
        if (e.ctrlKey && e.key === 's') { e.preventDefault(); this.saveFile(this.activeTab); }
        if (e.key === 'Escape' && this._ghostText) { this._clearGhost(); }
        if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageUp', 'PageDown'].includes(e.key) && this._ghostText && !e.ctrlKey) {
          this._clearGhost();
        }
        if (e.key === 'Enter') {
          if (this._ghostText) this._clearGhost();
          e.preventDefault();
          const s = textarea.selectionStart;
          const lineStart = textarea.value.lastIndexOf('\n', s - 1) + 1;
          const currentLine = textarea.value.substring(lineStart, s);
          const indent = currentLine.match(/^(\s*)/)[0];
          let extra = '';
          if (currentLine.trimEnd().endsWith(':') || currentLine.trimEnd().endsWith('{')) extra = '  ';
          this._insertText(textarea, '\n' + indent + extra);
        }
      });

      textarea.addEventListener('click', () => { if (this._ghostText) this._clearGhost(); });
    }

    const textarea = editorWrap.querySelector('#code-textarea');
    textarea.value = tab.content;
    this._currentLang = this._extToLang(tab.path);
    this._updateHighlight(tab.content);
  }

  // Insert text at cursor using execCommand to preserve undo/redo stack (Ctrl+Z)
  _insertText(textarea, text) {
    textarea.focus();
    // execCommand('insertText') is the only way to insert text
    // into a textarea while keeping the native undo history intact.
    document.execCommand('insertText', false, text);
  }
  _extToLang(path) {
    const ext = path.split('.').pop().toLowerCase();
    const map = {
      py: 'python', js: 'javascript', ts: 'typescript', jsx: 'javascript', tsx: 'typescript',
      html: 'html', css: 'css', json: 'json', md: 'markdown', sh: 'bash', yml: 'yaml', yaml: 'yaml',
      rs: 'rust', go: 'go', java: 'java', cpp: 'cpp', c: 'c', rb: 'ruby', php: 'php', sql: 'sql',
      toml: 'toml', xml: 'xml', txt: 'plaintext'
    };
    return map[ext] || 'plaintext';
  }

  _updateHighlight(code) {
    const pre = document.querySelector('#code-highlight');
    const gutter = document.querySelector('#code-gutter');
    if (!pre || !gutter) return;

    const codeEl = pre.querySelector('code');
    const lang = this._currentLang || 'plaintext';
    // Use hljs.highlight() (returns HTML) — NOT highlightElement (refuses re-processing)
    try {
      if (window.hljs && lang !== 'plaintext') {
        const result = hljs.highlight(code + '\n', { language: lang, ignoreIllegals: true });
        codeEl.innerHTML = result.value;
      } else {
        codeEl.textContent = code + '\n';
      }
    } catch (e) {
      // Fallback: no highlight
      codeEl.textContent = code + '\n';
    }
    codeEl.className = 'language-' + lang;

    // Line numbers and diff background
    const lines = code.split('\n').length;
    let gutterHtml = '';
    let diffBgHtml = '';
    for (let i = 1; i <= lines; i++) {
      const isHl = this._highlightLines && this._highlightLines.includes(i);
      gutterHtml += `<div class="line-num${isHl ? ' diff-hl' : ''}">${i}</div>`;
      diffBgHtml += `<div class="diff-bg-line${isHl ? ' diff-hl' : ''}"></div>`;
    }
    gutter.innerHTML = gutterHtml;

    let diffBg = document.querySelector('#code-diff-bg');
    if (!diffBg) {
      diffBg = document.createElement('div');
      diffBg.id = 'code-diff-bg';
      diffBg.className = 'code-editor-diff-bg';
      document.querySelector('.code-editor-content').prepend(diffBg);
    }
    diffBg.innerHTML = diffBgHtml;
  }

  highlightDiff(path, diffStr) {
    if (this.activeTab !== path || !diffStr) return;
    const lines = diffStr.split('\n');
    let currentLine = 0;
    const addedLines = [];
    for (const line of lines) {
      const headerMatch = line.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (headerMatch) {
        currentLine = parseInt(headerMatch[1], 10);
        continue;
      }
      if (line.startsWith('+') && !line.startsWith('+++')) {
        addedLines.push(currentLine);
        currentLine++;
      } else if (line.startsWith('-') && !line.startsWith('---')) {
        // removed line, doesn't advance currentLine in the new file
      } else if (!line.startsWith('\\')) { // context line
        currentLine++;
      }
    }
    this._highlightLines = addedLines;
    const tab = this.openTabs.find(t => t.path === path);
    if (tab) {
      this._updateHighlight(tab.content);
      // Scroll to the first changed line
      if (addedLines.length > 0) {
        const textarea = document.querySelector('#code-textarea');
        if (textarea) {
          // Approximate 21px line height (varies slightly by font, but close enough)
          textarea.scrollTop = Math.max(0, (addedLines[0] - 2) * 21);
        }
      }
    }
    // Clear highlight after 5 seconds to show it was a momentary diff
    setTimeout(() => {
      this._highlightLines = [];
      if (this.activeTab === path && tab) {
        this._updateHighlight(tab.content);
      }
    }, 5000);
  }

  // ---- AI Autocomplete (Copilot/Antigravity style) ----
  _ghostText = '';
  _ghostLines = [];
  _acTimer = null;
  _acAbort = null;
  _autoSaveTimer = null;
  _hlTimer = null;
  _acCursorPos = -1; // cursor position when autocomplete was triggered
  _acEnabled = true; // can be toggled

  _clearGhost() {
    this._ghostText = '';
    this._ghostLines = [];
    this._acCursorPos = -1;
    const ghost = document.querySelector('#code-ghost');
    if (ghost) {
      ghost.textContent = '';
      ghost.style.display = 'none';
    }
  }

  _showAutoSaveIndicator() {
    // Brief indicator on the tab bar
    const tabBar = document.querySelector('#editor-tabs');
    if (!tabBar) return;
    let ind = tabBar.querySelector('.auto-save-indicator');
    if (!ind) {
      ind = el('span', { class: 'auto-save-indicator', text: ' Saved' });
      tabBar.appendChild(ind);
    }
    ind.classList.add('visible');
    setTimeout(() => ind.classList.remove('visible'), 1500);
  }

  // ---- Rename File or Folder ----
  async renameFile(oldPath) {
    const oldName = oldPath.split('/').pop();
    const newName = prompt('Rename file or folder:', oldName);
    if (!newName || !newName.trim() || newName.trim() === oldName) return;
    // Build new path: replace the last segment
    const parts = oldPath.split('/');
    parts[parts.length - 1] = newName.trim();
    const newPath = parts.join('/');
    try {
      const r = await fetch('/workspace/rename', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_path: oldPath, new_path: newPath })
      });
      const d = await r.json();
      if (d.status === 'ok') {
        // Update open tab if renamed file is open
        const tab = this.openTabs.find(t => t.path === oldPath);
        if (tab) {
          tab.path = newPath;
          if (this.activeTab === oldPath) this.activeTab = newPath;
        }
        await this.loadTree();
        this.renderTabs();
        toast(' Renamed: ' + oldName + ' → ' + newName.trim());
        this.addActivity('', 'File renamed', oldPath + ' → ' + newPath);
      } else {
        toast(ICONS.x(14) + ' Rename failed');
      }
    } catch (e) { toast(ICONS.x(14) + ' Rename error'); }
  }

  /**
   * Detect the user's completion intent based on cursor context.
   * Returns: 'comment_generate' | 'correction' | 'continuation'
   */
  _detectCompletionIntent(prefix, suffix) {
    const lines = prefix.split('\n');
    const currentLine = lines[lines.length - 1];
    const prevLine = lines.length > 1 ? lines[lines.length - 2] : '';
    const trimCurrent = currentLine.trim();
    const trimPrev = prevLine.trim();

    // Comment patterns for various languages
    const commentPatterns = [
      /^#\s+\S/,           // Python: # do something
      /^\/\/\s+\S/,        // JS/C/Go: // do something
      /^\/\*.*\*\/$/,      // Single-line block comment: /* ... */
      /^\*\s+\S/,          // Inside block comment: * do something
      /^"""/,              // Python docstring open
      /^'''/,              // Python docstring open
      /^--\s+\S/,          // SQL/Lua: -- comment
    ];
    const isComment = (line) => commentPatterns.some(p => p.test(line.trim()));

    // 1. Comment-generate: cursor is on empty line after a comment,
    //    or cursor is at end of a comment line (comment is "complete")
    if (!trimCurrent && isComment(trimPrev)) return 'comment_generate';
    if (isComment(trimCurrent) && trimCurrent.length > 8) {
      // Check if we're at the end of the comment (not mid-typing)
      // — only trigger if the comment looks complete (ends with punctuation or word)
      if (/[.!?):\w]$/.test(trimCurrent)) return 'comment_generate';
    }
    // Multi-line docstring: """ or ''' just closed
    if (trimCurrent === '"""' || trimCurrent === "'''") return 'comment_generate';

    // 2. Correction: cursor is in the middle of a non-empty line
    //    (there is significant code after cursor on the same line)
    const afterCursorOnLine = suffix.split('\n')[0];
    if (afterCursorOnLine.trim().length > 2 && trimCurrent.length > 0) {
      return 'correction';
    }

    // 3. Default: continuation
    return 'continuation';
  }

  async _triggerAutocomplete(textarea) {
    if (!textarea.value.trim() || !this._acEnabled) return;
    const cursor = textarea.selectionStart;
    const fullText = textarea.value;

    // Don't trigger if there's a selection
    if (textarea.selectionStart !== textarea.selectionEnd) return;

    // Get prefix (up to 1500 chars before cursor) and suffix (up to 500 chars after)
    const prefix = fullText.substring(Math.max(0, cursor - 1500), cursor);
    const suffix = fullText.substring(cursor, Math.min(fullText.length, cursor + 500));

    // Minimal safety: skip truly empty contexts
    const lastLine = prefix.split('\n').pop();
    if (!lastLine.trim() && prefix.trim().length < 20) return;

    // Detect intent
    const intent = this._detectCompletionIntent(prefix, suffix);

    // Adaptive max_tokens: generate more code for comment→code generation
    const maxTokens = intent === 'comment_generate' ? 250 : 120;

    // Abort previous request
    if (this._acAbort) {
      this._acAbort.abort();
      this._acAbort = null;
    }
    const controller = new AbortController();
    this._acAbort = controller;
    this._acCursorPos = cursor;

    try {
      const r = await fetch('/api/autocomplete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prefix,
          suffix,
          intent,
          language: this._currentLang || 'plaintext',
          file_path: this.activeTab || '',
          provider: $('#provider-select').value,
          model: $('#model-select').value,
          max_tokens: maxTokens
        }),
        signal: controller.signal
      });
      if (!r.ok) return;
      const d = await r.json();
      let completion = (d.completion || '').trimEnd();
      if (!completion || completion.length < 2) return;

      // Don't show if cursor has moved since request
      if (textarea.selectionStart !== cursor) return;

      // Store and render ghost text
      this._ghostText = completion;
      this._ghostLines = completion.split('\n');
      this._renderGhost(textarea, cursor);
    } catch (e) {
      if (e.name === 'AbortError') return;
      /* silent fail */
    }
  }

  _renderGhost(textarea, cursor) {
    const ghost = document.querySelector('#code-ghost');
    if (!ghost || !this._ghostText) return;

    const fullText = textarea.value;
    const before = fullText.substring(0, cursor);
    const after = fullText.substring(cursor);

    // Full-text overlay technique: render entire document with
    // original text invisible, only ghost completion visible.
    // This guarantees pixel-perfect alignment because the <pre>
    // uses the exact same font/padding/layout as the textarea.
    ghost.textContent = ''; // clear

    // Invisible text before cursor
    const spanBefore = document.createElement('span');
    spanBefore.className = 'ghost-hidden';
    spanBefore.textContent = before;

    // Visible ghost completion
    const spanGhost = document.createElement('span');
    spanGhost.className = 'ghost-visible';
    spanGhost.textContent = this._ghostText;

    // Invisible text after cursor
    const spanAfter = document.createElement('span');
    spanAfter.className = 'ghost-hidden';
    spanAfter.textContent = after;

    ghost.appendChild(spanBefore);
    ghost.appendChild(spanGhost);
    ghost.appendChild(spanAfter);

    // Sync scroll position with textarea
    ghost.scrollTop = textarea.scrollTop;
    ghost.scrollLeft = textarea.scrollLeft;
    ghost.style.display = 'block';
  }


  showWelcome() {
    const area = $('#editor-code-area');
    area.innerHTML = '<div class="editor-welcome" id="editor-welcome"><div class="editor-welcome-icon"></div><h3>Clawzd Editor</h3><p>Open a file from the explorer or create a new one to start editing.</p></div>';
  }

  // ---- Activity Feed ----
  addActivity(iconStr, title, detail) {
    const list = $('#editor-activity-list');
    const empty = list.querySelector('.editor-activity-empty');
    if (empty) empty.remove();
    const now = new Date();
    const time = now.getHours().toString().padStart(2, '0') + ':' + now.getMinutes().toString().padStart(2, '0') + ':' + now.getSeconds().toString().padStart(2, '0');
    const item = el('div', { class: 'editor-activity-item' }, [
      el('span', { class: 'editor-activity-icon', html: iconStr }),
      el('div', { class: 'editor-activity-body' }, [
        el('div', { class: 'editor-activity-title', text: title }),
        detail ? el('div', { class: 'editor-activity-detail', text: detail }) : null
      ]),
      el('span', { class: 'editor-activity-time', text: time })
    ]);
    list.appendChild(item);
    list.scrollTop = list.scrollHeight;
  }

  // ---- Terminal ----
  async runCommand(cmd) {
    if (!cmd.trim()) return;
    const body = $('#editor-terminal-body');
    body.innerHTML += '<div class="term-line system">$ ' + escHtml(cmd) + '</div>';
    body.scrollTop = body.scrollHeight;
    this.addActivity('', 'Running command', cmd);
    try {
      const r = await fetch('/local/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: cmd, project: this.activeProject || '.' })
      });
      const d = await r.json();
      if (d.stdout) body.innerHTML += '<div class="term-line stdout">' + escHtml(d.stdout) + '</div>';
      if (d.stderr) body.innerHTML += '<div class="term-line stderr">' + escHtml(d.stderr) + '</div>';
      if (d.returncode === 0) {
        body.innerHTML += '<div class="term-line success"> Exit code: 0</div>';
        this.addActivity('', 'Command completed', cmd);
      } else {
        body.innerHTML += '<div class="term-line stderr"> Exit code: ' + (d.returncode || '?') + '</div>';
        this.addActivity('', 'Command failed', 'Exit ' + (d.returncode || '?'));
      }
    } catch (e) {
      body.innerHTML += '<div class="term-line stderr">' + ICONS.x(14) + ' Error: ' + escHtml(e.message) + '</div>';
    }
    body.scrollTop = body.scrollHeight;
  }

  // ---- Editor Chat (AI) ----
  async sendEditorChat() {
    const input = $('#editor-chat-input');
    const msg = input.value.trim();
    if (!msg || this.editorStreaming) return;

    // Hide any open popups
    this.hideFileRefPopup();

    if (!this.editorSessionId) {
      try {
        const r = await fetch('/chat/new', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider: $('#provider-select').value, model: $('#model-select').value, preprompt: this._getAgentPreprompt() }) });
        const d = await r.json();
        this.editorSessionId = d.id;
        this.connectEditorSSE();
      } catch (e) { toast(ICONS.x(14) + ' Session error'); return; }
    } else if (!this.editorES || this.editorES.readyState === 2) {
      this.connectEditorSSE();
    }

    // Inject active file context if available
    let enrichedMsg = msg;

    // Inject project context
    if (this.projectPath) {
      enrichedMsg = `[Context: Working in project directory "${this.projectPath}"]\\n\\n${enrichedMsg}`;
    }

    // Inject attached files context
    if (this.attachedFiles.length) {
      const filesCtx = this.attachedFiles.map(f => {
        const maxLen = 2000;
        const content = f.content.length > maxLen ? f.content.substring(0, maxLen) + '\n... (truncated)' : f.content;
        return `[Attached: ${f.path}]\n\`\`\`${this._extToLang(f.path)}\n${content}\n\`\`\``;
      }).join('\n\n');
      enrichedMsg = `${filesCtx}\n\n${enrichedMsg}`;
    }

    const activeTab = this.openTabs.find(t => t.path === this.activeTab);
    if (activeTab && activeTab.content) {
      const maxCtx = 3000; // Limit context size
      const fileContent = activeTab.content.length > maxCtx
        ? activeTab.content.substring(0, maxCtx) + '\n... (truncated)'
        : activeTab.content;
      enrichedMsg = `[Currently editing: ${activeTab.path}]\n\`\`\`${this._extToLang(activeTab.path)}\n${fileContent}\n\`\`\`\n\n${enrichedMsg}`;
    }

    // Inject Active Implementation Plan if available
    if (this.activePlan) {
      enrichedMsg = `[Active Implementation Plan:\n${this.activePlan}]\n\n${enrichedMsg}`;
    }

    // Track tokens
    this.editorTokenCount += this._estimateTokens(enrichedMsg);
    this._updateContextBar();

    this.addEditorMsg('user', msg);
    this.addActivity(icon('chat'), 'You', msg.substring(0, 80) + (msg.length > 80 ? '...' : ''));
    input.value = '';
    // Clear attached files after sending
    this.attachedFiles = [];
    this._renderFileBadges();

    try {
      await fetch('/send/' + this.editorSessionId, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: enrichedMsg, provider: $('#provider-select').value, model: $('#model-select').value, preprompt: this._getAgentPreprompt(), active_project: this.projectPath, active_file: this.activeTab })
      });
    } catch (e) { toast(ICONS.x(14) + ' Send error'); }
  }

  connectEditorSSE() {
    if (this.editorES) this.editorES.close();
    this.editorES = new EventSource('/stream/' + this.editorSessionId);
    this.editorES.onmessage = e => this.handleEditorToken(e.data);
  }

  handleEditorToken(tok) {
    if (!this.editorStreaming) {
      this.editorStreaming = true;
      this.editorText = '';
      this.editorBubble = this.addEditorMsg('assistant', '');
      this.addActivity('', 'AI responding...', '');
    }
    if (tok === '[DONE]') {
      if (this._editorRenderTimer) { clearTimeout(this._editorRenderTimer); this._editorRenderTimer = null; }
      this._editorRenderPending = false;
      this.editorStreaming = false;
      if (this.editorBubble) {
        const content = this.editorBubble.querySelector('.msg-content');
        if (content) content.innerHTML = renderMd(this._formatThoughtsBeforeMd(this.editorText));
        this.editorBubble.dataset.raw = encodeURIComponent(this.editorText);
        highlightAll(this.editorBubble);
      }
      // Track received tokens
      this.editorTokenCount += this._estimateTokens(this.editorText);
      this._updateContextBar();
      // Extract todos from AI response
      this._extractTodos(this.editorText);
      // Auto-extract files from code blocks and save to workspace
      this._autoSaveFiles(this.editorText);
      this.editorBubble = null;
      this.editorText = '';
      this.addActivity(icon('check'), 'AI response complete', '');
      // Refresh file tree in case AI created files
      this.loadTree();
      return;
    }
    this.editorText += tok;
    if (!this._editorRenderPending) {
      this._editorRenderPending = true;
      this._editorRenderTimer = setTimeout(() => {
        this._editorRenderPending = false;
        this._editorRenderTimer = null;

        if (this.editorBubble) {
          const content = this.editorBubble.querySelector('.msg-content');
          if (content) {
            // Capture open details
            const openDetails = [];
            content.querySelectorAll('details').forEach((d, i) => {
              if (d.hasAttribute('open')) openDetails.push(i);
            });

            let preview = this._formatThoughtsBeforeMd(this.editorText);
            const fc = (preview.match(/```/g) || []).length;
            if (fc % 2 !== 0) preview += '\n```';
            content.innerHTML = renderMd(preview) + '<span class="streaming-cursor"></span>';

            // Restore open details
            if (openDetails.length > 0) {
              content.querySelectorAll('details').forEach((d, i) => {
                if (openDetails.includes(i)) d.setAttribute('open', '');
              });
            }
          }
        }
        const msgs = $('#editor-chat-messages');
        msgs.scrollTop = msgs.scrollHeight;
        if (typeof highlightAll === 'function') highlightAll(this.editorBubble);
      }, 150);
    }
  }

  addEditorMsg(role, content) {
    const msgs = $('#editor-chat-messages');
    const modeLabel = this.agentMode === 'plan' ? ' Plan' : ' Build';
    const authorText = role === 'user' ? 'You' : `Clawzd · ${modeLabel}`;
    const div = el('div', { class: 'editor-chat-msg ' + role }, [
      el('div', { class: 'msg-author', text: authorText }),
      el('div', { class: 'msg-content', html: content ? renderMd(content) : '' })
    ]);
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return div;
  }

  _formatThoughtsBeforeMd(text) {
    if (!text) return text;
    let result = text.replace(/<thought>([\s\S]*?)<\/thought>/gi, (match, content) => {
      return `\n<details class="ai-thought"><summary>💭 Agent Reflections</summary>\n\n${content}\n\n</details>\n`;
    });
    if (result.includes('<thought>')) {
      result = result.replace(/<thought>([\s\S]*)$/i, (match, content) => {
        return `\n<details class="ai-thought" open><summary>💭 Agent Reflections (Thinking...)</summary>\n\n${content}\n\n</details>\n`;
      });
    }
    return result;
  }

  // ---- Agent Mode Toggle (Build / Plan) ----
  setAgentMode(mode) {
    if (mode === 'build' && this.agentMode === 'plan') {
      // Extract the last AI response as the active plan
      const msgs = document.querySelectorAll('#editor-chat-messages .editor-chat-msg.assistant');
      if (msgs.length > 0) {
        const lastMsg = msgs[msgs.length - 1];
        if (lastMsg.dataset.raw) {
          this.activePlan = decodeURIComponent(lastMsg.dataset.raw);
          toast(ICONS.check(14) + ' Plan captured! Context size optimized.');
        }
      }
    }

    this.agentMode = mode;
    $$('.agent-mode-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.agent === mode);
    });

    const indicator = $('#agent-mode-indicator');
    if (indicator) {
      indicator.innerHTML = this.activePlan ? '📋 Plan Active' : '';
    }

    // Force new session on mode change so preprompt switches
    this.editorSessionId = null;
    if (this.editorES) { this.editorES.close(); this.editorES = null; }
    const label = mode === 'plan' ? ' Switched to Plan mode — read-only analysis' : ' Switched to Build mode — full edit access';
    this.addEditorMsg('assistant', label);
    this.addActivity(mode === 'plan' ? '' : '', 'Mode changed', mode.charAt(0).toUpperCase() + mode.slice(1));
  }

  _getAgentPreprompt() {
    return this.agentMode === 'plan' ? 'ide_planner' : 'ide_developer';
  }


  _cmdClear() {
    this.editorSessionId = null;
    this.activePlan = null;
    if (this.editorES) { this.editorES.close(); this.editorES = null; }
    $('#editor-chat-messages').innerHTML = '';
    const indicator = $('#agent-mode-indicator');
    if (indicator) indicator.innerHTML = '';
    this.editorTokenCount = 0;
    this._updateContextBar();
    this.attachedFiles = [];
    this._renderFileBadges();
    toast(ICONS.circle(14) + ' ️ Chat cleared');
  }

  _cmdUndo() {
    if (!this.changeHistory.length) {
      this.addEditorMsg('assistant', ' No AI changes to undo.');
      return;
    }
    if (this.changeHistoryIdx < 0) this.changeHistoryIdx = this.changeHistory.length - 1;
    else if (this.changeHistoryIdx === 0) {
      this.addEditorMsg('assistant', ' Already at the oldest change.');
      return;
    } else {
      this.changeHistoryIdx--;
    }
    const change = this.changeHistory[this.changeHistoryIdx];
    this._applyFileContent(change.path, change.oldContent);
    this.addEditorMsg('assistant', `↩️ **Undone:** \`${change.path}\` reverted to previous version.`);
    this.addActivity('↩️', 'Undo', change.path);
  }

  _cmdRedo() {
    if (this.changeHistoryIdx < 0 || this.changeHistoryIdx >= this.changeHistory.length - 1) {
      this.addEditorMsg('assistant', ' Nothing to redo.');
      return;
    }
    this.changeHistoryIdx++;
    const change = this.changeHistory[this.changeHistoryIdx];
    this._applyFileContent(change.path, change.newContent);
    this.addEditorMsg('assistant', `↪️ **Redone:** \`${change.path}\` restored to AI version.`);
    this.addActivity('↪️', 'Redo', change.path);
  }

  async _applyFileContent(path, content) {
    try {
      await fetch('/workspace/file', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, content })
      });
      const tab = this.openTabs.find(t => t.path === path);
      if (tab) {
        tab.content = content;
        tab.original = content;
        tab.modified = false;
        if (this.activeTab === path) this.loadIntoEditor(tab);
        this.renderTabs();
      }
      this.loadTree();
    } catch (e) { toast(ICONS.x(14) + ' Apply error'); }
  }

  async _cmdInit() {
    this.addEditorMsg('assistant', ' Analyzing project structure to generate context...');
    // Send a special message to AI to generate the context
    const msg = '/init — Please analyze the entire workspace file tree, identify the project type, main frameworks, dependencies, and architecture. Generate a comprehensive clawzd.md context file that describes this project for future AI interactions. Include: project overview, tech stack, directory structure, key files, and coding conventions.';
    if (!this.editorSessionId) {
      try {
        const r = await fetch('/chat/new', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider: $('#provider-select').value, model: $('#model-select').value, preprompt: this._getAgentPreprompt() }) });
        const d = await r.json();
        this.editorSessionId = d.id;
        this.connectEditorSSE();
      } catch (e) { toast(ICONS.x(14) + ' Session error'); return; }
    }
    try {
      await fetch('/send/' + this.editorSessionId, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg, provider: $('#provider-select').value, model: $('#model-select').value, preprompt: 'ide_developer', active_project: this.projectPath })
      });
    } catch (e) { toast(ICONS.x(14) + ' Send error'); }
  }

  _cmdTodo() {
    // Switch to Todo tab
    $$('.editor-right-tab').forEach(t => t.classList.remove('active'));
    const todoTab = $('#ert-todo');
    if (todoTab) todoTab.classList.add('active');
    $('#editor-activity')?.classList.remove('active');
    $('#editor-chat')?.classList.remove('active');
    $('#editor-git')?.classList.remove('active');
    $('#editor-todo')?.classList.add('active');
  }

  _cmdDiff() {
    if (!this.changeHistory.length) {
      this.addEditorMsg('assistant', ' No AI changes recorded in this session.');
      return;
    }
    const lines = this.changeHistory.map((c, i) => {
      const time = new Date(c.timestamp).toLocaleTimeString();
      return `${i + 1}. \`${c.path}\` — ${time}`;
    }).join('\n');
    this.addEditorMsg('assistant', `** AI Changes This Session (${this.changeHistory.length}):**\n\n${lines}\n\nUse \`/undo\` to revert changes.`);
  }

  async _cmdCompact() {
    this.addEditorMsg('assistant', '️ Compacting session context... Starting a fresh session while preserving key context.');
    // Simply reset session — the backend will handle new context
    this.editorSessionId = null;
    if (this.editorES) { this.editorES.close(); this.editorES = null; }
    this.editorTokenCount = 0;
    this._updateContextBar();
    toast(ICONS.circle(14) + ' ️ Session compacted');
  }

  // ---- @ File References ----
  _fileRefIcon(path) {
    // Reuse the same SVG icons as the file explorer
    return this._fileIcon(path.split('/').pop());
  }

  showFileRefPopup(query) {
    const popup = $('#file-ref-popup');
    if (!this.files.length) { this.hideFileRefPopup(); return; }
    const q = query.toLowerCase().trim();
    let matches;
    if (!q) {
      // Empty query: show first 15 files
      matches = this.files.slice(0, 15);
    } else {
      // Fuzzy match: check full path AND basename
      matches = this.files
        .filter(f => {
          const lower = f.path.toLowerCase();
          const basename = lower.split('/').pop();
          return lower.includes(q) || basename.includes(q);
        })
        .sort((a, b) => {
          // Prioritize basename matches
          const aBase = a.path.toLowerCase().split('/').pop().startsWith(q);
          const bBase = b.path.toLowerCase().split('/').pop().startsWith(q);
          if (aBase && !bBase) return -1;
          if (!aBase && bBase) return 1;
          return a.path.length - b.path.length;
        })
        .slice(0, 15);
    }
    if (!matches.length) { this.hideFileRefPopup(); return; }
    this.fileRefIndex = 0;
    popup.innerHTML = matches.map((f, i) => {
      const sizeStr = f.size > 1024 ? (f.size / 1024).toFixed(0) + 'K' : f.size + 'B';
      const icon = this._fileRefIcon(f.path);
      // Highlight matching part
      const pathHtml = q ? this._highlightMatch(f.path, q) : escHtml(f.path);
      return `
        <div class="file-ref-item${i === 0 ? ' active' : ''}" data-path="${escHtml(f.path)}" data-idx="${i}">
          <span class="file-ref-icon">${icon}</span>
          <span class="file-ref-path">${pathHtml}</span>
          <span class="file-ref-size">${sizeStr}</span>
        </div>`;
    }).join('');
    popup.classList.add('open');
    popup.querySelectorAll('.file-ref-item').forEach((el, i) => {
      el.addEventListener('click', () => {
        this._attachFile(matches[i].path);
        this.hideFileRefPopup();
        this._clearAtQuery();
      });
    });
  }

  _highlightMatch(text, query) {
    if (!query) return escHtml(text);
    const idx = text.toLowerCase().indexOf(query);
    if (idx < 0) return escHtml(text);
    return escHtml(text.substring(0, idx)) +
      '<mark>' + escHtml(text.substring(idx, idx + query.length)) + '</mark>' +
      escHtml(text.substring(idx + query.length));
  }

  hideFileRefPopup() {
    const popup = $('#file-ref-popup');
    popup.classList.remove('open');
    popup.innerHTML = '';
    this.fileRefIndex = -1;
  }

  navigateFileRefPopup(dir) {
    const items = $$('#file-ref-popup .file-ref-item');
    if (!items.length) return;
    items[this.fileRefIndex]?.classList.remove('active');
    this.fileRefIndex = (this.fileRefIndex + dir + items.length) % items.length;
    items[this.fileRefIndex]?.classList.add('active');
    items[this.fileRefIndex]?.scrollIntoView({ block: 'nearest' });
  }

  selectFileRef() {
    const items = $$('#file-ref-popup .file-ref-item');
    if (this.fileRefIndex >= 0 && items[this.fileRefIndex]) {
      items[this.fileRefIndex].click();
      return true;
    }
    return false;
  }

  async _attachFile(path) {
    if (this.attachedFiles.some(f => f.path === path)) return; // already attached
    try {
      const r = await fetch('/workspace/file?path=' + encodeURIComponent(path));
      if (!r.ok) { toast(ICONS.x(14) + ' Cannot read file'); return; }
      const d = await r.json();
      this.attachedFiles.push({ path, content: d.content });
      this._renderFileBadges();
      toast(' Attached: ' + path.split('/').pop());
    } catch (e) { toast(ICONS.x(14) + ' File read error'); }
  }

  _detachFile(path) {
    this.attachedFiles = this.attachedFiles.filter(f => f.path !== path);
    this._renderFileBadges();
  }

  _renderFileBadges() {
    const container = $('#editor-file-badges');
    if (!container) return;
    container.innerHTML = '';
    if (!this.attachedFiles.length) {
      container.classList.remove('has-badges');
      return;
    }
    container.classList.add('has-badges');
    this.attachedFiles.forEach(f => {
      const name = f.path.split('/').pop();
      const badge = el('span', { class: 'file-badge' }, [
        el('span', { text: ' ' + name }),
        el('button', { class: 'file-badge-remove', text: '', onclick: () => this._detachFile(f.path) })
      ]);
      container.appendChild(badge);
    });
  }

  _clearAtQuery() {
    const input = $('#editor-chat-input');
    // Remove the @query from input
    const val = input.value;
    const atIdx = val.lastIndexOf('@');
    if (atIdx >= 0) {
      input.value = val.substring(0, atIdx);
    }
    input.focus();
  }

  _handleAtInput(value) {
    const atIdx = value.lastIndexOf('@');
    if (atIdx >= 0 && (atIdx === 0 || value[atIdx - 1] === ' ' || value[atIdx - 1] === '\n')) {
      const query = value.substring(atIdx + 1);
      // Only show if no space after query (still typing)
      if (!query.includes(' ') && !query.includes('\n')) {
        this.showFileRefPopup(query);
        return true;
      }
    }
    this.hideFileRefPopup();
    return false;
  }

  // ---- AI Change History ----
  _recordChange(path, oldContent, newContent) {
    // Trim history if we're in the middle of undo
    if (this.changeHistoryIdx >= 0 && this.changeHistoryIdx < this.changeHistory.length - 1) {
      this.changeHistory = this.changeHistory.slice(0, this.changeHistoryIdx + 1);
    }
    this.changeHistory.push({ path, oldContent, newContent, timestamp: Date.now() });
    this.changeHistoryIdx = this.changeHistory.length - 1;
    // Cap at 50 entries
    if (this.changeHistory.length > 50) {
      this.changeHistory.shift();
      this.changeHistoryIdx = Math.max(0, this.changeHistoryIdx - 1);
    }
  }

  // ---- Todo Panel ----
  _saveTodos() {
    localStorage.setItem('hoc-todo', JSON.stringify(this.todoItems));
    this._updateTodoBadge();
  }

  _updateTodoBadge() {
    const badge = $('#ert-todo .todo-badge');
    const count = this.todoItems.filter(t => !t.done).length;
    // Add or update badge in the Todo tab
    const tab = $('#ert-todo');
    if (!tab) return;
    let b = tab.querySelector('.todo-badge');
    if (!b) {
      b = document.createElement('span');
      b.className = 'todo-badge';
      tab.appendChild(b);
    }
    b.textContent = count > 0 ? count : '';
  }

  renderTodos() {
    const list = $('#todo-list');
    if (!list) return;
    if (!this.todoItems.length) {
      list.innerHTML = '<div class="todo-empty">No tasks yet.<br>Add tasks manually or let the AI create them.</div>';
      this._updateTodoBadge();
      return;
    }
    list.innerHTML = '';
    this.todoItems.forEach((item, i) => {
      const div = el('div', { class: 'todo-item' + (item.done ? ' done' : '') }, [
        el('button', {
          class: 'todo-checkbox', text: item.done ? ICONS.check(14) : '', onclick: () => {
            this.todoItems[i].done = !this.todoItems[i].done;
            this._saveTodos();
            this.renderTodos();
          }
        }),
        el('span', { class: 'todo-text', text: item.text }),
        el('button', {
          class: 'todo-delete', text: '', onclick: () => {
            this.todoItems.splice(i, 1);
            this._saveTodos();
            this.renderTodos();
          }
        })
      ]);
      list.appendChild(div);
    });
    this._updateTodoBadge();
  }

  addTodo(text) {
    if (!text || !text.trim()) return;
    this.todoItems.push({ text: text.trim(), done: false, created: Date.now() });
    this._saveTodos();
    this.renderTodos();
  }

  clearDoneTodos() {
    this.todoItems = this.todoItems.filter(t => !t.done);
    this._saveTodos();
    this.renderTodos();
  }

  _extractTodos(text) {
    // Extract __TODO__ markers from AI responses
    const re = /__TODO__(.+?)__TODO__/g;
    let match;
    while ((match = re.exec(text)) !== null) {
      const todoText = match[1].trim();
      if (todoText && !this.todoItems.some(t => t.text === todoText)) {
        this.addTodo(todoText);
      }
    }
    // Also extract markdown task lists: - [ ] task
    const taskRe = /^[-*]\s+\[\s*\]\s+(.+)$/gm;
    while ((match = taskRe.exec(text)) !== null) {
      const todoText = match[1].trim();
      if (todoText && !this.todoItems.some(t => t.text === todoText)) {
        this.addTodo(todoText);
      }
    }
  }

  // ---- Context Token Tracking ----
  _updateContextBar() {
    const bar = $('#editor-context-bar');
    const fill = $('#ctx-bar-fill');
    const value = $('#ctx-bar-value');
    if (!bar || !fill || !value) return;
    const pct = Math.min(100, Math.round((this.editorTokenCount / this.TOKEN_LIMIT) * 100));
    if (this.editorTokenCount > 500) {
      bar.classList.add('visible');
    } else {
      bar.classList.remove('visible');
      return;
    }
    fill.style.width = pct + '%';
    fill.classList.toggle('warning', pct > 75);
    value.textContent = pct + '%';
  }

  _estimateTokens(text) {
    // Rough estimate: ~4 chars per token
    return Math.ceil((text || '').length / 4);
  }

  // ---- Auto-save files from AI response ----
  async _autoSaveFiles(text) {
    if (!text) return;
    // Match code blocks with filename headers:
    // ```lang  filename.ext   or   ### filename.ext   then ```code```
    const fileBlocks = [];

    // Pattern 1: filename before or after ``` lang marker
    //   ```python filename.py  or  filename.py\n```python
    const regex = /(?:^|\n)(?:(?:#{1,4}\s+)?(?:`([^`\n]+\.[a-z0-9]+)`|(\S+\.[a-z0-9]+))\s*\n)?```\w*\s*(?:([^\n]+\.[a-z0-9]+)\s*)?\n([\s\S]*?)```/g;
    let m;
    while ((m = regex.exec(text)) !== null) {
      let filename = (m[1] || m[2] || m[3] || '').trim();
      if (filename.startsWith(':')) filename = filename.substring(1);
      const code = m[4];
      if (filename && code && filename.length < 100 && !filename.includes(' ')) {
        fileBlocks.push({ filename, code });
      }
    }

    // Pattern 2: standalone fenced block with explicit filename in first line comment
    // e.g.  ```python\n# filename.py\n...```
    if (!fileBlocks.length) {
      const regex2 = /```(\w+)\n(?:#|\/\/|--|;)\s*(\S+\.[a-z0-9]+)\n([\s\S]*?)```/g;
      while ((m = regex2.exec(text)) !== null) {
        const filename = m[2].trim();
        const code = m[3];
        if (filename && code && filename.length < 100 && !filename.includes(' ')) {
          fileBlocks.push({ filename, code });
        }
      }
    }

    if (!fileBlocks.length) return;

    // Save each file to workspace
    let firstFile = null;
    for (const fb of fileBlocks) {
      try {
        // Record old content for undo history
        let oldContent = '';
        try {
          const existingResp = await fetch('/workspace/file?path=' + encodeURIComponent(fb.filename));
          if (existingResp.ok) {
            const existingData = await existingResp.json();
            oldContent = existingData.content || '';
          }
        } catch (_) { /* new file, no old content */ }

        await fetch('/workspace/file', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: fb.filename, content: fb.code })
        });
        // Record in change history for undo/redo
        this._recordChange(fb.filename, oldContent, fb.code);
        this.addActivity(icon('save'), 'File created', fb.filename);
        if (!firstFile) firstFile = fb.filename;
      } catch (e) {
        this.addActivity(icon('x'), 'Save failed', fb.filename);
      }
    }

    // Refresh tree and open first file
    await this.loadTree();
    if (firstFile) {
      this.openFile(firstFile);
      toast(icon('save') + ' ' + fileBlocks.length + ' file' + (fileBlocks.length > 1 ? 's' : '') + ' saved to workspace');
    }
  }

  // ---- Diff Viewer ----
  showDiff(filename, oldContent, newContent) {
    const overlay = $('#editor-diff-overlay');
    $('#diff-title').textContent = '️ Changes — ' + filename;
    const body = $('#diff-body');
    body.innerHTML = '';
    const oldLines = oldContent.split('\n');
    const newLines = newContent.split('\n');
    const maxLen = Math.max(oldLines.length, newLines.length);
    // Simple line-by-line diff
    for (let i = 0; i < maxLen; i++) {
      const ol = i < oldLines.length ? oldLines[i] : undefined;
      const nl = i < newLines.length ? newLines[i] : undefined;
      if (ol === nl) {
        body.innerHTML += '<div class="diff-line context"><span class="diff-line-num">' + (i + 1) + '</span><span class="diff-line-content">' + escHtml(ol) + '</span></div>';
      } else {
        if (ol !== undefined) body.innerHTML += '<div class="diff-line removed"><span class="diff-line-num">' + (i + 1) + '</span><span class="diff-line-content">' + escHtml(ol) + '</span></div>';
        if (nl !== undefined) body.innerHTML += '<div class="diff-line added"><span class="diff-line-num">' + (i + 1) + '</span><span class="diff-line-content">' + escHtml(nl) + '</span></div>';
      }
    }
    // Store pending diff for Accept button
    this._pendingDiff = { filename, newContent };
    overlay.classList.add('open');
  }

  async acceptDiff() {
    if (!this._pendingDiff) return;
    const { filename, newContent } = this._pendingDiff;
    try {
      await fetch('/workspace/file', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: filename, content: newContent })
      });
      // Update open tab if the file is already open
      const tab = this.openTabs.find(t => t.path === filename);
      if (tab) {
        tab.content = newContent;
        tab.original = newContent;
        tab.modified = false;
        if (this.activeTab === filename) this.loadIntoEditor(tab);
        this.renderTabs();
      }
      toast(' Changes applied: ' + filename.split('/').pop());
      this.addActivity(ICONS.check(14), 'Diff accepted', filename);
    } catch (e) { toast(ICONS.x(14) + ' Apply error'); }
    this._pendingDiff = null;
    $('#editor-diff-overlay').classList.remove('open');
  }

  // ---- Find & Replace ----
  _updateSearchHighlight() {
    const hlLayer = document.querySelector('#code-search-hl');
    if (!hlLayer) return;
    const findInput = document.querySelector('#find-input');
    const textarea = document.querySelector('#code-textarea');
    if (!findInput || !textarea) return;

    const query = findInput.value;
    const text = textarea.value;

    if (!query || !$('#editor-find-bar') || !$('#editor-find-bar').classList.contains('open')) {
      hlLayer.innerHTML = '';
      return;
    }

    const escapeRegExp = (string) => string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(escapeRegExp(query), 'gi');

    let result = '';
    let lastIndex = 0;
    let match;
    while ((match = regex.exec(text)) !== null) {
      result += escHtml(text.substring(lastIndex, match.index));
      result += `<mark class="search-match">${escHtml(match[0])}</mark>`;
      lastIndex = regex.lastIndex;
    }
    result += escHtml(text.substring(lastIndex));

    hlLayer.innerHTML = result + '\n';
  }

  openFindReplace() {
    const bar = $('#editor-find-bar');
    if (!bar) return;
    bar.classList.add('open');
    const findInput = bar.querySelector('#find-input');
    if (findInput) {
      // Pre-populate with current selection if any
      const textarea = document.querySelector('#code-textarea');
      if (textarea) {
        const sel = textarea.value.substring(textarea.selectionStart, textarea.selectionEnd);
        if (sel && sel.length < 200) findInput.value = sel;
      }
      findInput.focus();
      findInput.select();
      this._updateSearchHighlight();
    }
  }

  closeFindReplace() {
    const bar = $('#editor-find-bar');
    if (bar) {
      bar.classList.remove('open');
      this._updateSearchHighlight();
    }
  }

  findNext() {
    const textarea = document.querySelector('#code-textarea');
    const findInput = document.querySelector('#find-input');
    if (!textarea || !findInput) return;
    const query = findInput.value;
    if (!query) return;
    const text = textarea.value;
    const startPos = textarea.selectionEnd || 0;
    let idx = text.indexOf(query, startPos);
    if (idx === -1) idx = text.indexOf(query, 0); // Wrap around
    if (idx === -1) { toast('Not found'); return; }
    textarea.selectionStart = idx;
    textarea.selectionEnd = idx + query.length;
    textarea.focus();
    // Scroll into view
    const lineNum = text.substring(0, idx).split('\n').length;
    const lineHeight = 20.8;
    textarea.scrollTop = Math.max(0, (lineNum - 5) * lineHeight);
  }

  replaceNext() {
    const textarea = document.querySelector('#code-textarea');
    const findInput = document.querySelector('#find-input');
    const replaceInput = document.querySelector('#replace-input');
    if (!textarea || !findInput || !replaceInput) return;
    const query = findInput.value;
    const replacement = replaceInput.value;
    if (!query) return;
    // If current selection matches, replace it
    const selText = textarea.value.substring(textarea.selectionStart, textarea.selectionEnd);
    if (selText === query) {
      const start = textarea.selectionStart;
      textarea.value = textarea.value.substring(0, start) + replacement + textarea.value.substring(start + query.length);
      textarea.selectionStart = start;
      textarea.selectionEnd = start + replacement.length;
      textarea.dispatchEvent(new Event('input'));
    }
    this.findNext();
  }

  replaceAll() {
    const textarea = document.querySelector('#code-textarea');
    const findInput = document.querySelector('#find-input');
    const replaceInput = document.querySelector('#replace-input');
    if (!textarea || !findInput || !replaceInput) return;
    const query = findInput.value;
    const replacement = replaceInput.value;
    if (!query) return;
    const count = textarea.value.split(query).length - 1;
    if (count === 0) { toast('Not found'); return; }
    textarea.value = textarea.value.split(query).join(replacement);
    textarea.dispatchEvent(new Event('input'));
    toast(`Replaced ${count} occurrence${count > 1 ? 's' : ''}`);
  }

  // ---- Context ----
  async loadContext() {
    try {
      const r = await fetch('/workspace/context');
      const d = await r.json();
      $('#context-textarea').value = d.content || '';
    } catch (e) { }
    $('#context-overlay').classList.add('open');
  }

  async saveContext() {
    const content = $('#context-textarea').value;
    try {
      await fetch('/workspace/context', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content }) });
      toast(ICONS.download(14) + ' Context saved');
      this.addActivity('', 'Project context updated', '');
    } catch (e) { toast(ICONS.x(14) + ' Save error'); }
    $('#context-overlay').classList.remove('open');
  }

  // ---- Git Clone ----
  openGitClone() {
    $('#git-clone-url').value = '';
    $('#git-clone-folder').value = '';
    $('#git-clone-branch').value = '';
    $('#git-clone-username').value = '';
    $('#git-clone-token').value = '';
    const authSection = $('#git-clone-auth-section');
    if (authSection) authSection.removeAttribute('open');
    $('#git-clone-progress').classList.remove('active');
    $('#git-clone-submit').disabled = false;
    $('#git-clone-overlay').classList.add('open');
  }

  async doGitClone() {
    const url = $('#git-clone-url').value.trim();
    if (!url) { toast(ICONS.x(14) + ' Enter a repository URL'); return; }
    const folder = $('#git-clone-folder').value.trim();
    const branch = $('#git-clone-branch').value.trim();
    const username = ($('#git-clone-username') || {}).value?.trim() || '';
    const token = ($('#git-clone-token') || {}).value?.trim() || '';

    $('#git-clone-submit').disabled = true;
    const progress = $('#git-clone-progress');
    progress.classList.add('active');
    $('#git-clone-progress-text').textContent = 'Cloning repository...';
    $('#git-clone-progress-fill').style.width = '30%';

    this.addActivity('', 'Cloning repository', url);

    try {
      const payload = { url, folder, branch };
      if (username) payload.username = username;
      if (token) payload.token = token;

      const r = await fetch('/workspace/git-clone', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const d = await r.json();
      if (d.status === 'ok') {
        $('#git-clone-progress-fill').style.width = '100%';
        $('#git-clone-progress-text').textContent = ' ' + d.message;
        toast(ICONS.check(14) + ' Repository cloned');
        this.addActivity('', 'Repository cloned', url);
        // Save credentials for push/pull during this session
        if (token) {
          this._gitCredentials = { username, token };
        }
        await this.loadTree();
        setTimeout(() => $('#git-clone-overlay').classList.remove('open'), 1200);
      } else {
        $('#git-clone-progress-text').textContent = ' ' + d.error;
        $('#git-clone-progress-fill').style.width = '0%';
        toast(ICONS.x(14) + ' Clone failed');
        this.addActivity('', 'Clone failed', d.error);
        $('#git-clone-submit').disabled = false;
      }
    } catch (e) {
      $('#git-clone-progress-text').textContent = ' ' + e.message;
      toast(ICONS.x(14) + ' Clone error');
      $('#git-clone-submit').disabled = false;
    }
  }

  // ---- Terminal Help ----
  _terminalCommands() {
    return [
      {
        section: 'Files & Navigation', cmds: [
          { key: 'ls', desc: 'List files in current directory' },
          { key: 'ls -la', desc: 'List all files with details' },
          { key: 'cat <file>', desc: 'Display file contents' },
          { key: 'head -20 <file>', desc: 'Show first 20 lines' },
          { key: 'tail -20 <file>', desc: 'Show last 20 lines' },
          { key: 'find . -name "*.py"', desc: 'Find Python files' },
          { key: 'wc -l <file>', desc: 'Count lines in file' },
          { key: 'tree', desc: 'Show directory tree' },
        ]
      },
      {
        section: 'Git', cmds: [
          { key: 'git status', desc: 'Show working tree status' },
          { key: 'git log --oneline -10', desc: 'Recent commit history' },
          { key: 'git diff', desc: 'Show unstaged changes' },
          { key: 'git branch -a', desc: 'List all branches' },
          { key: 'git add .', desc: 'Stage all changes' },
          { key: 'git commit -m "msg"', desc: 'Commit with message' },
          { key: 'git pull', desc: 'Pull latest changes' },
          { key: 'git push', desc: 'Push commits to remote' },
        ]
      },
      {
        section: 'Python', cmds: [
          { key: 'python <file>', desc: 'Run a Python script' },
          { key: 'python -m pytest', desc: 'Run tests with pytest' },
          { key: 'pip install <pkg>', desc: 'Install a package' },
          { key: 'pip list', desc: 'List installed packages' },
          { key: 'python -m venv venv', desc: 'Create virtual env' },
        ]
      },
      {
        section: 'System', cmds: [
          { key: 'grep -r "text" .', desc: 'Search text in files' },
          { key: 'du -sh *', desc: 'Disk usage by folder' },
          { key: 'df -h', desc: 'Disk space overview' },
          { key: 'uname -a', desc: 'System information' },
          { key: 'whoami', desc: 'Current user' },
          { key: 'pwd', desc: 'Current directory' },
        ]
      }
    ];
  }

  showTerminalHelp() {
    const popup = $('#term-help-popup');
    const cmds = this._terminalCommands();
    popup.innerHTML = '<div class="term-help-title">⌨️ Terminal Commands</div>';
    cmds.forEach(section => {
      popup.innerHTML += `<div class="term-help-section">
        <div class="term-help-section-title">${escHtml(section.section)}</div>
        ${section.cmds.map(c => `<div class="term-help-cmd" data-cmd="${escHtml(c.key)}">
          <span class="term-help-cmd-key">${escHtml(c.key)}</span>
          <span class="term-help-cmd-desc">${escHtml(c.desc)}</span>
        </div>`).join('')}
      </div>`;
    });
    popup.classList.toggle('open');
    // Bind clicks
    popup.querySelectorAll('.term-help-cmd').forEach(el2 => {
      el2.addEventListener('click', () => {
        $('#editor-terminal-input').value = el2.dataset.cmd;
        $('#editor-terminal-input').focus();
        popup.classList.remove('open');
      });
    });
  }

  // ---- Command History ----
  initCommandHistory() {
    this._cmdHistory = [];
    this._cmdIdx = -1;
  }

  pushHistory(cmd) {
    if (!this._cmdHistory) this.initCommandHistory();
    if (cmd.trim() && (this._cmdHistory.length === 0 || this._cmdHistory[this._cmdHistory.length - 1] !== cmd)) {
      this._cmdHistory.push(cmd);
    }
    this._cmdIdx = this._cmdHistory.length;
  }

  historyUp() {
    if (!this._cmdHistory || !this._cmdHistory.length) return '';
    if (this._cmdIdx > 0) this._cmdIdx--;
    return this._cmdHistory[this._cmdIdx] || '';
  }

  historyDown() {
    if (!this._cmdHistory || !this._cmdHistory.length) return '';
    if (this._cmdIdx < this._cmdHistory.length - 1) this._cmdIdx++;
    else { this._cmdIdx = this._cmdHistory.length; return ''; }
    return this._cmdHistory[this._cmdIdx] || '';
  }

  // ---- Search ----
  async searchFiles(query) {
    if (!query.trim()) return;
    this.addActivity('', 'Searching files', query);
    try {
      const r = await fetch('/workspace/search?q=' + encodeURIComponent(query));
      const d = await r.json();
      const results = d.results || [];
      const info = $('#editor-search-info');
      info.textContent = results.length + ' result' + (results.length !== 1 ? 's' : '') + (d.truncated ? ' (truncated)' : '');

      // Show results in activity feed
      if (!results.length) {
        this.addActivity('', 'No results', 'for "' + query + '"');
        return;
      }
      this.addActivity('', results.length + ' results found', 'for "' + query + '"');

      // Group by file
      const byFile = {};
      results.forEach(r2 => {
        if (!byFile[r2.path]) byFile[r2.path] = [];
        byFile[r2.path].push(r2);
      });
      Object.entries(byFile).forEach(([path, hits]) => {
        const detail = hits.slice(0, 3).map(h => `L${h.line}: ${h.text.substring(0, 80)}`).join('\n');
        this.addActivity('', path + ' (' + hits.length + ' hits)', detail);
      });

      // Open first result file
      if (results.length > 0) {
        this.openFile(results[0].path);
      }
    } catch (e) { toast(ICONS.x(14) + ' Search error'); }
  }

  // ---- Upload Files ----
  async uploadFiles(files) {
    for (const file of files) {
      const fd = new FormData();
      fd.append('file', file);
      try {
        const r = await fetch('/workspace/upload', { method: 'POST', body: fd });
        const d = await r.json();
        if (d.status === 'ok') {
          this.addActivity('', 'File uploaded', d.path + ' (' + (d.size / 1024).toFixed(1) + ' KB)');
          toast(' Uploaded: ' + file.name);
        }
      } catch (e) { toast(' Upload error: ' + file.name); }
    }
    await this.loadTree();
  }

  // ---- Git Panel ----
  async loadGitStatus() {
    try {
      const r = await fetch('/workspace/git-status');
      const d = await r.json();
      if (!d.has_repo) {
        $('#git-no-repo').style.display = '';
        $('#git-panel-content').style.display = 'none';
        return;
      }
      $('#git-no-repo').style.display = 'none';
      $('#git-panel-content').style.display = 'flex';

      $('#git-branch-name').textContent = d.branch;
      const ae = $('#git-ahead'), be = $('#git-behind');
      if (d.ahead > 0) { ae.textContent = '↑' + d.ahead; ae.style.display = ''; } else ae.style.display = 'none';
      if (d.behind > 0) { be.textContent = '↓' + d.behind; be.style.display = ''; } else be.style.display = 'none';
      const ru = $('#git-remote-url');
      if (d.remote_url) { ru.textContent = d.remote_url; ru.style.display = ''; } else ru.style.display = 'none';

      // Split staged/unstaged
      const staged = d.files.filter(f => f.staged);
      const unstaged = d.files.filter(f => !f.staged);
      this._renderGitFileList($('#git-staged-list'), staged, true);
      this._renderGitFileList($('#git-unstaged-list'), unstaged, false);
    } catch (e) { toast(ICONS.x(14) + ' Git status error'); }
  }

  _renderGitFileList(container, files, isStaged) {
    container.innerHTML = '';
    if (!files.length && isStaged) return;

    const title = isStaged ? 'Staged Changes' : 'Changes';
    const icon = isStaged ? ICONS.check(14) : '●';
    container.innerHTML += `<div class="git-section-title">${icon} ${title}<span class="git-section-count">${files.length}</span></div>`;

    files.forEach(f => {
      const name = f.path.split('/').pop();
      const dir = f.path.includes('/') ? f.path.substring(0, f.path.lastIndexOf('/')) : '';
      const statusChar = f.index || f.working || (f.status === 'added' ? '?' : 'M');
      const item = el('div', { class: 'git-file-item' }, [
        el('span', { class: 'git-file-status ' + statusChar, text: statusChar }),
        el('span', { class: 'git-file-name', text: name }),
        dir ? el('span', { class: 'git-file-dir', text: dir }) : null,
        el('div', { class: 'git-file-actions' }, [
          isStaged
            ? el('button', { class: 'git-file-action-btn', text: '−', title: 'Unstage', onclick: e => { e.stopPropagation(); this._gitReset(f.path); } })
            : el('button', { class: 'git-file-action-btn', text: '+', title: 'Stage', onclick: e => { e.stopPropagation(); this.gitAdd([f.path]); } }),
          el('button', { class: 'git-file-action-btn', text: '⇄', title: 'View diff', onclick: e => { e.stopPropagation(); this._viewGitDiff(f.path, isStaged); } })
        ])
      ]);
      item.addEventListener('click', () => this.openFile(f.path));
      container.appendChild(item);
    });
  }

  async gitAdd(paths) {
    try {
      await fetch('/workspace/git-add', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paths }) });
      this.addActivity('＋', 'Staged', paths.join(', '));
      this.loadGitStatus();
    } catch (e) { toast(ICONS.x(14) + ' Stage error'); }
  }

  async gitStageAll() {
    try {
      await fetch('/workspace/git-add', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ all: true }) });
      this.addActivity('＋', 'Staged all changes', '');
      toast(ICONS.check(14) + ' All changes staged');
      this.loadGitStatus();
    } catch (e) { toast(ICONS.x(14) + ' Stage error'); }
  }

  async _gitReset(path) {
    try {
      await fetch('/local/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command: 'git reset HEAD -- ' + path }) });
      this.loadGitStatus();
    } catch (e) { }
  }

  async _viewGitDiff(path, staged) {
    try {
      const r = await fetch('/workspace/git-diff?path=' + encodeURIComponent(path) + '&staged=' + (staged ? 'true' : 'false'));
      const d = await r.json();
      if (d.diff) {
        // Show in diff viewer
        const overlay = $('#editor-diff-overlay');
        $('#diff-title').textContent = '️ Diff — ' + path;
        const body = $('#diff-body');
        body.innerHTML = '';
        d.diff.split('\n').forEach(line => {
          let cls = 'context';
          if (line.startsWith('+') && !line.startsWith('+++')) cls = 'added';
          else if (line.startsWith('-') && !line.startsWith('---')) cls = 'removed';
          else if (line.startsWith('@@')) cls = 'context';
          body.innerHTML += '<div class="diff-line ' + cls + '"><span class="diff-line-content">' + escHtml(line) + '</span></div>';
        });
        overlay.classList.add('open');
      } else {
        toast('No changes to show');
      }
    } catch (e) { toast(ICONS.x(14) + ' Diff error'); }
  }

  async gitCommit(andPush) {
    const msg = $('#git-commit-msg').value.trim();
    if (!msg) { toast(ICONS.x(14) + ' Enter a commit message'); return; }
    try {
      const r = await fetch('/workspace/git-commit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: msg }) });
      const d = await r.json();
      if (d.status === 'ok') {
        toast(ICONS.check(14) + ' Committed');
        this.addActivity(ICONS.check(14), 'Committed', msg);
        $('#git-commit-msg').value = '';
        if (andPush) await this.gitPush();
        this.loadGitStatus();
        this.loadGitLog();
      } else {
        toast(' ' + d.error);
      }
    } catch (e) { toast(ICONS.x(14) + ' Commit error'); }
  }

  async gitPush() {
    this.addActivity('⬆', 'Pushing...', '');
    try {
      const payload = {};
      // Inject saved credentials if available
      if (this._gitCredentials) {
        if (this._gitCredentials.username) payload.username = this._gitCredentials.username;
        if (this._gitCredentials.token) payload.token = this._gitCredentials.token;
      }
      const r = await fetch('/workspace/git-push', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json();
      if (d.status === 'ok') {
        toast(ICONS.check(14) + ' Pushed to remote');
        this.addActivity('', 'Push successful', d.output || '');
      } else {
        toast(' Push failed: ' + d.error);
        this.addActivity('', 'Push failed', d.error);
      }
      this.loadGitStatus();
    } catch (e) { toast(ICONS.x(14) + ' Push error'); }
  }

  async gitPull() {
    this.addActivity('⬇', 'Pulling...', '');
    try {
      const payload = {};
      // Inject saved credentials if available
      if (this._gitCredentials) {
        if (this._gitCredentials.username) payload.username = this._gitCredentials.username;
        if (this._gitCredentials.token) payload.token = this._gitCredentials.token;
      }
      const r = await fetch('/workspace/git-pull', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json();
      if (d.status === 'ok') {
        toast(ICONS.check(14) + ' Pulled from remote');
        this.addActivity('', 'Pull successful', d.output || '');
        this.loadTree();
      } else {
        toast(' Pull failed: ' + d.error);
        this.addActivity('', 'Pull failed', d.error);
      }
      this.loadGitStatus();
    } catch (e) { toast(ICONS.x(14) + ' Pull error'); }
  }

  // ---- Git Graph (VS Code-style) ----
  async loadGitLog() {
    try {
      const r = await fetch('/workspace/git-log?limit=80');
      const d = await r.json();
      this.renderGraph(d.commits || [], d.branches || []);
    } catch (e) { console.error('Git log error', e); }
  }

  renderGraph(commits, branches) {
    const container = $('#git-graph-container');
    if (!commits.length) {
      container.innerHTML = '<div class="git-no-repo" style="padding:40px"><p>No commits yet</p></div>';
      return;
    }

    const ROW_H = 32, LANE_W = 20, DOT_R = 5, MAX_LANES = 6;
    const COLORS = ['#7c5cfc', '#2ecc71', '#e74c3c', '#f1c40f', '#3498db', '#e67e22', '#1abc9c', '#9b59b6'];

    // Assign lanes to commits
    const hashIdx = {};
    commits.forEach((c, i) => hashIdx[c.hash] = i);
    const lanes = [];
    const commitLane = [];

    for (let i = 0; i < commits.length; i++) {
      const c = commits[i];
      let myLane = lanes.indexOf(c.hash);
      if (myLane === -1) {
        myLane = lanes.indexOf(null);
        if (myLane === -1) { myLane = lanes.length; lanes.push(null); }
        lanes[myLane] = c.hash;
      }
      commitLane[i] = { lane: myLane, merges: [] };
      if (c.parents.length > 0) lanes[myLane] = c.parents[0];
      else lanes[myLane] = null;
      for (let p = 1; p < c.parents.length; p++) {
        const ph = c.parents[p];
        let pLane = lanes.indexOf(ph);
        if (pLane === -1) {
          pLane = lanes.indexOf(null);
          if (pLane === -1) { pLane = lanes.length; lanes.push(null); }
          lanes[pLane] = ph;
        }
        commitLane[i].merges.push(pLane);
      }
      for (let l = 0; l < lanes.length; l++) {
        if (lanes[l] && !commits.slice(i + 1).some(fc => fc.hash === lanes[l])) {
          if (!c.parents.includes(lanes[l])) lanes[l] = null;
        }
      }
    }

    const maxLane = Math.min(Math.max(...commitLane.map(c => c.lane), ...commitLane.flatMap(c => c.merges), 0) + 1, MAX_LANES);
    const svgW = (maxLane + 1) * LANE_W + 10;

    // Build graph
    let html = '<div class="git-graph-list">';

    for (let i = 0; i < commits.length; i++) {
      const c = commits[i];
      const cl = commitLane[i];
      const lane = Math.min(cl.lane, MAX_LANES - 1);
      const color = COLORS[lane % COLORS.length];
      const isHead = c.refs.some(r => r.type === 'head');

      const cx = lane * LANE_W + LANE_W / 2 + 4;
      const cy = ROW_H / 2;
      let svg = `<svg width="${svgW}" height="${ROW_H}" viewBox="0 0 ${svgW} ${ROW_H}">`;

      // Active lanes
      const activeLanesHere = new Set();
      if (i < commits.length - 1) activeLanesHere.add(commitLane[i + 1].lane);
      activeLanesHere.add(lane);
      cl.merges.forEach(ml => activeLanesHere.add(ml));

      // Draw lane lines
      activeLanesHere.forEach(l => {
        if (l >= MAX_LANES) return;
        const lx = l * LANE_W + LANE_W / 2 + 4;
        const lcolor = COLORS[l % COLORS.length];
        svg += `<line x1="${lx}" y1="0" x2="${lx}" y2="${ROW_H}" stroke="${lcolor}" stroke-width="2" opacity="0.35"/>`;
      });

      // Merge lines (curved)
      cl.merges.forEach(ml => {
        if (ml >= MAX_LANES) return;
        const mx = Math.min(ml, MAX_LANES - 1) * LANE_W + LANE_W / 2 + 4;
        const mcolor = COLORS[ml % COLORS.length];
        svg += `<path d="M${cx},${cy} C${cx},${ROW_H} ${mx},${cy} ${mx},${ROW_H}" stroke="${mcolor}" stroke-width="2" fill="none" opacity="0.6"/>`;
      });

      // Commit dot
      svg += `<circle cx="${cx}" cy="${cy}" r="${DOT_R}" fill="${color}"/>`;
      if (isHead) {
        svg += `<circle cx="${cx}" cy="${cy}" r="${DOT_R + 3}" fill="none" stroke="${color}" stroke-width="1.5" opacity="0.4"/>`;
      }
      svg += '</svg>';

      // Refs badges
      let refHtml = '';
      c.refs.forEach(ref => {
        refHtml += `<span class="git-ref-badge ${ref.type}">${escHtml(ref.name)}</span>`;
      });

      // Relative date
      const dateStr = this._relativeDate(c.date);

      html += `<div class="git-graph-item${isHead ? ' head' : ''}" data-hash="${c.hash}" data-short="${c.short}">
        <div class="git-graph-main">
          <div class="git-graph-lane">${svg}</div>
          <div class="git-graph-info">
            <div class="git-graph-msg">${refHtml}<span class="git-graph-subject">${escHtml(c.subject)}</span></div>
            <div class="git-graph-meta">
              <span class="git-graph-author">${escHtml(c.author)}</span>
              <span class="git-graph-sep">·</span>
              <span class="git-graph-date">${dateStr}</span>
              <span class="git-graph-sep">·</span>
              <span class="git-graph-hash">${c.short}</span>
            </div>
          </div>
        </div>
        <div class="git-graph-detail" id="git-detail-${c.short}" style="display:none"></div>
      </div>`;
    }

    html += '</div>';
    container.innerHTML = html;

    // Click handlers
    container.querySelectorAll('.git-graph-item').forEach(item => {
      item.querySelector('.git-graph-main').addEventListener('click', () => {
        const hash = item.dataset.hash;
        const detail = item.querySelector('.git-graph-detail');
        if (detail.style.display !== 'none') {
          detail.style.display = 'none';
          return;
        }
        // Load commit details
        detail.innerHTML = '<div style="padding:8px;color:var(--text-muted);font-size:11px;">Loading...</div>';
        detail.style.display = 'block';
        fetch('/workspace/git-show?commit=' + hash)
          .then(r => r.json())
          .then(d => {
            if (d.error) { detail.innerHTML = `<div style="padding:8px;color:var(--red);font-size:11px;">${escHtml(d.error)}</div>`; return; }
            let fhtml = '<div class="git-detail-files">';
            if (d.summary) fhtml += `<div class="git-detail-summary">${escHtml(d.summary)}</div>`;
            (d.files || []).forEach(f => {
              const total = f.additions + f.deletions || 1;
              const addPct = Math.round((f.additions / total) * 100);
              fhtml += `<div class="git-detail-file git-detail-file-clickable" data-fname="${escHtml(f.name)}" data-hash="${hash}">
                <span class="git-detail-fname">${escHtml(f.name)}</span>
                <span class="git-detail-stat">
                  <span class="git-detail-changes">${f.changes}</span>
                  <span class="git-detail-bar">
                    <span class="git-detail-add" style="width:${addPct}%"></span>
                    <span class="git-detail-del" style="width:${100 - addPct}%"></span>
                  </span>
                </span>
              </div>`;
            });
            if (!d.files || !d.files.length) fhtml += '<div style="padding:4px 8px;color:var(--text-muted);font-size:11px;">No file changes</div>';
            fhtml += '</div>';
            detail.innerHTML = fhtml;
            // Collect file list for navigation
            const commitFiles = (d.files || []).map(f => f.name);
            // Bind click on file rows
            detail.querySelectorAll('.git-detail-file-clickable').forEach(row => {
              row.addEventListener('click', e => {
                e.stopPropagation();
                this.openFileDiff(row.dataset.hash, row.dataset.fname, commitFiles);
              });
            });
          })
          .catch(() => { detail.innerHTML = '<div style="padding:8px;color:var(--red);font-size:11px;">Failed to load</div>'; });
      });
    });
  }

  // ---- Side-by-side Diff Viewer ----
  async openFileDiff(commit, filePath, commitFiles) {
    const area = $('#editor-code-area');
    // Store commit files for navigation
    this._diffCommitFiles = commitFiles || this._diffCommitFiles || [];
    this._diffCommit = commit;
    if (!area) return;

    // Show loading
    area.innerHTML = `<div class="diff-loading"><div style="text-align:center;padding:40px;color:var(--text-muted);">Loading diff for <strong>${escHtml(filePath)}</strong>...</div></div>`;

    try {
      const res = await fetch(`/workspace/git-file-diff?commit=${commit}&path=${encodeURIComponent(filePath)}`);
      const d = await res.json();
      if (d.error) {
        area.innerHTML = `<div style="padding:40px;text-align:center;color:var(--red);">${escHtml(d.error)}</div>`;
        return;
      }

      // Detect language for highlighting
      const lang = this._extToLang(filePath);

      // Compute aligned diff rows using the unified diff hunks
      const beforeLines = (d.before || '').split('\n');
      const afterLines = (d.after || '').split('\n');
      const diffRows = this._computeAlignedDiff(beforeLines, afterLines, d.diff || '');

      // Count changes
      const stats = { added: 0, removed: 0, modified: 0 };
      diffRows.forEach(r => {
        if (r.type === 'add') stats.added++;
        else if (r.type === 'del') stats.removed++;
        else if (r.type === 'mod') stats.modified++;
      });

      // File navigation context
      const fileList = this._diffCommitFiles;
      const fileIdx = fileList.indexOf(filePath);
      const hasPrevFile = fileIdx > 0;
      const hasNextFile = fileIdx >= 0 && fileIdx < fileList.length - 1;
      const fileCounter = fileList.length > 1 ? `<span class="diff-file-counter">${fileIdx + 1} / ${fileList.length}</span>` : '';

      let html = `
        <div class="diff-viewer">
          <div class="diff-header">
            <div class="diff-header-left">
              <button class="diff-file-nav-btn" id="diff-file-prev" title="Previous file" ${hasPrevFile ? '' : 'disabled'}>◄</button>
              <div class="diff-header-info">
                ${icon('gitCommit')} <strong>${escHtml(filePath)}</strong>
                <span class="diff-commit-hash">${commit.substring(0, 8)}</span>
                ${fileCounter}
                ${d.is_new ? '<span class="git-ref-badge head">NEW</span>' : ''}
                ${d.is_deleted ? '<span class="git-ref-badge" style="background:rgba(244,63,94,.2);color:var(--red);border:1px solid rgba(244,63,94,.3);">DELETED</span>' : ''}
              </div>
              <button class="diff-file-nav-btn" id="diff-file-next" title="Next file" ${hasNextFile ? '' : 'disabled'}>►</button>
            </div>
            <div class="diff-header-actions">
              <div class="diff-stats-bar">
                ${stats.added ? `<span class="diff-stat-badge diff-stat-add">+${stats.added}</span>` : ''}
                ${stats.removed ? `<span class="diff-stat-badge diff-stat-del">−${stats.removed}</span>` : ''}
                ${stats.modified ? `<span class="diff-stat-badge diff-stat-mod">→${stats.modified}</span>` : ''}
              </div>
              <button class="diff-nav-btn" id="diff-nav-prev" title="Previous change (↑)">▲</button>
              <button class="diff-nav-btn" id="diff-nav-next" title="Next change (↓)">▼</button>
              <button class="diff-close-btn" id="diff-viewer-close">${icon('x')} Close</button>
            </div>
          </div>
          <div class="diff-panels">
            <div class="diff-panel diff-panel-before">
              <div class="diff-panel-header">Before (${commit.substring(0, 8)}~1)</div>
              <div class="diff-panel-content" id="diff-panel-left">
                <table class="diff-table"><tbody>`;

      // Track which rows are change boundaries for navigation
      let changeChunkId = 0;
      let lastWasChange = false;

      // Render LEFT panel (before)
      diffRows.forEach((row, idx) => {
        const isChange = row.type !== 'ctx';
        // Insert chunk separator for non-contiguous changes
        if (isChange && !lastWasChange && idx > 0) {
          changeChunkId++;
        }
        lastWasChange = isChange;

        if (row.type === 'ctx') {
          // Context (unchanged) line
          html += `<tr class="diff-line diff-line-ctx">
            <td class="diff-ln">${row.leftNum || ''}</td>
            <td class="diff-gutter"></td>
            <td class="diff-code">${this._highlightLine(row.leftText, lang)}</td>
          </tr>`;
        } else if (row.type === 'del' || row.type === 'mod') {
          // Removed or modified line (left side)
          const marker = row.type === 'mod' ? '→' : '−';
          const cls = row.type === 'mod' ? 'diff-line-modified' : 'diff-line-removed';
          const codeHtml = row.type === 'mod' && row.rightText !== undefined
            ? this._highlightWordDiff(row.leftText || '', row.rightText || '', 'del', lang)
            : this._highlightLine(row.leftText, lang);
          html += `<tr class="diff-line ${cls}" data-chunk="${changeChunkId}">
            <td class="diff-ln">${row.leftNum || ''}</td>
            <td class="diff-gutter"><span class="diff-marker">${marker}</span></td>
            <td class="diff-code">${codeHtml}</td>
          </tr>`;
        } else if (row.type === 'add') {
          // Padding on left for added lines
          html += `<tr class="diff-line diff-line-pad" data-chunk="${changeChunkId}">
            <td class="diff-ln"></td>
            <td class="diff-gutter"><span class="diff-marker diff-marker-pad">+</span></td>
            <td class="diff-code diff-code-pad"></td>
          </tr>`;
        }
      });

      html += `</tbody></table></div></div>
            <div class="diff-panel diff-panel-after">
              <div class="diff-panel-header">After (${commit.substring(0, 8)})</div>
              <div class="diff-panel-content" id="diff-panel-right">
                <table class="diff-table"><tbody>`;

      // Render RIGHT panel (after)
      changeChunkId = 0;
      lastWasChange = false;
      diffRows.forEach((row, idx) => {
        const isChange = row.type !== 'ctx';
        if (isChange && !lastWasChange && idx > 0) {
          changeChunkId++;
        }
        lastWasChange = isChange;

        if (row.type === 'ctx') {
          html += `<tr class="diff-line diff-line-ctx">
            <td class="diff-ln">${row.rightNum || ''}</td>
            <td class="diff-gutter"></td>
            <td class="diff-code">${this._highlightLine(row.rightText, lang)}</td>
          </tr>`;
        } else if (row.type === 'add' || row.type === 'mod') {
          const marker = row.type === 'mod' ? '→' : '+';
          const cls = row.type === 'mod' ? 'diff-line-modified' : 'diff-line-added';
          const codeHtml = row.type === 'mod' && row.leftText !== undefined
            ? this._highlightWordDiff(row.leftText || '', row.rightText || '', 'add', lang)
            : this._highlightLine(row.rightText, lang);
          html += `<tr class="diff-line ${cls}" data-chunk="${changeChunkId}">
            <td class="diff-ln">${row.rightNum || ''}</td>
            <td class="diff-gutter"><span class="diff-marker">${marker}</span></td>
            <td class="diff-code">${codeHtml}</td>
          </tr>`;
        } else if (row.type === 'del') {
          // Padding on right for deleted lines
          html += `<tr class="diff-line diff-line-pad" data-chunk="${changeChunkId}">
            <td class="diff-ln"></td>
            <td class="diff-gutter"><span class="diff-marker diff-marker-pad">−</span></td>
            <td class="diff-code diff-code-pad"></td>
          </tr>`;
        }
      });

      html += `</tbody></table></div></div>
          </div>
        </div>`;

      area.innerHTML = html;

      // Close button
      const closeBtn = area.querySelector('#diff-viewer-close');
      if (closeBtn) {
        closeBtn.addEventListener('click', () => {
          const tab = this.openTabs.find(t => t.path === this.activeTab);
          if (tab) this.loadIntoEditor(tab);
          else this.showWelcome();
        });
      }

      // File navigation buttons (◄ ►)
      const filePrevBtn = area.querySelector('#diff-file-prev');
      const fileNextBtn = area.querySelector('#diff-file-next');
      if (filePrevBtn) {
        filePrevBtn.addEventListener('click', () => {
          const idx = this._diffCommitFiles.indexOf(filePath);
          if (idx > 0) this.openFileDiff(commit, this._diffCommitFiles[idx - 1]);
        });
      }
      if (fileNextBtn) {
        fileNextBtn.addEventListener('click', () => {
          const idx = this._diffCommitFiles.indexOf(filePath);
          if (idx >= 0 && idx < this._diffCommitFiles.length - 1) this.openFileDiff(commit, this._diffCommitFiles[idx + 1]);
        });
      }

      // Sync scroll between panels
      const panels = area.querySelectorAll('.diff-panel-content');
      if (panels.length === 2) {
        let syncing = false;
        panels.forEach((panel, idx) => {
          panel.addEventListener('scroll', () => {
            if (syncing) return;
            syncing = true;
            const other = panels[1 - idx];
            other.scrollTop = panel.scrollTop;
            other.scrollLeft = panel.scrollLeft;
            requestAnimationFrame(() => { syncing = false; });
          });
        });
      }

      // Navigation between change chunks
      let currentChunk = -1;
      const maxChunk = changeChunkId;
      const scrollToChunk = (chunkId) => {
        const targets = area.querySelectorAll(`[data-chunk="${chunkId}"]`);
        if (targets.length > 0) {
          // Scroll both panels to the first row of this chunk
          const leftTarget = area.querySelector(`#diff-panel-left [data-chunk="${chunkId}"]`);
          const rightTarget = area.querySelector(`#diff-panel-right [data-chunk="${chunkId}"]`);
          if (leftTarget) {
            const container = leftTarget.closest('.diff-panel-content');
            if (container) {
              container.scrollTop = leftTarget.offsetTop - container.offsetTop - 60;
            }
          }
          if (rightTarget) {
            const container = rightTarget.closest('.diff-panel-content');
            if (container) {
              container.scrollTop = rightTarget.offsetTop - container.offsetTop - 60;
            }
          }
          // Highlight active chunk briefly
          targets.forEach(t => {
            t.classList.add('diff-chunk-active');
            setTimeout(() => t.classList.remove('diff-chunk-active'), 1200);
          });
        }
      };
      const prevBtn = area.querySelector('#diff-nav-prev');
      const nextBtn = area.querySelector('#diff-nav-next');
      if (nextBtn) {
        nextBtn.addEventListener('click', () => {
          if (currentChunk < maxChunk) { currentChunk++; scrollToChunk(currentChunk); }
        });
      }
      if (prevBtn) {
        prevBtn.addEventListener('click', () => {
          if (currentChunk > 0) { currentChunk--; scrollToChunk(currentChunk); }
        });
      }

      // Auto-scroll to first change
      if (maxChunk >= 0) {
        setTimeout(() => { currentChunk = 0; scrollToChunk(0); }, 150);
      }

    } catch (e) {
      area.innerHTML = `<div style="padding:40px;text-align:center;color:var(--red);">Error: ${escHtml(e.message)}</div>`;
    }
  }

  /**
   * Compute aligned diff rows from before/after lines + unified diff.
   * Returns an array of { type: 'ctx'|'add'|'del'|'mod', leftNum, rightNum, leftText, rightText }
   */
  _computeAlignedDiff(beforeLines, afterLines, unifiedDiff) {
    const rows = [];
    if (!unifiedDiff) {
      // No diff — show all as context
      const max = Math.max(beforeLines.length, afterLines.length);
      for (let i = 0; i < max; i++) {
        rows.push({
          type: 'ctx',
          leftNum: i < beforeLines.length ? i + 1 : null,
          rightNum: i < afterLines.length ? i + 1 : null,
          leftText: i < beforeLines.length ? beforeLines[i] : '',
          rightText: i < afterLines.length ? afterLines[i] : '',
        });
      }
      return rows;
    }

    // Parse unified diff into hunks
    const hunks = [];
    let currentHunk = null;
    const lines = unifiedDiff.split('\n');
    for (const line of lines) {
      if (line.startsWith('@@')) {
        const m = line.match(/@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/);
        if (m) {
          currentHunk = {
            oldStart: parseInt(m[1]),
            oldCount: m[2] !== undefined ? parseInt(m[2]) : 1,
            newStart: parseInt(m[3]),
            newCount: m[4] !== undefined ? parseInt(m[4]) : 1,
            delLines: [],
            addLines: [],
            ops: []
          };
          hunks.push(currentHunk);
        }
      } else if (currentHunk) {
        if (line.startsWith('-') && !line.startsWith('---')) {
          currentHunk.ops.push({ type: 'del', text: line.substring(1) });
        } else if (line.startsWith('+') && !line.startsWith('+++')) {
          currentHunk.ops.push({ type: 'add', text: line.substring(1) });
        } else if (!line.startsWith('\\')) {
          currentHunk.ops.push({ type: 'ctx', text: line.startsWith(' ') ? line.substring(1) : line });
        }
      }
    }

    // Build aligned rows from hunks
    let leftIdx = 0;  // 0-based index into beforeLines
    let rightIdx = 0; // 0-based index into afterLines

    for (const hunk of hunks) {
      const hunkLeftStart = hunk.oldStart - 1; // 0-based
      const hunkRightStart = hunk.newStart - 1;

      // Add context lines before this hunk
      while (leftIdx < hunkLeftStart && rightIdx < hunkRightStart) {
        rows.push({
          type: 'ctx',
          leftNum: leftIdx + 1, rightNum: rightIdx + 1,
          leftText: beforeLines[leftIdx] || '', rightText: afterLines[rightIdx] || '',
        });
        leftIdx++;
        rightIdx++;
      }

      // Process hunk ops — group consecutive del+add as modifications
      let i = 0;
      while (i < hunk.ops.length) {
        const op = hunk.ops[i];
        if (op.type === 'ctx') {
          rows.push({
            type: 'ctx',
            leftNum: leftIdx + 1, rightNum: rightIdx + 1,
            leftText: beforeLines[leftIdx] || op.text,
            rightText: afterLines[rightIdx] || op.text,
          });
          leftIdx++;
          rightIdx++;
          i++;
        } else if (op.type === 'del') {
          // Collect consecutive del lines
          const dels = [];
          while (i < hunk.ops.length && hunk.ops[i].type === 'del') {
            dels.push(hunk.ops[i]);
            i++;
          }
          // Collect consecutive add lines right after
          const adds = [];
          while (i < hunk.ops.length && hunk.ops[i].type === 'add') {
            adds.push(hunk.ops[i]);
            i++;
          }
          // Pair up del/add as modifications
          const pairCount = Math.min(dels.length, adds.length);
          for (let p = 0; p < pairCount; p++) {
            rows.push({
              type: 'mod',
              leftNum: leftIdx + 1, rightNum: rightIdx + 1,
              leftText: beforeLines[leftIdx] || dels[p].text,
              rightText: afterLines[rightIdx] || adds[p].text,
            });
            leftIdx++;
            rightIdx++;
          }
          // Remaining dels (pure deletions)
          for (let p = pairCount; p < dels.length; p++) {
            rows.push({
              type: 'del',
              leftNum: leftIdx + 1, rightNum: null,
              leftText: beforeLines[leftIdx] || dels[p].text,
            });
            leftIdx++;
          }
          // Remaining adds (pure additions)
          for (let p = pairCount; p < adds.length; p++) {
            rows.push({
              type: 'add',
              leftNum: null, rightNum: rightIdx + 1,
              rightText: afterLines[rightIdx] || adds[p].text,
            });
            rightIdx++;
          }
        } else if (op.type === 'add') {
          rows.push({
            type: 'add',
            leftNum: null, rightNum: rightIdx + 1,
            rightText: afterLines[rightIdx] || op.text,
          });
          rightIdx++;
          i++;
        }
      }
    }

    // Add trailing context after last hunk
    while (leftIdx < beforeLines.length && rightIdx < afterLines.length) {
      rows.push({
        type: 'ctx',
        leftNum: leftIdx + 1, rightNum: rightIdx + 1,
        leftText: beforeLines[leftIdx] || '', rightText: afterLines[rightIdx] || '',
      });
      leftIdx++;
      rightIdx++;
    }
    // Handle any remaining lines
    while (leftIdx < beforeLines.length) {
      rows.push({ type: 'del', leftNum: leftIdx + 1, leftText: beforeLines[leftIdx] || '' });
      leftIdx++;
    }
    while (rightIdx < afterLines.length) {
      rows.push({ type: 'add', rightNum: rightIdx + 1, rightText: afterLines[rightIdx] || '' });
      rightIdx++;
    }

    return rows;
  }

  /**
   * Highlight word-level differences within a line.
   * side: 'del' = show removed tokens highlighted, 'add' = show added tokens highlighted
   */
  _highlightWordDiff(oldLine, newLine, side, lang) {
    if (!oldLine && !newLine) return '&nbsp;';
    const text = side === 'del' ? oldLine : newLine;
    if (!oldLine || !newLine) return escHtml(text) || '&nbsp;';

    // Split into tokens (words + whitespace)
    const tokenize = (s) => s.match(/\S+|\s+/g) || [];
    const oldTokens = tokenize(oldLine);
    const newTokens = tokenize(newLine);

    // Simple LCS-based token diff
    const oldSet = new Set();
    const newSet = new Set();

    // Find common prefix
    let commonPrefix = 0;
    while (commonPrefix < oldTokens.length && commonPrefix < newTokens.length &&
      oldTokens[commonPrefix] === newTokens[commonPrefix]) {
      commonPrefix++;
    }
    // Find common suffix
    let commonSuffix = 0;
    while (commonSuffix < (oldTokens.length - commonPrefix) &&
      commonSuffix < (newTokens.length - commonPrefix) &&
      oldTokens[oldTokens.length - 1 - commonSuffix] === newTokens[newTokens.length - 1 - commonSuffix]) {
      commonSuffix++;
    }

    // Mark changed token indices
    for (let i = commonPrefix; i < oldTokens.length - commonSuffix; i++) oldSet.add(i);
    for (let i = commonPrefix; i < newTokens.length - commonSuffix; i++) newSet.add(i);

    // Build highlighted output
    const tokens = side === 'del' ? oldTokens : newTokens;
    const changedSet = side === 'del' ? oldSet : newSet;
    let result = '';
    tokens.forEach((tok, i) => {
      const escaped = escHtml(tok);
      if (changedSet.has(i)) {
        const cls = side === 'del' ? 'diff-word-del' : 'diff-word-add';
        result += `<span class="${cls}">${escaped}</span>`;
      } else {
        result += escaped;
      }
    });
    return result || '&nbsp;';
  }

  _highlightLine(line, lang) {
    if (!line) return '&nbsp;';
    try {
      if (window.hljs && lang !== 'plaintext') {
        return hljs.highlight(line, { language: lang, ignoreIllegals: true }).value;
      }
    } catch (e) { }
    return escHtml(line) || '&nbsp;';
  }

  _parseDiffHunks(diff) {
    const removed = new Set();
    const added = new Set();
    if (!diff) return { removed, added };
    let oldLine = 0, newLine = 0;
    const lines = diff.split('\n');
    for (const line of lines) {
      if (line.startsWith('@@')) {
        // Parse hunk header: @@ -old,count +new,count @@
        const m = line.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
        if (m) { oldLine = parseInt(m[1]); newLine = parseInt(m[2]); }
      } else if (line.startsWith('-') && !line.startsWith('---')) {
        removed.add(oldLine);
        oldLine++;
      } else if (line.startsWith('+') && !line.startsWith('+++')) {
        added.add(newLine);
        newLine++;
      } else if (!line.startsWith('\\')) {
        oldLine++;
        newLine++;
      }
    }
    return { removed, added };
  }


  _relativeDate(dateStr) {
    try {
      const d = new Date(dateStr);
      const now = new Date();
      const diff = Math.floor((now - d) / 1000);
      if (diff < 60) return 'just now';
      if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
      if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
      if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
      if (diff < 2592000) return Math.floor(diff / 604800) + 'w ago';
      return d.toLocaleDateString();
    } catch (e) { return dateStr.substring(0, 10); }
  }


  // ---- Project Management ----
  async loadProjects() {
    try {
      const r = await fetch('/workspace/tree');
      const d = await r.json();
      const select = $('#project-select');
      if (!select) return;
      select.innerHTML = '<option value=".">workspace /</option>';
      // Add top-level directories as projects (extract from flat file list)
      const dirs = new Set();
      (d.files || []).forEach(f => {
        const firstDir = f.path.split('/')[0];
        if (f.path.includes('/') && firstDir) dirs.add(firstDir);
      });
      [...dirs].sort().forEach(dirName => {
        const opt = document.createElement('option');
        opt.value = dirName;
        opt.textContent = ' ' + dirName;
        select.appendChild(opt);
      });
      // Restore last project
      const last = localStorage.getItem('clawzd_project');
      if (last && select.querySelector(`option[value="${last}"]`)) {
        select.value = last;
      }
      // Add history projects that aren't in current tree
      this._addHistoryOptions(select);
    } catch (e) { }
  }

  _addHistoryOptions(select) {
    const history = JSON.parse(localStorage.getItem('clawzd_project_history') || '[]');
    history.forEach(p => {
      if (!select.querySelector(`option[value="${p}"]`) && p !== '.') {
        const opt = document.createElement('option');
        opt.value = p;
        opt.textContent = ' ' + p + ' (history)';
        opt.style.color = '#888';
        select.appendChild(opt);
      }
    });
  }

  switchProject(projectName) {
    localStorage.setItem('clawzd_project', projectName);
    // Add to history
    const history = JSON.parse(localStorage.getItem('clawzd_project_history') || '[]');
    if (!history.includes(projectName)) {
      history.unshift(projectName);
      if (history.length > 10) history.pop();
      localStorage.setItem('clawzd_project_history', JSON.stringify(history));
    }
    // Close all tabs
    this.openTabs = [];
    this.activeTab = null;
    this.renderTabs();
    this.showWelcome();
    // Reload tree for the project
    this.loadTree();
    this.addActivity(icon('folder'), 'Switched project', projectName === '.' ? 'workspace root' : projectName);
    toast('Project: ' + (projectName === '.' ? 'workspace' : projectName));
  }

  closeProject() {
    const current = $('#project-select').value;
    if (current === '.') { toast('Cannot close workspace root'); return; }
    // Remove from history
    let history = JSON.parse(localStorage.getItem('clawzd_project_history') || '[]');
    history = history.filter(p => p !== current);
    localStorage.setItem('clawzd_project_history', JSON.stringify(history));
    // Switch to root
    $('#project-select').value = '.';
    localStorage.setItem('clawzd_project', '.');
    this.openTabs = [];
    this.activeTab = null;
    this.renderTabs();
    this.showWelcome();
    this.loadTree();
    this.loadProjects();
    this.addActivity(icon('x'), 'Closed project', current);
  }

  showProjectHistory() {
    const history = JSON.parse(localStorage.getItem('clawzd_project_history') || '[]');
    if (!history.length) { toast('No project history'); return; }
    const choice = prompt('Recent projects:\n' + history.map((p, i) => (i + 1) + '. ' + p).join('\n') + '\n\nEnter number to open:');
    if (choice && history[parseInt(choice) - 1]) {
      this.switchProject(history[parseInt(choice) - 1]);
      $('#project-select').value = history[parseInt(choice) - 1];
    }
  }
}

// Backward compatibility
window.EditorMode = EditorMode;
