/**
 * Clawzd — Structured UI Component Renderer.
 *
 * Parses __MARKER__{ JSON }__MARKER__ blocks in LLM responses
 * and renders them as interactive DOM components:
 *   - CHART  → Chart.js canvas
 *   - TABLE  → Sortable HTML table
 *   - PROGRESS → Animated progress bar
 *   - CARD   → Styled info card
 *   - ALERT  → Callout box
 *   - ARTIFACT → Artifact reference card
 *
 * Used by both streaming_parser.js (live preview) and renderMd (final).
 */

const StructuredUI = (() => {
  // Unique ID counter for chart canvases
  let _chartId = 0;

  /**
   * Parse and render all structured UI markers in HTML text.
   * @param {string} html - HTML string with __MARKER__ blocks
   * @returns {string} - HTML with markers replaced by components
   */
  function renderComponents(html) {
    html = _renderCharts(html);
    html = _renderTables(html);
    html = _renderProgress(html);
    html = _renderCards(html);
    html = _renderAlerts(html);
    html = _renderArtifacts(html);
    return html;
  }

  // ── Charts ─────────────────────────────────────────────
  function _renderCharts(html) {
    return html.replace(/__CHART__(\{[\s\S]*?\})__CHART__/g, (_, jsonStr) => {
      try {
        const config = JSON.parse(jsonStr);
        const id = `sui-chart-${++_chartId}`;
        const title = config.title ? `<div class="sui-chart-title">${config.title}</div>` : '';

        // Store config for Chart.js initialization after DOM insert
        setTimeout(() => _initChart(id, config), 100);

        return `<div class="sui-chart-wrapper">
          ${title}
          <canvas id="${id}" style="width:100%;max-height:320px;"></canvas>
        </div>`;
      } catch (e) {
        return `<div class="sui-error">⚠️ Invalid chart data</div>`;
      }
    });
  }

  function _initChart(canvasId, config) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === 'undefined') return;

    // Color palette
    const colors = [
      'rgba(99, 102, 241, 0.8)',   // Indigo
      'rgba(16, 185, 129, 0.8)',   // Emerald
      'rgba(245, 158, 11, 0.8)',   // Amber
      'rgba(239, 68, 68, 0.8)',    // Red
      'rgba(139, 92, 246, 0.8)',   // Violet
      'rgba(14, 165, 233, 0.8)',   // Sky
      'rgba(236, 72, 153, 0.8)',   // Pink
      'rgba(34, 197, 94, 0.8)',    // Green
    ];

    const datasets = (config.datasets || []).map((ds, i) => ({
      ...ds,
      backgroundColor: ds.backgroundColor || colors[i % colors.length],
      borderColor: ds.borderColor || colors[i % colors.length].replace('0.8', '1'),
      borderWidth: ds.borderWidth || 2,
      tension: 0.3,
    }));

    new Chart(canvas, {
      type: config.type || 'bar',
      data: { labels: config.labels || [], datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            labels: { color: getComputedStyle(document.body).getPropertyValue('--text-primary').trim() || '#e2e8f0' }
          }
        },
        scales: config.type !== 'pie' && config.type !== 'doughnut' ? {
          x: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(148,163,184,0.1)' } },
          y: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(148,163,184,0.1)' } },
        } : undefined,
      }
    });
  }

  // ── Tables ─────────────────────────────────────────────
  function _renderTables(html) {
    return html.replace(/__TABLE__(\{[\s\S]*?\})__TABLE__/g, (_, jsonStr) => {
      try {
        const config = JSON.parse(jsonStr);
        const title = config.title ? `<div class="sui-table-title">${config.title}</div>` : '';
        const headers = (config.headers || []).map(h => `<th>${h}</th>`).join('');
        const rows = (config.rows || []).map(row =>
          '<tr>' + row.map(cell => `<td>${cell}</td>`).join('') + '</tr>'
        ).join('');

        return `<div class="sui-table-wrapper">
          ${title}
          <div class="sui-table-scroll">
            <table class="sui-table">
              <thead><tr>${headers}</tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>`;
      } catch (e) {
        return `<div class="sui-error">⚠️ Invalid table data</div>`;
      }
    });
  }

  // ── Progress ───────────────────────────────────────────
  function _renderProgress(html) {
    return html.replace(/__PROGRESS__(\{[\s\S]*?\})__PROGRESS__/g, (_, jsonStr) => {
      try {
        const config = JSON.parse(jsonStr);
        const pct = Math.min(100, Math.max(0, (config.value / (config.max || 100)) * 100));
        const statusClass = config.status || 'info';

        return `<div class="sui-progress">
          <div class="sui-progress-label">
            <span>${config.label || ''}</span>
            <span>${Math.round(pct)}%</span>
          </div>
          <div class="sui-progress-bar">
            <div class="sui-progress-fill sui-${statusClass}" style="width:${pct}%"></div>
          </div>
        </div>`;
      } catch (e) {
        return '';
      }
    });
  }

  // ── Cards ──────────────────────────────────────────────
  function _renderCards(html) {
    return html.replace(/__CARD__(\{[\s\S]*?\})__CARD__/g, (_, jsonStr) => {
      try {
        const config = JSON.parse(jsonStr);
        const color = config.color || 'blue';

        return `<div class="sui-card sui-card-${color}">
          <div class="sui-card-icon">${config.icon || '📋'}</div>
          <div class="sui-card-body">
            <div class="sui-card-title">${config.title || ''}</div>
            <div class="sui-card-content">${config.content || ''}</div>
          </div>
        </div>`;
      } catch (e) {
        return '';
      }
    });
  }

  // ── Alerts ─────────────────────────────────────────────
  function _renderAlerts(html) {
    return html.replace(/__ALERT__(\{[\s\S]*?\})__ALERT__/g, (_, jsonStr) => {
      try {
        const config = JSON.parse(jsonStr);
        const icons = { info: 'ℹ️', success: '✅', warning: '⚠️', error: '❌' };
        const type = config.type || 'info';

        return `<div class="sui-alert sui-alert-${type}">
          <span class="sui-alert-icon">${icons[type] || 'ℹ️'}</span>
          <div>
            ${config.title ? `<strong>${config.title}</strong><br>` : ''}
            ${config.message || ''}
          </div>
        </div>`;
      } catch (e) {
        return '';
      }
    });
  }

  // ── Artifacts ──────────────────────────────────────────
  function _renderArtifacts(html) {
    return html.replace(/__ARTIFACT__(\{[\s\S]*?\})__ARTIFACT__/g, (_, jsonStr) => {
      try {
        const config = JSON.parse(jsonStr);
        const langBadge = config.language ? `<span class="sui-badge">${config.language}</span>` : '';
        const version = config.version ? `v${config.version}` : '';

        return `<div class="sui-artifact" data-artifact-id="${config.id || ''}">
          <div class="sui-artifact-header">
            <span class="sui-artifact-icon">📄</span>
            <span class="sui-artifact-title">${config.title || 'Artifact'}</span>
            ${langBadge}
            <span class="sui-artifact-version">${version}</span>
          </div>
          ${config.preview ? `<pre class="sui-artifact-preview"><code>${config.preview}</code></pre>` : ''}
        </div>`;
      } catch (e) {
        return '';
      }
    });
  }

  // Public API
  return { renderComponents };
})();

window.StructuredUI = StructuredUI;
