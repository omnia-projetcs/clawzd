/**
 * Clawzd — System Dashboard Component.
 *
 * Displays aggregated metrics from /dashboard/metrics in a compact
 * modal view. Shows subsystem health, counts, and key statistics.
 *
 * API: GET /dashboard/metrics
 */

const SystemDashboard = (() => {
  let _overlayEl = null;
  let _metrics = null;

  function init() {
    _createOverlay();
  }

  function _createOverlay() {
    _overlayEl = document.createElement('div');
    _overlayEl.id = 'system-dashboard-overlay';
    _overlayEl.className = 'sys-dash-overlay';
    _overlayEl.innerHTML = `
      <div class="sys-dash-modal">
        <div class="sys-dash-header">
          <h3>📊 System Dashboard</h3>
          <button class="sys-dash-close" onclick="SystemDashboard.close()">&times;</button>
        </div>
        <div class="sys-dash-body" id="sys-dash-body">
          <div class="sys-dash-loading">Loading metrics…</div>
        </div>
      </div>
    `;
    _overlayEl.addEventListener('click', (e) => {
      if (e.target === _overlayEl) close();
    });
    document.body.appendChild(_overlayEl);
  }

  async function open() {
    if (!_overlayEl) return;
    _overlayEl.classList.add('sys-dash-open');
    await _loadMetrics();
  }

  function close() {
    if (_overlayEl) _overlayEl.classList.remove('sys-dash-open');
  }

  async function _loadMetrics() {
    const body = document.getElementById('sys-dash-body');
    if (!body) return;

    try {
      const res = await fetch('/dashboard/metrics');
      _metrics = await res.json();
      _renderMetrics(body);
    } catch (e) {
      body.innerHTML = '<div class="sys-dash-loading">Failed to load metrics</div>';
    }
  }

  function _renderMetrics(body) {
    if (!_metrics?.subsystems) return;
    const subs = _metrics.subsystems;

    const cards = [
      _card('🔌', 'Plugins', subs.plugins, [
        ['Registered', subs.plugins?.total],
        ['Enabled', subs.plugins?.enabled],
      ]),
      _card('📤', 'Uploads', subs.upload_store, [
        ['Files', subs.upload_store?.total_files],
        ['Size', `${subs.upload_store?.total_size_mb || 0} MB`],
      ]),
      _card('🔔', 'Notifications', subs.notifications, [
        ['Queue', subs.notifications?.queue_size],
        ['Subscribers', subs.notifications?.active_subscribers],
      ]),
      _card('🔄', 'Replays', subs.replays, [
        ['Sessions', subs.replays?.total_sessions],
        ['Size', `${subs.replays?.total_size_kb || 0} KB`],
      ]),
      _card('🏗️', 'Apps', subs.app_builder, [
        ['Created', subs.app_builder?.total_apps],
      ]),
      _card('📄', 'Artifacts', subs.artifacts, [
        ['Total', subs.artifacts?.total],
        ['Pinned', subs.artifacts?.pinned],
      ]),
      _card('🗄️', 'Database', subs.database, [
        ['DB', `${subs.database?.db_size_mb || 0} MB`],
        ['WAL', `${subs.database?.wal_size_mb || 0} MB`],
      ]),
      _card('📋', 'Contracts', subs.contracts, [
        ['Schemas', subs.contracts?.registered_schemas],
      ]),
    ];

    body.innerHTML = `
      <div class="sys-dash-timestamp">Last updated: ${new Date(_metrics.timestamp).toLocaleTimeString()}</div>
      <div class="sys-dash-grid">${cards.join('')}</div>
    `;
  }

  function _card(icon, name, data, fields) {
    const hasError = data?.error;
    const statusClass = hasError ? 'sys-dash-card-error' : 'sys-dash-card-ok';
    const fieldsHtml = fields.map(([label, value]) =>
      `<div class="sys-dash-field"><span>${label}</span><span>${value ?? '—'}</span></div>`
    ).join('');

    return `
      <div class="sys-dash-card ${statusClass}">
        <div class="sys-dash-card-header">
          <span class="sys-dash-card-icon">${icon}</span>
          <span class="sys-dash-card-name">${name}</span>
          <span class="sys-dash-card-status">${hasError ? '⚠️' : '●'}</span>
        </div>
        ${hasError ? `<div class="sys-dash-card-error-msg">${data.error}</div>` : fieldsHtml}
      </div>
    `;
  }

  return { init, open, close };
})();

window.SystemDashboard = SystemDashboard;
