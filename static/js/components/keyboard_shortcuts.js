/**
 * Clawzd — Keyboard Shortcuts for OpenClaw OS Panels.
 *
 * Shortcuts:
 *   Ctrl+Shift+A — Toggle Artifact Panel
 *   Ctrl+Shift+R — Toggle Tool Replay Panel
 *   Ctrl+Shift+D — Open System Dashboard
 *   Ctrl+Shift+B — Open App Builder
 *   Ctrl+Shift+G — Toggle Agent Sidebar
 *   Escape       — Close any open panel/modal
 */

(function initShortcuts() {
  document.addEventListener('keydown', (e) => {
    // Don't interfere with typing in inputs/textareas
    const tag = e.target.tagName;
    const isInput = tag === 'INPUT' || tag === 'TEXTAREA' || e.target.isContentEditable;

    // Escape — close open panels
    if (e.key === 'Escape') {
      if (window.AgentSidebar) AgentSidebar.toggle(false);
      if (window.ArtifactPanel) ArtifactPanel.toggle(false);
      if (window.ReplayPanel) ReplayPanel.toggle(false);
      if (window.SystemDashboard) SystemDashboard.close();
      if (window.AppBuilderPanel) AppBuilderPanel.close();
      return;
    }

    // Ctrl+Shift shortcuts (work even in inputs)
    if (e.ctrlKey && e.shiftKey) {
      switch (e.key.toUpperCase()) {
        case 'A':
          e.preventDefault();
          if (window.ArtifactPanel) ArtifactPanel.toggle();
          break;
        case 'R':
          e.preventDefault();
          if (window.ReplayPanel) ReplayPanel.toggle();
          break;
        case 'D':
          e.preventDefault();
          if (window.SystemDashboard) SystemDashboard.open();
          break;
        case 'G':
          e.preventDefault();
          if (window.AgentSidebar) AgentSidebar.toggle();
          break;
        case 'B':
          e.preventDefault();
          if (window.AppBuilderPanel) AppBuilderPanel.open();
          break;
      }
    }
  });

  // Update status bar with live plugin count on load
  _updateStatusPlugins();

  async function _updateStatusPlugins() {
    try {
      const res = await fetch('/plugins');
      const plugins = await res.json();
      const el = document.getElementById('status-plugins');
      if (el) {
        const enabled = plugins.filter(p => p.enabled).length;
        el.textContent = `🔌 ${enabled}`;
        el.title = `${enabled} active plugin(s): ${plugins.map(p => p.name).join(', ')}`;
      }
    } catch (e) {
      // Silent — status bar is non-critical
    }
  }
})();
