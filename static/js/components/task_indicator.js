/**
 * Clawzd — TaskIndicator
 *
 * Global component that polls /api/tasks/active to detect running
 * background tasks and shows pulsing badges on the corresponding
 * mode buttons. Also notifies individual studios to reconnect
 * when they become visible.
 */
/* global $, $$, toast, ICONS */

class TaskIndicator {
  constructor() {
    this._interval = null;
    this._tasks = [];
    this._badges = new Map(); // mode -> badge DOM element
    this.start();
  }

  start() {
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
