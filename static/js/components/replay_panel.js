/**
 * Clawzd — Tool Replay Panel.
 *
 * Visualizes tool execution sequences from the Tool Replay API.
 * Shows timeline view with duration, status, params, and export options.
 *
 * API:
 *   GET  /replays                     — List sessions
 *   GET  /replays/{id}                — Full replay
 *   GET  /replays/{id}/summary        — Summary analytics
 *   GET  /replays/{id}/workflow       — Export as workflow
 *   DELETE /replays/{id}              — Delete
 */

const ReplayPanel = (() => {
  let _panelEl = null;
  let _isOpen = false;
  let _sessions = [];
  let _activeSession = null;

  function init() {
    _createPanel();
  }

  function _createPanel() {
    _panelEl = document.createElement('div');
    _panelEl.id = 'replay-panel';
    _panelEl.className = 'replay-panel';
    _panelEl.innerHTML = `
      <div class="replay-panel-header">
        <h3>🔄 Tool Replay</h3>
        <div class="replay-panel-actions">
          <button class="rp-btn-sm" onclick="ReplayPanel.refresh()" title="Refresh">↻</button>
          <button class="rp-btn-sm" onclick="ReplayPanel.toggle(false)" title="Close">&times;</button>
        </div>
      </div>
      <div class="replay-panel-body">
        <div class="replay-sessions" id="replay-sessions">
          <div class="replay-empty">Loading...</div>
        </div>
        <div class="replay-detail" id="replay-detail" style="display:none"></div>
      </div>
    `;
    document.body.appendChild(_panelEl);
  }

  async function refresh() {
    try {
      const res = await fetch('/replays?limit=30');
      _sessions = await res.json();
      _renderSessions();
    } catch (e) {
      console.warn('ReplayPanel: load failed', e);
    }
  }

  function _renderSessions() {
    const el = document.getElementById('replay-sessions');
    if (!el) return;

    if (_sessions.length === 0) {
      el.innerHTML = '<div class="replay-empty">No replay sessions yet. Tool calls are recorded automatically.</div>';
      return;
    }

    el.innerHTML = _sessions.map(s => {
      const time = _timeAgo(s.last_modified || s.created);
      const size = s.size_bytes ? `${Math.round(s.size_bytes / 1024)}KB` : '';
      return `
        <div class="rp-session" onclick="ReplayPanel.loadSession('${s.session_id}')">
          <div class="rp-session-id">${s.session_id.slice(0, 12)}…</div>
          <div class="rp-session-meta">
            <span>${time}</span>
            ${size ? `<span>${size}</span>` : ''}
          </div>
        </div>
      `;
    }).join('');
  }

  async function loadSession(sessionId) {
    _activeSession = sessionId;
    const detailEl = document.getElementById('replay-detail');
    const sessionsEl = document.getElementById('replay-sessions');
    if (!detailEl || !sessionsEl) return;

    detailEl.style.display = 'block';
    sessionsEl.style.display = 'none';
    detailEl.innerHTML = '<div class="replay-empty">Loading replay…</div>';

    try {
      const [entriesRes, summaryRes] = await Promise.all([
        fetch(`/replays/${sessionId}`),
        fetch(`/replays/${sessionId}/summary`),
      ]);
      const entries = await entriesRes.json();
      const summary = await summaryRes.json();
      _renderDetail(entries, summary);
    } catch (e) {
      detailEl.innerHTML = '<div class="replay-empty">Failed to load replay</div>';
    }
  }

  function _renderDetail(entries, summary) {
    const el = document.getElementById('replay-detail');
    if (!el) return;

    const statsHtml = `
      <div class="rp-stats">
        <div class="rp-stat"><span class="rp-stat-val">${summary.total_calls}</span><span class="rp-stat-label">Calls</span></div>
        <div class="rp-stat"><span class="rp-stat-val">${summary.unique_tools}</span><span class="rp-stat-label">Tools</span></div>
        <div class="rp-stat"><span class="rp-stat-val">${summary.error_count}</span><span class="rp-stat-label">Errors</span></div>
        <div class="rp-stat"><span class="rp-stat-val">${_formatDuration(summary.total_duration_ms)}</span><span class="rp-stat-label">Duration</span></div>
      </div>
    `;

    const timelineHtml = entries.map((e, i) => {
      const success = e.success !== false;
      const duration = e.duration_ms ? `${Math.round(e.duration_ms)}ms` : '';
      const paramsPreview = _truncate(JSON.stringify(e.params || {}), 80);
      const resultPreview = _truncate(e.result_preview || '', 60);

      return `
        <div class="rp-entry ${success ? '' : 'rp-entry-error'}">
          <div class="rp-entry-marker">
            <span class="rp-entry-dot">${success ? '✅' : '❌'}</span>
            ${i < entries.length - 1 ? '<div class="rp-entry-line"></div>' : ''}
          </div>
          <div class="rp-entry-body">
            <div class="rp-entry-header">
              <span class="rp-entry-tool">${e.tool}</span>
              <span class="rp-entry-duration">${duration}</span>
            </div>
            <div class="rp-entry-params">${paramsPreview}</div>
            ${resultPreview ? `<div class="rp-entry-result">${resultPreview}</div>` : ''}
          </div>
        </div>
      `;
    }).join('');

    el.innerHTML = `
      <div class="rp-detail-toolbar">
        <button class="rp-btn-sm" onclick="ReplayPanel.backToList()">← Back</button>
        <button class="rp-btn-sm rp-btn-export" onclick="ReplayPanel.exportWorkflow('${_activeSession}')">📦 Export</button>
        <button class="rp-btn-sm rp-btn-delete" onclick="ReplayPanel.deleteSession('${_activeSession}')">🗑️</button>
      </div>
      ${statsHtml}
      <div class="rp-timeline">${timelineHtml}</div>
    `;
  }

  function backToList() {
    _activeSession = null;
    const detailEl = document.getElementById('replay-detail');
    const sessionsEl = document.getElementById('replay-sessions');
    if (detailEl) detailEl.style.display = 'none';
    if (sessionsEl) sessionsEl.style.display = 'block';
  }

  async function exportWorkflow(sessionId) {
    try {
      const res = await fetch(`/replays/${sessionId}/workflow`);
      const wf = await res.json();
      const blob = new Blob([JSON.stringify(wf, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `workflow-${sessionId.slice(0, 8)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      if (typeof window.toast === 'function') window.toast('Workflow exported', 'success');
    } catch (e) {
      console.warn('Export failed', e);
    }
  }

  async function deleteSession(sessionId) {
    if (!confirm('Delete this replay?')) return;
    try {
      await fetch(`/replays/${sessionId}`, { method: 'DELETE' });
      backToList();
      refresh();
      if (typeof window.toast === 'function') window.toast('Replay deleted', 'info');
    } catch (e) {
      console.warn('Delete failed', e);
    }
  }

  function toggle(force) {
    _isOpen = force !== undefined ? force : !_isOpen;
    if (_panelEl) {
      _panelEl.classList.toggle('replay-panel-open', _isOpen);
      if (_isOpen) {
        backToList();
        refresh();
      }
    }
  }

  function _timeAgo(iso) {
    if (!iso) return '';
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
  }

  function _truncate(str, max) {
    return str.length > max ? str.slice(0, max) + '…' : str;
  }

  function _formatDuration(ms) {
    if (!ms || ms < 1000) return (ms || 0) + 'ms';
    return (ms / 1000).toFixed(1) + 's';
  }

  return { init, refresh, toggle, loadSession, backToList, exportWorkflow, deleteSession };
})();

window.ReplayPanel = ReplayPanel;
