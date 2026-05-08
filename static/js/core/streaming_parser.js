/**
 * Clawzd — Streaming Markdown Parser v2.
 *
 * Hybrid approach:
 * - During streaming: lightweight incremental preview with basic
 *   markdown formatting (headings, bold, code blocks, lists).
 *   No complex block categorization that could misrender content.
 * - On finish(): delegates to the full renderMd() for the final
 *   pixel-perfect render with all features (charts, mermaid, tables, etc.)
 *
 * Performance gains:
 * - TTFT + TPS metrics via EventBus
 * - requestAnimationFrame batching (no redundant renders)
 * - Scrolling only when needed
 * - No full innerHTML rebuild during streaming
 */
(function () {
  'use strict';

  /* ---- Utility ---- */

  function escHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  /**
   * Lightweight live preview renderer.
   * Much simpler than renderMd — only handles the essentials
   * needed for a readable streaming preview. No charts, mermaid,
   * tables, tool calls, or image markers — those are rendered
   * by renderMd() on finish().
   */
  function livePreview(text) {
    let h = escHtml(text);

    // Tool/thinking blocks → simple collapsible (no complex JSON parsing)
    const toolFenceRe = /```(?:tool_call|tool|execute_python|search_web|screenshot_remote|screenshot_local|generate_image|run_command|browse_web|audit_code|rag_search)\s*\n([\s\S]*?)(?:```|$)/g;
    h = h.replace(toolFenceRe, (_, content) => {
      return '<details class="tool-thinking"><summary> <em>Thinking…</em></summary>' +
             '<pre style="margin:8px 0;background:var(--bg-primary);border:1px solid var(--border);border-radius:8px;padding:12px;overflow-x:auto;font-size:12px;">' +
             '<code>' + content.trim() + '</code></pre></details>';
    });

    // <think> tags → collapsible
    h = h.replace(/&lt;think&gt;([\s\S]*?)(?:&lt;\/think&gt;|$)/g, (_, content) => {
      return '<details class="tool-thinking" open><summary> <em>Thinking…</em></summary>' +
             '<div style="padding:12px;color:var(--text-muted);font-style:italic;">' +
             content.trim() + '</div></details>';
    });

    // Terminal output details
    h = h.replace(/__DETAILS__([\s\S]*?)__DETAILS__/g, (_, content) => {
      return '<details class="tool-thinking"><summary>Terminal Output</summary>' +
             '<pre style="margin:8px 0;background:var(--bg-primary);border:1px solid var(--border);border-radius:8px;padding:12px;overflow-x:auto;">' +
             '<code>' + content.trim() + '</code></pre></details>';
    });

    // Remove internal markers
    h = h.replace(/__FILE_EDIT__({.+?})__/g, '');

    // Code blocks with language
    h = h.replace(/```(\w+)(?::|[ \t])([^\n]*?\.[\w]+)[ \t]*\n([\s\S]*?)```/g, (_, lang, fname, code) => {
      return '<div class="code-block-header"><span>' + escHtml(fname.trim()) + '</span></div>' +
             '<pre><code class="language-' + lang + '">' + code + '</code></pre>';
    });
    h = h.replace(/```(\w+)[ \t]*\n([\s\S]*?)```/g, (_, lang, code) => {
      return '<div class="code-block-header"><span>' + escHtml(lang) + '</span></div>' +
             '<pre><code class="language-' + lang + '">' + code + '</code></pre>';
    });
    // Bare code fences
    h = h.replace(/```[ \t]*\n?([\s\S]*?)```/g, (_, code) => {
      return '<div class="code-block-header"><span>code</span></div>' +
             '<pre><code>' + code + '</code></pre>';
    });

    // Auto-close unclosed code fences for live preview
    const fenceCount = (h.match(/```/g) || []).length;
    if (fenceCount % 2 !== 0) {
      // Find the last unclosed fence and render the rest as code
      const lastFence = h.lastIndexOf('```');
      const before = h.slice(0, lastFence);
      const fenceLine = h.slice(lastFence + 3);
      const langMatch = fenceLine.match(/^(\w*)/);
      const lang = langMatch ? langMatch[1] : '';
      const codeContent = fenceLine.slice(lang.length).replace(/^\s*\n?/, '');
      h = before +
          '<div class="code-block-header"><span>' + (lang || 'code') + '</span></div>' +
          '<pre><code' + (lang ? ' class="language-' + lang + '"' : '') + '>' +
          codeContent + '</code></pre>';
    }

    // Headings
    h = h.replace(/^### (.+)$/gm, '<h4>$1</h4>');
    h = h.replace(/^## (.+)$/gm, '<h3>$1</h3>');
    h = h.replace(/^# (.+)$/gm, '<h2>$1</h2>');

    // HR
    h = h.replace(/^---+$/gm, '<hr>');

    // Bold, italic, inline code
    h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
    h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/\*(.+?)\*/g, '<em>$1</em>');

    // Lists (simple — no nested)
    h = h.replace(/^[-*] (.+)$/gm, '<li>$1</li>');
    h = h.replace(/((?:<li>[\s\S]*?<\/li>\s*)+)/g, '<ul>$1</ul>');
    h = h.replace(/^(\d+)\. (.+)$/gm, '<li value="$1">$2</li>');
    h = h.replace(/((?:<li value="\d+">[\s\S]*?<\/li>\s*)+)/g, '<ol>$1</ol>');

    // Blockquotes
    h = h.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');

    // Newlines
    h = h.replace(/\n\n+/g, '<br><div style="margin-top:8px"></div>');
    h = h.replace(/\n/g, '<br>');

    // Clean spurious <br> around block elements
    h = h.replace(/<br>\s*(<\/?(?:ul|ol|li|h[2-4]|hr|blockquote|div|pre|details))/g, '$1');
    h = h.replace(/(<\/(?:ul|ol|li|h[2-4]|blockquote|div|pre|details)>)\s*<br>/g, '$1');

    return h;
  }

  /* ---- StreamingParser class ---- */

  class StreamingParser {
    /**
     * @param {HTMLElement} container - DOM element to render into
     * @param {Object} [opts]
     * @param {boolean} [opts.showCursor] - Show streaming cursor (default: true)
     */
    constructor(container, opts) {
      this.container = container;
      this.opts = opts || {};
      this._text = '';
      this._renderQueued = false;
      this._cursorEl = null;
      this._totalTokens = 0;
      this._firstTokenTime = 0;
      this._startTime = Date.now();
      this._ttft = 0;
      this._lastRenderLen = 0;
    }

    /* ---- Public API ---- */

    /**
     * Feed new tokens into the parser.
     * @param {string} token
     */
    pushToken(token) {
      this._totalTokens++;

      // Track Time To First Token
      if (this._totalTokens === 1) {
        this._firstTokenTime = Date.now();
        this._ttft = this._firstTokenTime - this._startTime;
        if (window.EventBus) {
          window.EventBus.emit('perf:ttft', { ms: this._ttft });
        }
      }

      this._text += token;
      this._scheduleRender();
    }

    /**
     * Signal that streaming is complete.
     * Delegates to renderMd() for the final pixel-perfect render.
     */
    finish() {
      // Remove cursor
      if (this._cursorEl) {
        this._cursorEl.remove();
        this._cursorEl = null;
      }

      // Final render using the full renderMd (with charts, mermaid, tables, etc.)
      if (typeof window._clawzdRenderMd === 'function') {
        this.container.innerHTML = window._clawzdRenderMd(this._text);
        // Apply syntax highlighting
        if (typeof window._clawzdHighlightAll === 'function') {
          window._clawzdHighlightAll(this.container);
        }
      } else {
        // Fallback: use live preview
        this.container.innerHTML = livePreview(this._text);
      }

      // Emit TPS metrics
      const elapsed = (Date.now() - this._startTime) / 1000;
      const tps = elapsed > 0 ? (this._totalTokens / elapsed).toFixed(1) : 0;
      if (window.EventBus) {
        window.EventBus.emit('perf:tps', {
          tps: parseFloat(tps),
          total: this._totalTokens,
          elapsed
        });
      }
    }

    /**
     * Get the accumulated text.
     * @returns {string}
     */
    getText() {
      return this._text;
    }

    /**
     * Reset the parser.
     */
    reset() {
      this._text = '';
      this._totalTokens = 0;
      this._startTime = Date.now();
      this._lastRenderLen = 0;
      this.container.innerHTML = '';
    }

    /* ---- Internal ---- */

    _scheduleRender() {
      if (this._renderQueued) return;
      this._renderQueued = true;
      requestAnimationFrame(() => {
        this._renderQueued = false;
        this._render();
      });
    }

    _render() {
      // Skip render if text hasn't grown enough (throttle for very fast streaming)
      const delta = this._text.length - this._lastRenderLen;
      if (delta < 3 && this._lastRenderLen > 0) return;
      this._lastRenderLen = this._text.length;

      // Use lightweight live preview during streaming
      this.container.innerHTML = livePreview(this._text);

      // Add streaming cursor
      if (this.opts.showCursor !== false) {
        if (!this._cursorEl) {
          this._cursorEl = document.createElement('span');
          this._cursorEl.className = 'streaming-cursor';
        }
        this.container.appendChild(this._cursorEl);
      }

      // Syntax highlighting for completed code blocks only
      if (window.hljs) {
        this.container.querySelectorAll('pre code').forEach(codeEl => {
          if (!codeEl.dataset.highlighted) {
            window.hljs.highlightElement(codeEl);
          }
        });
      }

      // Auto-scroll
      const msgEl = this.container.closest('#chat-messages') || this.container.parentElement;
      if (msgEl) msgEl.scrollTop = msgEl.scrollHeight;
    }
  }

  /* ---- Export ---- */
  window.StreamingParser = StreamingParser;
})();
