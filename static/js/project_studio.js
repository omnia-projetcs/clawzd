/* Clawzd — Project Studio Module */
(function () {
  'use strict';
  function $(s, c) { return (c || document).querySelector(s) }
  function $$(s, c) { return Array.from((c || document).querySelectorAll(s)) }
  function toast(m) { const t = document.createElement('div'); t.className = 'toast'; t.innerHTML = m; document.body.appendChild(t); setTimeout(() => t.remove(), 3100) }

  class ProjectStudio {
    constructor() {
      this.layout = $('#project-layout');
      this.currentProj = null;
      this.view = 'kanban';
      this._saveTimer = null;
      this._sortCol = null;
      this._sortDir = 1;
      this._loadingFirst = false;
      this._init();
    }
    _init() {
      $('#proj-btn-new')?.addEventListener('click', () => this.createProject());
      $('#proj-btn-add-member')?.addEventListener('click', () => this.addMember());
      $('#proj-btn-add-col')?.addEventListener('click', () => this.addColumn());
      $('#proj-btn-add-task')?.addEventListener('click', () => this.addTask());
      $('#proj-btn-ai-generate')?.addEventListener('click', () => this.generateAI());
      $('#proj-ai-prompt')?.addEventListener('keypress', e => { if (e.key === 'Enter') this.generateAI() });
      $('#proj-name-input')?.addEventListener('input', () => {
        const btn = $('#proj-btn-save-name');
        if (btn) btn.style.display = 'inline-block';
      });
      $('#proj-btn-save-name')?.addEventListener('click', () => {
        this.saveProject();
        $('#proj-btn-save-name').style.display = 'none';
        toast(ICONS.check(14) + ' Nom du projet appliqué');
      });
      // Import TXT
      $('#proj-btn-import-txt')?.addEventListener('click', () => {
        $('#proj-import-txt-input')?.click();
        $('#proj-actions-dropdown')?.classList.remove('open');
      });
      $('#proj-import-txt-input')?.addEventListener('change', e => this.importTxt(e));
      // View toggle
      $$('#proj-view-toggle .proj-view-btn').forEach(b => {
        b.addEventListener('click', () => {
          $$('#proj-view-toggle .proj-view-btn').forEach(x => x.classList.remove('active'));
          b.classList.add('active');
          this.view = b.dataset.view;
          this._showView();
        });
      });
      // Actions dropdown
      $('#proj-btn-actions')?.addEventListener('click', () => {
        $('#proj-actions-dropdown')?.classList.toggle('open');
      });
      document.addEventListener('click', e => {
        if (!e.target.closest('#proj-actions-dropdown')) $('#proj-actions-dropdown')?.classList.remove('open');
      });
      $('#proj-export-excel')?.addEventListener('click', () => this.exportExcel());
      $('#proj-export-pres')?.addEventListener('click', () => this.exportPresentation());
      // GitHub
      $('#proj-btn-github')?.addEventListener('click', () => {
        $('#proj-github-overlay')?.classList.add('open');
        $('#proj-actions-dropdown')?.classList.remove('open');
      });
      $('#proj-github-close')?.addEventListener('click', () => $('#proj-github-overlay')?.classList.remove('open'));
      $('#proj-github-overlay')?.addEventListener('click', e => { if (e.target.id === 'proj-github-overlay') e.target.classList.remove('open') });
      $('#proj-github-push')?.addEventListener('click', () => this.githubPush());
      $('#proj-github-import')?.addEventListener('click', () => this.githubImport());
      // Trivy
      $('#proj-btn-trivy')?.addEventListener('click', () => this.trivyScan());
      // Internet Research
      $('#proj-btn-research')?.addEventListener('click', () => this.internetResearch());
      // Transfer to Editor
      $('#proj-btn-sync-editor')?.addEventListener('click', () => {
        this.syncWithEditor();
        $('#proj-actions-dropdown')?.classList.remove('open');
      });
      $('#proj-btn-to-editor')?.addEventListener('click', () => {
        this.transferToEditor();
        $('#proj-actions-dropdown')?.classList.remove('open');
      });
      // Task modal
      $('#proj-task-close')?.addEventListener('click', () => $('#proj-task-overlay')?.classList.remove('open'));
      $('#proj-task-overlay')?.addEventListener('click', e => { if (e.target.id === 'proj-task-overlay') e.target.classList.remove('open') });
      $('#proj-task-save')?.addEventListener('click', () => this.saveTaskModal());
      $('#proj-task-delete')?.addEventListener('click', () => this.deleteTaskModal());
      $('#proj-task-progress')?.addEventListener('input', e => { $('#proj-task-progress-val').textContent = e.target.value + '%' });
      // Table sort
      $$('.proj-table th[data-sort]').forEach(th => {
        th.addEventListener('click', () => this._sortTable(th.dataset.sort));
      });
      this.loadProjects();
    }
    toggle(show) {
      if (this.layout) this.layout.style.display = show ? 'flex' : 'none';
      if (show) this.loadProjects();
    }
    _showView() {
      ['kanban', 'table', 'timeline'].forEach(v => {
        const el = $(`#proj-${v}-view`);
        if (el) el.classList.toggle('active', v === this.view);
      });
      // Specs view toggle
      const specsView = $('#proj-specs-view');
      if (specsView) specsView.style.display = this.view === 'specs' ? 'flex' : 'none';
      // Hide other views when specs is active
      if (this.view === 'specs') {
        ['kanban', 'table', 'timeline'].forEach(v => {
          const el = $(`#proj-${v}-view`);
          if (el) el.classList.remove('active');
        });
      }
      this._render();
    }
    _render() {
      if (!this.currentProj) return;
      if (this.view === 'kanban') this.renderKanban();
      else if (this.view === 'table') this.renderTable();
      else if (this.view === 'timeline') this.renderTimeline();
      else if (this.view === 'specs') this._renderSpecs();
      this.renderMembers();
    }
    _renderSpecs() {
      if (!this.currentProj) return;
      if (!this._specStudio) {
        this._specStudio = new window.SpecStudio();
      }
      this._specStudio.setProject(this.currentProj.id);
    }
    _autoSave() {
      clearTimeout(this._saveTimer);
      this._saveTimer = setTimeout(() => this.saveProject(), 1000);
    }

    // ── Project CRUD ──
    async loadProjects() {
      try {
        const r = await fetch('/project/projects');
        const d = await r.json();
        const list = $('#proj-list');
        if (!list) return;
        const projs = d.projects || [];
        if (!projs.length) { list.innerHTML = '<div class="proj-list-empty">No projects yet.<br>Click + to create one.</div>'; return; }

        let shouldLoadFirst = false;
        if (!this.currentProj && !this._loadingFirst && projs.length > 0) {
          shouldLoadFirst = true;
          this._loadingFirst = true;
        }

        list.innerHTML = '';
        projs.forEach(p => {
          const item = document.createElement('div');
          item.className = 'proj-list-item' + (this.currentProj?.id === p.id ? ' active' : '');
          item.innerHTML = `<span class="proj-list-item-name">${p.name}</span><span class="proj-list-item-count">${p.task_count}</span><span class="proj-list-item-delete" title="Delete">${ICONS.x(14)}</span>`;
          item.querySelector('.proj-list-item-name').addEventListener('click', () => this.loadProject(p.id));
          item.querySelector('.proj-list-item-delete').addEventListener('click', async e => {
            e.stopPropagation();
            if (!confirm('Delete project "' + p.name + '"?')) return;
            await fetch(`/project/projects/${p.id}`, { method: 'DELETE' });
            if (this.currentProj?.id === p.id) { this.currentProj = null; this._clearViews(); }
            this.loadProjects();
            toast(ICONS.trash(14) + ' Project deleted');
          });
          list.appendChild(item);
        });

        if (shouldLoadFirst) {
          this.loadProject(projs[0].id);
        }
      } catch (e) { console.error('Failed to load projects', e) }
    }
    async loadProject(id) {
      try {
        const r = await fetch(`/project/projects/${id}`);
        const d = await r.json();
        this.currentProj = d.project;
        const ni = $('#proj-name-input');
        if (ni) ni.value = this.currentProj.name || '';
        const btn = $('#proj-btn-save-name');
        if (btn) btn.style.display = 'none';
        if (this.currentProj.github_repo) {
          const gi = $('#proj-github-repo');
          if (gi) gi.value = this.currentProj.github_repo;
        }
        this._render();
        this.loadProjects();
        toast(ICONS.folderOpen(14) + ' Loaded: ' + this.currentProj.name);
      } catch (e) { toast(ICONS.x(14) + ' Failed to load project') }
    }
    async createProject() {
      const name = prompt('Project name:', 'New Project');
      if (!name?.trim()) return;
      try {
        const r = await fetch('/project/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name.trim() }) });
        const d = await r.json();
        this.currentProj = d.project;
        const ni = $('#proj-name-input'); if (ni) ni.value = name.trim();
        this._render(); this.loadProjects();
        toast(ICONS.check(14) + ' Project created: ' + name.trim());
      } catch (e) { toast(ICONS.x(14) + ' Failed to create project') }
    }
    async saveProject() {
      if (!this.currentProj) return;
      const ni = $('#proj-name-input');
      if (ni) this.currentProj.name = ni.value;
      try {
        await fetch(`/project/projects/${this.currentProj.id}`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: this.currentProj.name, columns: this.currentProj.columns, members: this.currentProj.members, tasks: this.currentProj.tasks })
        });
        this.loadProjects();
      } catch (e) { console.error('Save failed', e) }
    }
    _clearViews() {
      const k = $('#proj-kanban'); if (k) k.innerHTML = '';
      const t = $('#proj-table-body'); if (t) t.innerHTML = '';
      const tl = $('#proj-timeline'); if (tl) tl.innerHTML = '';
      const ni = $('#proj-name-input'); if (ni) ni.value = '';
      const btn = $('#proj-btn-save-name'); if (btn) btn.style.display = 'none';
    }

    // ── Members ──
    addMember() {
      const name = prompt('Member name:');
      if (!name?.trim() || !this.currentProj) return;
      if (!this.currentProj.members.includes(name.trim())) {
        this.currentProj.members.push(name.trim());
        this.renderMembers(); this._autoSave();
      }
    }
    renderMembers() {
      const el = $('#proj-members'); if (!el || !this.currentProj) return;
      if (!this.currentProj.members.length) { el.innerHTML = '<div class="proj-members-empty">No members assigned.</div>'; return; }
      el.innerHTML = '';
      this.currentProj.members.forEach(m => {
        const chip = document.createElement('span'); chip.className = 'proj-member-chip';
        const initial = m.charAt(0).toUpperCase();
        chip.innerHTML = `<span class="proj-member-avatar">${initial}</span>${m}<span class="remove">${ICONS.x(14)}</span>`;
        chip.querySelector('.remove').addEventListener('click', () => {
          if (!confirm(`Remove member "${m}"? Tasks assigned to them will be unassigned.`)) return;
          this.currentProj.members = this.currentProj.members.filter(x => x !== m);
          let count = 0;
          this.currentProj.tasks.forEach(t => {
            if (t.assignee === m) { t.assignee = ''; count++; }
          });
          this.renderMembers(); this._render(); this._autoSave();
          if (count > 0) toast(`${ICONS.circle(14)} {ICONS.circleSlash(14)} ${count} tasks are now not attributed`);
        });
        el.appendChild(chip);
      });
    }

    // ── Trivy Security Scan ──
    async trivyScan() {
      if (!this.currentProj) { toast('Load a project first'); return; }
      const path = prompt('Path to scan (relative to workspace, or "." for all):', '.');
      if (path === null) return;
      const scanType = prompt('Scan type: fs (filesystem), secret (secrets/tokens), both:', 'both');
      if (!scanType) return;

      toast(ICONS.shield(14) + ' Running Trivy scan...');
      $('#proj-actions-dropdown')?.classList.remove('open');

      try {
        const r = await fetch(`/project/projects/${this.currentProj.id}/scan/trivy`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: path || '.', type: scanType || 'both' })
        });
        const d = await r.json();

        if (d.status === 'error') {
          toast(ICONS.x(14) + ' ' + d.message);
          return;
        }

        const count = d.vulnerabilities || 0;
        if (count === 0) {
          toast(ICONS.check(14) + ' No vulnerabilities or secrets found!');
          return;
        }

        const importAll = confirm(
          `Trivy found ${count} issue(s):\n\n` +
          (d.tasks || []).slice(0, 5).map(t => `• ${t.title}`).join('\n') +
          (count > 5 ? `\n... and ${count - 5} more` : '') +
          '\n\nImport all as project tasks?'
        );

        if (importAll && d.tasks?.length) {
          const ir = await fetch(`/project/projects/${this.currentProj.id}/scan/trivy/apply`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tasks: d.tasks })
          });
          const id = await ir.json();
          toast(ICONS.check(14) + ` Imported ${id.imported} security tasks`);
          await this.loadProject(this.currentProj.id);
        }
      } catch (e) {
        toast(ICONS.x(14) + ' Trivy scan failed: ' + e.message);
      }
    }

    // ── Internet Research ──
    async internetResearch() {
      if (!this.currentProj) { toast('Load a project first'); return; }
      const query = prompt('Research query (default: project name):', this.currentProj.name);
      if (query === null) return;
      const topicsStr = prompt(
        'Research topics (comma-separated):',
        'best practices, security vulnerabilities, architecture patterns, recommended tools'
      );
      if (topicsStr === null) return;

      const topics = topicsStr.split(',').map(t => t.trim()).filter(Boolean);
      toast(ICONS.search(14) + ' Searching the web...');
      $('#proj-actions-dropdown')?.classList.remove('open');

      try {
        const r = await fetch(`/project/projects/${this.currentProj.id}/research`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: query || this.currentProj.name, topics })
        });
        const d = await r.json();

        let msg = `Found ${d.total_results} results.\n\n`;
        if (d.summary) msg += `Summary: ${d.summary}\n\n`;

        const tasks = d.suggested_tasks || [];
        if (tasks.length) {
          msg += `${tasks.length} suggested tasks:\n` +
            tasks.slice(0, 5).map(t => `• ${t.title}`).join('\n');
        }

        const importTasks = tasks.length && confirm(
          msg + '\n\nImport suggested tasks into the project?'
        );

        if (importTasks) {
          const ir = await fetch(`/project/projects/${this.currentProj.id}/scan/trivy/apply`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tasks })
          });
          const id = await ir.json();
          toast(ICONS.check(14) + ` Imported ${id.imported} research tasks`);
          await this.loadProject(this.currentProj.id);
        } else {
          toast(ICONS.check(14) + ` Research complete. ${d.total_results} results found.`);
        }
      } catch (e) {
        toast(ICONS.x(14) + ' Research failed: ' + e.message);
      }
    }

    // ── Columns ──
    deleteColumn(col) {
      if (!this.currentProj) return;
      const tasksInCol = (this.currentProj.tasks || []).filter(t => t.status === col);
      if (tasksInCol.length > 0) {
        toast(`${ICONS.circle(14)} {ICONS.circleSlash(14)} Move or delete the ${tasksInCol.length} task(s) in "${col}" before removing it.`);
        return;
      }
      if (!confirm(`Delete column "${col}"?`)) return;
      this.currentProj.columns = this.currentProj.columns.filter(c => c !== col);
      this.renderKanban(); this._autoSave();
      toast(`${ICONS.circle(14)} {ICONS.trash(14)} Column "${col}" deleted`);
    }
    addColumn() {
      if (!this.currentProj) return;
      const name = prompt('Column name:');
      if (!name?.trim()) return;
      this.currentProj.columns.push(name.trim());
      this._render(); this._autoSave();
    }

    // ── KANBAN ──
    renderKanban() {
      const container = $('#proj-kanban'); if (!container || !this.currentProj) return;
      container.innerHTML = '';
      this.currentProj.columns.forEach(col => {
        const tasks = (this.currentProj.tasks || []).filter(t => t.status === col).sort((a, b) => (a.order || 0) - (b.order || 0));
        const colEl = document.createElement('div'); colEl.className = 'proj-kanban-col'; colEl.dataset.status = col;
        colEl.innerHTML = `<div class="proj-kanban-col-header"><span>${col} <span class="proj-kanban-col-count">${tasks.length}</span></span><div style="display:flex;gap:4px"><button class="proj-kanban-col-add" title="Add task">+</button><button class="proj-kanban-col-del" title="Delete column" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:13px;padding:0 2px;line-height:1;transition:color .15s" onmouseover="this.style.color='var(--red)'" onmouseout="this.style.color='var(--text-muted)'">${ICONS.x(14)}</button></div></div><div class="proj-kanban-col-body"></div>`;
        const body = colEl.querySelector('.proj-kanban-col-body');
        colEl.querySelector('.proj-kanban-col-add').addEventListener('click', () => this.addTask(col));
        colEl.querySelector('.proj-kanban-col-del').addEventListener('click', () => this.deleteColumn(col));
        // Drag & drop on column
        colEl.addEventListener('dragover', e => { e.preventDefault(); colEl.classList.add('drag-over') });
        colEl.addEventListener('dragleave', () => colEl.classList.remove('drag-over'));
        colEl.addEventListener('drop', e => {
          e.preventDefault(); colEl.classList.remove('drag-over');
          const tid = e.dataTransfer.getData('text/plain');
          if (!tid) return;
          this._moveTask(tid, col, tasks.length);
        });
        tasks.forEach((task, idx) => {
          const card = this._createCard(task);
          card.setAttribute('draggable', 'true');
          card.addEventListener('dragstart', e => {
            e.dataTransfer.setData('text/plain', task.id);
            card.classList.add('dragging');
            setTimeout(() => card.style.display = 'none', 0);
          });
          card.addEventListener('dragend', () => { card.classList.remove('dragging'); card.style.display = '' });
          card.addEventListener('click', () => this.openTaskDetail(task.id));
          body.appendChild(card);
        });
        container.appendChild(colEl);
      });
    }
    _createCard(task) {
      const card = document.createElement('div'); card.className = 'proj-kanban-card'; card.dataset.taskId = task.id;
      const isOverdue = task.deadline && new Date(task.deadline) < new Date() && task.status !== 'Done';
      let html = `<div class="proj-kanban-card-title">${task.title || 'Untitled'}</div>`;
      html += `<div class="proj-kanban-card-meta"><span class="proj-card-priority ${task.priority || 'medium'}"></span>`;
      if (task.assignee) html += `<span class="proj-card-assignee">${task.assignee}</span>`;
      else html += `<span class="proj-card-assignee unassigned">${ICONS.circleSlash(14)} Unassigned</span>`;
      if (task.deadline) html += `<span class="proj-card-deadline${isOverdue ? ' overdue' : ''}">${task.deadline}</span>`;
      html += `</div>`;
      if (task.progress > 0) html += `<div class="proj-card-progress"><div class="proj-card-progress-fill" style="width:${task.progress}%"></div></div>`;
      if (task.tags?.length) html += `<div class="proj-card-tags">${task.tags.map(t => `<span class="proj-card-tag">${t}</span>`).join('')}</div>`;
      card.innerHTML = html; return card;
    }
    async _moveTask(taskId, newStatus, newOrder) {
      const task = this.currentProj.tasks.find(t => t.id === taskId);
      if (!task) return;
      task.status = newStatus; task.order = newOrder;
      this.renderKanban();
      try {
        await fetch(`/project/projects/${this.currentProj.id}/reorder`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task_id: taskId, new_status: newStatus, new_order: newOrder })
        });
      } catch (e) { console.error('Reorder failed', e) }
    }
    async addTask(status) {
      if (!this.currentProj) return;
      const targetStatus = status || (this.currentProj.columns && this.currentProj.columns[0]) || 'To Do';
      const title = prompt('Task title:');
      if (!title?.trim()) return;
      try {
        const r = await fetch(`/project/projects/${this.currentProj.id}/tasks`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: title.trim(), status: targetStatus })
        });
        const d = await r.json();
        this.currentProj.tasks.push(d.task);
        this._render(); this.loadProjects();
      } catch (e) { toast(ICONS.x(14) + ' Failed to add task') }
    }

    // ── TABLE ──
    renderTable() {
      const tbody = $('#proj-table-body'); if (!tbody || !this.currentProj) return;
      let tasks = [...(this.currentProj.tasks || [])];
      if (this._sortCol) {
        tasks.sort((a, b) => {
          let va = a[this._sortCol] ?? '', vb = b[this._sortCol] ?? '';
          if (typeof va === 'number') return (va - vb) * this._sortDir;
          return String(va).localeCompare(String(vb)) * this._sortDir;
        });
      }
      tbody.innerHTML = '';
      tasks.forEach(task => {
        const tr = document.createElement('tr');
        const assigneeHtml = task.assignee ? task.assignee : `<span class="proj-table-unassigned">${ICONS.circleSlash(14)} Unassigned</span>`;
        tr.innerHTML = `<td>${task.title || ''}</td><td>${task.status || ''}</td><td>${assigneeHtml}</td><td><span class="proj-table-priority ${task.priority || 'medium'}">${task.priority || 'medium'}</span></td><td><div class="proj-table-progress"><div class="proj-table-progress-bar"><div class="proj-table-progress-fill" style="width:${task.progress || 0}%"></div></div><span>${task.progress || 0}%</span></div></td><td>${task.deadline || '—'}</td><td>${task.estimated_hours || 0}h</td><td>$${task.estimated_cost || 0}</td><td class="proj-table-actions"><button class="icon-btn" title="Edit">${ICONS.pen(14)}</button><button class="icon-btn" title="Delete" style="color:var(--red)">${ICONS.x(14)}</button></td>`;
        tr.querySelector('.icon-btn[title="Edit"]').addEventListener('click', e => { e.stopPropagation(); this.openTaskDetail(task.id) });
        tr.querySelector('.icon-btn[title="Delete"]').addEventListener('click', e => { e.stopPropagation(); this._deleteTask(task.id) });
        tr.addEventListener('click', () => this.openTaskDetail(task.id));
        tbody.appendChild(tr);
      });
    }
    _sortTable(col) {
      if (this._sortCol === col) this._sortDir *= -1;
      else { this._sortCol = col; this._sortDir = 1; }
      $$('.proj-table th').forEach(th => th.classList.remove('sorted'));
      $(`.proj-table th[data-sort="${col}"]`)?.classList.add('sorted');
      this.renderTable();
    }

    // ── TIMELINE ──
    renderTimeline() {
      const container = $('#proj-timeline'); if (!container || !this.currentProj) return;
      const tasks = this.currentProj.tasks || [];
      if (!tasks.length) { container.innerHTML = '<div class="proj-timeline-empty">No tasks with dates to display.<br>Add tasks with start dates and deadlines.</div>'; return; }
      // Compute date range
      const now = new Date();
      let minD = new Date(now), maxD = new Date(now);
      minD.setDate(minD.getDate() - 7); maxD.setDate(maxD.getDate() + 30);
      tasks.forEach(t => {
        if (t.start_date) { const d = new Date(t.start_date); if (d < minD) minD = new Date(d) }
        if (t.deadline) { const d = new Date(t.deadline); if (d > maxD) maxD = new Date(d) }
      });
      maxD.setDate(maxD.getDate() + 7);
      const days = []; for (let d = new Date(minD); d <= maxD; d.setDate(d.getDate() + 1))days.push(new Date(d));
      const totalDays = days.length; const todayStr = now.toISOString().slice(0, 10);
      let html = '<div class="proj-timeline-header"><div class="proj-timeline-label-col">Task</div><div class="proj-timeline-dates">';
      days.forEach(d => {
        const ds = d.toISOString().slice(0, 10); const isToday = ds === todayStr;
        const mn = d.toLocaleDateString('en', { month: 'short' });
        html += `<div class="proj-timeline-date-cell${isToday ? ' today' : ''}"><div class="date-day">${d.getDate()}</div><div class="date-month">${mn}</div></div>`;
      });
      html += '</div></div>';
      tasks.forEach(task => {
        const start = task.start_date ? new Date(task.start_date) : null;
        const end = task.deadline ? new Date(task.deadline) : null;
        html += `<div class="proj-timeline-row"><div class="proj-timeline-row-label" data-task-id="${task.id}">${task.title || 'Untitled'}</div><div class="proj-timeline-bars">`;
        if (start && end) {
          const startIdx = Math.max(0, Math.round((start - minD) / (86400000)));
          const endIdx = Math.min(totalDays - 1, Math.round((end - minD) / (86400000)));
          const left = (startIdx / totalDays * 100).toFixed(2);
          const width = ((endIdx - startIdx + 1) / totalDays * 100).toFixed(2);
          const statusCls = 'status-' + ((task.status || '').toLowerCase().replace(/\s+/g, ''));
          html += `<div class="proj-timeline-bar ${statusCls}" style="left:${left}%;width:${width}%" title="${task.title}: ${task.start_date} → ${task.deadline}">${task.progress || 0}%</div>`;
        }
        html += '</div></div>';
      });
      // Today line
      const todayIdx = days.findIndex(d => d.toISOString().slice(0, 10) === todayStr);
      if (todayIdx >= 0) {
        const todayPct = ((todayIdx + 0.5) / totalDays * 100).toFixed(2);
        html += `<div class="proj-timeline-today-line" style="left:calc(200px + ${todayPct}% * (100% - 200px) / 100)"></div>`;
      }
      container.innerHTML = html;
      // Click on labels
      $$('.proj-timeline-row-label[data-task-id]', container).forEach(el => {
        el.addEventListener('click', () => this.openTaskDetail(el.dataset.taskId));
      });
    }

    // ── Task Detail Modal ──
    openTaskDetail(taskId) {
      if (!this.currentProj) return;
      const task = this.currentProj.tasks.find(t => t.id === taskId);
      if (!task) return;
      this._editingTaskId = taskId;
      $('#proj-task-title').value = task.title || '';
      $('#proj-task-desc').value = task.description || '';
      // Populate status select
      const sel = $('#proj-task-status'); sel.innerHTML = '';
      this.currentProj.columns.forEach(c => { const o = document.createElement('option'); o.value = c; o.textContent = c; sel.appendChild(o) });
      sel.value = task.status || this.currentProj.columns[0];
      $('#proj-task-assignee').value = task.assignee || '';
      $('#proj-task-priority').value = task.priority || 'medium';
      $('#proj-task-progress').value = task.progress || 0;
      $('#proj-task-progress-val').textContent = (task.progress || 0) + '%';
      $('#proj-task-start').value = task.start_date || '';
      $('#proj-task-deadline').value = task.deadline || '';
      $('#proj-task-hours').value = task.estimated_hours || 0;
      $('#proj-task-cost').value = task.estimated_cost || 0;
      $('#proj-task-tags').value = (task.tags || []).join(', ');
      $('#proj-task-overlay')?.classList.add('open');
    }
    saveTaskModal() {
      if (!this.currentProj || !this._editingTaskId) return;
      const task = this.currentProj.tasks.find(t => t.id === this._editingTaskId);
      if (!task) return;
      task.title = $('#proj-task-title').value;
      task.description = $('#proj-task-desc').value;
      task.status = $('#proj-task-status').value;
      task.assignee = $('#proj-task-assignee').value;
      task.priority = $('#proj-task-priority').value;
      task.progress = parseInt($('#proj-task-progress').value) || 0;
      task.start_date = $('#proj-task-start').value;
      task.deadline = $('#proj-task-deadline').value;
      task.estimated_hours = parseFloat($('#proj-task-hours').value) || 0;
      task.estimated_cost = parseFloat($('#proj-task-cost').value) || 0;
      const tagsVal = $('#proj-task-tags').value;
      task.tags = tagsVal ? tagsVal.split(',').map(t => t.trim()).filter(Boolean) : [];
      $('#proj-task-overlay')?.classList.remove('open');
      this._render(); this._autoSave();
      toast(ICONS.check(14) + ' Task updated');
    }
    deleteTaskModal() {
      if (!this._editingTaskId) return;
      this._deleteTask(this._editingTaskId);
      $('#proj-task-overlay')?.classList.remove('open');
    }
    async _deleteTask(taskId) {
      if (!this.currentProj) return;
      this.currentProj.tasks = this.currentProj.tasks.filter(t => t.id !== taskId);
      this._render(); this.loadProjects();
      try { await fetch(`/project/projects/${this.currentProj.id}/tasks/${taskId}`, { method: 'DELETE' }) } catch (e) { }
      toast(ICONS.trash(14) + ' Task deleted');
    }

    // ── AI Generation ──
    async generateAI() {
      const input = $('#proj-ai-prompt');
      const prompt = input?.value.trim();
      if (!prompt) { toast('Please describe your project.'); return; }
      const btn = $('#proj-btn-ai-generate');
      if (btn) { btn.disabled = true; btn.classList.add('loading'); }
      toast(ICONS.sparkles(14) + ' AI is generating your project plan...');
      try {
        const r = await fetch('/project/ai-generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt }) });
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        if (data.tasks) {
          if (!this.currentProj) {
            const cr = await fetch('/project/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: data.name || 'AI Project' }) });
            const cd = await cr.json(); this.currentProj = cd.project;
            $('#proj-name-input').value = this.currentProj.name;
          }
          if (data.name) this.currentProj.name = data.name;
          if (data.columns) this.currentProj.columns = data.columns;
          if (data.members) this.currentProj.members = data.members;
          this.currentProj.tasks = data.tasks;
          if ($('#proj-name-input')) $('#proj-name-input').value = this.currentProj.name;
          await this.saveProject();
          this._render(); this.loadProjects();
          toast(ICONS.check(14) + ' Project generated! ' + data.tasks.length + ' tasks created.');
        }
      } catch (e) { toast(ICONS.x(14) + ' AI generation failed: ' + e.message) }
      finally {
        if (btn) { btn.disabled = false; btn.classList.remove('loading'); }
      }
    }

    // ── Sync with Editor ──
    async syncWithEditor() {
      if (!this.currentProj) { toast('No project loaded'); return; }
      const p = this.currentProj;
      const slug = p.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '') || 'project';
      const basePath = slug;
      const btn = $('#proj-btn-sync-editor');
      if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
      try {
        const r = await fetch(`/workspace/file?path=${encodeURIComponent(basePath + '/TODO.md')}`);
        if (!r.ok) throw new Error('TODO.md not found in Editor workspace');
        const d = await r.json();
        const content = d.content;
        const lines = content.split('\n');
        let movedCount = 0;
        let newCount = 0;
        const reviewCol = this.currentProj.columns.includes('Review') ? 'Review' : 'Done';
        const doneCol = this.currentProj.columns.includes('Done') ? 'Done' : (this.currentProj.columns[this.currentProj.columns.length - 1] || 'Done');
        const inProgCol = this.currentProj.columns.includes('In Progress') ? 'In Progress' : (this.currentProj.columns[0] || 'To Do');
        const defaultCol = this.currentProj.columns[0] || 'To Do';

        lines.forEach(line => {
          const match = line.match(/^\s*(?:[-*]\s+)?\[([xX ])\]\s*(.+)$/);
          if (match) {
            const isDone = match[1].toLowerCase() === 'x';
            let rawTitle = match[2].trim();
            // Clean markdown chars
            rawTitle = rawTitle.replace(/[\*\_`~>#]/g, '').trim();
            if (isDone) {
              let task = this.currentProj.tasks.find(t => t.title.trim() === rawTitle);
              if (!task) {
                // partial match if exact match fails (e.g. emojis or extra text)
                task = this.currentProj.tasks.find(t => {
                  const tTitle = t.title.trim().toLowerCase();
                  return rawTitle.toLowerCase().includes(tTitle);
                });
              }
              if (task) {
                if (task.status !== doneCol && task.status !== reviewCol) {
                  task.status = reviewCol;
                  movedCount++;
                }
              } else {
                // Create new task from Editor
                const newTask = {
                  id: 't' + Math.random().toString(36).substring(2, 9),
                  title: rawTitle,
                  description: '',
                  status: reviewCol,
                  assignee: '',
                  priority: 'medium',
                  progress: 100,
                  deadline: '',
                  start_date: '',
                  estimated_hours: 0,
                  estimated_cost: 0,
                  tags: [],
                  created_at: new Date().toISOString(),
                  order: this.currentProj.tasks.length
                };
                this.currentProj.tasks.push(newTask);
                newCount++;
              }
            } else {
              // Unchecked in editor
              let task = this.currentProj.tasks.find(t => t.title.trim() === rawTitle);
              if (!task) {
                task = this.currentProj.tasks.find(t => {
                  const tTitle = t.title.trim().toLowerCase();
                  return rawTitle.toLowerCase().includes(tTitle);
                });
              }
              if (task) {
                if (task.status === doneCol || task.status === reviewCol) {
                  task.status = inProgCol;
                  movedCount++;
                }
              } else {
                // Create new unchecked task from Editor
                const newTask = {
                  id: 't' + Math.random().toString(36).substring(2, 9),
                  title: rawTitle,
                  description: '',
                  status: defaultCol,
                  assignee: '',
                  priority: 'medium',
                  progress: 0,
                  deadline: '',
                  start_date: '',
                  estimated_hours: 0,
                  estimated_cost: 0,
                  tags: [],
                  created_at: new Date().toISOString(),
                  order: this.currentProj.tasks.length
                };
                this.currentProj.tasks.push(newTask);
                newCount++;
              }
            }
          }
        });
        if (movedCount > 0 || newCount > 0) {
          await this.saveProject();
          this._render();
          toast(`${ICONS.circle(14)} {ICONS.check(14)} Synced with Editor: ${movedCount} moved, ${newCount} added`);
        } else {
          toast(`${ICONS.circle(14)} {ICONS.refresh(14)} Synced with Editor: No tasks to update`);
        }
      } catch (e) {
        toast(ICONS.x(14) + ' Sync failed: ' + e.message);
      } finally {
        if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
      }
    }

    // ── Transfer to Editor ──
    async transferToEditor() {
      if (!this.currentProj) { toast('No project loaded'); return; }
      const p = this.currentProj;
      const slug = p.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '') || 'project';
      const basePath = slug;

      // Generate README.md
      let readme = `# ${p.name}\n\n`;
      if (p.description) readme += `> ${p.description}\n\n`;
      readme += `## Project Overview\n\n`;
      readme += `- **Members:** ${p.members.length ? p.members.join(', ') : '_None assigned_'}\n`;
      readme += `- **Total Tasks:** ${p.tasks.length}\n`;
      const done = p.tasks.filter(t => t.status === 'Done').length;
      readme += `- **Completed:** ${done}/${p.tasks.length}\n`;
      const totalH = p.tasks.reduce((s, t) => s + (t.estimated_hours || 0), 0);
      const totalC = p.tasks.reduce((s, t) => s + (t.estimated_cost || 0), 0);
      if (totalH) readme += `- **Estimated Hours:** ${totalH}h\n`;
      if (totalC) readme += `- **Estimated Cost:** $${totalC}\n`;
      readme += `\n## Structure\n\n`;
      readme += `\`\`\`\n${basePath}/\n├── README.md\n├── TODO.md\n`;
      const dirs = new Set();
      p.tasks.forEach(t => { (t.tags || []).forEach(tag => dirs.add(tag)) });
      dirs.forEach(d => readme += `├── ${d}/\n`);
      readme += `└── src/\n\`\`\`\n`;

      // Generate TODO.md
      let todo = '';
      (p.columns || []).forEach(col => {
        const tasks = p.tasks.filter(t => t.status === col).sort((a, b) => (a.order || 0) - (b.order || 0));
        tasks.forEach(t => {
          const check = t.status === 'Done' ? 'x' : ' ';
          todo += `[${check}] ${t.title}\n`;
        });
      });

      // Save files via workspace API
      try {
        await fetch('/workspace/file', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: `${basePath}/README.md`, content: readme }) });
        await fetch('/workspace/file', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: `${basePath}/TODO.md`, content: todo }) });

        // Switch to Editor mode
        const editorBtn = document.querySelector('#mode-toggle .mode-btn[data-mode="editor"]');
        if (editorBtn) editorBtn.click();

        // Wait for editor to be ready, then open the files
        setTimeout(async () => {
          if (window.editor) {
            await window.editor.loadTree();
            await window.editor.openFile(`${basePath}/README.md`);
            await window.editor.openFile(`${basePath}/TODO.md`);
          }
        }, 300);

        toast(`${ICONS.circle(14)} {ICONS.folder(14)} Project transferred to Editor: ${basePath}/`);
      } catch (e) { toast(ICONS.x(14) + ' Transfer failed: ' + e.message) }
    }

    // ── Import TXT ──
    async importTxt(e) {
      const file = e.target.files?.[0];
      if (!file) return;
      if (!this.currentProj) {
        // Auto-create project from filename
        const name = file.name.replace(/\.(txt|md|todo)$/i, '').replace(/[_-]/g, ' ') || 'Imported Project';
        try {
          const cr = await fetch('/project/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
          const cd = await cr.json(); this.currentProj = cd.project;
          const ni = $('#proj-name-input'); if (ni) ni.value = name;
        } catch (err) { toast(ICONS.x(14) + ' Failed to create project'); return; }
      }
      const fd = new FormData(); fd.append('file', file);
      try {
        const r = await fetch(`/project/projects/${this.currentProj.id}/import/txt`, { method: 'POST', body: fd });
        if (!r.ok) throw new Error(await r.text());
        const d = await r.json();
        await this.loadProject(this.currentProj.id);
        toast(`${ICONS.circle(14)} {ICONS.fileText(14)} Imported ${d.imported} tasks from ${file.name}`);
      } catch (err) { toast(ICONS.x(14) + ' Import failed: ' + err.message) }
      // Reset file input so same file can be re-selected
      e.target.value = '';
    }

    // ── Export ──
    async exportExcel() {
      if (!this.currentProj) { toast('No project loaded'); return; }
      try {
        const r = await fetch(`/project/projects/${this.currentProj.id}/export/excel`, { method: 'POST' });
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a'); a.href = url; a.download = `project_${this.currentProj.name}.xlsx`; a.click();
        URL.revokeObjectURL(url); toast(ICONS.barChart(14) + ' Excel exported!');
      } catch (e) { toast(ICONS.x(14) + ' Export failed') }
      $('#proj-actions-dropdown')?.classList.remove('open');
    }
    async exportPresentation() {
      if (!this.currentProj) { toast('No project loaded'); return; }
      try {
        const r = await fetch(`/project/projects/${this.currentProj.id}/export/presentation`, { method: 'POST' });
        const d = await r.json();
        toast(ICONS.barChart(14) + ' Presentation created: ' + d.slide_count + ' slides');
      } catch (e) { toast(ICONS.x(14) + ' Export failed') }
      $('#proj-actions-dropdown')?.classList.remove('open');
    }

    // ── GitHub ──
    async githubPush() {
      if (!this.currentProj) { toast('No project loaded'); return; }
      const repo = $('#proj-github-repo')?.value?.trim();
      const token = $('#proj-github-token')?.value?.trim();
      if (!repo || !token) { toast('Repository and token are required'); return; }
      toast(ICONS.hourglass(14) + ' Syncing with GitHub...');
      try {
        const r = await fetch(`/project/projects/${this.currentProj.id}/github/sync`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ repo, token }) });
        const d = await r.json();
        toast(`${ICONS.check(14)} Synced ${d.synced} issues to GitHub` + (d.errors ? ` (${d.errors} errors)` : ''));
        $('#proj-github-overlay')?.classList.remove('open');
      } catch (e) { toast(ICONS.x(14) + ' GitHub sync failed') }
    }
    async githubImport() {
      if (!this.currentProj) { toast('No project loaded'); return; }
      const repo = $('#proj-github-repo')?.value?.trim();
      const token = $('#proj-github-token')?.value?.trim();
      if (!repo || !token) { toast('Repository and token are required'); return; }
      toast(ICONS.hourglass(14) + ' Importing from GitHub...');
      try {
        const r = await fetch(`/project/projects/${this.currentProj.id}/github/import?repo=${encodeURIComponent(repo)}&token=${encodeURIComponent(token)}`);
        const d = await r.json();
        await this.loadProject(this.currentProj.id);
        toast(`${ICONS.circle(14)} {ICONS.check(14)} Imported ${d.imported} issues from GitHub`);
        $('#proj-github-overlay')?.classList.remove('open');
      } catch (e) { toast(ICONS.x(14) + ' GitHub import failed') }
    }
  }

  window.ProjectStudio = ProjectStudio;
})();
