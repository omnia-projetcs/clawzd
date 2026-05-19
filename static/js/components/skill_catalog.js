/**
 * Clawzd — SkillCatalog
 * Extracted from app.js for modular architecture.
 * Uses window globals for shared utilities (el, $, $$, toast, escHtml, icon, ICONS).
 */
/* global $, $$, el, toast, escHtml, icon, ICONS, OC */

// ---- Skill Catalog ----
class SkillCatalog {
  constructor() {
    this._overlay = $('#skills-catalog-overlay');
    this._grid = $('#skills-catalog-grid');
    this._subtitle = $('#skills-catalog-subtitle');
    this._searchInput = $('#skills-catalog-search-input');
    this._searchClear = $('#skills-search-clear');
    this._tabs = $('#skills-catalog-tabs');
    this._skills = [];
    this._activeFilter = 'all';
    this._searchQuery = '';

    // Search handler
    if (this._searchInput) {
      this._searchInput.addEventListener('input', () => {
        this._searchQuery = this._searchInput.value.toLowerCase().trim();
        if (this._searchClear) this._searchClear.classList.toggle('visible', this._searchQuery.length > 0);
        this._renderGrid();
      });
    }

    // Search clear button
    if (this._searchClear) {
      this._searchClear.addEventListener('click', () => {
        this._searchInput.value = '';
        this._searchQuery = '';
        this._searchClear.classList.remove('visible');
        this._renderGrid();
        this._searchInput.focus();
      });
    }

    // Tab handlers
    if (this._tabs) {
      this._tabs.addEventListener('click', (e) => {
        const tab = e.target.closest('.skills-cat-tab');
        if (!tab) return;
        this._tabs.querySelectorAll('.skills-cat-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        this._activeFilter = tab.dataset.cat;
        this._renderGrid();
      });
    }

    const btnCreateMiniApp = document.getElementById('btn-create-mini-app');
    if (btnCreateMiniApp) {
      btnCreateMiniApp.addEventListener('click', async () => {
        // Switch to the Application tab
        const appTab = this._tabs ? this._tabs.querySelector('[data-cat="application"]') : null;
        if (appTab) {
          this._tabs.querySelectorAll('.skills-cat-tab').forEach(t => t.classList.remove('active'));
          appTab.classList.add('active');
          this._activeFilter = 'application';
        }

        // Show ab-body and hide the skills grid
        const abBody = document.getElementById('ab-body');
        if (abBody) {
          abBody.style.display = 'block';
          abBody.dataset.loaded = 'true';
        }
        this._grid.style.display = 'none';

        // Ensure AppBuilderPanel data is loaded, then show the create form
        if (window.AppBuilderPanel) {
          await window.AppBuilderPanel.open();
          window.AppBuilderPanel.showCreate();
        }
      });
    }

    // Refresh button
    const btnRefresh = document.getElementById('skills-catalog-refresh');
    if (btnRefresh) {
      btnRefresh.addEventListener('click', () => this.refresh());
    }
  }

  async open() {
    this._overlay.classList.add('open');
    await this._loadSkills();
  }

  close() {
    this._overlay.classList.remove('open');
  }

  async _loadSkills() {
    try {
      const r = await fetch('/skills/catalog');
      const d = await r.json();
      this._skills = d.skills || [];
      this._subtitle.textContent = `${d.total} skills • ${d.active_count} active`;
      this._renderGrid();
    } catch (e) {
      this._subtitle.textContent = 'Error loading catalog';
      this._grid.innerHTML = '<div class="skills-catalog-empty">' + ICONS.x(14) + ' Failed to load skill catalog</div>';
    }
  }


  _renderGrid() {
    let filtered = this._skills;
    const abBody = document.getElementById('ab-body');
    const searchContainer = this._searchInput ? this._searchInput.parentElement : null;

    if (this._activeFilter === 'application') {
      this._grid.style.display = 'none';
      if (searchContainer) searchContainer.style.display = 'none';
      if (abBody) {
        abBody.style.display = 'block';
        if (window.AppBuilderPanel && !abBody.dataset.loaded) {
          window.AppBuilderPanel.open();
          abBody.dataset.loaded = 'true';
        }
      }
      return;
    } else {
      this._grid.style.display = '';
      if (searchContainer) searchContainer.style.display = '';
      if (abBody) abBody.style.display = 'none';
    }

    // Category filter
    if (this._activeFilter !== 'all') {
      filtered = filtered.filter(s => s.category === this._activeFilter);
    }

    // Search filter
    if (this._searchQuery) {
      filtered = filtered.filter(s =>
        s.name.toLowerCase().includes(this._searchQuery) ||
        (s.description || '').toLowerCase().includes(this._searchQuery) ||
        (s.category || '').toLowerCase().includes(this._searchQuery)
      );
    }

    if (!filtered.length) {
      this._grid.innerHTML = '<div class="skills-catalog-empty">No skills match your search.</div>';
      return;
    }

    // Sort: active first, then core, then alphabetical
    filtered.sort((a, b) => {
      if (a.active !== b.active) return a.active ? -1 : 1;
      if (a.source === 'core' && b.source !== 'core') return -1;
      if (b.source === 'core' && a.source !== 'core') return 1;
      return a.name.localeCompare(b.name);
    });

    this._grid.innerHTML = filtered.map(skill => this._renderCard(skill)).join('');

    // Bind toggle events
    this._grid.querySelectorAll('.skill-toggle input').forEach(inp => {
      inp.addEventListener('change', (e) => this._handleToggle(e.target));
    });

    // Close card menus after clicking a dropdown item
    this._grid.querySelectorAll('.ab-dd-item').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.ab-card-dropdown.open').forEach(d => d.classList.remove('open'));
      });
    });
  }

  _renderCard(skill) {
    const isCore = skill.source === 'core';
    const cardClass = isCore ? 'skill-card skill-core' : (skill.active ? 'skill-card skill-active' : 'skill-card');
    const catClass = `cat-${skill.category || 'other'}`;
    const srcClass = `src-${skill.source || 'user'}`;

    const categoryIcons = {
      code: ICONS.monitor(14), web: ICONS.globe ? ICONS.globe(14) : ICONS.link(14), media: ICONS.palette(14), data: ICONS.barChart(14),
      automation: ICONS.settings(14), integration: ICONS.link(14), other: ICONS.penTool(14)
    };
    const icon = categoryIcons[skill.category] || ICONS.penTool(14);

    const toggleHtml = isCore
      ? '<span class="skill-core-badge">ALWAYS ON</span>'
      : `<label class="skill-toggle">
           <input type="checkbox" data-skill="${escHtml(skill.name)}" ${skill.active ? 'checked' : ''}>
           <span class="skill-toggle-slider"></span>
         </label>`;

    const versionTag = skill.version && skill.version !== '—'
      ? `<span class="skill-meta-tag">${skill.version}</span>` : '';

    const usageTag = skill.usage_count
      ? `<span class="skill-meta-tag">${skill.usage_count}× used</span>` : '';

    return `
      <div class="${cardClass}" data-skill-name="${escHtml(skill.name)}">
        <div class="skill-card-header">
          <span class="skill-card-name">${icon} ${escHtml(skill.name)}</span>
          ${toggleHtml}
        </div>
        <div class="skill-card-desc">${escHtml(skill.description || 'No description')}</div>
        <div class="skill-card-meta">
          <span class="skill-meta-tag ${catClass}">${escHtml(skill.category || 'other')}</span>
          <span class="skill-meta-tag ${srcClass}">${escHtml(skill.source || 'user')}</span>
          ${versionTag}
          ${usageTag}
        </div>
      </div>`;
  }

  async _handleToggle(input) {
    const name = input.dataset.skill;
    const activate = input.checked;
    const url = activate ? `/skills/activate/${name}` : `/skills/deactivate/${name}`;

    try {
      const r = await fetch(url, { method: 'POST' });
      const d = await r.json();

      const card = input.closest('.skill-card');
      if (card) card.classList.toggle('skill-active', activate);

      this._subtitle.textContent = `${this._skills.length} skills • ${d.active_count} active`;

      const skill = this._skills.find(s => s.name === name);
      if (skill) skill.active = activate;

      this._updateBadge(d.active_count);

      toast(activate ? `${ICONS.bolt(14)} ${name} activated` : `${ICONS.link(14)} ${name} deactivated`);
    } catch (e) {
      input.checked = !activate;
      toast(ICONS.x(14) + ' Toggle failed');
    }
  }

  _updateBadge(count) {
    const badge = $('#skill-badge');
    const indicator = $('#input-skill-indicator');
    const countEl = $('#input-skill-count');

    if (badge) {
      badge.textContent = count;
      badge.style.display = count > 0 ? 'flex' : 'none';
    }
    if (indicator) {
      indicator.style.display = count > 0 ? 'inline-flex' : 'none';
    }
    if (countEl) {
      countEl.textContent = count;
    }
  }

  async refresh() {
    const btn = document.getElementById('skills-catalog-refresh');
    if (btn) btn.classList.add('spin');
    try {
      if (this._activeFilter === 'application' && window.AppBuilderPanel) {
        await window.AppBuilderPanel.open();
      } else {
        await this._loadSkills();
      }
      toast(`${ICONS.refresh ? ICONS.refresh(14) : ICONS.bolt(14)} Catalog refreshed`);
    } catch (e) {
      toast(ICONS.x(14) + ' Refresh failed');
    } finally {
      if (btn) btn.classList.remove('spin');
    }
  }

  async refreshBadge() {
    try {
      const r = await fetch('/skills/active');
      const d = await r.json();
      this._updateBadge(d.count || 0);
    } catch (e) { /* non-critical */ }
  }
}

// Backward compatibility
window.SkillCatalog = SkillCatalog;
