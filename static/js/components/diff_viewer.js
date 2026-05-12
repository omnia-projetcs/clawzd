/* Inline Diff Viewer — shows git changes with stage/revert actions */
(function () {
  'use strict';

  const $ = s => document.querySelector(s);

  class DiffViewer {
    constructor() {
      this._panelEl = null;
      this._project = '';
    }

    /** Toggle the diff panel visibility */
    toggle(project) {
      this._project = project || '';
      if (this._panelEl && this._panelEl.style.display !== 'none') {
        this.close();
      } else {
        this.open();
      }
    }

    /** Open and fetch diff */
    async open() {
      this._ensurePanel();
      this._panelEl.style.display = 'block';
      this._panelEl.querySelector('.diff-body').innerHTML =
        '<div class="diff-loading">⏳ Loading diff…</div>';

      try {
        const url = this._project
          ? `/api/diff?project=${encodeURIComponent(this._project)}`
          : '/api/diff';
        const res = await fetch(url);
        const data = await res.json();

        if (data.error) {
          this._renderError(data.error);
          return;
        }
        this._renderDiff(data);
      } catch (e) {
        this._renderError('Failed to load diff: ' + e.message);
      }
    }

    close() {
      if (this._panelEl) this._panelEl.style.display = 'none';
    }

    /** Create the panel DOM */
    _ensurePanel() {
      if (this._panelEl) return;

      const panel = document.createElement('div');
      panel.id = 'diff-viewer-panel';
      panel.className = 'diff-panel';
      panel.innerHTML = `
        <div class="diff-header">
          <span class="diff-title">
            <svg class="ic" width="14" height="14"><use href="#icon-git-branch"></use></svg>
            Uncommitted Changes
          </span>
          <div class="diff-header-actions">
            <button class="diff-refresh-btn" title="Refresh">↻</button>
            <button class="diff-close-btn" title="Close">✕</button>
          </div>
        </div>
        <div class="diff-stats"></div>
        <div class="diff-body"></div>
      `;
      document.body.appendChild(panel);
      this._panelEl = panel;

      panel.querySelector('.diff-close-btn').addEventListener('click', () => this.close());
      panel.querySelector('.diff-refresh-btn').addEventListener('click', () => this.open());
    }

    _renderError(msg) {
      this._panelEl.querySelector('.diff-body').innerHTML =
        `<div class="diff-error">⚠️ ${msg}</div>`;
      this._panelEl.querySelector('.diff-stats').innerHTML = '';
    }

    _renderDiff(data) {
      const { files, stats, status_files } = data;
      const statsEl = this._panelEl.querySelector('.diff-stats');
      const bodyEl = this._panelEl.querySelector('.diff-body');

      // Stats bar
      statsEl.innerHTML = `
        <span class="diff-stat-files">${stats.files_changed} file${stats.files_changed !== 1 ? 's' : ''}</span>
        <span class="diff-stat-add">+${stats.additions}</span>
        <span class="diff-stat-del">−${stats.deletions}</span>
      `;

      if (files.length === 0) {
        bodyEl.innerHTML = '<div class="diff-empty">✓ No uncommitted changes</div>';
        // Show status files if any (untracked, etc.)
        if (status_files && status_files.length > 0) {
          bodyEl.innerHTML = `
            <div class="diff-status-list">
              ${status_files.map(f => `
                <div class="diff-status-item">
                  <span class="diff-status-code diff-status-${f.status.replace(/[^a-zA-Z]/g, '')}">${f.status}</span>
                  <span class="diff-status-file">${this._escHtml(f.file)}</span>
                </div>
              `).join('')}
            </div>
          `;
        }
        return;
      }

      bodyEl.innerHTML = files.map((f, i) => `
        <div class="diff-file" data-file="${this._escHtml(f.file)}">
          <div class="diff-file-header" data-idx="${i}">
            <span class="diff-file-name">${this._escHtml(f.file)}</span>
            <span class="diff-file-stats">
              <span class="diff-stat-add">+${f.additions}</span>
              <span class="diff-stat-del">−${f.deletions}</span>
            </span>
            <div class="diff-file-actions">
              <button class="diff-action-btn diff-stage-btn" data-file="${this._escHtml(f.file)}" title="Stage file">Stage</button>
              <button class="diff-action-btn diff-revert-btn" data-file="${this._escHtml(f.file)}" title="Revert changes">Revert</button>
            </div>
          </div>
          <div class="diff-file-content" id="diff-content-${i}">
            ${f.hunks.map(h => `
              <div class="diff-hunk">
                <div class="diff-hunk-header">${this._escHtml(h.header)}</div>
                ${h.lines.map(l => `
                  <div class="diff-line diff-line-${l.type}"><code>${this._escHtml(l.content)}</code></div>
                `).join('')}
              </div>
            `).join('')}
          </div>
        </div>
      `).join('');

      // Collapse/expand file contents
      bodyEl.querySelectorAll('.diff-file-header').forEach(header => {
        header.addEventListener('click', (e) => {
          if (e.target.closest('.diff-action-btn')) return;
          const idx = header.dataset.idx;
          const content = bodyEl.querySelector(`#diff-content-${idx}`);
          if (content) content.classList.toggle('collapsed');
        });
      });

      // Stage buttons
      bodyEl.querySelectorAll('.diff-stage-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const file = btn.dataset.file;
          btn.disabled = true; btn.textContent = '…';
          try {
            const res = await fetch('/api/diff/stage', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ project: this._project, file }),
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);
            btn.textContent = '✓ Staged';
            btn.classList.add('done');
          } catch (err) {
            btn.textContent = '✗ Error';
            if (typeof toast === 'function') toast('Stage failed: ' + err.message);
          }
        });
      });

      // Revert buttons
      bodyEl.querySelectorAll('.diff-revert-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const file = btn.dataset.file;
          if (!confirm(`Revert all changes to "${file}"?`)) return;
          btn.disabled = true; btn.textContent = '…';
          try {
            const res = await fetch('/api/diff/revert', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ project: this._project, file }),
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);
            // Remove file from display
            const fileEl = btn.closest('.diff-file');
            if (fileEl) fileEl.remove();
            if (typeof toast === 'function') toast('✓ Reverted: ' + file);
            this.open(); // Refresh
          } catch (err) {
            btn.textContent = '✗ Error';
            if (typeof toast === 'function') toast('Revert failed: ' + err.message);
          }
        });
      });
    }

    _escHtml(s) {
      const div = document.createElement('div');
      div.textContent = s || '';
      return div.innerHTML;
    }
  }

  window.diffViewer = new DiffViewer();
})();
