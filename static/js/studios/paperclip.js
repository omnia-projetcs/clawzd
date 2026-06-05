/**
 * Clawzd — Paperclip Agent Orchestration Studio.
 *
 * Controls multi-agent parallel dispatching, centralized agent registry,
 * and execution traces logs. Inspired by paperclip.ing.
 */
class PaperclipStudio {
  constructor() {
    this.activePmode = 'dispatcher';
    this.selectedAgents = new Set();
    this.selectedFiles = new Set();
    this.agents = {};
    this.files = [];
    this.eventSources = {};
    this.timers = {};
    
    this.icons = {
      orchestrator: 'brain',
      developer: 'code',
      researcher: 'search',
      soul: 'heart'
    };
    
    this.colors = {
      orchestrator: '#6366f1',
      developer: '#10b981',
      researcher: '#f59e0b',
      soul: '#ec4899'
    };
  }

  init() {
    this.layoutEl = document.getElementById('paperclip-layout');
    if (!this.layoutEl) return;

    // Bind sub-tabs switching
    this.layoutEl.querySelectorAll('.paperclip-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        this.layoutEl.querySelectorAll('.paperclip-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        this.switchSubMode(tab.dataset.pmode);
      });
    });

    // Bind files refresh & search
    const fileRefreshBtn = document.getElementById('paperclip-files-refresh');
    if (fileRefreshBtn) fileRefreshBtn.addEventListener('click', () => this.loadFiles());

    const fileSearchInput = document.getElementById('paperclip-files-search');
    if (fileSearchInput) {
      fileSearchInput.addEventListener('input', (e) => this.filterFiles(e.target.value));
    }

    // Bind Dispatch action
    const dispatchBtn = document.getElementById('paperclip-btn-dispatch');
    if (dispatchBtn) dispatchBtn.addEventListener('click', () => this.dispatchParallel());

    // Bind monitor close/stop controls
    const newDispatchBtn = document.getElementById('paperclip-btn-new-dispatch');
    if (newDispatchBtn) {
      newDispatchBtn.addEventListener('click', () => {
        document.getElementById('paperclip-dispatcher-monitor-view').style.display = 'none';
        document.getElementById('paperclip-dispatcher-input-grid').style.display = 'grid';
      });
    }

    const abortAllBtn = document.getElementById('paperclip-btn-stop-all');
    if (abortAllBtn) abortAllBtn.addEventListener('click', () => this.abortAll());

    // Bind registry agent create button
    const regCreateBtn = document.getElementById('paperclip-registry-create-btn');
    if (regCreateBtn && window.AgentSidebar) {
      regCreateBtn.addEventListener('click', () => {
        if (typeof window.AgentSidebar.openAgentEditor === 'function') {
          window.AgentSidebar.openAgentEditor('');
        } else {
          // Fallback if not globally exported, simulate sidebar click
          const createBtn = document.getElementById('agent-create-btn');
          if (createBtn) createBtn.click();
        }
      });
    }

    // Bind traces refresh
    const tracesRefreshBtn = document.getElementById('paperclip-traces-refresh');
    if (tracesRefreshBtn) tracesRefreshBtn.addEventListener('click', () => this.loadTraces());

    // Bind Trace Modal close
    const modalClose = document.getElementById('paperclip-trace-modal-close');
    if (modalClose) {
      modalClose.addEventListener('click', () => {
        document.getElementById('paperclip-trace-modal').style.display = 'none';
      });
    }

    // Listen to agent saves from sidebar to refresh registry
    window.addEventListener('agent:save', () => this.loadAgents());

    // Initial loads
    this.loadFiles();
    this.loadAgents();
    this.loadTraces();
  }

  toggle(active) {
    if (this.layoutEl) {
      this.layoutEl.style.display = active ? 'flex' : 'none';
    }
    if (active) {
      this.loadFiles();
      this.loadAgents();
      this.loadTraces();
    }
  }

  switchSubMode(pmode) {
    this.activePmode = pmode;
    this.layoutEl.querySelectorAll('.paperclip-view').forEach(view => {
      view.style.display = 'none';
    });
    const targetView = document.getElementById(`paperclip-view-${pmode}`);
    if (targetView) targetView.style.display = 'flex';
  }

  async loadFiles() {
    const listEl = document.getElementById('paperclip-files-list');
    if (!listEl) return;
    listEl.innerHTML = '<div class="paperclip-loading-spinner">Loading files...</div>';

    try {
      const res = await fetch('/workspace/tree');
      const data = await res.json();
      this.files = data.files || [];
      this.renderFilesList(this.files);
    } catch (e) {
      listEl.innerHTML = '<div class="paperclip-loading-spinner" style="color:var(--text-danger);">Failed to load workspace files</div>';
    }
  }

  renderFilesList(files) {
    const listEl = document.getElementById('paperclip-files-list');
    if (!listEl) return;

    if (files.length === 0) {
      listEl.innerHTML = '<div class="paperclip-loading-spinner">No files in workspace yet.</div>';
      return;
    }

    listEl.innerHTML = files.map(file => {
      const isChecked = this.selectedFiles.has(file.path) ? 'checked' : '';
      const sizeKB = (file.size / 1024).toFixed(1);
      return `
        <label class="file-checkbox-label">
          <input type="checkbox" data-path="${file.path}" ${isChecked}>
          <span>${file.path} <span style="opacity:0.5;font-size:10px;">(${sizeKB} KB)</span></span>
        </label>
      `;
    }).join('');

    // Bind check events
    listEl.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      cb.addEventListener('change', () => {
        const path = cb.dataset.path;
        if (cb.checked) {
          this.selectedFiles.add(path);
        } else {
          this.selectedFiles.delete(path);
        }
      });
    });
  }

  filterFiles(query) {
    const q = query.toLowerCase();
    const filtered = this.files.filter(f => f.path.toLowerCase().includes(q));
    this.renderFilesList(filtered);
  }

  async loadAgents() {
    try {
      const res = await fetch('/agents/list');
      const data = await res.json();
      this.agents = data.agents || {};
      
      this.renderAgentsSelection();
      this.renderRegistry();
    } catch (e) {
      console.warn('PaperclipStudio: failed to load agents', e);
    }
  }

  renderAgentsSelection() {
    const grid = document.getElementById('paperclip-agents-selection-grid');
    if (!grid) return;

    const baseKeys = ['orchestrator', 'developer', 'researcher', 'soul'];
    const loadedKeys = Object.keys(this.agents);
    const agentKeys = Array.from(new Set([...baseKeys, ...loadedKeys]));

    grid.innerHTML = agentKeys.map(key => {
      const agent = this.agents[key];
      const name = agent?.name || key.toUpperCase();
      const role = agent?.role || 'Custom Persona';
      const icon = this.icons[key] || 'bot';
      const color = this.colors[key] || '#6366f1';
      const isActive = this.selectedAgents.has(key) ? 'active' : '';

      return `
        <div class="agent-select-card ${isActive}" data-agent-key="${key}" style="--agent-color: ${color}">
          <svg class="ic" width="20" height="20" style="color: ${color}"><use href="#icon-${icon}"></use></svg>
          <div style="flex:1;">
            <div class="agent-select-name">${name}</div>
            <div class="agent-select-role">${role}</div>
          </div>
          <div class="agent-select-checkbox"></div>
        </div>
      `;
    }).join('');

    // Bind click events
    grid.querySelectorAll('.agent-select-card').forEach(card => {
      card.addEventListener('click', () => {
        const key = card.dataset.agentKey;
        if (this.selectedAgents.has(key)) {
          this.selectedAgents.delete(key);
          card.classList.remove('active');
        } else {
          this.selectedAgents.add(key);
          card.classList.add('active');
        }
      });
    });
  }

  renderRegistry() {
    const grid = document.getElementById('paperclip-registry-grid');
    if (!grid) return;

    const baseKeys = ['orchestrator', 'developer', 'researcher', 'soul'];
    const loadedKeys = Object.keys(this.agents);
    const agentKeys = Array.from(new Set([...baseKeys, ...loadedKeys]));

    grid.innerHTML = agentKeys.map(key => {
      const agent = this.agents[key];
      const name = agent?.name || key.toUpperCase();
      const role = agent?.role || 'Pre-configured Assistant';
      const model = agent?.model || 'gpt-4o / sonnet';
      const icon = this.icons[key] || 'bot';
      const color = this.colors[key] || '#6366f1';
      const skills = (agent?.skills || 'execute_python, search_web').split(',').map(s => s.trim());
      const skillsHtml = skills.map(s => `<span class="skill-tag">${s}</span>`).join('');

      return `
        <div class="registry-agent-card">
          <div class="registry-agent-header">
            <div class="registry-agent-title">
              <svg class="ic" width="24" height="24" style="color: ${color}"><use href="#icon-${icon}"></use></svg>
              <div>
                <span class="registry-agent-name">${name}</span>
                <br><span class="registry-agent-model">${model}</span>
              </div>
            </div>
            <button class="icon-btn registry-edit-btn" data-agent-key="${key}" title="Edit Preprompt">
              <svg class="ic" width="14" height="14"><use href="#icon-pen"></use></svg>
            </button>
          </div>
          <div class="registry-agent-desc">${role}</div>
          <div class="registry-agent-skills">
            <div style="font-size:10px; color:var(--text-muted); text-transform:uppercase; font-weight:600; letter-spacing:0.5px; margin-bottom:4px;">Allowed Skills</div>
            <div class="skill-tags">${skillsHtml}</div>
          </div>
        </div>
      `;
    }).join('');

    // Bind edit buttons
    grid.querySelectorAll('.registry-edit-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const key = btn.dataset.agentKey;
        if (window.AgentSidebar && typeof window.AgentSidebar.openAgentEditor === 'function') {
          window.AgentSidebar.openAgentEditor(key);
        }
      });
    });
  }

  async dispatchParallel() {
    const promptText = document.getElementById('paperclip-task-prompt').value.trim();
    if (!promptText) {
      if (typeof window.toast === 'function') window.toast('Please define a mission goal prompt first', 'warning');
      return;
    }
    if (this.selectedAgents.size === 0) {
      if (typeof window.toast === 'function') window.toast('Please select at least one Agent', 'warning');
      return;
    }

    // Show monitors, hide config
    document.getElementById('paperclip-dispatcher-input-grid').style.display = 'none';
    const monitorView = document.getElementById('paperclip-dispatcher-monitor-view');
    monitorView.style.display = 'flex';
    document.getElementById('paperclip-live-task-label').textContent = `Mission: ${promptText.substring(0, 60)}${promptText.length > 60 ? '...' : ''}`;

    // Read attached files context
    let contextStr = '';
    if (this.selectedFiles.size > 0) {
      contextStr += '\n\n### ATTACHED WORKSPACE CONTEXT:\n';
      for (const filepath of this.selectedFiles) {
        try {
          const res = await fetch(`/workspace/file?path=${encodeURIComponent(filepath)}`);
          const fileData = await res.json();
          contextStr += `\n**FILE: ${filepath}**\n\`\`\`\n${fileData.content || ''}\n\`\`\`\n`;
        } catch (e) {
          console.warn('Failed to load workspace file content', filepath);
        }
      }
    }

    const fullPrompt = promptText + contextStr;

    // Clear monitor cols container
    const container = document.getElementById('paperclip-parallel-monitors');
    container.innerHTML = '';

    // Abort any lingering streams
    this.abortAll();

    // Start each agent execution in parallel
    const selectedList = Array.from(this.selectedAgents);
    selectedList.forEach(agentKey => {
      this.runAgentExecution(agentKey, fullPrompt);
    });
  }

  runAgentExecution(agentKey, prompt) {
    const container = document.getElementById('paperclip-parallel-monitors');
    const agent = this.agents[agentKey];
    const name = agent?.name || agentKey.toUpperCase();
    const icon = this.icons[agentKey] || 'bot';
    const color = this.colors[agentKey] || '#6366f1';
    
    // Create unique session ID
    const dateStr = Date.now();
    const sessionId = `paperclip-${agentKey}-${dateStr}`;

    // Build Column Element
    const col = document.createElement('div');
    col.className = 'agent-monitor-column';
    col.id = `monitor-col-${agentKey}`;
    col.innerHTML = `
      <div class="monitor-col-header">
        <div class="monitor-col-title">
          <svg class="ic" width="16" height="16" style="color: ${color}"><use href="#icon-${icon}"></use></svg>
          <span>${name}</span>
        </div>
        <span class="monitor-col-badge badge-thinking" id="badge-${agentKey}">thinking</span>
        <span class="monitor-col-timer" id="timer-${agentKey}">0.0s</span>
        <button class="icon-btn stop-agent-btn" data-sid="${sessionId}" data-key="${agentKey}" title="Stop execution">
          <svg class="ic" width="12" height="12" style="color:var(--text-danger);"><use href="#icon-x"></use></svg>
        </button>
      </div>
      <div class="monitor-col-terminal" id="terminal-${agentKey}"></div>
    `;
    container.appendChild(col);

    // Bind Stop Action
    col.querySelector('.stop-agent-btn').addEventListener('click', (e) => {
      const btn = e.currentTarget;
      this.stopAgent(btn.dataset.key, btn.dataset.sid);
    });

    const terminal = col.querySelector(`.monitor-col-terminal`);
    terminal.innerHTML = '<span style="color:var(--text-muted);">Launching async worker...</span><br>';

    // Timer trigger
    let elapsed = 0;
    const timerEl = col.querySelector(`#timer-${agentKey}`);
    this.timers[agentKey] = setInterval(() => {
      elapsed += 0.1;
      timerEl.textContent = `${elapsed.toFixed(1)}s`;
    }, 100);

    const modelOption = document.getElementById('paperclip-opt-model').value;
    const tokenLimit = parseInt(document.getElementById('paperclip-opt-budget').value) || 15000;

    // Dispatch POST `/send`
    let accumulatedText = '';
    
    fetch(`/send/${sessionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: prompt,
        agent: agentKey,
        model: modelOption || undefined
      })
    })
    .then(res => res.json())
    .then(data => {
      col.querySelector(`#badge-${agentKey}`).className = 'monitor-col-badge badge-executing';
      col.querySelector(`#badge-${agentKey}`).textContent = 'executing';
      
      // Connect EventSource to stream the output
      const es = new EventSource(`/stream/${sessionId}`);
      this.eventSources[agentKey] = es;

      es.onmessage = (e) => {
        const token = e.data;
        if (token === '[DONE]') {
          es.close();
          delete this.eventSources[agentKey];
          
          clearInterval(this.timers[agentKey]);
          delete this.timers[agentKey];

          col.querySelector(`#badge-${agentKey}`).className = 'monitor-col-badge badge-success';
          col.querySelector(`#badge-${agentKey}`).textContent = 'success';
          
          // Re-load traces history
          this.loadTraces();
          return;
        }

        // Intercept suggestions or HITL requests
        if (token.includes('__TOOL_APPROVAL__')) {
          try {
            const match = /__TOOL_APPROVAL__(.+?)__TOOL_APPROVAL__/.exec(token);
            if (match && window.toolApproval) {
              const data = JSON.parse(match[1]);
              window.toolApproval._show(data);
            }
          } catch(err) {}
          return;
        }

        accumulatedText += token;
        
        // Render stream markdown live
        if (window.renderMd) {
          terminal.innerHTML = window.renderMd(accumulatedText);
        } else {
          terminal.textContent = accumulatedText;
        }
        
        // Auto-scroll terminal
        terminal.scrollTop = terminal.scrollHeight;
      };

      es.onerror = () => {
        es.close();
        this.handleFailure(agentKey);
      };
    })
    .catch(err => {
      this.handleFailure(agentKey);
    });
  }

  handleFailure(agentKey) {
    clearInterval(this.timers[agentKey]);
    delete this.timers[agentKey];
    
    if (this.eventSources[agentKey]) {
      this.eventSources[agentKey].close();
      delete this.eventSources[agentKey];
    }

    const badge = document.getElementById(`badge-${agentKey}`);
    if (badge) {
      badge.className = 'monitor-col-badge badge-error';
      badge.textContent = 'failed';
    }
  }

  stopAgent(agentKey, sessionId) {
    this.handleFailure(agentKey);
    fetch(`/stop/${sessionId}`, { method: 'POST' }).catch(() => {});
  }

  abortAll() {
    Object.keys(this.eventSources).forEach(key => {
      if (this.eventSources[key]) {
        this.eventSources[key].close();
      }
    });
    this.eventSources = {};

    Object.keys(this.timers).forEach(key => {
      clearInterval(this.timers[key]);
    });
    this.timers = {};
  }

  async loadTraces() {
    const tbody = document.getElementById('paperclip-traces-list');
    if (!tbody) return;

    try {
      const res = await fetch('/agents/history');
      const data = await res.json();
      const logs = data.history || [];

      if (logs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="paperclip-loading-spinner">No traces recorded yet.</td></tr>';
        return;
      }

      tbody.innerHTML = logs.map(log => {
        const time = new Date(log.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const date = new Date(log.timestamp * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' });
        
        return `
          <tr>
            <td style="font-family:var(--font-mono); font-size:11px;">${date} ${time}</td>
            <td style="font-family:var(--font-mono); font-size:11px; max-width:140px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${log.session_id}</td>
            <td>
              <span class="skill-tag" style="background:${this.colors[log.agent] || '#6366f1'}; color:#fff;">
                ${log.agent}
              </span>
            </td>
            <td style="max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${log.prompt || ''}">${log.prompt || ''}</td>
            <td style="font-family:var(--font-mono);">${(log.duration_s || 0).toFixed(1)}s</td>
            <td style="font-family:var(--font-mono);">${log.tokens_in + log.tokens_out} tokens</td>
            <td>
              <button class="btn btn-secondary btn-sm trace-view-btn" data-sid="${log.session_id}">
                View Trace
              </button>
            </td>
          </tr>
        `;
      }).join('');

      tbody.querySelectorAll('.trace-view-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          this.viewTraceDetails(btn.dataset.sid);
        });
      });
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan="7" class="paperclip-loading-spinner" style="color:var(--text-danger);">Failed to load execution traces.</td></tr>';
    }
  }

  async viewTraceDetails(sessionId) {
    const modal = document.getElementById('paperclip-trace-modal');
    const body = document.getElementById('paperclip-trace-modal-body');
    const title = document.getElementById('paperclip-trace-modal-title');
    
    if (!modal || !body) return;
    
    title.textContent = `Audit Trail: ${sessionId}`;
    body.innerHTML = '<div class="paperclip-loading-spinner">Loading message traces...</div>';
    modal.style.display = 'flex';

    try {
      const res = await fetch(`/chat/sessions/${sessionId}`);
      const data = await res.json();
      const messages = data.messages || [];

      if (messages.length === 0) {
        body.innerHTML = '<p style="color:var(--text-muted);text-align:center;">No trace events saved for this execution.</p>';
        return;
      }

      body.innerHTML = messages.map(msg => {
        const isUser = msg.role === 'user';
        const roleColor = isUser ? 'var(--text-primary)' : '#a5b4fc';
        const roleLabel = isUser ? 'User Request' : 'Agent Response';
        const formatted = window.renderMd ? window.renderMd(msg.content) : msg.content;
        
        return `
          <div style="margin-bottom:20px; border-bottom:1px solid var(--border); padding-bottom:12px;">
            <div style="font-weight:700; font-size:11px; text-transform:uppercase; color:${roleColor}; margin-bottom:6px;">
              ${roleLabel}
            </div>
            <div style="font-size:13px; color:var(--text-primary);">${formatted}</div>
          </div>
        `;
      }).join('');
    } catch (e) {
      body.innerHTML = '<p style="color:var(--text-danger);text-align:center;">Failed to parse agent trace data.</p>';
    }
  }
}

window.PaperclipStudio = PaperclipStudio;
