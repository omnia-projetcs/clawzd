/**
 * Clawzd — Global Event Bus.
 *
 * Lightweight pub/sub system for decoupling UI components.
 * Components emit and listen to events without direct references.
 *
 * Usage:
 *   EventBus.on('chat:token', (data) => { ... });
 *   EventBus.emit('chat:token', { token: '...', sessionId: '...' });
 *   EventBus.off('chat:token', handler);
 *   EventBus.once('chat:done', (data) => { ... });
 *
 * Standard events:
 *   chat:token          — New token received from SSE
 *   chat:done           — Streaming finished
 *   chat:message-sent   — User message submitted
 *   chat:session-new    — New session created
 *   chat:session-loaded — Session loaded from history
 *   file:extracted      — File extracted from LLM response
 *   tool:executed       — Tool call completed
 *   theme:changed       — Theme switched
 *   keyboard:shortcut   — Global shortcut triggered
 *   perf:ttft           — Time to first token measured
 *   perf:tps            — Tokens per second updated
 */
(function () {
  'use strict';

  /** @type {Map<string, Set<Function>>} */
  const _handlers = new Map();

  const EventBus = {
    /**
     * Subscribe to an event.
     * @param {string} event - Event name (e.g., 'chat:token')
     * @param {Function} handler - Callback function
     * @returns {Function} Unsubscribe function
     */
    on(event, handler) {
      if (!_handlers.has(event)) _handlers.set(event, new Set());
      _handlers.get(event).add(handler);
      return () => this.off(event, handler);
    },

    /**
     * Subscribe to an event once (auto-unsubscribes after first call).
     * @param {string} event
     * @param {Function} handler
     * @returns {Function} Unsubscribe function
     */
    once(event, handler) {
      const wrapper = (data) => {
        this.off(event, wrapper);
        handler(data);
      };
      return this.on(event, wrapper);
    },

    /**
     * Unsubscribe from an event.
     * @param {string} event
     * @param {Function} handler
     */
    off(event, handler) {
      const set = _handlers.get(event);
      if (set) {
        set.delete(handler);
        if (set.size === 0) _handlers.delete(event);
      }
    },

    /**
     * Emit an event to all subscribers.
     * @param {string} event
     * @param {*} data - Payload passed to handlers
     */
    emit(event, data) {
      const set = _handlers.get(event);
      if (!set) return;
      set.forEach(handler => {
        try {
          handler(data);
        } catch (e) {
          console.error(`[EventBus] Error in handler for "${event}":`, e);
        }
      });
    },

    /**
     * Remove all handlers for an event, or all handlers entirely.
     * @param {string} [event] - If omitted, clears everything
     */
    clear(event) {
      if (event) {
        _handlers.delete(event);
      } else {
        _handlers.clear();
      }
    },

    /** Debug: list registered events and handler counts */
    debug() {
      const info = {};
      _handlers.forEach((set, event) => { info[event] = set.size; });
      console.table(info);
      return info;
    }
  };

  window.EventBus = EventBus;
})();
