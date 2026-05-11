/**
 * Clawzd — Roo Code-Inspired Chat Enhancements.
 *
 * Features:
 * 1. Suggestion Chips — clickable follow-up suggestions after each response
 * 2. Mode Switch Hint — interactive chip when AI suggests a mode change
 *
 * Note: Prompt enhancement is automatic (handled in Chat.send() via /api/enhance).
 * Loaded by app.js after Chat class init.
 */

/* ------------------------------------------------------------------ */
/*  1. Suggestion Chips                                                */
/* ------------------------------------------------------------------ */

/**
 * Parse and extract suggestions from an SSE token.
 * Returns the suggestions array if found, or null.
 */
function extractSuggestions(token) {
  const marker = '__SUGGESTIONS__';
  if (typeof token !== 'string' || !token.includes(marker)) return null;

  try {
    const start = token.indexOf(marker) + marker.length;
    const end = token.lastIndexOf(marker);
    if (end <= start) return null;
    const json = token.substring(start, end);
    const arr = JSON.parse(json);
    if (Array.isArray(arr) && arr.every(s => typeof s === 'string')) return arr;
  } catch (e) {
    console.debug('Failed to parse suggestions:', e);
  }
  return null;
}

/**
 * Render suggestion chips below the last assistant message bubble.
 */
function renderSuggestionChips(suggestions, chatInstance) {
  if (!suggestions || !suggestions.length) return;

  const msgEl = document.getElementById('chat-messages');
  if (!msgEl) return;

  // Remove any existing suggestion chips
  msgEl.querySelectorAll('.suggestion-chips').forEach(el => el.remove());

  const container = document.createElement('div');
  container.className = 'suggestion-chips';

  suggestions.forEach(text => {
    const chip = document.createElement('button');
    chip.className = 'suggestion-chip';
    chip.textContent = text;
    chip.title = 'Click to send as follow-up';

    chip.addEventListener('click', () => {
      // Remove chips
      container.remove();
      // Put text in input and send
      const input = document.getElementById('chat-input');
      if (input) {
        input.value = text;
        input.dispatchEvent(new Event('input'));
      }
      // Trigger send
      if (chatInstance && typeof chatInstance.send === 'function') {
        chatInstance.send();
      } else {
        const sendBtn = document.getElementById('chat-send');
        if (sendBtn) sendBtn.click();
      }
    });

    // Shift+click to edit before sending
    chip.addEventListener('mousedown', (e) => {
      if (e.shiftKey) {
        e.preventDefault();
        e.stopPropagation();
        container.remove();
        const input = document.getElementById('chat-input');
        if (input) {
          input.value = text;
          input.focus();
          input.style.height = 'auto';
          input.style.height = input.scrollHeight + 'px';
        }
      }
    });

    container.appendChild(chip);
  });

  msgEl.appendChild(container);
  msgEl.scrollTop = msgEl.scrollHeight;
}


/* ------------------------------------------------------------------ */
/*  2. Todo Panel — Plan Board (inspired by Claude Code TodoWriteTool) */
/* ------------------------------------------------------------------ */


const _TODO_MARKER = '__TODO_UPDATE__';

const _STATUS_ICONS = {
  pending:     '⏳',
  in_progress: '🔄',
  completed:   '✅',
  cancelled:   '❌',
};

const _PRIORITY_CLASSES = {
  high:   'todo-priority-high',
  medium: 'todo-priority-medium',
  low:    'todo-priority-low',
};

/**
 * Parse a __TODO_UPDATE__ SSE token.
 * Returns the parsed todo data object, or null if not a todo marker.
 */
function parseTodoUpdate(token) {
  if (typeof token !== 'string' || !token.includes(_TODO_MARKER)) return null;
  try {
    const start = token.indexOf(_TODO_MARKER) + _TODO_MARKER.length;
    const end   = token.lastIndexOf(_TODO_MARKER);
    if (end <= start) return null;
    return JSON.parse(token.substring(start, end));
  } catch (e) {
    console.debug('Failed to parse todo update:', e);
    return null;
  }
}

/**
 * Render or update the floating Todo Panel.
 * Creates the panel if it doesn't exist, otherwise updates in place.
 */
function renderTodoPanel(data) {
  if (!data || !Array.isArray(data.todos)) return;

  const todos = data.todos;
  const action = data.action || 'written';

  // Clear panel if action is 'cleared'
  if (action === 'cleared' || todos.length === 0) {
    const existing = document.getElementById('chat-todo-panel');
    if (existing) {
      existing.classList.add('todo-panel-exit');
      setTimeout(() => existing.remove(), 350);
    }
    return;
  }

  let panel = document.getElementById('chat-todo-panel');
  const isNew = !panel;

  if (isNew) {
    panel = document.createElement('div');
    panel.id = 'chat-todo-panel';
    panel.className = 'todo-panel';
    panel.innerHTML = `
      <div class="todo-panel-header">
        <span class="todo-panel-title">📋 Plan</span>
        <span class="todo-panel-count" id="todo-panel-count"></span>
        <button class="todo-panel-close" title="Close plan panel" aria-label="Close">×</button>
      </div>
      <ul class="todo-panel-list" id="todo-panel-list"></ul>
    `;
    panel.querySelector('.todo-panel-close').addEventListener('click', () => {
      panel.classList.add('todo-panel-exit');
      setTimeout(() => panel.remove(), 350);
    });
    // Insert at the top of the chat area (or body)
    const chatArea = document.getElementById('chat-messages') || document.body;
    const parent = chatArea.parentElement || document.body;
    parent.insertBefore(panel, chatArea);
  }

  // Update items
  const list = panel.querySelector('#todo-panel-list') || panel.querySelector('ul');
  const countEl = panel.querySelector('#todo-panel-count');

  if (!list) return;

  // Render each item (update existing or add new)
  const existingIds = new Set();
  list.querySelectorAll('.todo-item[data-id]').forEach(el => existingIds.add(el.dataset.id));

  todos.forEach(todo => {
    const id = todo.id || '';
    const icon = _STATUS_ICONS[todo.status] || '⏳';
    const prioClass = _PRIORITY_CLASSES[todo.priority] || 'todo-priority-medium';
    const isDone = todo.status === 'completed' || todo.status === 'cancelled';

    let item = list.querySelector(`.todo-item[data-id="${id}"]`);
    if (item) {
      // Update existing item in-place
      item.className = `todo-item todo-status-${todo.status} ${prioClass}`;
      const iconEl = item.querySelector('.todo-icon');
      const contentEl = item.querySelector('.todo-content');
      if (iconEl) iconEl.textContent = icon;
      if (contentEl) contentEl.textContent = todo.content;
      if (isDone) item.classList.add('todo-done');
      else item.classList.remove('todo-done');
    } else {
      // Add new
      item = document.createElement('li');
      item.className = `todo-item todo-status-${todo.status} ${prioClass}`;
      item.dataset.id = id;
      item.innerHTML = `
        <span class="todo-icon">${icon}</span>
        <span class="todo-content">${_escHtml(todo.content)}</span>
      `;
      list.appendChild(item);
      // Entrance animation
      requestAnimationFrame(() => item.classList.add('todo-item-visible'));
    }
  });

  // Update count badge
  const done = todos.filter(t => t.status === 'completed').length;
  if (countEl) countEl.textContent = `${done}/${todos.length}`;

  // Entrance animation for new panel
  if (isNew) {
    requestAnimationFrame(() => panel.classList.add('todo-panel-visible'));
  }
}

function _escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}


/* ------------------------------------------------------------------ */
/*  3. Mode Switch Hint                                                */
/* ------------------------------------------------------------------ */

/**
 * Detect mode-switch suggestions in assistant text and render
 * an interactive chip that changes the mode selector.
 */
function renderModeSwitchHint(text) {
  const modeMap = {
    'chat': 'none',
    'code': 'developer',
    'developer': 'developer',
    'write': 'writer',
    'writer': 'writer',
    'audit': 'auditor',
    'auditor': 'auditor',
    'architect': 'architect',
    'design': 'designer',
    'designer': 'designer',
  };

  const pattern = /💡[^.]*?(?:switch|try|essaye|passe)[^.]*?\b(chat|code|developer|write|writer|audit|auditor|architect|design|designer)\b[^.]*?mode/i;
  const match = text.match(pattern);
  if (!match) return;

  const suggestedMode = modeMap[match[1].toLowerCase()];
  if (!suggestedMode) return;

  const modeSelect = document.getElementById('action-mode-select');
  if (!modeSelect || modeSelect.value === suggestedMode) return;

  // Find the target option label
  const option = modeSelect.querySelector(`option[value="${suggestedMode}"]`);
  if (!option) return;

  const msgEl = document.getElementById('chat-messages');
  if (!msgEl) return;

  // Don't add duplicate switch hints
  if (msgEl.querySelector('.mode-switch-hint')) return;

  const hint = document.createElement('div');
  hint.className = 'mode-switch-hint';
  hint.innerHTML = `
    <span class="mode-switch-label">💡 Switch to ${option.textContent.trim()} mode?</span>
    <button class="mode-switch-btn" data-mode="${suggestedMode}">Switch</button>
    <button class="mode-switch-dismiss">✕</button>
  `;

  hint.querySelector('.mode-switch-btn').addEventListener('click', () => {
    modeSelect.value = suggestedMode;
    modeSelect.dispatchEvent(new Event('change'));
    hint.remove();
    if (typeof window.toast === 'function') window.toast(`Switched to ${option.textContent.trim()} mode`);
  });

  hint.querySelector('.mode-switch-dismiss').addEventListener('click', () => {
    hint.classList.add('dismissing');
    setTimeout(() => hint.remove(), 300);
  });

  msgEl.appendChild(hint);
  msgEl.scrollTop = msgEl.scrollHeight;
}


/* ------------------------------------------------------------------ */
/*  Export                                                              */
/* ------------------------------------------------------------------ */

window.ChatEnhancements = {
  extractSuggestions,
  renderSuggestionChips,
  renderModeSwitchHint,
  parseTodoUpdate,
  renderTodoPanel,
};
