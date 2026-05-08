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
    orchestrator: { icon: '🧠', color: '#6366f1', label: 'Atlas' },
    developer:    { icon: '💻', color: '#10b981', label: 'Dev' },
    researcher:   { icon: '🔍', color: '#f59e0b', label: 'Researcher' },
    soul:         { icon: '💜', color: '#ec4899', label: 'Soul' },
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
    btn.innerHTML = `<span class="agent-toggle-icon">${_META[_currentAgent]?.icon || '🧠'}</span>`;
    btn.onclick = () => toggle();

    // Insert at the start of the container
    container.insertBefore(btn, container.firstChild);
  }

  function _renderPanel() {
    const agentKeys = ['orchestrator', 'developer', 'researcher', 'soul'];
    const cards = agentKeys.map(key => {
      const meta = _META[key] || { icon: '🤖', color: '#64748b', label: key };
      const agent = _agents[key];
      const isActive = key === _currentAgent;
      const role = agent?.role || '';

      return `
        <div class="agent-card ${isActive ? 'agent-card-active' : ''}"
             data-agent-key="${key}"
             style="--agent-color: ${meta.color}">
          <div class="agent-card-icon">${meta.icon}</div>
          <div class="agent-card-body">
            <div class="agent-card-name">${agent?.name || meta.label}</div>
            <div class="agent-card-role">${role}</div>
          </div>
          ${isActive ? '<div class="agent-card-badge">Active</div>' : ''}
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
      const meta = _META[key] || { icon: '🤖' };
      btn.querySelector('.agent-toggle-icon').textContent = meta.icon;
    }
    // Dispatch event for gateway integration
    window.dispatchEvent(new CustomEvent('agent:switch', { detail: { agent: key } }));

    // Show toast
    const name = _agents[key]?.name || key;
    if (typeof window.toast === 'function') {
      window.toast(`Agent switched to ${name}`, 'info');
    }
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
