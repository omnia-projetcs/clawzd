/* Global Token Tracker — shared across Chat, Research, and all tool studios */
(function () {
  'use strict';

  class TokenTracker {
    constructor() {
      this.inputTokens = 0;
      this.outputTokens = 0;
      this._el = document.getElementById('token-counter');
      this._sessionId = null;
    }

    /** Set the active session */
    setSession(sessionId) {
      this._sessionId = sessionId;
    }

    /** Add tokens from any source (chat, research, spec, etc.) */
    addInput(count) {
      this.inputTokens += count;
      this._render();
    }

    addOutput(count) {
      this.outputTokens += count;
      this._render();
    }

    /** Bulk add from a {input_tokens, output_tokens} object */
    addUsage(usage) {
      if (!usage) return;
      this.inputTokens += (usage.input_tokens || 0);
      this.outputTokens += (usage.output_tokens || 0);
      this._render();
    }

    /** Reset counters (e.g., on new session) */
    reset() {
      this.inputTokens = 0;
      this.outputTokens = 0;
      this._sessionId = null;
      this._render();
      if (this._el) this._el.style.display = 'none';
    }

    /** Sync from backend totals */
    async syncFromBackend() {
      try {
        const res = await fetch('/api/token-usage');
        const data = await res.json();
        this.inputTokens = data.input_tokens || 0;
        this.outputTokens = data.output_tokens || 0;
        this._render();
      } catch (e) {
        // Silently fail — counter stays local
      }
    }

    get total() { return this.inputTokens + this.outputTokens; }

    _render() {
      if (!this._el) this._el = document.getElementById('token-counter');
      if (!this._el) return;
      const total = this.total;
      if (total === 0) { this._el.style.display = 'none'; return; }

      this._el.innerHTML =
        `<span class="tc-item tc-sent" title="Input tokens">↑ ${this._fmt(this.inputTokens)}</span>` +
        `<span class="tc-item tc-recv" title="Output tokens">↓ ${this._fmt(this.outputTokens)}</span>` +
        `<span class="tc-item tc-total" title="Total tokens">Σ ${this._fmt(total)}</span>`;

      this._el.style.display = 'flex';
    }

    /** Format large numbers: 12345 → 12.3K */
    _fmt(n) {
      if (n < 1000) return String(n);
      if (n < 1000000) return (n / 1000).toFixed(1) + 'K';
      return (n / 1000000).toFixed(2) + 'M';
    }
  }

  window.tokenTracker = new TokenTracker();
})();
