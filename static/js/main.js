/**
 * Clawzd — Main Entry Point (init script).
 *
 * Core modules (EventBus, ComponentRegistry, etc.) are loaded as
 * regular <script> tags and register on window.* directly.
 * This script handles panel initialization after DOM is ready.
 */

// ---- OpenClaw OS Panel Initialization ----
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _initPanels);
} else {
  _initPanels();
}

function _initPanels() {
  try { if (window.AppBuilderPanel) window.AppBuilderPanel.init(); } catch (e) { /* silent */ }
  try { if (window.NotificationBadge) window.NotificationBadge.init(); } catch (e) { /* silent */ }
  try { if (window.AgentSidebar) window.AgentSidebar.init('header-right'); } catch (e) { /* silent */ }
}
