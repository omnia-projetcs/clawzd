/**
 * Clawzd — Main ES Module Entry Point.
 *
 * This is the single entry point for Vite bundling.
 * It imports all core modules, components, and utilities,
 * initializes them, and exposes necessary globals for
 * backward compatibility with non-module scripts (app.js, icons.js).
 *
 * Build: `npm run build` → static/dist/js/main.js
 * Dev:   `npm run dev`   → HMR via Vite dev server
 */

// ---- Core Modules ----
import { EventBus } from './core/event_bus.js';
import { ComponentRegistry } from './core/component_registry.js';
import { StreamingParser } from './core/streaming_parser.js';
import { ThemeEngine } from './core/theme.js';
import { $, $$, el, toast, escHtml, timeAgo } from './core/utils.js';

// ---- Components ----
// These are self-contained IIFEs loaded via <script> tags.
// When they migrate to ES modules, import them here:
// import './components/token_tracker.js';
// import './components/chat_enhancements.js';

// ---- Initialization ----
// Core modules self-register on window.* in their files.
// This entry point ensures they load in the correct order
// and logs a confirmation.
console.log(
  '%c[Clawzd]%c Core ES modules loaded: EventBus, ComponentRegistry, StreamingParser, ThemeEngine',
  'color: #6366f1; font-weight: bold;',
  'color: inherit;'
);

// Export for use by other ES modules
export {
  EventBus,
  ComponentRegistry,
  StreamingParser,
  ThemeEngine,
  $,
  $$,
  el,
  toast,
  escHtml,
  timeAgo,
};
