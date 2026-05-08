/**
 * Clawzd — Artifact Panel Component.
 *
 * Sidebar panel for browsing, previewing, and managing persistent artifacts
 * generated during chat sessions. Integrates with the artifacts REST API.
 *
 * API:
 *   GET    /artifacts           — List
 *   GET    /artifacts/{id}      — Detail
 *   PUT    /artifacts/{id}      — Update (pin/unpin)
 *   DELETE /artifacts/{id}      — Delete
 *   GET    /artifacts/{id}/history — Version chain
 */

const ArtifactPanel = (() => {
  let _panelEl = null;
  let _isOpen = false;
  let _artifacts = [];

  const _ICONS = {
    code: '📄', text: '📝', chart: '📊', table: '📋',
    image: '🖼️', other: '📦',
  };

  /**
   * Initialize the artifact panel.
   */
  function init() {
    _createPanel();
    _createToggleButton();
  }

  function _createPanel() {
    _panelEl = document.createElement('div');
    _panelEl.id = 'artifact-panel';
    _panelEl.className = 'artifact-panel';
    _panelEl.innerHTML = `
      <div class="artifact-panel-header">
        <h3>📄 Artifacts</h3>
        <div class="artifact-panel-actions">
          <button class="artifact-panel-refresh" title="Refresh" onclick="ArtifactPanel.refresh()">↻</button>
          <button class="artifact-panel-close" title="Close" onclick="ArtifactPanel.toggle(false)">&times;</button>
        </div>
      </div>
      <div class="artifact-panel-filter">
        <select id="artifact-filter-kind" onchange="ArtifactPanel.refresh()">
          <option value="">All types</option>
          <option value="code">Code</option>
          <option value="text">Text</option>
          <option value="chart">Chart</option>
        </select>
        <label class="artifact-pin-filter">
          <input type="checkbox" id="artifact-filter-pinned" onchange="ArtifactPanel.refresh()">
          Pinned only
        </label>
      </div>
      <div class="artifact-panel-list" id="artifact-panel-list">
        <div class="artifact-panel-empty">No artifacts yet</div>
      </div>
    `;
    document.body.appendChild(_panelEl);
  }

  function _createToggleButton() {
    // Find header-right area
    const headerRight = document.querySelector('.header-right');
    if (!headerRight) return;

    const btn = document.createElement('button');
    btn.id = 'artifact-toggle-btn';
    btn.className = 'icon-btn';
    btn.title = 'Artifacts';
    btn.innerHTML = '📄';
    btn.style.cssText = 'font-size: 16px; position: relative;';
    btn.onclick = () => toggle();

    headerRight.insertBefore(btn, headerRight.firstChild);
  }

  async function refresh() {
    const kindEl = document.getElementById('artifact-filter-kind');
    const pinnedEl = document.getElementById('artifact-filter-pinned');

    const params = new URLSearchParams();
    if (kindEl?.value) params.set('kind', kindEl.value);
    if (pinnedEl?.checked) params.set('pinned_only', 'true');
    params.set('limit', '30');

    try {
      const res = await fetch('/artifacts?' + params.toString());
      _artifacts = await res.json();
      _renderList();
    } catch (e) {
      console.warn('ArtifactPanel: failed to load', e);
    }
  }

  function _renderList() {
    const listEl = document.getElementById('artifact-panel-list');
    if (!listEl) return;

    if (_artifacts.length === 0) {
      listEl.innerHTML = '<div class="artifact-panel-empty">No artifacts found</div>';
      return;
    }

    listEl.innerHTML = _artifacts.map(a => {
      const icon = _ICONS[a.kind] || _ICONS.other;
      const lang = a.language ? `<span class="ap-lang">${a.language}</span>` : '';
      const pinClass = a.pinned ? 'ap-pinned' : '';
      const preview = (a.content || '').slice(0, 80).replace(/</g, '&lt;');
      const timeAgo = _timeAgo(a.created_at);

      return `
        <div class="ap-item ${pinClass}" data-id="${a.id}">
          <div class="ap-item-header">
            <span class="ap-icon">${icon}</span>
            <span class="ap-title">${a.title || 'Untitled'}</span>
            ${lang}
            <span class="ap-version">v${a.version}</span>
          </div>
          <div class="ap-preview">${preview}</div>
          <div class="ap-item-footer">
            <span class="ap-time">${timeAgo}</span>
            <div class="ap-actions">
              <button class="ap-btn" onclick="ArtifactPanel.togglePin('${a.id}', ${!a.pinned})" title="${a.pinned ? 'Unpin' : 'Pin'}">${a.pinned ? '📌' : '📍'}</button>
              <button class="ap-btn ap-btn-danger" onclick="ArtifactPanel.remove('${a.id}')" title="Delete">🗑️</button>
            </div>
          </div>
        </div>
      `;
    }).join('');
  }

  function _timeAgo(isoDate) {
    if (!isoDate) return '';
    const diff = (Date.now() - new Date(isoDate).getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
  }

  async function togglePin(id, pinned) {
    try {
      await fetch(`/artifacts/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pinned }),
      });
      refresh();
    } catch (e) {
      console.warn('Pin toggle failed', e);
    }
  }

  async function remove(id) {
    if (!confirm('Delete this artifact?')) return;
    try {
      await fetch(`/artifacts/${id}`, { method: 'DELETE' });
      refresh();
      if (typeof window.toast === 'function') {
        window.toast('Artifact deleted', 'info');
      }
    } catch (e) {
      console.warn('Delete failed', e);
    }
  }

  function toggle(force) {
    _isOpen = force !== undefined ? force : !_isOpen;
    if (_panelEl) {
      _panelEl.classList.toggle('artifact-panel-open', _isOpen);
      if (_isOpen) refresh();
    }
  }

  return { init, refresh, toggle, togglePin, remove };
})();

window.ArtifactPanel = ArtifactPanel;
