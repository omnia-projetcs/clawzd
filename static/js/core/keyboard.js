/**
 * Clawzd — Global Keyboard Shortcuts.
 *
 * Centralized keyboard shortcut manager.
 * Shortcuts are disabled inside text inputs/textareas unless explicitly allowed.
 *
 * Usage:
 *   KeyboardManager.init();
 *   KeyboardManager.register('ctrl+k', () => openCommandPalette());
 */
(function () {
  'use strict';

  /** @type {Map<string, {handler: Function, description: string, allowInInput: boolean}>} */
  const _shortcuts = new Map();

  /** Whether the manager is active */
  let _active = false;

  /**
   * Normalize a KeyboardEvent into a shortcut string.
   * @param {KeyboardEvent} e
   * @returns {string} e.g., 'ctrl+k', 'ctrl+shift+p', 'escape'
   */
  function _normalize(e) {
    const parts = [];
    if (e.ctrlKey || e.metaKey) parts.push('ctrl');
    if (e.shiftKey) parts.push('shift');
    if (e.altKey) parts.push('alt');

    let key = e.key.toLowerCase();
    // Normalize special keys
    if (key === ' ') key = 'space';
    if (key === 'arrowup') key = 'up';
    if (key === 'arrowdown') key = 'down';
    if (key === 'arrowleft') key = 'left';
    if (key === 'arrowright') key = 'right';

    // Don't include modifier keys themselves
    if (['control', 'shift', 'alt', 'meta'].includes(key)) return '';

    parts.push(key);
    return parts.join('+');
  }

  /**
   * Check if the event target is a text input element.
   */
  function _isTextInput(target) {
    if (!target) return false;
    const tag = target.tagName;
    if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
    if (tag === 'INPUT') {
      const type = target.type || 'text';
      return ['text', 'search', 'email', 'password', 'url', 'number', 'tel'].includes(type);
    }
    if (target.isContentEditable) return true;
    // CodeMirror
    if (target.classList && target.classList.contains('cm-content')) return true;
    return false;
  }

  const KeyboardManager = {
    /**
     * Initialize the keyboard manager.
     * Registers the global keydown listener and default shortcuts.
     */
    init() {
      if (_active) return;
      _active = true;

      document.addEventListener('keydown', (e) => {
        const combo = _normalize(e);
        if (!combo) return;

        const shortcut = _shortcuts.get(combo);
        if (!shortcut) return;

        // Skip if in text input (unless allowed)
        if (!shortcut.allowInInput && _isTextInput(e.target)) return;

        e.preventDefault();
        e.stopPropagation();

        try {
          shortcut.handler(e);
        } catch (err) {
          console.error(`[Keyboard] Error in shortcut "${combo}":`, err);
        }

        if (window.EventBus) {
          window.EventBus.emit('keyboard:shortcut', { combo, description: shortcut.description });
        }
      });

      // Register default shortcuts
      this._registerDefaults();
    },

    /**
     * Register a keyboard shortcut.
     * @param {string} combo - e.g., 'ctrl+k', 'ctrl+shift+p', 'escape'
     * @param {Function} handler
     * @param {Object} [opts]
     * @param {string} [opts.description] - Human-readable description
     * @param {boolean} [opts.allowInInput] - Allow in text inputs (default: false)
     */
    register(combo, handler, opts) {
      const o = opts || {};
      _shortcuts.set(combo.toLowerCase(), {
        handler,
        description: o.description || combo,
        allowInInput: !!o.allowInInput,
      });
    },

    /**
     * Unregister a shortcut.
     * @param {string} combo
     */
    unregister(combo) {
      _shortcuts.delete(combo.toLowerCase());
    },

    /**
     * Get all registered shortcuts for help display.
     * @returns {Array<{combo: string, description: string}>}
     */
    list() {
      const result = [];
      _shortcuts.forEach((v, k) => {
        result.push({ combo: k, description: v.description });
      });
      return result.sort((a, b) => a.combo.localeCompare(b.combo));
    },

    /**
     * Show keyboard shortcuts help modal.
     */
    showHelp() {
      const shortcuts = this.list();
      const rows = shortcuts.map(s => {
        const keys = s.combo.split('+').map(k =>
          `<kbd>${k.charAt(0).toUpperCase() + k.slice(1)}</kbd>`
        ).join(' + ');
        return `<tr><td>${keys}</td><td>${s.description}</td></tr>`;
      }).join('');

      const html = `
        <div class="keyboard-help-overlay" onclick="if(event.target===this)this.remove()">
          <div class="keyboard-help-modal">
            <div class="keyboard-help-header">
              <h3>⌨️ Keyboard Shortcuts</h3>
              <button onclick="this.closest('.keyboard-help-overlay').remove()"
                      style="background:none;border:none;color:var(--text-secondary);font-size:18px;cursor:pointer;">✕</button>
            </div>
            <table class="keyboard-help-table">
              <thead><tr><th>Shortcut</th><th>Action</th></tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>`;

      const el = document.createElement('div');
      el.innerHTML = html;
      document.body.appendChild(el.firstElementChild);
    },

    /** Register default application shortcuts */
    _registerDefaults() {
      // New session
      this.register('ctrl+n', () => {
        if (window.chat) window.chat.newSession();
      }, { description: 'New chat session' });

      // Focus chat input
      this.register('ctrl+.', () => {
        const input = document.getElementById('chat-input');
        if (input) { input.focus(); input.select(); }
      }, { description: 'Focus chat input' });

      // Toggle sidebar
      this.register('ctrl+/', () => {
        const sidebar = document.getElementById('sidebar');
        if (sidebar) sidebar.classList.toggle('collapsed');
      }, { description: 'Toggle sidebar' });

      // Export session as Markdown
      this.register('ctrl+shift+s', () => {
        if (window.OC && window.OC.exportMarkdown) window.OC.exportMarkdown();
      }, { description: 'Export session as Markdown' });

      // Escape — close active modal/overlay
      this.register('escape', () => {
        // Close lightbox
        const lb = document.querySelector('.lightbox-overlay');
        if (lb) { lb.remove(); return; }
        // Close any open modal
        const modal = document.querySelector('.modal-overlay:not([style*="display: none"]):not([style*="display:none"])');
        if (modal) { modal.style.display = 'none'; return; }
        // Close keyboard help
        const kh = document.querySelector('.keyboard-help-overlay');
        if (kh) { kh.remove(); return; }
        // Close model picker dropdown
        const mpd = document.getElementById('model-picker-dropdown');
        if (mpd && mpd.classList.contains('active')) {
          mpd.classList.remove('active');
        }
      }, { description: 'Close active overlay', allowInInput: true });

      // Theme toggle
      this.register('ctrl+shift+t', () => {
        if (window.ThemeEngine) window.ThemeEngine.toggle();
      }, { description: 'Toggle dark/light theme' });

      // Show shortcuts help
      this.register('ctrl+shift+/', () => {
        this.showHelp();
      }, { description: 'Show keyboard shortcuts' });

      // Stop generation
      this.register('ctrl+shift+x', () => {
        const stopBtn = document.getElementById('chat-stop');
        if (stopBtn && stopBtn.style.display !== 'none') stopBtn.click();
      }, { description: 'Stop AI generation' });
    }
  };

  window.KeyboardManager = KeyboardManager;
})();
