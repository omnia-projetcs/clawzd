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
/*  2. Mode Switch Hint                                                */
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
};
