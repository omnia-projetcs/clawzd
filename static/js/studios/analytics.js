/**
 * Clawzd — Analytics Studio.
 *
 * Real-time dashboard with fleet overview KPIs and Chart.js charts.
 * Inspired by OpenClaw Studio's runtime summary architecture.
 *
 * Endpoints consumed:
 *   GET /dashboard/fleet
 *   GET /dashboard/analytics/timeseries
 *   GET /dashboard/analytics/models
 *   GET /dashboard/analytics/tools
 *   GET /dashboard/analytics/heatmap
 */
;(function () {
  'use strict';

  const $ = s => document.querySelector(s);
  const $$ = s => document.querySelectorAll(s);

  // Chart.js instances (destroyed on re-render to prevent leaks)
  let tokenChart = null;
  let modelChart = null;
  let toolChart = null;
  let pollTimer = null;

  // Chart.js color palette
  const COLORS = {
    indigo: 'rgba(99, 102, 241, 1)',
    indigo30: 'rgba(99, 102, 241, 0.3)',
    green: 'rgba(16, 185, 129, 1)',
    green30: 'rgba(16, 185, 129, 0.3)',
    amber: 'rgba(245, 158, 11, 1)',
    blue: 'rgba(59, 130, 246, 1)',
    purple: 'rgba(139, 92, 246, 1)',
    red: 'rgba(239, 68, 68, 1)',
    rose: 'rgba(244, 63, 94, 1)',
    cyan: 'rgba(6, 182, 212, 1)',
    lime: 'rgba(132, 204, 22, 1)',
  };
  const PALETTE = [
    COLORS.indigo, COLORS.green, COLORS.amber,
    COLORS.blue, COLORS.purple, COLORS.red,
    COLORS.rose, COLORS.cyan, COLORS.lime,
  ];

  // Default chart options matching the dark theme
  const CHART_DEFAULTS = {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 600, easing: 'easeOutQuart' },
    plugins: {
      legend: {
        labels: {
          color: 'rgba(255,255,255,0.65)',
          font: { size: 11, weight: '600' },
          boxWidth: 12, boxHeight: 12, padding: 12,
        },
      },
      tooltip: {
        backgroundColor: 'rgba(30, 30, 45, 0.95)',
        titleFont: { size: 12, weight: '700' },
        bodyFont: { size: 11 },
        padding: 10, cornerRadius: 8,
        borderColor: 'rgba(99, 102, 241, 0.3)',
        borderWidth: 1,
      },
    },
    scales: {
      x: {
        ticks: { color: 'rgba(255,255,255,0.45)', font: { size: 10 } },
        grid: { color: 'rgba(255,255,255,0.05)' },
      },
      y: {
        ticks: { color: 'rgba(255,255,255,0.45)', font: { size: 10 } },
        grid: { color: 'rgba(255,255,255,0.05)' },
      },
    },
  };

  // ---- Helpers ----

  function fmt(n) {
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return String(n);
  }

  function timeAgo(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    const s = Math.floor((Date.now() - d.getTime()) / 1000);
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return d.toLocaleDateString();
  }

  function escHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }

  // ---- Data Fetching ----

  async function fetchFleet() {
    try {
      const r = await fetch('/dashboard/fleet');
      return await r.json();
    } catch (e) {
      console.warn('[Analytics] Fleet fetch failed:', e);
      return null;
    }
  }

  async function fetchTimeseries(hours) {
    const bucket = hours <= 12 ? 15 : hours <= 48 ? 60 : 360;
    try {
      const r = await fetch(
        `/dashboard/analytics/timeseries?hours=${hours}&bucket_minutes=${bucket}`
      );
      return await r.json();
    } catch (e) {
      console.warn('[Analytics] Timeseries fetch failed:', e);
      return null;
    }
  }

  async function fetchModels(hours) {
    try {
      const r = await fetch(`/dashboard/analytics/models?hours=${hours}`);
      return await r.json();
    } catch (e) {
      return null;
    }
  }

  async function fetchTools(hours) {
    try {
      const r = await fetch(`/dashboard/analytics/tools?hours=${hours}`);
      return await r.json();
    } catch (e) {
      return null;
    }
  }

  async function fetchHeatmap() {
    try {
      const r = await fetch('/dashboard/analytics/heatmap');
      return await r.json();
    } catch (e) {
      return null;
    }
  }

  // ---- KPI Rendering ----

  function renderKPIs(fleet) {
    if (!fleet || !fleet.totals) return;
    const t = fleet.totals;
    const v = id => $(`#${id}`);
    v('an-val-calls').textContent = fmt(t.total_calls_today || 0);
    v('an-val-tokens').textContent = fmt(t.total_tokens_today || 0);
    v('an-val-latency').textContent = (t.avg_latency_s || 0).toFixed(2) + 's';
    v('an-val-tps').textContent = fmt(t.avg_tokens_per_s || 0);
    v('an-val-sessions').textContent = t.active_sessions || 0;
    v('an-val-saved').textContent = fmt(t.total_saved_chars || 0);
  }

  // ---- Token Usage Chart ----

  function renderTokenChart(data) {
    if (!data || !data.buckets || !data.buckets.length) return;
    const ctx = $('#an-chart-tokens');
    if (!ctx) return;

    const labels = data.buckets.map(b => {
      const d = new Date(b.timestamp);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    });

    if (tokenChart) tokenChart.destroy();

    tokenChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'Input Tokens',
            data: data.buckets.map(b => b.input_tokens),
            borderColor: COLORS.indigo,
            backgroundColor: COLORS.indigo30,
            fill: true, tension: 0.4,
            pointRadius: 2, pointHoverRadius: 5,
          },
          {
            label: 'Output Tokens',
            data: data.buckets.map(b => b.output_tokens),
            borderColor: COLORS.green,
            backgroundColor: COLORS.green30,
            fill: true, tension: 0.4,
            pointRadius: 2, pointHoverRadius: 5,
          },
        ],
      },
      options: {
        ...CHART_DEFAULTS,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          ...CHART_DEFAULTS.plugins,
          tooltip: {
            ...CHART_DEFAULTS.plugins.tooltip,
            callbacks: {
              label: ctx => `${ctx.dataset.label}: ${fmt(ctx.raw)}`,
            },
          },
        },
      },
    });
  }

  // ---- Model Performance Chart ----

  function renderModelChart(data) {
    if (!data || !data.models || !data.models.length) return;
    const ctx = $('#an-chart-models');
    if (!ctx) return;

    const models = data.models.slice(0, 8);

    if (modelChart) modelChart.destroy();

    modelChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: models.map(m => {
          const name = m.model || 'unknown';
          return name.length > 18 ? name.slice(0, 16) + '…' : name;
        }),
        datasets: [
          {
            label: 'Avg Latency (s)',
            data: models.map(m => m.avg_latency_s),
            backgroundColor: COLORS.amber,
            borderRadius: 4, barPercentage: 0.6,
            yAxisID: 'y',
          },
          {
            label: 'Tokens/sec',
            data: models.map(m => m.avg_tokens_per_s),
            backgroundColor: COLORS.indigo,
            borderRadius: 4, barPercentage: 0.6,
            yAxisID: 'y1',
          },
        ],
      },
      options: {
        ...CHART_DEFAULTS,
        scales: {
          ...CHART_DEFAULTS.scales,
          y: {
            ...CHART_DEFAULTS.scales.y,
            position: 'left',
            title: {
              display: true, text: 'Latency (s)',
              color: 'rgba(255,255,255,0.4)', font: { size: 10 },
            },
          },
          y1: {
            ...CHART_DEFAULTS.scales.y,
            position: 'right',
            grid: { drawOnChartArea: false },
            title: {
              display: true, text: 'Tokens/sec',
              color: 'rgba(255,255,255,0.4)', font: { size: 10 },
            },
          },
        },
      },
    });
  }

  // ---- Tool Savings Doughnut ----

  function renderToolChart(data) {
    if (!data || !data.tools || !data.tools.length) return;
    const ctx = $('#an-chart-tools');
    if (!ctx) return;

    const tools = data.tools.slice(0, 8);

    if (toolChart) toolChart.destroy();

    toolChart = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: tools.map(t => t.tool),
        datasets: [{
          data: tools.map(t => t.count),
          backgroundColor: PALETTE.slice(0, tools.length),
          borderColor: 'transparent',
          hoverOffset: 6,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '55%',
        animation: { duration: 600 },
        plugins: {
          ...CHART_DEFAULTS.plugins,
          tooltip: {
            ...CHART_DEFAULTS.plugins.tooltip,
            callbacks: {
              label: ctx => {
                const t = tools[ctx.dataIndex];
                return `${t.tool}: ${t.count} (${t.savings_pct}% saved)`;
              },
            },
          },
        },
      },
    });
  }

  // ---- Heatmap ----

  function renderHeatmap(data) {
    const container = $('#an-heatmap-container');
    if (!container || !data || !data.heatmap) return;

    const maxVal = Math.max(
      1,
      ...data.heatmap.flatMap(r => r.hours)
    );

    let html = '';

    // Hour labels row
    html += '<div class="an-heatmap-hours">';
    for (let h = 0; h < 24; h++) {
      if (h % 3 === 0) {
        html += `<span class="an-heatmap-hour-label">${String(h).padStart(2, '0')}</span>`;
      } else {
        html += '<span class="an-heatmap-hour-label"></span>';
      }
    }
    html += '</div>';

    for (const row of data.heatmap) {
      html += '<div class="an-heatmap-row">';
      html += `<span class="an-heatmap-label">${escHtml(row.day)}</span>`;
      html += '<div class="an-heatmap-cells">';
      for (let h = 0; h < 24; h++) {
        const val = row.hours[h] || 0;
        const level = val === 0 ? 0
          : val <= maxVal * 0.2 ? 1
          : val <= maxVal * 0.4 ? 2
          : val <= maxVal * 0.6 ? 3
          : val <= maxVal * 0.8 ? 4
          : 5;
        html += `<div class="an-heatmap-cell" data-level="${level}" title="${row.day} ${String(h).padStart(2,'0')}h: ${val} calls"></div>`;
      }
      html += '</div></div>';
    }

    container.innerHTML = html;
  }

  // ---- Sessions Table ----

  function renderSessions(fleet) {
    const tbody = $('#an-sessions-tbody');
    if (!tbody || !fleet || !fleet.sessions) return;

    if (!fleet.sessions.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="an-empty">No sessions today</td></tr>';
      return;
    }

    tbody.innerHTML = fleet.sessions.map(s => `
      <tr>
        <td><span class="an-session-id">${escHtml((s.session_id || '').slice(0, 12))}</span></td>
        <td><span class="an-model-badge">${escHtml(s.model || '—')}</span></td>
        <td>${s.call_count}</td>
        <td>${fmt(s.total_tokens)}</td>
        <td>${(s.avg_latency_s || 0).toFixed(2)}s</td>
        <td>${timeAgo(s.last_call)}</td>
      </tr>
    `).join('');
  }

  // ---- Full Refresh ----

  async function refreshAll() {
    const hours = parseInt($('#an-range-select')?.value || '24', 10);

    // Update freshness indicator
    const fresh = $('#an-freshness');
    if (fresh) fresh.innerHTML = '<span class="an-live-dot"></span> Loading…';

    const [fleet, ts, models, tools, heatmap] = await Promise.all([
      fetchFleet(),
      fetchTimeseries(hours),
      fetchModels(hours),
      fetchTools(hours),
      fetchHeatmap(),
    ]);

    renderKPIs(fleet);
    renderTokenChart(ts);
    renderModelChart(models);
    renderToolChart(tools);
    renderHeatmap(heatmap);
    renderSessions(fleet);

    if (fresh) fresh.innerHTML = '<span class="an-live-dot"></span> Live';
  }

  // ---- Analytics Studio Class ----

  class AnalyticsStudio {
    constructor() {
      this._inited = false;
    }

    toggle(show) {
      const panel = $('#analytics-studio');
      if (!panel) return;
      panel.style.display = show ? 'flex' : 'none';

      if (show && !this._inited) {
        this._init();
        this._inited = true;
      }

      if (show) {
        refreshAll();
        this._startPolling();
      } else {
        this._stopPolling();
      }
    }

    _init() {
      // Range select change
      const sel = $('#an-range-select');
      if (sel) sel.addEventListener('change', () => refreshAll());

      // Refresh button
      const btn = $('#an-refresh-btn');
      if (btn) btn.addEventListener('click', () => refreshAll());
    }

    _startPolling() {
      this._stopPolling();
      pollTimer = setInterval(() => refreshAll(), 15000);
    }

    _stopPolling() {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }
  }

  // Expose globally
  window.AnalyticsStudio = AnalyticsStudio;
})();
