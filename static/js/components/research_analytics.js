/* Research Analytics Dashboard — renders charts and metrics from /research/analytics */
(function () {
  'use strict';

  class ResearchAnalytics {
    constructor() {
      this._data = null;
      this._panelEl = null;
    }

    /** Open the analytics panel and load data */
    async open() {
      this._ensurePanel();
      this._panelEl.style.display = 'flex';
      this._panelEl.querySelector('.ra-body').innerHTML =
        '<div class="ra-loading">⏳ Loading analytics…</div>';
      try {
        const res = await fetch('/research/analytics');
        this._data = await res.json();
        this._render();
      } catch (e) {
        this._panelEl.querySelector('.ra-body').innerHTML =
          `<div class="ra-error">⚠️ Failed to load: ${e.message}</div>`;
      }
    }

    close() {
      if (this._panelEl) this._panelEl.style.display = 'none';
    }

    toggle() {
      if (this._panelEl && this._panelEl.style.display !== 'none') this.close();
      else this.open();
    }

    _ensurePanel() {
      if (this._panelEl) return;
      const panel = document.createElement('div');
      panel.id = 'research-analytics-panel';
      panel.className = 'ra-panel';
      panel.innerHTML = `
        <div class="ra-header">
          <span class="ra-title">📊 Research Analytics</span>
          <button class="ra-close-btn" title="Close">✕</button>
        </div>
        <div class="ra-body"></div>
      `;
      document.body.appendChild(panel);
      this._panelEl = panel;
      panel.querySelector('.ra-close-btn').addEventListener('click', () => this.close());
    }

    _render() {
      const d = this._data;
      const body = this._panelEl.querySelector('.ra-body');

      body.innerHTML = `
        <!-- KPI Cards -->
        <div class="ra-kpis">
          ${this._kpiCard('📁', 'Projects', d.project_count)}
          ${this._kpiCard('✅', 'Completed', d.completed_count)}
          ${this._kpiCard('🔄', 'Iterations', d.total_iterations)}
          ${this._kpiCard('📈', 'Avg Score', d.avg_score + '%')}
          ${this._kpiCard('🏆', 'Best Score', d.best_score + '%')}
          ${this._kpiCard('⚡', 'Avg Iter/Proj', d.avg_iterations_per_project)}
        </div>

        <!-- Score Timeline -->
        <div class="ra-section">
          <h3 class="ra-section-title">Score Timeline</h3>
          <div class="ra-chart" id="ra-score-chart"></div>
        </div>

        <!-- Source Breakdown -->
        <div class="ra-section">
          <h3 class="ra-section-title">Source Breakdown</h3>
          <div class="ra-bars" id="ra-source-bars"></div>
        </div>

        <!-- Domain Stats -->
        <div class="ra-section">
          <h3 class="ra-section-title">Research Domains</h3>
          <div class="ra-domains" id="ra-domain-grid"></div>
        </div>

        <!-- Strategy Archive -->
        ${this._renderArchive(d.archive_stats)}

        <!-- Recent Projects -->
        <div class="ra-section">
          <h3 class="ra-section-title">Recent Projects</h3>
          <div class="ra-recent" id="ra-recent-list"></div>
        </div>
      `;

      this._renderScoreChart(d.score_timeline);
      this._renderSourceBars(d.source_breakdown);
      this._renderDomainGrid(d.domain_stats);
      this._renderRecentList(d.recent_projects);
    }

    _kpiCard(icon, label, value) {
      return `
        <div class="ra-kpi">
          <span class="ra-kpi-icon">${icon}</span>
          <span class="ra-kpi-value">${value}</span>
          <span class="ra-kpi-label">${label}</span>
        </div>`;
    }

    /** CSS-only mini bar chart for score timeline */
    _renderScoreChart(timeline) {
      const container = this._panelEl.querySelector('#ra-score-chart');
      if (!timeline || !timeline.length) {
        container.innerHTML = '<div class="ra-empty">No iterations yet</div>';
        return;
      }
      // Show last 30 data points
      const points = timeline.slice(-30);
      const maxScore = 100;
      container.innerHTML = `
        <div class="ra-bar-chart">
          ${points.map((p, i) => {
            const h = Math.max(2, (p.score / maxScore) * 100);
            const color = p.score >= 70 ? 'var(--green)' : p.score >= 40 ? 'var(--accent)' : 'var(--red)';
            return `<div class="ra-bar-col" title="${p.project}\nIter ${p.iteration}: ${p.score}%">
              <div class="ra-bar" style="height:${h}%;background:${color}"></div>
              <span class="ra-bar-label">${p.score}</span>
            </div>`;
          }).join('')}
        </div>
        <div class="ra-chart-legend">
          <span>← Oldest</span><span>Latest →</span>
        </div>
      `;
    }

    /** Horizontal bars for source type breakdown */
    _renderSourceBars(sources) {
      const container = this._panelEl.querySelector('#ra-source-bars');
      if (!sources || !Object.keys(sources).length) {
        container.innerHTML = '<div class="ra-empty">No sources yet</div>';
        return;
      }
      const entries = Object.entries(sources).sort((a, b) => b[1] - a[1]);
      const maxCount = entries[0][1];
      const colors = {
        tavily: '#6366f1', duckduckgo: '#f59e0b', scholar: '#10b981',
        reddit: '#ef4444', twitter: '#3b82f6', news: '#ec4899',
        semantic_scholar: '#8b5cf6', scholar_fallback: '#6ee7b7',
      };
      container.innerHTML = entries.map(([src, count]) => {
        const pct = Math.max(5, (count / maxCount) * 100);
        const color = colors[src] || 'var(--accent)';
        return `
          <div class="ra-hbar-row">
            <span class="ra-hbar-label">${this._esc(src)}</span>
            <div class="ra-hbar-track">
              <div class="ra-hbar-fill" style="width:${pct}%;background:${color}"></div>
            </div>
            <span class="ra-hbar-count">${count}</span>
          </div>`;
      }).join('');
    }

    /** Domain stats grid */
    _renderDomainGrid(domains) {
      const container = this._panelEl.querySelector('#ra-domain-grid');
      if (!domains || !Object.keys(domains).length) {
        container.innerHTML = '<div class="ra-empty">No domains yet</div>';
        return;
      }
      container.innerHTML = Object.entries(domains).map(([domain, stats]) => {
        const emoji = {
          technology: '💻', science: '🔬', finance: '💰', security: '🔒',
          business: '📊', geopolitics: '🌍', society: '👥', general: '📋',
        }[domain] || '📋';
        return `
          <div class="ra-domain-card">
            <span class="ra-domain-icon">${emoji}</span>
            <span class="ra-domain-name">${this._esc(domain)}</span>
            <span class="ra-domain-count">${stats.count} proj</span>
            <span class="ra-domain-score">${stats.avg_score}% avg</span>
          </div>`;
      }).join('');
    }

    /** Strategy archive section */
    _renderArchive(archive) {
      if (!archive || !archive.total) {
        return `<div class="ra-section"><h3 class="ra-section-title">🏛️ Strategy Archive</h3>
          <div class="ra-empty">No strategies archived yet</div></div>`;
      }
      const domainCards = Object.entries(archive.domains || {}).map(([d, s]) =>
        `<span class="ra-archive-domain">${d}: ${s.count} (best ${Math.round(s.best_score * 100)}%)</span>`
      ).join('');
      return `
        <div class="ra-section">
          <h3 class="ra-section-title">🏛️ Strategy Archive</h3>
          <div class="ra-archive-stats">
            <span>Total: <strong>${archive.total}</strong> strategies</span>
            <span>Avg score: <strong>${Math.round(archive.avg_score * 100)}%</strong></span>
          </div>
          <div class="ra-archive-domains">${domainCards}</div>
        </div>`;
    }

    /** Recent projects list */
    _renderRecentList(projects) {
      const container = this._panelEl.querySelector('#ra-recent-list');
      if (!projects || !projects.length) {
        container.innerHTML = '<div class="ra-empty">No projects yet</div>';
        return;
      }
      container.innerHTML = projects.map(p => {
        const statusClass = p.status === 'completed' ? 'done' :
          p.status === 'running' ? 'running' : 'idle';
        return `
          <div class="ra-recent-item">
            <div class="ra-recent-info">
              <span class="ra-recent-title">${this._esc(p.title)}</span>
              <span class="ra-recent-meta">${p.domain} · ${p.iterations} iter · ${p.sources_count} sources</span>
            </div>
            <span class="ra-recent-score">${p.score}%</span>
            <span class="ra-recent-status ${statusClass}">${p.status}</span>
          </div>`;
      }).join('');
    }

    _esc(s) {
      const d = document.createElement('div');
      d.textContent = s || '';
      return d.innerHTML;
    }
  }

  window.researchAnalytics = new ResearchAnalytics();
})();
