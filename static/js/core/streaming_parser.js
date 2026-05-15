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
/* ---- Utility ---- */

  function escHtml(s) {
    if (s == null) return '';
    s = String(s);
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
    const blocks = [];
    function ph(html) { const k = '\x00BLK' + blocks.length + '\x00'; blocks.push(html); return k; }

    // Tool/thinking blocks → simple collapsible (no complex JSON parsing)
    const toolFenceRe = /```(tool_call|tool|execute_python|search_web|screenshot_remote|screenshot_local|generate_image|run_command|browse_web|audit_code|rag_search|create_app|update_app|analyze_data|fetch_market_data)\s*\n([\s\S]*?)(?:```|$)/g;
    h = h.replace(toolFenceRe, (match, toolLabel, content) => {
      let readableContent = content.trim();
      let langClass = '';
      if (toolLabel === 'create_app' || toolLabel === 'update_app') {
          langClass = ' class="language-html"';
          if (readableContent.toLowerCase().startsWith('html\n')) {
              readableContent = readableContent.substring(5).trim();
          }
      } else if (toolLabel === 'execute_python') {
          langClass = ' class="language-python"';
      }
      return ph(`<details class="tool-thinking"><summary> <em>Thinking… </em><span class="tool-thinking-label">${escHtml(toolLabel)}</span></summary>` +
             `<pre style="margin:8px 0;background:var(--bg-primary);border:1px solid var(--border);border-radius:8px;padding:12px;overflow-x:auto;">` +
             `<code${langClass}>${readableContent}</code></pre></details>`);
    });

    // <think> tags → collapsible
    h = h.replace(/&lt;think&gt;/g, '<details class="tool-thinking" open><summary> <em>Thinking…</em></summary><div style="padding:12px;color:var(--text-muted);font-style:italic;overflow-x:auto;">');
    h = h.replace(/&lt;\/think&gt;/g, '</div></details>');

    // Terminal output details
    h = h.replace(/__DETAILS__([\s\S]*?)__DETAILS__/g, (_, content) => {
      return ph('<details class="tool-thinking"><summary>Terminal Output</summary>' +
             '<pre style="margin:8px 0;background:var(--bg-primary);border:1px solid var(--border);border-radius:8px;padding:12px;overflow-x:auto;">' +
             '<code>' + content.trim() + '</code></pre></details>');
    });

    // Handle inline tool approval requests (HITL)
    h = h.replace(/__TOOL_APPROVAL__([\s\S]+?)__TOOL_APPROVAL__/g, (m, content) => {
      try {
        if (window.toolApproval) window.toolApproval._show(JSON.parse(content));
      } catch (e) {}
      return '';
    });

    // Remove internal markers
    h = h.replace(/__FILE_EDIT__({.+?})__/g, '');

    function streamingCodeBlock(lang, label, code) {
      const id = 'cb-' + Math.random().toString(36).slice(2, 8);
      const ll = (lang || '').toLowerCase();
      const run = ['python', 'py', 'sh', 'bash'].includes(ll);
      const preview = ['html', 'htm', 'svg'].includes(ll);
      const rb = run && window.icon ? `<button class="code-run-btn" onclick="OC.runCode('${id}')">${window.icon('terminal', 14)} Run</button>` : '';
      const pb = preview && window.icon ? `<button class="code-action-btn code-preview-btn" onclick="OC.previewHtml('${id}')">${window.icon('eye', 14)} Preview</button>` : '';
      const sb = window.icon ? `<button class="code-action-btn code-save-btn" onclick="OC.saveToFiles('${id}','${escHtml(lang)}','${escHtml(label)}')">${window.icon('save', 14)} Save</button>` : '';
      const cb = window.icon ? `<button class="code-action-btn" onclick="OC.copyCode('${id}')">${window.icon('copy', 14)} Copy</button>` : '';
      const lcls = lang ? ` class="language-${lang}"` : '';
      return ph(
        `<div class="code-block-header"><span>${escHtml(label)}</span>` +
        `<div class="code-block-actions">${pb}${sb}${cb}${rb}</div></div>` +
        `<pre id="${id}"><code${lcls}>${code}</code></pre>`
      );
    }

    // Code blocks with language
    h = h.replace(/```(\w+)(?::|[ \t])([^\n]*?\.[\w]+)[ \t]*\n([\s\S]*?)```/g, (_, lang, fname, code) => {
      return streamingCodeBlock(lang, fname.trim(), code);
    });
    h = h.replace(/```(\w+)[ \t]*\n([\s\S]*?)```/g, (_, lang, code) => {
      return streamingCodeBlock(lang, lang, code);
    });
    // Bare code fences
    h = h.replace(/```[ \t]*\n?([\s\S]*?)```/g, (_, code) => {
      return streamingCodeBlock('', 'code', code);
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
      h = before + streamingCodeBlock(lang, lang || 'code', codeContent);
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
    h = h.replace(/<br>\s*(<\/?(?:ul|ol|li|h[2-4]|hr|blockquote|div|pre|details|summary))/g, '$1');
    h = h.replace(/(<\/(?:ul|ol|li|h[2-4]|blockquote|div|pre|details|summary)>)\s*<br>/g, '$1');

    // Format tool execution markers nicely
    h = h.replace(/⚡ \*Executing <code>([^<]+)<\/code>\.\.\.\*/g, '<div class="tool-call-status" style="margin:8px 0;padding:8px 12px;background:var(--bg-secondary);border-radius:6px;font-size:13px;display:flex;align-items:center;gap:8px;color:var(--text-secondary);border:1px solid var(--border);"><span class="tool-spinner" style="display:inline-block;width:12px;height:12px;border:2px solid var(--accent);border-right-color:transparent;border-radius:50%;animation:spin 1s linear infinite;"></span> Executing <strong>$1</strong>...</div>');
    h = h.replace(/⚡ \*<code>([^<]+)<\/code> → <code>([^<]+)<\/code>\* —/g, '<div class="tool-call-status" style="margin:8px 0;padding:8px 12px;background:var(--bg-secondary);border-radius:6px;font-size:13px;display:flex;align-items:center;gap:8px;color:var(--text-secondary);border:1px solid var(--border);"><span class="tool-spinner" style="display:inline-block;width:12px;height:12px;border:2px solid var(--accent);border-right-color:transparent;border-radius:50%;animation:spin 1s linear infinite;"></span> Routing <strong>$1</strong> → <strong>$2</strong>...</div>');
    h = h.replace(/✅ \*Done\.\*/g, '<div class="tool-call-status success" style="margin:4px 0 12px 0;color:var(--success);font-size:12px;display:flex;align-items:center;gap:6px;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg> Done.</div>');

    // Render basic IMG/SVG tags during streaming
    h = h.replace(/__IMG__([^|]+)\|([^|]+)\|(.+?)__IMG__/g, (_, url, label) => {
      return ph(`<div style="margin:12px 0;"><img src="${url}" alt="${escHtml(label)}" style="max-width:100%;border-radius:8px;box-shadow:0 4px 20px rgba(0,0,0,0.4);"></div>`);
    });
    h = h.replace(/__SVG__([^|]+)\|([^|]+)\|(.+?)__SVG__/g, (_, url, label) => {
      return ph(`<div style="margin:12px 0;background:var(--bg-secondary);border-radius:8px;padding:16px;text-align:center;box-shadow:0 4px 20px rgba(0,0,0,0.4);"><img src="${url}" alt="${escHtml(label)}" style="max-width:100%;max-height:300px;"></div>`);
    });


    // Restore blocks
    h = h.replace(/\x00BLK(\d+)\x00/g, (_, i) => blocks[parseInt(i)]);

    // Structured UI components (charts, tables, progress, cards, alerts)
    if (window.StructuredUI) {
      h = window.StructuredUI.renderComponents(h);
    }

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
      if (typeof window.renderMd === 'function') {
        this.container.innerHTML = window.renderMd(this._text);
        // Apply syntax highlighting
        if (typeof window.highlightAll === 'function') {
          window.highlightAll(this.container);
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

      const msgEl = this.container.closest('#chat-messages') || this.container.parentElement;
      const isAtBottom = msgEl ? (msgEl.scrollHeight - msgEl.scrollTop - msgEl.clientHeight < 50) : false;

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
      if (typeof window.highlightAll === 'function') {
        window.highlightAll(this.container);
      } else if (window.hljs) {
        this.container.querySelectorAll('pre code').forEach(codeEl => {
          if (!codeEl.dataset.highlighted) {
            window.hljs.highlightElement(codeEl);
          }
        });
      }

      // Auto-scroll
      if (msgEl && isAtBottom) {
        msgEl.scrollTop = msgEl.scrollHeight;
      }
    }
  }

  /* ---- Export ---- */
  window.StreamingParser = StreamingParser;
