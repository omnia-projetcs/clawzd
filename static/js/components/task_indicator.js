/**
 * Clawzd — TaskIndicator
 *
 * Global component that polls /api/tasks/active to detect running
 * background tasks, shows pulsing badges on the corresponding
 * mode buttons, and exposes a compact task center in the status bar.
 * It also notifies individual studios to reconnect when they become visible.
 */
/* global toast, ICONS */

class TaskIndicator {
  constructor() {
    this._interval = null;
    this._tasks = [];
    this._history = [];
    this._badges = new Map(); // mode -> badge DOM element
    this._panelOpen = false;
    this._lastHistoryFetch = 0;
    this._rootEl = null;
    this._buttonEl = null;
    this._countEl = null;
    this._panelEl = null;
    this.start();
  }

  start() {
    this._ensureStatusWidget();
    // Poll every 3 seconds
    this._poll();
    this._interval = setInterval(() => this._poll(), 3000);
  }

  stop() {
    if (this._interval) {
      clearInterval(this._interval);
      this._interval = null;
    }
  }

  async _poll() {
    try {
      const resp = await fetch('/api/tasks/active');
      if (!resp.ok) return;
      const data = await resp.json();
      this._tasks = data.tasks || [];
      this._updateBadges();
      this._updateStatusWidget();
      if (this._panelOpen && Date.now() - this._lastHistoryFetch > 2500) {
        await this._refreshHistory();
      }
    } catch (e) {
      // Silently ignore poll errors
    }
  }

  _updateBadges() {
    // Map task types to mode button IDs
    const typeToMode = {
      'research': 'research',
      'image': 'media',
      'video': 'media',
      'audio': 'media',
      'audio_lab': 'media',
    };

    // Determine which modes have active tasks
    const activeModes = new Map(); // mode -> task type (for coloring)
    for (const task of this._tasks) {
      const mode = typeToMode[task.type] || task.type;
      if (!activeModes.has(mode)) {
        activeModes.set(mode, task.type);
      }
    }

    // Find all mode buttons
    const buttons = document.querySelectorAll('#mode-toggle .mode-btn');
    buttons.forEach(btn => {
      const mode = btn.dataset.mode;
      if (!mode) return;

      if (activeModes.has(mode)) {
        // Add or update badge
        let badge = this._badges.get(mode);
        if (!badge) {
          badge = document.createElement('span');
          badge.className = 'task-indicator-badge';
          btn.appendChild(badge);
          this._badges.set(mode, badge);
        }
        // Update type class for coloring
        badge.className = 'task-indicator-badge type-' + activeModes.get(mode);
      } else {
        // Remove badge if exists
        const badge = this._badges.get(mode);
        if (badge) {
          badge.remove();
          this._badges.delete(mode);
        }
      }
    });

    // Notify studios about active tasks so they can reconnect
    this._notifyStudios();
  }

  _ensureStatusWidget() {
    if (this._rootEl) return;

    const host = document.querySelector('.status-bar-right') || document.getElementById('status-bar');
    if (!host) return;

    const root = document.createElement('div');
    root.className = 'task-center';

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'task-center-btn idle';
    button.title = 'Background tasks';
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-controls', 'task-center-panel');
    button.innerHTML = `${this._icon('activity', 12)}<span class="task-center-label">Tasks</span><span class="task-center-count">0</span>`;

    const panel = document.createElement('div');
    panel.id = 'task-center-panel';
    panel.className = 'task-center-panel';
    panel.hidden = true;

    button.addEventListener('click', (event) => {
      event.stopPropagation();
      this._togglePanel();
    });

    document.addEventListener('click', (event) => {
      if (this._panelOpen && this._rootEl && !this._rootEl.contains(event.target)) {
        this._closePanel();
      }
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && this._panelOpen) {
        this._closePanel();
      }
    });

    root.appendChild(button);
    root.appendChild(panel);
    host.insertBefore(root, host.firstChild);

    this._rootEl = root;
    this._buttonEl = button;
    this._countEl = button.querySelector('.task-center-count');
    this._panelEl = panel;
    this._renderPanel();
  }

  _togglePanel() {
    if (this._panelOpen) {
      this._closePanel();
    } else {
      this._openPanel();
    }
  }

  async _openPanel() {
    this._ensureStatusWidget();
    if (!this._panelEl || !this._buttonEl) return;
    this._panelOpen = true;
    this._panelEl.hidden = false;
    this._buttonEl.setAttribute('aria-expanded', 'true');
    this._buttonEl.classList.add('open');
    this._renderPanel();
    await this._refreshHistory();
  }

  _closePanel() {
    if (!this._panelEl || !this._buttonEl) return;
    this._panelOpen = false;
    this._panelEl.hidden = true;
    this._buttonEl.setAttribute('aria-expanded', 'false');
    this._buttonEl.classList.remove('open');
  }

  async _refreshHistory() {
    try {
      const resp = await fetch('/api/tasks/history?limit=10');
      if (!resp.ok) return;
      const data = await resp.json();
      this._history = data.tasks || [];
      this._lastHistoryFetch = Date.now();
      this._renderPanel();
    } catch (e) {
      // Best-effort panel metadata.
    }
  }

  _updateStatusWidget() {
    this._ensureStatusWidget();
    if (!this._buttonEl || !this._countEl) return;

    const activeCount = this._tasks.length;
    this._countEl.textContent = String(activeCount);
    this._buttonEl.classList.toggle('idle', activeCount === 0);
    this._buttonEl.classList.toggle('has-active', activeCount > 0);
    this._buttonEl.title = activeCount > 0
      ? `${activeCount} background task${activeCount > 1 ? 's' : ''} running`
      : 'No background task running';

    if (this._panelOpen) {
      this._renderPanel();
    }
  }

  _renderPanel() {
    if (!this._panelEl) return;

    const panel = this._panelEl;
    panel.textContent = '';

    const header = document.createElement('div');
    header.className = 'task-center-header';

    const title = document.createElement('div');
    title.className = 'task-center-title';
    title.innerHTML = `${this._icon('activity', 13)}<span>Tasks</span>`;

    const actions = document.createElement('div');
    actions.className = 'task-center-actions';

    const refreshBtn = document.createElement('button');
    refreshBtn.type = 'button';
    refreshBtn.className = 'task-center-icon-btn';
    refreshBtn.title = 'Refresh';
    refreshBtn.innerHTML = this._icon('refresh', 12) || 'R';
    refreshBtn.addEventListener('click', async (event) => {
      event.stopPropagation();
      await this._poll();
      await this._refreshHistory();
    });

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'task-center-icon-btn';
    closeBtn.title = 'Close';
    closeBtn.innerHTML = this._icon('x', 12) || 'x';
    closeBtn.addEventListener('click', (event) => {
      event.stopPropagation();
      this._closePanel();
    });

    actions.appendChild(refreshBtn);
    actions.appendChild(closeBtn);
    header.appendChild(title);
    header.appendChild(actions);
    panel.appendChild(header);

    panel.appendChild(this._renderSection('Running', this._tasks, true));
    panel.appendChild(this._renderSection('Recent', this._history, false));
  }

  _renderSection(title, tasks, active) {
    const section = document.createElement('section');
    section.className = 'task-center-section';

    const header = document.createElement('div');
    header.className = 'task-center-section-title';

    const label = document.createElement('span');
    label.textContent = title;

    const count = document.createElement('span');
    count.className = 'task-center-section-count';
    count.textContent = String(tasks.length);

    header.appendChild(label);
    header.appendChild(count);
    section.appendChild(header);

    const list = document.createElement('div');
    list.className = 'task-center-list';

    if (!tasks.length) {
      const empty = document.createElement('div');
      empty.className = 'task-center-empty';
      empty.textContent = active ? 'No running tasks' : 'No recent tasks';
      list.appendChild(empty);
    } else {
      tasks.forEach((task) => list.appendChild(this._renderTaskItem(task, active)));
    }

    section.appendChild(list);
    return section;
  }

  _renderTaskItem(task, active) {
    const item = document.createElement('div');
    item.className = `task-center-item type-${task.type || 'unknown'} status-${task.status || 'unknown'}`;

    const top = document.createElement('div');
    top.className = 'task-center-item-top';

    const dot = document.createElement('span');
    dot.className = `task-center-dot type-${task.type || 'unknown'}`;

    const main = document.createElement('div');
    main.className = 'task-center-main';

    const name = document.createElement('div');
    name.className = 'task-center-name';
    name.title = this._taskTitle(task);
    name.textContent = this._taskTitle(task);

    const meta = document.createElement('div');
    meta.className = 'task-center-meta';
    meta.textContent = this._taskMeta(task, active);

    main.appendChild(name);
    main.appendChild(meta);

    top.appendChild(dot);
    top.appendChild(main);

    if (active && this._isCancellable(task.type)) {
      const stopBtn = document.createElement('button');
      stopBtn.type = 'button';
      stopBtn.className = 'task-center-stop';
      stopBtn.title = 'Stop task';
      stopBtn.innerHTML = `${this._icon('square', 11)}<span>Stop</span>`;
      stopBtn.addEventListener('click', (event) => {
        event.stopPropagation();
        this._stopTask(task.id, stopBtn);
      });
      top.appendChild(stopBtn);
    } else {
      const status = document.createElement('span');
      status.className = `task-center-status status-${task.status || 'unknown'}`;
      status.textContent = this._statusLabel(task.status);
      top.appendChild(status);
    }

    item.appendChild(top);

    if (active) {
      const progress = this._safeProgress(task.progress);
      const bar = document.createElement('div');
      bar.className = 'task-center-progress';
      const fill = document.createElement('span');
      fill.style.width = `${progress}%`;
      bar.appendChild(fill);
      item.appendChild(bar);
    }

    return item;
  }

  async _stopTask(taskId, button) {
    if (!taskId) return;
    const oldHtml = button ? button.innerHTML : '';
    if (button) {
      button.disabled = true;
      button.innerHTML = this._icon('hourglass', 11) || '...';
    }

    try {
      const resp = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/stop`, { method: 'POST' });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || 'Stop failed');
      }
      if (typeof toast === 'function') toast(`${this._icon('check', 14)} Task stopped`);
      await this._poll();
      await this._refreshHistory();
    } catch (e) {
      if (button) {
        button.disabled = false;
        button.innerHTML = oldHtml;
      }
      if (typeof toast === 'function') toast(`${this._icon('x', 14)} ${e.message || 'Stop failed'}`);
    }
  }

  _taskTitle(task) {
    const type = this._typeLabel(task.type);
    const label = task.label || task.metadata?.prompt || task.metadata?.filename || '';
    if (!label) return type;
    return `${type}: ${label}`;
  }

  _taskMeta(task, active) {
    const bits = [];
    const stage = task.stage && task.stage !== task.status ? task.stage : task.status;
    if (stage) bits.push(this._statusLabel(stage));
    if (active) bits.push(`${this._safeProgress(task.progress)}%`);
    const since = task.updated_at || task.ended_at || task.started_at;
    if (since) bits.push(this._timeAgo(since));
    return bits.join(' - ');
  }

  _typeLabel(type) {
    const labels = {
      research: 'Research',
      image: 'Image',
      video: 'Video',
      audio: 'Audio',
      automation: 'Automation',
      presentation: 'Presentation',
      audio_lab: 'Audio Lab',
    };
    if (!type) return 'Task';
    return labels[type] || String(type).charAt(0).toUpperCase() + String(type).slice(1);
  }

  _statusLabel(status) {
    const labels = {
      queued: 'Queued',
      running: 'Running',
      completed: 'Done',
      failed: 'Failed',
      stopped: 'Stopped',
      paused: 'Paused',
      interrupted: 'Interrupted',
      generating: 'Generating',
    };
    if (!status) return 'Unknown';
    return labels[status] || String(status).replace(/_/g, ' ');
  }

  _safeProgress(progress) {
    const value = Number(progress);
    if (!Number.isFinite(value)) return 0;
    return Math.max(0, Math.min(100, Math.round(value)));
  }

  _isCancellable(type) {
    return ['research', 'image', 'video', 'audio'].includes(type);
  }

  _timeAgo(iso) {
    if (typeof window.timeAgo === 'function') return window.timeAgo(iso);
    const date = new Date(iso);
    const diff = (Date.now() - date.getTime()) / 1000;
    if (!Number.isFinite(diff)) return '';
    if (diff < 60) return 'now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
    return `${Math.floor(diff / 86400)}d`;
  }

  _icon(name, size) {
    if (window.icon) return window.icon(name, size);
    if (typeof ICONS !== 'undefined' && ICONS[name]) return ICONS[name](size);
    return '';
  }

  _notifyStudios() {
    // Research: if there's a running research task and the studio is visible, reconnect SSE
    const researchTasks = this._tasks.filter(t => t.type === 'research');
    if (window.researchStudio && researchTasks.length > 0) {
      const rs = window.researchStudio;
      // Only reconnect if the studio is visible and we're not already connected
      if (rs._isVisible && rs.currentProject && !rs._sse) {
        const runningTask = researchTasks.find(t => t.id === rs.currentProject.id);
        if (runningTask) {
          rs._connectSSE(rs.currentProject.id);
          rs._updateStatus('running');
        }
      }
    }

    // Media: if there's a running media task and the studio is visible
    const mediaTasks = this._tasks.filter(t =>
      t.type === 'image' || t.type === 'video' || t.type === 'audio'
    );
    if (window.mediaStudio && mediaTasks.length > 0) {
      const ms = window.mediaStudio;
      if (ms.active && !ms.generating) {
        ms._resumeFromTask(mediaTasks[0]);
      }
    }
  }

  /** Get all current active tasks */
  getTasks() {
    return this._tasks;
  }

  /** Check if a specific task type is running */
  hasActiveTask(type) {
    return this._tasks.some(t => t.type === type);
  }

  /** Force a refresh */
  refresh() {
    this._poll();
  }
}

window.TaskIndicator = TaskIndicator;
