class ResearchStudioV2 {
  constructor() {
    this.currentProject = null;
    this.projects = [];
    this.profiles = [];
    this._sse = null;
    this._init();
  }

  async _init() {
    // Bind UI elements
    const bind = (id) => document.getElementById(id);
    this.ui = {
      btnNew: bind('rs-btn-new'),
      btnStart: bind('rs-btn-start'),
      btnResume: bind('rs-btn-resume'),
      btnPause: bind('rs-btn-pause'),
      btnEval: bind('rs-btn-evaluate'),
      btnDelete: bind('rs-btn-delete'),
      btnSaveProcess: bind('rs-btn-save-process'),
      btnRunCode: bind('rs-btn-run-code'),
      btnInstallDeps: bind('rs-btn-install-deps'),
      
      searchInput: bind('rs-search'),
      queryInput: bind('rs-query-input'),
      profileSelect: bind('rs-profile-select'),
      providerSelect: bind('rs-provider-select'),
      modelSelect: bind('rs-model-select'),
      externalToggle: bind('rs-external-ai-toggle'),
      providerModelWrap: bind('rs-provider-model-wrap'),
      targetScore: bind('rs-target-score'),
      maxIter: bind('rs-max-iter'),
      
      projectList: bind('rs-project-list'),
      logArea: bind('rs-log'),
      reportArea: bind('rs-report'),
      assetsGrid: bind('rs-assets-grid'),
      resultsWrap: bind('rs-results-wrap'),
      assetList: bind('rs-asset-list'),
      
      statusBadge: bind('rs-status-badge'),
      scoreFill: bind('rs-score-fill'),
      scoreLabel: bind('rs-score-label'),
      iterLabel: bind('rs-iteration-label'),
      
      processEditor: bind('rs-process-editor'),
    };

    // Load initial data
    await this.loadProfiles();

    // Event Listeners
    if (this.ui.btnNew) this.ui.btnNew.addEventListener('click', () => this.createProject());
    if (this.ui.btnStart) this.ui.btnStart.addEventListener('click', () => {
      if (this.currentProject && this.currentProject.status !== 'running') this.startResearch(this.currentProject.id);
      else this.createProject();
    });
    
    if (this.ui.btnResume) this.ui.btnResume.addEventListener('click', () => { if (this.currentProject) this.startResearch(this.currentProject.id); });
    if (this.ui.btnPause) this.ui.btnPause.addEventListener('click', () => { if (this.currentProject) this.stopResearch(this.currentProject.id); });
    if (this.ui.btnEval) this.ui.btnEval.addEventListener('click', () => { if (this.currentProject) this.evaluate(this.currentProject.id); });
    if (this.ui.btnDelete) this.ui.btnDelete.addEventListener('click', () => { if (this.currentProject) this.deleteProject(this.currentProject.id); });
    
    if (this.ui.btnSaveProcess) this.ui.btnSaveProcess.addEventListener('click', () => this.saveProcess());

    // Auto-save process on edit (debounced)
    this._processAutoSaveTimer = null;
    if (this.ui.processEditor) {
      this.ui.processEditor.addEventListener('input', () => {
        clearTimeout(this._processAutoSaveTimer);
        this._processAutoSaveTimer = setTimeout(() => this.saveProcess(), 800);
      });
    }

    // External AI toggle
    if (this.ui.externalToggle) {
      this.ui.externalToggle.addEventListener('change', () => {
        const enabled = this.ui.externalToggle.checked;
        if (this.ui.providerModelWrap) {
          this.ui.providerModelWrap.style.display = enabled ? 'flex' : 'none';
        }
        if (enabled && this.ui.providerSelect) {
          // Load models for the currently selected provider
          this._loadModelsForProvider(this.ui.providerSelect.value);
        }
      });
    }

    // Reload model list when provider changes
    if (this.ui.providerSelect) {
      this.ui.providerSelect.addEventListener('change', () => {
        this._loadModelsForProvider(this.ui.providerSelect.value);
      });
    }

    // Profile selection auto-fills process template and auto-saves
    if (this.ui.profileSelect) {
      this.ui.profileSelect.addEventListener('change', (e) => {
        const pId = e.target.value;
        if (!pId) return;
        const profile = this.profiles.find(p => p.id === pId);
        if (profile && this.ui.processEditor) {
          // Replace placeholders with current values if available
          let md = profile.process_template || '';
          md = md.replace('{query}', this.ui.queryInput?.value || '...');
          md = md.replace('{model}', this.ui.providerSelect?.value || 'System Default');
          md = md.replace('{provider}', this.ui.providerSelect?.value || 'System Default');
          md = md.replace('{sources}', profile.sources || 'Web');
          md = md.replace('{target_score}', profile.target_score || '0.7');
          md = md.replace('{max_iterations}', profile.max_iterations || '10');
          this.ui.processEditor.value = md;
          
          if (this.ui.targetScore) this.ui.targetScore.value = profile.target_score || 0.7;
          if (this.ui.maxIter) this.ui.maxIter.value = profile.max_iterations || 10;

          // Auto-save process to backend if a project is loaded
          this.saveProcess();
        }
      });
    }

    // Tabs
    document.querySelectorAll('.rs-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('.rs-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const panel = tab.dataset.rsTab;
        document.querySelectorAll('.rs-panel').forEach(p => p.classList.remove('active'));
        const target = document.getElementById(`rs-panel-${panel}`);
        if (target) target.classList.add('active');
        
        if (panel === 'social' && window.twitterWatch) {
          window.twitterWatch.loadWatchlist();
        }
      });
    });

    // Exports
    const bindExport = (id, fmt) => document.getElementById(id)?.addEventListener('click', () => this.exportReport(fmt));
    bindExport('rs-export-md', 'md');
    bindExport('rs-export-docx', 'docx');
    bindExport('rs-export-pdf', 'pdf');
    document.getElementById('rs-export-zip')?.addEventListener('click', () => this.exportZip());

    // Search filter
    if (this.ui.searchInput) {
      this.ui.searchInput.addEventListener('input', e => {
        const q = e.target.value.toLowerCase();
        document.querySelectorAll('.rs-project-item').forEach(el => {
          const text = el.querySelector('.rs-project-item-title')?.textContent.toLowerCase() || '';
          el.style.display = text.includes(q) ? '' : 'none';
        });
      });
    }
    
    // Enter on query input
    if (this.ui.queryInput) {
      this.ui.queryInput.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); this.ui.btnStart?.click(); }
      });
    }
  }

  toggle(show) {
    const el = document.getElementById('research-layout');
    if (el) el.style.display = show ? 'flex' : 'none';
    this._isVisible = show;
    if (show) {
      this.loadProjects();
      // Auto-reconnect: if current project is running but SSE disconnected
      this._checkRunningReconnect();
    }
  }

  async _checkRunningReconnect() {
    if (!this.currentProject) return;
    try {
      const resp = await fetch(`/api/tasks/${this.currentProject.id}`);
      if (!resp.ok) {
        // Task endpoint failed — check the project status directly
        if (this.currentProject.status === 'running') {
          // Server doesn't know about a running task — fix the stale status
          const projResp = await fetch(`/research/projects/${this.currentProject.id}`);
          if (projResp.ok) {
            const projData = await projResp.json();
            if (projData.project && projData.project.status !== 'running') {
              this.currentProject.status = projData.project.status;
              this._updateStatus(projData.project.status);
            }
          }
        }
        return;
      }
      const data = await resp.json();
      if (data.active && !this._sse) {
        // Project is still running on the server — reconnect SSE
        this._connectSSE(this.currentProject.id);
        this._updateStatus('running');
      } else if (!data.active && this.currentProject.status === 'running') {
        // Server says not running but UI shows running — fix phantom status
        const projResp = await fetch(`/research/projects/${this.currentProject.id}`);
        if (projResp.ok) {
          const projData = await projResp.json();
          this.currentProject = projData.project;
          this._updateStatus(projData.project.status);
        }
      }
    } catch (e) {
      // Silently ignore — will be caught on next poll
    }
  }

  async loadProfiles() {
    try {
      const res = await fetch('/research/profiles');
      const data = await res.json();
      this.profiles = data.profiles || [];
      if (this.ui.profileSelect) {
        this.ui.profileSelect.innerHTML = '<option value="">Select a Profile...</option>';
        this.profiles.forEach(p => {
          const opt = document.createElement('option');
          opt.value = p.id;
          opt.textContent = `${p.name} (${p.builtin ? 'Built-in' : 'Custom'})`;
          this.ui.profileSelect.appendChild(opt);
        });
      }
    } catch(e) { console.error("Failed to load profiles", e); }
  }

  async loadProjects() {
    try {
      const res = await fetch('/research/projects');
      const data = await res.json();
      this.projects = data.projects || [];
      this._renderProjectList();

      // Auto-reconnect: if no project is selected, check if any is running
      if (!this.currentProject) {
        const running = this.projects.find(p => p.status === 'running');
        if (running) {
          await this.selectProject(running.id);
        } else {
          // Restore last selected project from sessionStorage on page reload
          const lastPid = sessionStorage.getItem('rs_last_project');
          if (lastPid) {
            const exists = this.projects.find(p => p.id === lastPid);
            if (exists) {
              await this.selectProject(lastPid);
            }
          }
        }
      }
    } catch(e) { console.error("Failed to load projects", e); }
  }

  _renderProjectList() {
    const list = this.ui.projectList;
    if (!list) return;
    if (!this.projects.length) {
      list.innerHTML = '<div class="rs-empty">No research projects yet.<br>Click + to start.</div>';
      return;
    }
    list.innerHTML = '';
    this.projects.forEach(p => {
      const el = document.createElement('div');
      el.className = 'rs-project-item' + (this.currentProject?.id === p.id ? ' active' : '');
      const profileName = this.profiles.find(pf => pf.id === p.profile_id)?.name || 'Custom';
      el.innerHTML = `
        <div class="rs-project-item-info">
          <div class="rs-project-item-title">${this._esc(p.title)}</div>
          <div class="rs-project-item-meta">${profileName} · ${p.iteration_count||0} iter</div>
        </div>
        <span class="rs-project-item-status ${p.status}">${p.status}</span>`;
      el.addEventListener('click', () => this.selectProject(p.id));
      list.appendChild(el);
    });
  }

  async createProject() {
    const query = this.ui.queryInput?.value.trim();
    if (!query) { if (window.toast) toast('Enter a research topic first.'); return; }
    
    const profileId = this.ui.profileSelect?.value || '';
    const profile = this.profiles.find(p => p.id === profileId);
    
    const targetScore = parseFloat(this.ui.targetScore?.value || '0.7');
    const maxIter = parseInt(this.ui.maxIter?.value || '10');

    // External AI: only use provider/model when toggle is ON
    const externalEnabled = this.ui.externalToggle?.checked || false;
    const provider = externalEnabled ? (this.ui.providerSelect?.value || '') : '';
    const model = externalEnabled ? (this.ui.modelSelect?.value || '') : '';
    
    const reqBody = {
      query, provider, model, profile_id: profileId,
      target_score: targetScore, max_iterations: maxIter,
      profile_data: profile
    };
    
    try {
      const res = await fetch('/research/projects', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify(reqBody)
      });
      const data = await res.json();
      if (data.project) {
        if (window.toast) toast(ICONS.check(14) + ' Project created');
        await this.loadProjects();
        await this.selectProject(data.project.id);
        
        // Save the process from the editor if modified
        if (this.ui.processEditor && this.ui.processEditor.value) {
            await fetch(`/research/projects/${data.project.id}/process`, {
                method:'PUT', headers:{'Content-Type':'application/json'},
                body:JSON.stringify({process_md: this.ui.processEditor.value})
            });
        }
        
        this.startResearch(data.project.id);
      }
    } catch(e) { if (window.toast) toast(ICONS.x(14) + ' Failed to create project'); }
  }

  async selectProject(pid) {
    try {
      const res = await fetch(`/research/projects/${pid}`);
      const data = await res.json();
      this.currentProject = data.project;
      
      const procRes = await fetch(`/research/projects/${pid}/process`);
      const procData = await procRes.json();
      if (this.ui.processEditor) this.ui.processEditor.value = procData.process_md || '';
      
      this._renderProjectList();
      this._updateDetails();
      
      // Bug 7: Don't wipe live logs if research is running and SSE is connected
      const isRunningWithSSE = this.currentProject.status === 'running' && this._sse;
      if (!isRunningWithSSE) {
        this._renderLog();
      }
      
      this._renderReport();
      this._renderAssets();
      this._renderResults();
      
      if (this.currentProject.status === 'running') this._connectSSE(pid);
      else this._disconnectSSE();
      
    } catch(e) { if (window.toast) toast(ICONS.x(14) + ' Failed to load project'); }
    // Persist selection for page reload
    try { sessionStorage.setItem('rs_last_project', pid); } catch(_) {}
  }

  async saveProcess() {
    if (!this.currentProject || !this.ui.processEditor) return;
    try {
      await fetch(`/research/projects/${this.currentProject.id}/process`, {
        method:'PUT', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({process_md: this.ui.processEditor.value})
      });
      if (window.toast) toast(ICONS.check(14) + ' Process saved');
    } catch(e) { if (window.toast) toast(ICONS.x(14) + ' Failed to save process'); }
  }

  async startResearch(pid) {
    try {
      const res = await fetch(`/research/projects/${pid}/start`, {method:'POST'});
      if (!res.ok) { if (window.toast) toast(ICONS.x(14) + ' Failed to start: ' + res.status); return; }
      const data = await res.json();
      if (data.status === 'started' || data.status === 'already_running') {
        this._connectSSE(pid);
        this._updateStatus('running');
        if (window.toast) toast(ICONS.sparkles(14) + ' Research started');
      }
    } catch(e) { if (window.toast) toast(ICONS.x(14) + ' Failed to start'); }
  }

  async stopResearch(pid) {
    try {
      await fetch(`/research/projects/${pid}/stop`, {method:'POST'});
      this._disconnectSSE();
      this._updateStatus('paused');
      if (window.toast) toast('Research paused');
    } catch(e) { if (window.toast) toast(ICONS.x(14) + ' Failed to stop'); }
  }

  async deleteProject(pid) {
    if (!confirm('Delete this research project?')) return;
    try {
      const res = await fetch(`/research/projects/${pid}`, {method:'DELETE'});
      if (!res.ok) {
        const errText = await res.text().catch(() => 'Unknown error');
        throw new Error(errText);
      }
      this._disconnectSSE();
      this.currentProject = null;
      try { sessionStorage.removeItem('rs_last_project'); } catch(_) {}
      await this.loadProjects();
      this._clearUI();
      if (window.toast) toast(ICONS.trash(14) + ' Project deleted');
    } catch(e) {
      console.error('Delete failed:', e);
      if (window.toast) toast(ICONS.x(14) + ' Failed to delete: ' + e.message);
    }
  }

  async evaluate(pid) {
    try {
      const res = await fetch(`/research/projects/${pid}/evaluate`, {method:'POST'});
      const data = await res.json();
      if (this.currentProject) this.currentProject.current_score = data.score;
      this._updateScore(data.score);
      if (window.toast) toast(ICONS.sparkles(14) + ` Score: ${Math.round(data.score*100)}%`);
    } catch(e) { if (window.toast) toast(ICONS.x(14) + ' Evaluation failed'); }
  }

  async exportReport(fmt) {
    if (!this.currentProject) return;
    try {
      const res = await fetch(`/research/projects/${this.currentProject.id}/export`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({format:fmt}) });
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = `research.${fmt}`; a.click();
      URL.revokeObjectURL(url);
      if (window.toast) toast(ICONS.download(14) + ` Exported as .${fmt}`);
    } catch(e) { if (window.toast) toast(ICONS.x(14) + ' Export failed: ' + e.message); }
  }

  async exportZip() {
    if (!this.currentProject) return;
    try {
      const res = await fetch(`/research/projects/${this.currentProject.id}/export-zip`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = 'research_project.zip'; a.click();
      URL.revokeObjectURL(url);
      if (window.toast) toast(ICONS.download(14) + ' ZIP exported');
    } catch(e) { if (window.toast) toast(ICONS.x(14) + ' ZIP export failed'); }
  }

  _connectSSE(pid) {
    this._disconnectSSE();
    this._sse = new EventSource(`/research/projects/${pid}/status`);
    this._sse.onmessage = e => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === 'log') this._addLogEntry(data.msg, '', data);
        else if (data.type === 'status') {
            this._updateStatus(data.status);
            if (data.status === 'completed' || data.status === 'paused' || data.status === 'error') {
                this.selectProject(pid); // Refresh all data when done
            }
        }
        else if (data.type === 'iteration_start') this._addLogEntry(`── Iteration ${data.iteration} ──`, 'search');
        else if (data.type === 'iteration_end') {
            this._updateScore(data.score);
            this._updateIteration(data.iteration);
            this._addLogEntry(`Score: ${Math.round(data.score*100)}% — ${data.evaluation||''}`, 'eval');
            // Refresh results & assets from server after each iteration
            this._refreshProjectData(pid);
        }
        else if (data.type === 'report_ready') { this._addLogEntry('📝 Report ready!', 'done'); this._refreshProjectData(pid); }
        else if (data.type === 'new_results' && data.results) {
            // Real-time incremental result updates
            if (this.currentProject) {
                if (!this.currentProject.search_results) this.currentProject.search_results = [];
                this.currentProject.search_results.push(...data.results);
                this._renderResults();
            }
        }
        else if (data.type === 'new_asset' && data.name) {
            // Real-time incremental asset updates
            if (this.currentProject) {
                if (!this.currentProject.assets) this.currentProject.assets = [];
                this.currentProject.assets.push(data);
                this._renderAssets();
            }
        }
        else if (data.type === 'token_usage' && window.tokenTracker) {
          window.tokenTracker.addUsage(data);
        }
      } catch(err) { /* ignore parse errors */ }
    };
    this._sse.onerror = () => { /* auto-reconnect */ };
  }

  _disconnectSSE() {
    if (this._sse) { this._sse.close(); this._sse = null; }
  }

  async _refreshProjectData(pid) {
    // Fetch fresh project data to update results, assets, and report
    // without disrupting the live log stream
    try {
      const res = await fetch(`/research/projects/${pid}`);
      if (!res.ok) return;
      const data = await res.json();
      if (!data.project || !this.currentProject || this.currentProject.id !== pid) return;
      // Update in-memory project data (preserve status from SSE)
      const liveStatus = this.currentProject.status;
      this.currentProject.search_results = data.project.search_results || [];
      this.currentProject.assets = data.project.assets || [];
      this.currentProject.report_md = data.project.report_md || '';
      this.currentProject.current_score = data.project.current_score || 0;
      this.currentProject.iterations = data.project.iterations || [];
      this.currentProject.status = liveStatus; // Keep SSE status, not stale disk status
      this._renderResults();
      this._renderAssets();
      if (data.project.report_md) this._renderReport();
    } catch (_) { /* Silently ignore — next iteration will retry */ }
  }

  _addLogEntry(msg, cls='', details=null) {
    const log = this.ui.logArea;
    if (!log) return;
    const empty = log.querySelector('.rs-log-empty');
    if (empty) empty.remove();
    
    let time = new Date().toLocaleTimeString();
    if (details && details.timestamp) {
        time = new Date(details.timestamp).toLocaleTimeString();
    }
    
    const entry = document.createElement('div');
    entry.className = 'rs-log-entry ' + cls;
    
    let inner = `<span class="rs-log-entry-time">${time}</span><span class="rs-log-entry-msg">${this._esc(msg)}</span>`;
    
    const urls = Array.isArray(details) ? details : (details?.urls || []);
    const code = !Array.isArray(details) ? details?.code : null;
    const output = !Array.isArray(details) ? details?.output : null;
    
    let detailsHtml = '';
    
    if (urls && urls.length > 0) {
        detailsHtml += `<div class="rs-log-urls" style="margin-top: 4px; font-size: 11px; color: var(--text-muted); padding-left: 10px; max-height: 200px; overflow-y: auto;">
            ${urls.map(u => `<div><a href="${u}" target="_blank" style="color:var(--primary);text-decoration:none;">${this._esc(u)}</a></div>`).join('')}
        </div>`;
    }
    
    if (code) {
        detailsHtml += `<div class="rs-log-code" style="margin-top: 4px; font-size: 11px; color: var(--text-muted); padding-left: 10px; max-height: 200px; overflow-y: auto;">
            <strong>Code:</strong><br><pre style="margin:2px 0; background:rgba(0,0,0,0.1); padding:4px; overflow-x: auto;">${this._esc(code)}</pre>
        </div>`;
    }
    
    if (output) {
        detailsHtml += `<div class="rs-log-output" style="margin-top: 4px; font-size: 11px; color: var(--text-muted); padding-left: 10px; max-height: 200px; overflow-y: auto;">
            <strong>Output:</strong><br><pre style="margin:2px 0; background:rgba(0,0,0,0.1); padding:4px; overflow-x: auto;">${this._esc(output)}</pre>
        </div>`;
    }
    
    if (detailsHtml) {
        inner += `<div class="rs-log-details" style="display:none; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 4px; margin-top: 4px;">${detailsHtml}</div>`;
        entry.style.cursor = 'pointer';
        entry.title = "Click to toggle details";
        entry.addEventListener('click', (e) => {
            if (e.target.tagName.toLowerCase() === 'a') return;
            const detailsDiv = entry.querySelector('.rs-log-details');
            if (detailsDiv) detailsDiv.style.display = detailsDiv.style.display === 'none' ? 'block' : 'none';
        });
    }
    
    entry.innerHTML = inner;
    
    if (msg.includes('── Iteration')) {
        const block = document.createElement('div');
        block.className = 'rs-iteration-block';
        block.style.display = 'flex';
        block.style.flexDirection = 'column';
        block.style.gap = '6px';
        block.style.marginBottom = '12px';
        this.currentIterationBlock = block;
        log.prepend(block);
    }

    if (this.currentIterationBlock && !cls.includes('error')) {
        this.currentIterationBlock.appendChild(entry);
    } else {
        log.prepend(entry);
    }
  }

  _updateStatus(status) {
    if (this.currentProject) this.currentProject.status = status;
    const badge = this.ui.statusBadge;
    if (badge) { badge.textContent = status; badge.className = 'rs-status-badge ' + status; }
    
    if (this.ui.btnResume) this.ui.btnResume.style.display = (status === 'paused' || status === 'idle' || status === 'error') ? '' : 'none';
    if (this.ui.btnPause) this.ui.btnPause.style.display = status === 'running' ? '' : 'none';
    if (this.ui.btnEval) this.ui.btnEval.style.display = (status !== 'running') ? '' : 'none';

    // Update sidebar project list to reflect the new status
    if (this.currentProject) {
      const proj = this.projects.find(p => p.id === this.currentProject.id);
      if (proj) proj.status = status;
      this._renderProjectList();
    }
  }

  _updateScore(score) {
    const pct = Math.round(score * 100);
    if (this.ui.scoreFill) this.ui.scoreFill.style.width = pct + '%';
    if (this.ui.scoreLabel) this.ui.scoreLabel.textContent = pct + '%';
  }

  _updateIteration(num) {
    const max = this.currentProject?.max_iterations || 10;
    if (this.ui.iterLabel) this.ui.iterLabel.textContent = `${num} / ${max}`;
  }

  _updateDetails() {
    const p = this.currentProject;
    if (!p) return;
    this._updateStatus(p.status);
    this._updateScore(p.current_score || 0);
    this._updateIteration(p.iterations?.length || 0);
    if (this.ui.targetScore) this.ui.targetScore.value = p.target_score || 0.7;
    if (this.ui.maxIter) this.ui.maxIter.value = p.max_iterations || 10;
    if (this.ui.queryInput) this.ui.queryInput.value = p.query || '';
    if (this.ui.profileSelect) this.ui.profileSelect.value = p.profile_id || '';

    // Restore external AI toggle state from saved project
    const hasExternalProvider = p.provider && p.provider !== 'ollama';
    if (this.ui.externalToggle) {
      this.ui.externalToggle.checked = hasExternalProvider;
      if (this.ui.providerModelWrap) {
        this.ui.providerModelWrap.style.display = hasExternalProvider ? 'flex' : 'none';
      }
      if (hasExternalProvider && p.provider) {
        if (this.ui.providerSelect) this.ui.providerSelect.value = p.provider;
        this._loadModelsForProvider(p.provider, p.model);
      }
    }
  }

  _renderLog() {
    const log = this.ui.logArea;
    if (!log || !this.currentProject) return;
    const iters = this.currentProject.iterations || [];
    if (!iters.length) {
      log.innerHTML = '<div class="rs-log-empty"><svg class="ic" width="40" height="40" style="opacity:0.3"><use href="#icon-search"></use></svg><p>Start a research to see live progress.</p></div>';
      return;
    }
    log.innerHTML = '';
    this.currentIterationBlock = null;

    iters.forEach(it => {
      this._addLogEntry(`── Iteration ${it.num} ──`, 'search', {timestamp: it.started_at});
      (it.actions||[]).forEach(a => {
          const ts = a.timestamp || it.started_at;
          if (a.type === 'web_search') {
              const q = (a.params || {}).query || '';
              this._addLogEntry(`web_search: ${q.substring(0,120)}`, '', {timestamp: ts});
              if (a.urls && a.urls.length > 0) {
                  this._addLogEntry(`   Found ${a.count} results`, '', {urls: a.urls, timestamp: ts});
              } else {
                  this._addLogEntry(`   Found ${a.count} results`, '', {timestamp: ts});
              }
          } else if (a.type === 'smart_scrape') {
              this._addLogEntry(`smart_scrape: ${a.count} pages`, '', {timestamp: ts});
              if (a.urls && a.urls.length > 0) {
                  this._addLogEntry(`   🔍 Smart-scraped ${a.count} pages`, '', {urls: a.urls, timestamp: ts});
              } else {
                  this._addLogEntry(`   🔍 Smart-scraped ${a.count} pages`, '', {timestamp: ts});
              }
          } else if (a.type === 'scrape') {
              this._addLogEntry(`scrape: ${a.url}`, '', {timestamp: ts});
              this._addLogEntry(`   Scraped content`, '', {urls: [a.url], timestamp: ts});
          } else if (a.type === 'script') {
              this._addLogEntry(`write_script: executed`, '', {timestamp: ts});
              this._addLogEntry(`   Script output`, '', {code: a.code, output: a.output, timestamp: ts});
          } else {
              const label = a.query || a.url || a.question || a.symbol || a.description || '';
              this._addLogEntry(`${a.type}: ${label.substring(0,120)}`, '', {timestamp: ts});
          }
      });
      if (it.evaluation) {
          this._addLogEntry(`Score: ${Math.round(it.score*100)}% — ${it.evaluation}`, 'eval', {timestamp: it.completed_at || it.started_at});
      }
    });

    if (this.currentProject.status === 'error' && this.currentProject.error_msg) {
        this._addLogEntry(`❌ Error: ${this.currentProject.error_msg}`, 'error');
    }
  }

  _renderReport() {
    const el = this.ui.reportArea;
    if (!el || !this.currentProject) return;
    const md = this.currentProject.report_md || '';
    if (!md) {
      el.innerHTML = '<div class="rs-log-empty"><svg class="ic" width="40" height="40" style="opacity:0.3"><use href="#icon-file-text"></use></svg><p>Report will appear here once generated.</p></div>';
      return;
    }
    // Build quality dashboard header from project metadata
    const dashboardHtml = this._buildReportDashboard();
    
    let reportHtml = '';
    if (window.renderMd) {
        reportHtml = renderMd(md);
    } else {
        reportHtml = `<pre style="white-space:pre-wrap;font-family:inherit;">${this._esc(md)}</pre>`;
    }
    // Post-process: catch any surviving __TABLE__/__CHART__ markers
    if (window.StructuredUI) {
        reportHtml = StructuredUI.renderComponents(reportHtml);
    }
    el.innerHTML = dashboardHtml + reportHtml;
    // Highlight code blocks
    if (window.highlightAll) highlightAll(el);
  }

  _buildReportDashboard() {
    const p = this.currentProject;
    if (!p) return '';
    const score = Math.round((p.current_score || 0) * 100);
    const iters = (p.iterations || []).length;
    const sources = (p.search_results || []).length;
    const assets = (p.assets || []).length;
    const lastIter = (p.iterations || []).slice(-1)[0] || {};
    const scoresDetail = lastIter.scores_detail || {};
    
    // SVG circular gauge
    const radius = 40;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference - (score / 100) * circumference;
    const scoreColor = score >= 70 ? '#10b981' : score >= 40 ? '#f59e0b' : '#ef4444';
    
    const gaugeHtml = `
      <svg viewBox="0 0 100 100" class="rs-dash-gauge">
        <circle cx="50" cy="50" r="${radius}" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="8"/>
        <circle cx="50" cy="50" r="${radius}" fill="none" stroke="${scoreColor}" stroke-width="8"
          stroke-dasharray="${circumference}" stroke-dashoffset="${offset}"
          stroke-linecap="round" transform="rotate(-90 50 50)" style="transition: stroke-dashoffset 1s ease;"/>
        <text x="50" y="46" text-anchor="middle" fill="${scoreColor}" font-size="22" font-weight="700">${score}%</text>
        <text x="50" y="60" text-anchor="middle" fill="var(--text-muted)" font-size="8">Quality</text>
      </svg>`;
    
    // Metric cards
    const cards = [
      { icon: '🔍', label: 'Sources', value: sources },
      { icon: '🔄', label: 'Iterations', value: iters },
      { icon: '📁', label: 'Assets', value: assets },
    ].map(c => `
      <div class="rs-dash-card">
        <span class="rs-dash-card-icon">${c.icon}</span>
        <span class="rs-dash-card-value">${c.value}</span>
        <span class="rs-dash-card-label">${c.label}</span>
      </div>`).join('');
    
    // Per-axis mini progress bars
    const axes = ['coverage', 'depth', 'reliability', 'coherence', 'recency'];
    const axisLabels = { coverage: 'Coverage', depth: 'Depth', reliability: 'Reliability', coherence: 'Coherence', recency: 'Recency' };
    let axesBarsHtml = '';
    if (Object.keys(scoresDetail).length > 0) {
      axesBarsHtml = '<div class="rs-dash-axes">' + axes.map(ax => {
        const val = Math.round((scoresDetail[ax] || 0) * 100);
        const color = val >= 70 ? '#10b981' : val >= 40 ? '#f59e0b' : '#ef4444';
        return `<div class="rs-dash-axis">
          <span class="rs-dash-axis-label">${axisLabels[ax] || ax}</span>
          <div class="rs-dash-axis-bar"><div class="rs-dash-axis-fill" style="width:${val}%;background:${color}"></div></div>
          <span class="rs-dash-axis-val">${val}%</span>
        </div>`;
      }).join('') + '</div>';
    }
    
    return `<div class="rs-report-dashboard">
      <div class="rs-dash-main">
        <div class="rs-dash-gauge-wrap">${gaugeHtml}</div>
        <div class="rs-dash-cards">${cards}</div>
      </div>
      ${axesBarsHtml}
    </div>`;
  }

  _renderResults() {
      const wrap = this.ui.resultsWrap;
      if (!wrap || !this.currentProject) return;
      const results = this.currentProject.search_results || [];
      if (!results.length) {
          wrap.innerHTML = '<div class="rs-log-empty"><svg class="ic" width="40" height="40" style="opacity:0.3"><use href="#icon-list"></use></svg><p>Collected results and sources will appear here.</p></div>';
          return;
      }
      wrap.innerHTML = '';
      
      // Deduplicate by URL for display
      const uniqueResults = [];
      const seenUrls = new Set();
      results.forEach(r => {
          if (r.url && !seenUrls.has(r.url)) {
              seenUrls.add(r.url);
              uniqueResults.push(r);
          }
      });
      
      uniqueResults.forEach(r => {
          const card = document.createElement('div');
          card.className = 'rs-result-card';
          card.innerHTML = `
            <div class="rs-result-header">
                <h4 class="rs-result-title">${this._esc(r.title || 'Untitled')}</h4>
                <a href="${this._esc(r.url || '')}" target="_blank" class="rs-result-url">${this._esc(r.url || '')}</a>
            </div>
            <div class="rs-result-snippet">${this._esc(r.snippet || '')}</div>
            <div class="rs-result-meta">
                <span class="rs-result-source">${this._esc(r.source || 'Web')}</span>
                ${r.score ? `<span>Score: ${r.score.toFixed(2)}</span>` : ''}
            </div>
          `;
          wrap.prepend(card);
      });
  }

  _renderAssets() {
    const grid = this.ui.assetsGrid, sidebar = this.ui.assetList;
    const assets = this.currentProject?.assets || [];
    if (grid) {
      if (!assets.length) {
        grid.innerHTML = '<div class="rs-log-empty"><svg class="ic" width="40" height="40" style="opacity:0.3"><use href="#icon-folder"></use></svg><p>No assets downloaded yet.</p></div>';
      } else {
        grid.innerHTML = '';
        assets.forEach(a => {
          const card = document.createElement('div');
          card.className = 'rs-asset-card';
          const icon = a.type === 'pdf' ? '📄' : (a.type.match(/png|jpg|jpeg|gif|webp|svg/) ? '🖼️' : '📁');
          card.innerHTML = `<div class="rs-asset-icon">${icon}</div><div class="rs-asset-name">${this._esc(a.name)}</div><div class="rs-asset-meta">${a.type} · ${this._fileSize(a.size||0)}</div>`;
          card.addEventListener('click', () => window.open(`/data/research/${this.currentProject.id}/assets/${a.name}`, '_blank'));
          grid.appendChild(card);
        });
      }
    }
    if (sidebar) {
      if (!assets.length) { sidebar.innerHTML = '<span style="opacity:0.5;font-size:12px">No assets yet</span>'; }
      else {
        sidebar.innerHTML = '';
        assets.forEach(a => {
          const el = document.createElement('div');
          el.className = 'rs-asset-list-item';
          el.textContent = a.name;
          el.addEventListener('click', () => window.open(`/data/research/${this.currentProject.id}/assets/${a.name}`, '_blank'));
          sidebar.appendChild(el);
        });
      }
    }
  }

  _clearUI() {
    if (this.ui.logArea) this.ui.logArea.innerHTML = '<div class="rs-log-empty"><p>Start a research project.</p></div>';
    if (this.ui.reportArea) this.ui.reportArea.innerHTML = '';
    if (this.ui.assetsGrid) this.ui.assetsGrid.innerHTML = '';
    if (this.ui.resultsWrap) this.ui.resultsWrap.innerHTML = '';
    if (this.ui.processEditor) this.ui.processEditor.value = '';
    this._updateStatus('idle');
    this._updateScore(0);
    this._updateIteration(0);
  }

  _fileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes/1024).toFixed(1) + ' KB';
    return (bytes/1048576).toFixed(1) + ' MB';
  }

  _esc(str) { const d = document.createElement('div'); d.textContent = str; return d.innerHTML; }

  // --- External AI: Dynamic model loading ---
  async _loadModelsForProvider(provider, selectValue = '') {
    const sel = this.ui.modelSelect;
    if (!sel || !provider) return;
    sel.innerHTML = '<option value="">Loading...</option>';
    try {
      const res = await fetch('/api/models');
      if (!res.ok) throw new Error('Failed');
      const data = await res.json();
      const models = (data.providers || {})[provider] || [];
      sel.innerHTML = '';
      if (!models.length) {
        sel.innerHTML = '<option value="">No models available</option>';
        return;
      }
      models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = m.label || m.id;
        if (m.id === selectValue) opt.selected = true;
        sel.appendChild(opt);
      });
    } catch(e) {
      sel.innerHTML = '<option value="">Could not load models</option>';
    }
  }
  
  // Public API to launch research from chat
  launchFromChat(query, profileId = 'quick_explore') {
      // Toggle to research mode
      const modeBtn = document.querySelector('.mode-btn[data-mode="research"]');
      if (modeBtn) modeBtn.click();
      
      // Fill form
      if (this.ui.queryInput) this.ui.queryInput.value = query;
      if (this.ui.profileSelect) {
          this.ui.profileSelect.value = profileId;
          // Trigger change event to load template
          this.ui.profileSelect.dispatchEvent(new Event('change'));
      }
      
      // Auto start after a short delay
      setTimeout(() => {
          if (this.ui.btnStart) this.ui.btnStart.click();
      }, 500);
  }
}

// Make it globally available
window.ResearchStudioV2 = ResearchStudioV2;
