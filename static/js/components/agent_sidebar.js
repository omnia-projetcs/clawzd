/**
 * Clawzd — Agent Sidebar Component.
 *
 * Renders a sidebar panel showing available AI agents (Developer,
 * Researcher, Soul, Orchestrator) with real-time switching, status
 * indicators, and execution history.
 *
 * Communicates with:
 *   GET  /agents/list    — Agent profiles
 *   GET  /agents/detect  — Auto-detect best agent
 *   GET  /agents/history — Execution history
 */

const AgentSidebar = (() => {
  let _currentAgent = 'orchestrator';
  let _agents = {};
  let _panelEl = null;
  let _isOpen = false;

  // Agent icons and colors
  const _META = {
    orchestrator: { icon: 'brain', color: '#6366f1', label: 'Atlas' },
    developer:    { icon: 'code', color: '#10b981', label: 'Dev' },
    researcher:   { icon: 'search', color: '#f59e0b', label: 'Researcher' },
    soul:         { icon: 'heart', color: '#ec4899', label: 'Soul' },
  };

  /**
   * Initialize the agent sidebar.
   * @param {string} containerId - ID of the element to attach the toggle to
   */
  async function init(containerId) {
    await _loadAgents();
    _createPanel();
    _createToggleButton(containerId);
  }

  async function _loadAgents() {
    try {
      const res = await fetch('/agents/list');
      const data = await res.json();
      _agents = data.agents || {};
    } catch (e) {
      console.warn('AgentSidebar: failed to load agents', e);
    }
  }

  function _createPanel() {
    _panelEl = document.createElement('div');
    _panelEl.id = 'agent-sidebar';
    _panelEl.className = 'agent-sidebar';
    _panelEl.innerHTML = _renderPanel();
    document.body.appendChild(_panelEl);

    // Bind events
    _panelEl.addEventListener('click', (e) => {
      const editBtn = e.target.closest('.agent-card-edit-btn');
      if (editBtn) {
        e.stopPropagation();
        const key = editBtn.dataset.agentKey;
        openAgentEditor(key);
        return;
      }

      const createBtn = e.target.closest('#agent-create-btn');
      if (createBtn) {
        e.stopPropagation();
        openAgentEditor('');
        return;
      }

      const card = e.target.closest('[data-agent-key]');
      if (card) {
        selectAgent(card.dataset.agentKey);
      }
      if (e.target.closest('.agent-sidebar-close')) {
        toggle(false);
      }
    });
  }

  function _createToggleButton(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const btn = document.createElement('button');
    btn.id = 'agent-toggle-btn';
    btn.className = 'agent-toggle-btn';
    btn.title = 'Switch AI Agent';
    const iconName = _META[_currentAgent]?.icon || 'brain';
    btn.innerHTML = `<span class="agent-toggle-icon"><svg class="ic" width="16" height="16"><use href="#icon-${iconName}"></use></svg></span>`;
    btn.onclick = () => toggle();

    // Insert at the start of the container
    container.insertBefore(btn, container.firstChild);
  }

  function _renderPanel() {
    const baseKeys = ['orchestrator', 'developer', 'researcher', 'soul'];
    const loadedKeys = Object.keys(_agents);
    const agentKeys = Array.from(new Set([...baseKeys, ...loadedKeys]));

    const cards = agentKeys.map(key => {
      const meta = _META[key] || { icon: 'bot', color: '#6366f1', label: key };
      const agent = _agents[key];
      const isActive = key === _currentAgent;
      const role = agent?.role || '';
      const iconHtml = `<svg class="ic" width="28" height="28" style="color: ${meta.color}"><use href="#icon-${meta.icon}"></use></svg>`;

      return `
        <div class="agent-card ${isActive ? 'agent-card-active' : ''}"
             data-agent-key="${key}"
             style="--agent-color: ${meta.color}">
          <div class="agent-card-icon">${iconHtml}</div>
          <div class="agent-card-body">
            <div class="agent-card-name">${agent?.name || meta.label}</div>
            <div class="agent-card-role">${role}</div>
          </div>
          <button class="agent-card-edit-btn" 
                  data-agent-key="${key}" 
                  title="Edit Preprompt" 
                  style="background:none; border:none; color:var(--text-muted); cursor:pointer; padding:4px; margin-left:8px; display:flex; align-items:center; justify-content:center; border-radius:4px; transition:all 0.2s">
            <svg class="ic" width="14" height="14" style="color:var(--text-muted)">
              <use href="#icon-pen"></use>
            </svg>
          </button>
          ${isActive ? '<div class="agent-card-badge" style="margin-left:6px;">Active</div>' : ''}
        </div>
      `;
    }).join('');

    return `
      <div class="agent-sidebar-header">
        <h3>AI Agents</h3>
        <button class="agent-sidebar-close" title="Close">&times;</button>
      </div>
      <div class="agent-sidebar-cards">${cards}</div>
      <div class="agent-sidebar-footer">
        <button class="btn btn-secondary btn-block" id="agent-create-btn" style="margin-bottom:12px; width:100%; display:flex; align-items:center; justify-content:center; gap:6px;">
          <svg class="ic" width="14" height="14"><use href="#icon-plus"></use></svg>
          Create Custom Agent
        </button>
        <div class="agent-sidebar-hint">
          Agent auto-detects from your message context.
          Click to manually override.
        </div>
      </div>
    `;
  }

  function selectAgent(key) {
    _currentAgent = key;
    // Re-render panel
    if (_panelEl) {
      _panelEl.innerHTML = _renderPanel();
    }
    // Update toggle button icon
    const btn = document.getElementById('agent-toggle-btn');
    if (btn) {
      const meta = _META[key] || { icon: 'bot' };
      btn.querySelector('.agent-toggle-icon').innerHTML = `<svg class="ic" width="16" height="16"><use href="#icon-${meta.icon}"></use></svg>`;
    }
    // Dispatch event for gateway integration
    window.dispatchEvent(new CustomEvent('agent:switch', { detail: { agent: key } }));

    // Show toast
    const name = _agents[key]?.name || key;
    if (typeof window.toast === 'function') {
      window.toast(`Agent switched to ${name}`, 'info');
    }
  }

  function openAgentEditor(key) {
    const overlay = document.getElementById('agent-editor-overlay');
    if (!overlay) return;

    const titleEl = document.getElementById('agent-editor-title');
    const keyInput = document.getElementById('agent-editor-key');
    const nameInput = document.getElementById('agent-editor-name');
    const roleInput = document.getElementById('agent-editor-role');
    const modelInput = document.getElementById('agent-editor-model');
    const skillsInput = document.getElementById('agent-editor-skills');
    const promptTextarea = document.getElementById('agent-editor-system-prompt');

    if (key) {
      titleEl.textContent = 'Edit Agent Preprompt';
      keyInput.value = key;
      keyInput.disabled = true;

      // Fetch details from backend
      fetch(`/agents/detail?key=${encodeURIComponent(key)}`)
        .then(res => res.json())
        .then(data => {
          if (data.error) {
            if (typeof window.toast === 'function') window.toast(data.error, 'error');
            return;
          }
          nameInput.value = data.name || '';
          roleInput.value = data.role || '';
          modelInput.value = data.model || '';
          skillsInput.value = data.skills || '';
          promptTextarea.value = data.system_prompt || '';
        })
        .catch(err => {
          console.error('Error fetching agent detail:', err);
          if (typeof window.toast === 'function') window.toast('Failed to load agent details', 'error');
        });
    } else {
      titleEl.textContent = 'Create Custom Agent';
      keyInput.value = '';
      keyInput.disabled = false;
      nameInput.value = '';
      roleInput.value = '';
      modelInput.value = '';
      skillsInput.value = '';
      promptTextarea.value = '';
    }

    overlay.style.display = 'flex';

    const closeBtn = document.getElementById('agent-editor-close');
    const cancelBtn = document.getElementById('agent-editor-cancel');
    const saveBtn = document.getElementById('agent-editor-save');

    function closeEditor() {
      overlay.style.display = 'none';
      cleanup();
    }

    async function saveAgent() {
      const payload = {
        key: keyInput.value.trim(),
        name: nameInput.value.trim(),
        role: roleInput.value.trim(),
        model: modelInput.value.trim(),
        skills: skillsInput.value.trim(),
        system_prompt: promptTextarea.value
      };

      if (!payload.key) {
        if (typeof window.toast === 'function') window.toast('Agent identifier key is required', 'warning');
        return;
      }
      if (!payload.name) {
        if (typeof window.toast === 'function') window.toast('Agent display name is required', 'warning');
        return;
      }

      if (typeof window.setButtonLoading === 'function') {
        window.setButtonLoading(saveBtn, true);
      } else {
        saveBtn.disabled = true;
      }

      try {
        const res = await fetch('/agents/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.error) {
          if (typeof window.toast === 'function') window.toast(data.error, 'error');
        } else {
          if (typeof window.toast === 'function') window.toast('Agent preprompt saved successfully', 'success');
          closeEditor();
          await _loadAgents();
          if (_panelEl) {
            _panelEl.innerHTML = _renderPanel();
          }
        }
      } catch (err) {
        console.error('Error saving agent:', err);
        if (typeof window.toast === 'function') window.toast('Failed to save agent profile', 'error');
      } finally {
        if (typeof window.setButtonLoading === 'function') {
          window.setButtonLoading(saveBtn, false);
        } else {
          saveBtn.disabled = false;
        }
      }
    }

    function cleanup() {
      closeBtn.removeEventListener('click', closeEditor);
      cancelBtn.removeEventListener('click', closeEditor);
      saveBtn.removeEventListener('click', saveAgent);
    }

    closeBtn.addEventListener('click', closeEditor);
    cancelBtn.addEventListener('click', closeEditor);
    saveBtn.addEventListener('click', saveAgent);
  }

  function toggle(force) {
    _isOpen = force !== undefined ? force : !_isOpen;
    if (_panelEl) {
      _panelEl.classList.toggle('agent-sidebar-open', _isOpen);
    }
  }

  function getCurrentAgent() {
    return _currentAgent;
  }

  return { init, selectAgent, toggle, getCurrentAgent };
})();

window.AgentSidebar = AgentSidebar;
