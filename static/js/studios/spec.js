/* Clawzd — Spec Studio Module (OpenSpec-inspired SDD) */
(function () {
  'use strict';
  function $(s, c) { return (c || document).querySelector(s) }
  function $$(s, c) { return Array.from((c || document).querySelectorAll(s)) }
  function toast(m) {
    const t = document.createElement('div');
    t.className = 'toast'; t.innerHTML = m;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3100);
  }

  const ARTIFACT_ORDER = ['proposal', 'specs', 'design', 'tasks'];

  class SpecStudio {
    constructor() {
      this._projId = null;
      this._changes = [];
      this._activeChange = null;
      this._activeArtifact = null;
      this._saveTimer = null;
    }

    /** Set the active project ID and render the spec studio panel */
    setProject(projId) {
      this._projId = projId;
      this._activeChange = null;
      this._activeArtifact = null;
      if (projId) this.loadChanges();
    }

    /** Render the full spec studio inside the given container */
    render(container) {
      if (!container) return;
      container.innerHTML = '';
      const wrap = document.createElement('div');
      wrap.className = 'spec-studio';
      wrap.id = 'spec-studio-root';
      container.appendChild(wrap);

      if (this._activeChange) {
        this._renderDetail(wrap);
      } else {
        this._renderList(wrap);
      }
    }

    // ── List View ──

    _renderList(wrap) {
      // Header
      const header = document.createElement('div');
      header.className = 'spec-header';
      header.innerHTML = `
        <div class="spec-title">
          <span class="spec-title-icon">S</span>
          Spec-Driven Changes
        </div>
        <div class="spec-actions">
          <button class="btn btn-primary btn-sm" id="spec-btn-new">+ New Change</button>
          <button class="btn btn-secondary btn-sm" id="spec-btn-specs">Main Specs</button>
          <button class="btn btn-secondary btn-sm" id="spec-btn-archive">Archive</button>
        </div>`;
      wrap.appendChild(header);

      header.querySelector('#spec-btn-new').addEventListener('click', () => this.createChange());
      header.querySelector('#spec-btn-specs').addEventListener('click', () => this._showMainSpecs(wrap));
      header.querySelector('#spec-btn-archive').addEventListener('click', () => this._showArchive(wrap));

      // Changes grid
      const grid = document.createElement('div');
      grid.className = 'spec-changes';
      grid.id = 'spec-changes-grid';
      wrap.appendChild(grid);

      if (!this._changes.length) {
        grid.innerHTML = `
          <div class="spec-empty" style="grid-column: 1/-1;">
            <div class="spec-empty-icon">📋</div>
            No changes yet.<br>
            Create a new change to start the spec-driven workflow.
          </div>`;
        return;
      }

      this._changes.forEach(ch => {
        const card = document.createElement('div');
        card.className = 'spec-change-card';
        const pct = ch.artifacts_total ? Math.round(ch.artifacts_done / ch.artifacts_total * 100) : 0;
        card.innerHTML = `
          <div class="spec-change-name">${this._esc(ch.name)}</div>
          <div class="spec-change-meta">
            <span class="spec-change-status ${ch.status}">${ch.status}</span>
            <span class="spec-change-progress">
              <span class="spec-change-progress-bar">
                <span class="spec-change-progress-fill" style="width:${pct}%"></span>
              </span>
              ${ch.artifacts_done}/${ch.artifacts_total}
            </span>
          </div>`;
        card.addEventListener('click', () => this.loadChange(ch.id));
        grid.appendChild(card);
      });
    }

    // ── Detail View ──

    _renderDetail(wrap) {
      const ch = this._activeChange;
      if (!ch) return;

      // Header
      const header = document.createElement('div');
      header.className = 'spec-detail-header';
      header.innerHTML = `
        <div style="display:flex;align-items:center;gap:10px;">
          <button class="spec-back-btn" id="spec-back">← Back</button>
          <span class="spec-detail-title">${this._esc(ch.name)}</span>
          <span class="spec-change-status ${ch.status}">${ch.status}</span>
        </div>
        <div class="spec-actions">
          <button class="btn btn-primary btn-sm" id="spec-btn-verify">✓ Verify</button>
          <button class="btn btn-secondary btn-sm" id="spec-btn-archive-change">Archive</button>
          <button class="btn btn-secondary btn-sm" id="spec-btn-delete-change" style="color:var(--red)">Delete</button>
        </div>`;
      wrap.appendChild(header);

      header.querySelector('#spec-back').addEventListener('click', () => {
        this._activeChange = null;
        this._activeArtifact = null;
        this.render($('#spec-studio-container'));
      });
      header.querySelector('#spec-btn-verify').addEventListener('click', () => this.verifyChange());
      header.querySelector('#spec-btn-archive-change').addEventListener('click', () => this.archiveChange());
      header.querySelector('#spec-btn-delete-change').addEventListener('click', () => this.deleteChange());

      // DAG
      this._renderDAG(wrap);

      // Editor for active artifact
      if (!this._activeArtifact) {
        // Default to first ready/blocked artifact
        const arts = ch.artifacts || {};
        this._activeArtifact = ARTIFACT_ORDER.find(a =>
          !arts[a]?.content
        ) || ARTIFACT_ORDER[0];
      }
      this._renderEditor(wrap);

      // Verification results
      if (ch.verification) {
        this._renderVerification(wrap, ch.verification);
      }
    }

    _renderDAG(wrap) {
      const ch = this._activeChange;
      const arts = ch.artifacts || {};
      const dag = document.createElement('div');
      dag.className = 'spec-dag';

      ARTIFACT_ORDER.forEach((aid, i) => {
        const art = arts[aid] || {};
        const status = art.content ? 'done' : art.status || 'blocked';
        const isActive = this._activeArtifact === aid;

        const node = document.createElement('div');
        node.className = 'spec-dag-node' + (isActive ? ' active' : '');
        node.innerHTML = `
          <div class="spec-dag-node-box ${status}">
            ${status === 'done' ? '✓' : status === 'ready' ? '●' : '○'}
          </div>
          <span class="spec-dag-label">${aid}</span>`;
        node.addEventListener('click', () => {
          this._activeArtifact = aid;
          this.render($('#spec-studio-container'));
        });
        dag.appendChild(node);

        if (i < ARTIFACT_ORDER.length - 1) {
          const arrow = document.createElement('div');
          arrow.className = 'spec-dag-arrow';
          arrow.textContent = '→';
          dag.appendChild(arrow);
        }
      });

      wrap.appendChild(dag);
    }

    _renderEditor(wrap) {
      const ch = this._activeChange;
      const aid = this._activeArtifact;
      const art = ch.artifacts?.[aid] || {};

      const edWrap = document.createElement('div');
      edWrap.className = 'spec-editor-wrap';

      const toolbar = document.createElement('div');
      toolbar.className = 'spec-editor-toolbar';
      toolbar.innerHTML = `
        <span class="spec-editor-artifact-name">${aid}</span>
        <div class="spec-editor-actions">
          <button class="btn btn-primary btn-sm" id="spec-btn-gen">✨ Generate AI</button>
          <button class="btn btn-secondary btn-sm" id="spec-btn-save-art">Save</button>
        </div>`;
      edWrap.appendChild(toolbar);

      const textarea = document.createElement('textarea');
      textarea.className = 'spec-editor-textarea';
      textarea.id = 'spec-editor-content';
      textarea.value = art.content || '';
      textarea.placeholder = `Write or generate the ${aid} artifact...`;
      edWrap.appendChild(textarea);

      // Auto-save
      textarea.addEventListener('input', () => {
        clearTimeout(this._saveTimer);
        this._saveTimer = setTimeout(() => this._saveArtifact(), 2000);
      });

      wrap.appendChild(edWrap);

      toolbar.querySelector('#spec-btn-gen').addEventListener('click', () => this.generateArtifact());
      toolbar.querySelector('#spec-btn-save-art').addEventListener('click', () => this._saveArtifact());
    }

    _renderVerification(wrap, v) {
      const panel = document.createElement('div');
      panel.className = 'spec-verify-panel';

      let scoresHtml = '';
      ['completeness', 'correctness', 'coherence'].forEach(axis => {
        const score = v[axis]?.score ?? 0;
        const pct = Math.round(score * 100);
        const color = pct >= 70 ? '#4ade80' : pct >= 40 ? '#fbbf24' : '#f87171';
        scoresHtml += `
          <div class="spec-verify-score">
            <span class="spec-verify-score-value" style="color:${color}">${pct}%</span>
            <span class="spec-verify-score-label">${axis}</span>
          </div>`;
      });

      const overallPct = Math.round((v.overall_score || 0) * 100);
      const overallColor = overallPct >= 70 ? '#4ade80' : overallPct >= 40 ? '#fbbf24' : '#f87171';
      scoresHtml += `
        <div class="spec-verify-score">
          <span class="spec-verify-score-value" style="color:${overallColor};font-size:22px">${overallPct}%</span>
          <span class="spec-verify-score-label">Overall</span>
        </div>`;

      let issuesHtml = '';
      (v.critical_issues || []).forEach(i => {
        issuesHtml += `<div class="spec-verify-issue critical"><span class="spec-verify-badge" style="background:rgba(239,68,68,0.2)">CRIT</span>${this._esc(i)}</div>`;
      });
      (v.warnings || []).forEach(i => {
        issuesHtml += `<div class="spec-verify-issue warning"><span class="spec-verify-badge" style="background:rgba(245,158,11,0.2)">WARN</span>${this._esc(i)}</div>`;
      });
      (v.suggestions || []).forEach(i => {
        issuesHtml += `<div class="spec-verify-issue suggestion"><span class="spec-verify-badge" style="background:rgba(59,130,246,0.2)">TIP</span>${this._esc(i)}</div>`;
      });

      panel.innerHTML = `
        <div class="spec-verify-title">Verification Results</div>
        <div class="spec-verify-scores">${scoresHtml}</div>
        ${issuesHtml ? `<div class="spec-verify-issues">${issuesHtml}</div>` : ''}`;

      wrap.appendChild(panel);
    }

    // ── API Methods ──

    async loadChanges() {
      if (!this._projId) return;
      try {
        const r = await fetch(`/spec/projects/${this._projId}/changes`);
        const d = await r.json();
        this._changes = d.changes || [];
        this.render($('#spec-studio-container'));
      } catch (e) {
        console.error('Failed to load changes', e);
      }
    }

    async loadChange(changeId) {
      if (!this._projId) return;
      try {
        const r = await fetch(`/spec/projects/${this._projId}/changes/${changeId}`);
        const d = await r.json();
        this._activeChange = d.change;
        this._activeArtifact = null;
        this.render($('#spec-studio-container'));
      } catch (e) {
        toast('Failed to load change');
      }
    }

    async createChange() {
      if (!this._projId) { toast('Load a project first'); return; }
      const name = prompt('Change name:', 'New Feature');
      if (!name?.trim()) return;
      const desc = prompt('Brief description (optional):', '');

      try {
        const r = await fetch(`/spec/projects/${this._projId}/changes`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: name.trim(), description: desc || '' }),
        });
        const d = await r.json();
        this._activeChange = d.change;
        this._activeArtifact = 'proposal';
        this.render($('#spec-studio-container'));
        toast('✅ Change created: ' + name.trim());
      } catch (e) {
        toast('Failed to create change');
      }
    }

    async _saveArtifact() {
      if (!this._projId || !this._activeChange || !this._activeArtifact) return;
      const content = $('#spec-editor-content')?.value || '';
      try {
        await fetch(
          `/spec/projects/${this._projId}/changes/${this._activeChange.id}/artifacts/${this._activeArtifact}`,
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content }),
          }
        );
        // Update local state
        if (!this._activeChange.artifacts) this._activeChange.artifacts = {};
        if (!this._activeChange.artifacts[this._activeArtifact]) {
          this._activeChange.artifacts[this._activeArtifact] = {};
        }
        this._activeChange.artifacts[this._activeArtifact].content = content;
        // Re-render DAG only
        const dagEl = $('.spec-dag', $('#spec-studio-root'));
        if (dagEl) {
          const parent = dagEl.parentElement;
          dagEl.remove();
          const newDag = document.createElement('div');
          parent.insertBefore(newDag, parent.children[1]);
          this._renderDAGInto(newDag);
        }
      } catch (e) {
        console.error('Save artifact failed', e);
      }
    }

    _renderDAGInto(container) {
      const ch = this._activeChange;
      const arts = ch.artifacts || {};
      container.className = 'spec-dag';
      container.innerHTML = '';

      ARTIFACT_ORDER.forEach((aid, i) => {
        const art = arts[aid] || {};
        const status = art.content ? 'done' : art.status || 'blocked';
        const isActive = this._activeArtifact === aid;

        const node = document.createElement('div');
        node.className = 'spec-dag-node' + (isActive ? ' active' : '');
        node.innerHTML = `
          <div class="spec-dag-node-box ${status}">
            ${status === 'done' ? '✓' : status === 'ready' ? '●' : '○'}
          </div>
          <span class="spec-dag-label">${aid}</span>`;
        node.addEventListener('click', () => {
          this._activeArtifact = aid;
          this.render($('#spec-studio-container'));
        });
        container.appendChild(node);

        if (i < ARTIFACT_ORDER.length - 1) {
          const arrow = document.createElement('div');
          arrow.className = 'spec-dag-arrow';
          arrow.textContent = '→';
          container.appendChild(arrow);
        }
      });
    }

    async generateArtifact() {
      if (!this._projId || !this._activeChange || !this._activeArtifact) return;

      const ta = $('#spec-editor-content');
      if (!ta) return;

      ta.classList.add('loading');
      toast('✨ Generating ' + this._activeArtifact + '...');

      try {
        const r = await fetch(
          `/spec/projects/${this._projId}/changes/${this._activeChange.id}/generate/${this._activeArtifact}`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
          }
        );
        if (!r.ok) {
          const err = await r.json();
          toast('❌ ' + (err.detail || 'Generation failed'));
          ta.classList.remove('loading');
          return;
        }
        const d = await r.json();
        ta.value = d.content || '';
        ta.classList.remove('loading');

        // Track token usage
        if (d.token_usage && window.tokenTracker) {
          window.tokenTracker.addUsage(d.token_usage);
        }

        // Update local state
        if (!this._activeChange.artifacts) this._activeChange.artifacts = {};
        if (!this._activeChange.artifacts[this._activeArtifact]) {
          this._activeChange.artifacts[this._activeArtifact] = {};
        }
        this._activeChange.artifacts[this._activeArtifact].content = d.content;

        // Move to next artifact
        const nextIdx = ARTIFACT_ORDER.indexOf(this._activeArtifact) + 1;
        if (nextIdx < ARTIFACT_ORDER.length) {
          // Re-render to update DAG
          this.render($('#spec-studio-container'));
        }
        toast('✅ ' + this._activeArtifact + ' generated!');
      } catch (e) {
        ta.classList.remove('loading');
        toast('❌ Generation failed: ' + e.message);
      }
    }

    async verifyChange() {
      if (!this._projId || !this._activeChange) return;
      toast('🔍 Verifying change...');
      try {
        const r = await fetch(
          `/spec/projects/${this._projId}/changes/${this._activeChange.id}/verify`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
          }
        );
        const d = await r.json();
        this._activeChange.verification = d.verification;
        // Track token usage
        if (d.token_usage && window.tokenTracker) {
          window.tokenTracker.addUsage(d.token_usage);
        }
        this.render($('#spec-studio-container'));
        const pct = Math.round((d.verification?.overall_score || 0) * 100);
        toast(`✅ Verification complete: ${pct}% overall`);
      } catch (e) {
        toast('❌ Verification failed');
      }
    }

    async archiveChange() {
      if (!this._projId || !this._activeChange) return;
      if (!confirm('Archive this change? Delta specs will be merged into main specs.')) return;
      try {
        const r = await fetch(
          `/spec/projects/${this._projId}/changes/${this._activeChange.id}/archive`,
          { method: 'POST' }
        );
        const d = await r.json();
        this._activeChange = null;
        this._activeArtifact = null;
        this.loadChanges();
        toast('📦 Change archived' + (d.specs_merged ? ' — specs merged!' : ''));
      } catch (e) {
        toast('❌ Archive failed');
      }
    }

    async deleteChange() {
      if (!this._projId || !this._activeChange) return;
      if (!confirm('Delete this change permanently?')) return;
      try {
        await fetch(
          `/spec/projects/${this._projId}/changes/${this._activeChange.id}`,
          { method: 'DELETE' }
        );
        this._activeChange = null;
        this._activeArtifact = null;
        this.loadChanges();
        toast('🗑️ Change deleted');
      } catch (e) {
        toast('❌ Delete failed');
      }
    }

    async _showMainSpecs(wrap) {
      if (!this._projId) return;
      try {
        const r = await fetch(`/spec/projects/${this._projId}/specs`);
        const d = await r.json();

        wrap.innerHTML = '';

        const header = document.createElement('div');
        header.className = 'spec-detail-header';
        header.innerHTML = `
          <div style="display:flex;align-items:center;gap:10px;">
            <button class="spec-back-btn" id="spec-main-back">← Back</button>
            <span class="spec-detail-title">Main Project Specs</span>
          </div>
          <div class="spec-actions">
            <button class="btn btn-primary btn-sm" id="spec-main-save">Save</button>
          </div>`;
        wrap.appendChild(header);

        header.querySelector('#spec-main-back').addEventListener('click', () => {
          this.render($('#spec-studio-container'));
        });

        const ta = document.createElement('textarea');
        ta.className = 'spec-editor-textarea';
        ta.id = 'spec-main-content';
        ta.value = d.specs || '';
        ta.placeholder = 'Main project specifications (merged from archived changes)...';
        ta.style.minHeight = '400px';
        wrap.appendChild(ta);

        header.querySelector('#spec-main-save').addEventListener('click', async () => {
          try {
            await fetch(`/spec/projects/${this._projId}/specs`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ content: ta.value }),
            });
            toast('✅ Main specs saved');
          } catch (e) {
            toast('❌ Save failed');
          }
        });
      } catch (e) {
        toast('❌ Failed to load specs');
      }
    }

    async _showArchive(wrap) {
      if (!this._projId) return;
      try {
        const r = await fetch(`/spec/projects/${this._projId}/archive`);
        const d = await r.json();

        wrap.innerHTML = '';

        const header = document.createElement('div');
        header.className = 'spec-detail-header';
        header.innerHTML = `
          <div style="display:flex;align-items:center;gap:10px;">
            <button class="spec-back-btn" id="spec-archive-back">← Back</button>
            <span class="spec-detail-title">Archived Changes</span>
          </div>`;
        wrap.appendChild(header);

        header.querySelector('#spec-archive-back').addEventListener('click', () => {
          this.render($('#spec-studio-container'));
        });

        const list = document.createElement('div');
        list.className = 'spec-archive-list';

        if (!d.archive?.length) {
          list.innerHTML = '<div class="spec-empty">No archived changes yet.</div>';
        } else {
          d.archive.forEach(a => {
            const item = document.createElement('div');
            item.className = 'spec-archive-item';
            item.innerHTML = `
              <span>${this._esc(a.name)}</span>
              <span class="spec-archive-date">${a.archived_at?.slice(0, 10) || ''}</span>`;
            list.appendChild(item);
          });
        }

        wrap.appendChild(list);
      } catch (e) {
        toast('❌ Failed to load archive');
      }
    }

    // ── Helpers ──

    _esc(s) {
      const d = document.createElement('div');
      d.textContent = s || '';
      return d.innerHTML;
    }
  }

  window.SpecStudio = SpecStudio;
})();
