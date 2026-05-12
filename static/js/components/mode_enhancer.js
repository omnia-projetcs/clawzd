/**
 * Mode Enhancer — enriches the action-mode-select with tool
 * restriction badges and wires up mode-specific UI hints
 * (accent color, auto-open sidebars, etc.)
 */
(function () {
  'use strict';

  const $ = s => document.querySelector(s);
  let _modesCache = null;

  /**
   * Fetch modes from the API and cache them.
   */
  async function loadModes() {
    if (_modesCache) return _modesCache;
    try {
      const res = await fetch('/api/modes');
      const data = await res.json();
      _modesCache = data.modes || [];
      return _modesCache;
    } catch (e) {
      console.warn('Failed to load modes:', e);
      return [];
    }
  }

  /**
   * Enhance the select dropdown options with restriction badges.
   */
  async function enhanceModeSelector() {
    const sel = $('#action-mode-select');
    if (!sel) return;

    const modes = await loadModes();
    if (!modes.length) return;

    // Build a lookup map
    const modeMap = {};
    modes.forEach(m => { modeMap[m.key] = m; });

    // Enhance existing options with restriction info in title attr
    Array.from(sel.options).forEach(opt => {
      const mode = modeMap[opt.value];
      if (!mode) return;
      if (mode.has_tool_restrictions) {
        opt.textContent = `${mode.icon} ${mode.label} 🔒`;
        opt.title = `${mode.label} — some tools are restricted in this mode`;
      }
    });

    // Listen for mode changes to apply UI hints
    sel.addEventListener('change', () => applyModeHints(sel.value, modeMap));

    // Store globally for other components
    window._agentModes = modeMap;
  }

  /**
   * Apply UI hints when a mode is selected.
   */
  function applyModeHints(modeKey, modeMap) {
    const mode = modeMap[modeKey];
    if (!mode) return;
    const hints = mode.ui_hints || {};

    // Accent color on the input bar
    const inputBar = $('.chat-input-bar') || $('.chat-input');
    if (inputBar && hints.accent) {
      inputBar.style.borderColor = hints.accent;
      // Reset after 3s for subtle effect
      setTimeout(() => { inputBar.style.borderColor = ''; }, 3000);
    }

    // Auto-open sidebar/panel
    if (hints.auto_open) {
      switch (hints.auto_open) {
        case 'editor':
          if (window.AgentSidebar) AgentSidebar.toggle(true);
          break;
        case 'media':
          // Switch to media studio if available
          const mediaBtn = document.querySelector('.mode-btn[data-mode="media"]');
          if (mediaBtn) mediaBtn.click();
          break;
      }
    }

    // Read-only indicator
    if (hints.read_only) {
      if (typeof toast === 'function') {
        toast(`🔒 ${mode.label} mode — file editing is restricted`);
      }
    }

    // Show tool restriction summary on mode switch
    if (mode.has_tool_restrictions && typeof toast === 'function') {
      toast(`${mode.icon} ${mode.label} — some tools are restricted`);
    }
  }

  /**
   * Create a mode info tooltip that shows on hover over the selector.
   */
  function addModeTooltip() {
    const sel = $('#action-mode-select');
    if (!sel) return;

    sel.addEventListener('mouseover', async () => {
      const modes = await loadModes();
      const currentKey = sel.value;
      const mode = modes.find(m => m.key === currentKey);
      if (!mode) return;

      let tip = `${mode.icon} ${mode.label}`;
      if (mode.has_tool_restrictions) {
        tip += '\n🔒 Tool restrictions active';
      }
      const hints = mode.ui_hints || {};
      if (hints.accent) {
        tip += `\n🎨 Accent: ${hints.accent}`;
      }
      sel.title = tip;
    });
  }

  // Initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      enhanceModeSelector();
      addModeTooltip();
    });
  } else {
    enhanceModeSelector();
    addModeTooltip();
  }

  // Expose for external use
  window.ModeEnhancer = {
    loadModes,
    applyHints: applyModeHints,
    getCache: () => _modesCache,
  };
})();
