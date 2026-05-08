/**
 * Clawzd — Streaming Markdown Parser.
 *
 * Incremental parser inspired by OpenUI's createStreamingParser().
 * Instead of re-rendering the entire markdown on every token batch,
 * this parser maintains a block-level AST and only updates the
 * last modified block in the DOM.
 *
 * Performance gain: ~80% CPU reduction during streaming vs full re-render.
 *
 * Usage:
 *   const parser = new StreamingParser(containerEl);
 *   parser.pushToken('Hello ');    // appends to current paragraph
 *   parser.pushToken('```python'); // opens a new code block
 *   parser.pushToken('\nprint()'); // appends to code block
 *   parser.pushToken('\n```');     // closes code block
 *   parser.finish();              // final cleanup
 */
(function () {
  'use strict';

  /* ------------------------------------------------------------------ */
  /*  Block Types                                                        */
  /* ------------------------------------------------------------------ */

  const BLOCK_PARAGRAPH = 'paragraph';
  const BLOCK_CODE      = 'code';
  const BLOCK_TABLE     = 'table';
  const BLOCK_HEADING   = 'heading';
  const BLOCK_LIST      = 'list';
  const BLOCK_QUOTE     = 'blockquote';
  const BLOCK_HR        = 'hr';
  const BLOCK_COMPONENT = 'component'; // chart, mermaid, etc.
  const BLOCK_THINKING  = 'thinking';  // <think> or tool_call blocks

  /* ------------------------------------------------------------------ */
  /*  Utility: inline markdown → HTML (lightweight, no block parsing)    */
  /* ------------------------------------------------------------------ */

  function escHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function inlineMd(text) {
    let h = escHtml(text);
    // Images: ![alt](url)
    h = h.replace(/!\[([^\]]*)\]\(([^)]+)\)/g,
      '<img src="$2" alt="$1" style="max-width:100%;border-radius:8px;margin:8px 0;">');
    // Links: [text](url)
    h = h.replace(/\[([^\]]+)\]\(([^)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:underline;text-underline-offset:2px">$1</a>');
    // Auto-link bare URLs
    h = h.replace(/(^|[^"(=])(\bhttps?:\/\/[^\s<>&)\]"]+)/g, (m, pre, url) => {
      const clean = url.replace(/[.,;:!?)]+$/, '');
      return pre + `<a href="${clean}" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:underline;text-underline-offset:2px">${clean}</a>`;
    });
    // Inline code
    h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Bold
    h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Italic
    h = h.replace(/\*(.+?)\*/g, '<em>$1</em>');
    return h;
  }

  /* ------------------------------------------------------------------ */
  /*  Block class — represents one logical block in the output           */
  /* ------------------------------------------------------------------ */

  class Block {
    /**
     * @param {string} type
     * @param {Object} [meta] - Extra metadata (lang, level, etc.)
     */
    constructor(type, meta) {
      this.type = type;
      this.meta = meta || {};
      this.lines = [];
      this.el = null;      // DOM element
      this.dirty = true;   // needs re-render
      this.id = 'blk-' + Math.random().toString(36).slice(2, 8);
    }

    /** Append text to the last line, or start a new line */
    append(text) {
      if (this.lines.length === 0) {
        this.lines.push(text);
      } else {
        this.lines[this.lines.length - 1] += text;
      }
      this.dirty = true;
    }

    /** Start a new line within the block */
    newLine() {
      this.lines.push('');
      this.dirty = true;
    }

    /** Get full text content */
    text() {
      return this.lines.join('\n');
    }
  }

  /* ------------------------------------------------------------------ */
  /*  StreamingParser                                                     */
  /* ------------------------------------------------------------------ */

  class StreamingParser {
    /**
     * @param {HTMLElement} container - DOM element to render into
     * @param {Object} [opts]
     * @param {Function} [opts.onBlock] - Called when a block is finalized
     * @param {boolean} [opts.showCursor] - Show streaming cursor (default: true)
     */
    constructor(container, opts) {
      this.container = container;
      this.opts = opts || {};
      this.blocks = [];
      this._buffer = '';
      this._inCodeFence = false;
      this._codeLang = '';
      this._codeLabel = '';
      this._inThink = false;
      this._lineBuffer = '';
      this._cursorEl = null;
      this._renderQueued = false;
      this._totalTokens = 0;
      this._firstTokenTime = 0;
      this._startTime = Date.now();

      // Performance tracking
      this._ttft = 0; // time to first token (ms)
    }

    /* ---- Public API ---- */

    /**
     * Feed new tokens into the parser.
     * @param {string} token
     */
    pushToken(token) {
      this._totalTokens++;

      // Track TTFT
      if (this._totalTokens === 1) {
        this._firstTokenTime = Date.now();
        this._ttft = this._firstTokenTime - this._startTime;
        if (window.EventBus) {
          window.EventBus.emit('perf:ttft', { ms: this._ttft });
        }
      }

      this._buffer += token;
      this._processBuffer();
      this._scheduleRender();
    }

    /**
     * Signal that streaming is complete. Finalizes all blocks.
     */
    finish() {
      // Flush remaining buffer
      if (this._lineBuffer) {
        this._commitLine(this._lineBuffer);
        this._lineBuffer = '';
      }

      // Close unclosed code fences
      if (this._inCodeFence) {
        this._inCodeFence = false;
      }

      // Close unclosed think blocks
      if (this._inThink) {
        this._inThink = false;
      }

      // Remove cursor
      if (this._cursorEl) {
        this._cursorEl.remove();
        this._cursorEl = null;
      }

      // Final render pass
      this._renderAllDirty();

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
     * Get the full concatenated text of all blocks.
     * Used for file extraction after streaming.
     * @returns {string}
     */
    getText() {
      return this.blocks.map(b => {
        if (b.type === BLOCK_CODE || b.type === BLOCK_COMPONENT) {
          const lang = b.meta.lang || '';
          const label = b.meta.label || '';
          const header = label && label !== lang ? `${lang}:${label}` : lang;
          return '```' + header + '\n' + b.text() + '\n```';
        }
        if (b.type === BLOCK_THINKING) {
          return '<think>' + b.text() + '</think>';
        }
        return b.text();
      }).join('\n\n');
    }

    /**
     * Reset the parser (e.g., for a new message).
     */
    reset() {
      // Destroy component instances
      if (window.ComponentRegistry) {
        this.blocks.forEach(b => {
          if (b.type === BLOCK_COMPONENT) {
            window.ComponentRegistry.destroyInstance(b.id);
          }
        });
      }
      this.blocks = [];
      this._buffer = '';
      this._inCodeFence = false;
      this._inThink = false;
      this._lineBuffer = '';
      this._totalTokens = 0;
      this._startTime = Date.now();
      this.container.innerHTML = '';
    }

    /* ---- Internal: Buffer Processing ---- */

    _processBuffer() {
      // Process character by character looking for newlines
      while (this._buffer.length > 0) {
        const nlIdx = this._buffer.indexOf('\n');
        if (nlIdx === -1) {
          // No newline — accumulate in line buffer
          this._lineBuffer += this._buffer;
          this._buffer = '';
          // Update last block with partial line (for live preview)
          this._updateCurrentBlock(this._lineBuffer);
          break;
        }

        // Found a newline — commit the line
        const line = this._lineBuffer + this._buffer.slice(0, nlIdx);
        this._lineBuffer = '';
        this._buffer = this._buffer.slice(nlIdx + 1);
        this._commitLine(line);
      }
    }

    /**
     * Update the current block with a partial line (during streaming).
     * This provides live preview without committing the line.
     */
    _updateCurrentBlock(partialLine) {
      const current = this._currentBlock();

      if (this._inCodeFence) {
        // Check if partial line closes the fence
        if (partialLine.trim() === '```') return;
        // Update last line of code block
        if (current && current.type === BLOCK_CODE) {
          if (current.lines.length === 0) current.lines.push('');
          current.lines[current.lines.length - 1] = partialLine;
          current.dirty = true;
        }
        return;
      }

      if (this._inThink) {
        if (current && current.type === BLOCK_THINKING) {
          if (current.lines.length === 0) current.lines.push('');
          current.lines[current.lines.length - 1] = partialLine;
          current.dirty = true;
        }
        return;
      }

      // For regular text, update the current paragraph
      if (!partialLine.trim()) return;

      if (!current || current.type !== BLOCK_PARAGRAPH) {
        const block = new Block(BLOCK_PARAGRAPH);
        block.append(partialLine);
        this.blocks.push(block);
      } else {
        if (current.lines.length === 0) current.lines.push('');
        current.lines[current.lines.length - 1] = partialLine;
        current.dirty = true;
      }
    }

    /**
     * Commit a complete line to the block AST.
     */
    _commitLine(line) {
      const trimmed = line.trim();

      // --- Code fence open/close ---
      if (trimmed.startsWith('```')) {
        if (this._inCodeFence) {
          // Close code fence
          this._inCodeFence = false;
          const current = this._currentBlock();
          if (current) {
            // Remove trailing empty line if present
            if (current.lines.length > 0 && current.lines[current.lines.length - 1] === '') {
              current.lines.pop();
            }
            current.dirty = true;
          }
          return;
        }

        // Open code fence
        this._inCodeFence = true;
        const langMatch = trimmed.slice(3).trim();

        // Parse lang:filename or lang filename
        let lang = '';
        let label = '';
        if (langMatch) {
          const colonIdx = langMatch.indexOf(':');
          const spaceIdx = langMatch.indexOf(' ');
          if (colonIdx > 0) {
            lang = langMatch.slice(0, colonIdx);
            label = langMatch.slice(colonIdx + 1).trim();
          } else if (spaceIdx > 0) {
            lang = langMatch.slice(0, spaceIdx);
            label = langMatch.slice(spaceIdx + 1).trim();
          } else {
            lang = langMatch;
            label = langMatch;
          }
        }

        // Check if this is a rich component
        const componentLangs = ['chart', 'mermaid', 'form', 'kanban', 'timeline', 'progress'];
        const toolLangs = ['tool_call', 'tool', 'execute_python', 'search_web',
          'screenshot_remote', 'screenshot_local', 'generate_image',
          'run_command', 'browse_web', 'audit_code', 'rag_search'];

        let blockType = BLOCK_CODE;
        if (componentLangs.includes(lang.toLowerCase())) {
          blockType = BLOCK_COMPONENT;
        } else if (toolLangs.includes(lang.toLowerCase())) {
          blockType = BLOCK_THINKING;
        }

        const block = new Block(blockType, { lang, label: label || lang || 'code' });
        this.blocks.push(block);
        return;
      }

      // Inside a code fence — just append
      if (this._inCodeFence) {
        const current = this._currentBlock();
        if (current) {
          current.lines.push(line);
          current.dirty = true;
        }
        return;
      }

      // --- <think> tags ---
      if (trimmed === '&lt;think&gt;' || trimmed === '<think>') {
        this._inThink = true;
        const block = new Block(BLOCK_THINKING);
        this.blocks.push(block);
        return;
      }
      if ((trimmed === '&lt;/think&gt;' || trimmed === '</think>') && this._inThink) {
        this._inThink = false;
        return;
      }
      if (this._inThink) {
        const current = this._currentBlock();
        if (current) {
          current.lines.push(line);
          current.dirty = true;
        }
        return;
      }

      // --- Headings ---
      const headingMatch = trimmed.match(/^(#{1,4})\s+(.+)$/);
      if (headingMatch) {
        const level = headingMatch[1].length;
        const block = new Block(BLOCK_HEADING, { level });
        block.append(headingMatch[2]);
        this.blocks.push(block);
        return;
      }

      // --- Horizontal rule ---
      if (/^-{3,}$/.test(trimmed)) {
        this.blocks.push(new Block(BLOCK_HR));
        return;
      }

      // --- Blockquote ---
      if (trimmed.startsWith('> ') || trimmed === '>') {
        const content = trimmed.startsWith('> ') ? trimmed.slice(2) : '';
        const current = this._currentBlock();
        if (current && current.type === BLOCK_QUOTE) {
          current.lines.push(content);
          current.dirty = true;
        } else {
          const block = new Block(BLOCK_QUOTE);
          block.append(content);
          this.blocks.push(block);
        }
        return;
      }

      // --- Table row ---
      if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
        const current = this._currentBlock();
        if (current && current.type === BLOCK_TABLE) {
          current.lines.push(trimmed);
          current.dirty = true;
        } else {
          const block = new Block(BLOCK_TABLE);
          block.append(trimmed);
          this.blocks.push(block);
        }
        return;
      }

      // --- List items ---
      const olMatch = trimmed.match(/^(\d+)\.\s+(.+)$/);
      const ulMatch = trimmed.match(/^[-*]\s+(.+)$/);
      if (olMatch || ulMatch) {
        const content = olMatch ? olMatch[2] : ulMatch[1];
        const listType = olMatch ? 'ol' : 'ul';
        const current = this._currentBlock();
        if (current && current.type === BLOCK_LIST && current.meta.listType === listType) {
          current.lines.push(content);
          current.dirty = true;
        } else {
          const block = new Block(BLOCK_LIST, { listType });
          block.append(content);
          this.blocks.push(block);
        }
        return;
      }

      // --- Empty line = paragraph break ---
      if (!trimmed) {
        // Don't create empty blocks at the start
        if (this.blocks.length > 0) {
          const current = this._currentBlock();
          if (current && current.type === BLOCK_PARAGRAPH && current.text().trim()) {
            // Next text will create a new paragraph
          }
        }
        return;
      }

      // --- Tool/Image markers ---
      if (trimmed.startsWith('__IMG__') || trimmed.startsWith('__SVG__') ||
          trimmed.startsWith('__DETAILS__') || trimmed.startsWith('__FILE_EDIT__')) {
        const block = new Block(BLOCK_PARAGRAPH);
        block.append(line);
        this.blocks.push(block);
        return;
      }

      // --- Regular paragraph text ---
      const current = this._currentBlock();
      if (current && current.type === BLOCK_PARAGRAPH) {
        current.lines.push(line);
        current.dirty = true;
      } else {
        const block = new Block(BLOCK_PARAGRAPH);
        block.append(line);
        this.blocks.push(block);
      }
    }

    _currentBlock() {
      return this.blocks.length > 0 ? this.blocks[this.blocks.length - 1] : null;
    }

    /* ---- Internal: Rendering ---- */

    _scheduleRender() {
      if (this._renderQueued) return;
      this._renderQueued = true;
      requestAnimationFrame(() => {
        this._renderQueued = false;
        this._renderAllDirty();
      });
    }

    /**
     * Only re-render blocks that are marked dirty.
     * This is the key performance optimization over full re-render.
     */
    _renderAllDirty() {
      this.blocks.forEach((block, idx) => {
        if (!block.dirty) return;

        const html = this._renderBlock(block);
        if (block.el) {
          // Update existing element
          block.el.innerHTML = html;
        } else {
          // Create new element
          const wrapper = document.createElement('div');
          wrapper.className = 'sp-block sp-block-' + block.type;
          wrapper.dataset.blockId = block.id;
          wrapper.innerHTML = html;
          block.el = wrapper;
          this.container.appendChild(wrapper);
        }
        block.dirty = false;

        // Post-render hooks (highlight, chart init, etc.)
        this._postRender(block);
      });

      // Streaming cursor
      if (this.opts.showCursor !== false) {
        if (!this._cursorEl) {
          this._cursorEl = document.createElement('span');
          this._cursorEl.className = 'streaming-cursor';
        }
        this.container.appendChild(this._cursorEl);
      }

      // Auto-scroll
      const msgEl = this.container.closest('.chat-messages') || this.container.parentElement;
      if (msgEl) msgEl.scrollTop = msgEl.scrollHeight;
    }

    /**
     * Render a single block to HTML string.
     */
    _renderBlock(block) {
      switch (block.type) {
        case BLOCK_PARAGRAPH:
          return this._renderParagraph(block);
        case BLOCK_CODE:
          return this._renderCode(block);
        case BLOCK_COMPONENT:
          return this._renderComponent(block);
        case BLOCK_TABLE:
          return this._renderTable(block);
        case BLOCK_HEADING:
          return this._renderHeading(block);
        case BLOCK_LIST:
          return this._renderList(block);
        case BLOCK_QUOTE:
          return this._renderQuote(block);
        case BLOCK_HR:
          return '<hr>';
        case BLOCK_THINKING:
          return this._renderThinking(block);
        default:
          return escHtml(block.text());
      }
    }

    _renderParagraph(block) {
      const text = block.text();
      // Handle special markers (delegate to main renderMd for complex ones)
      if (text.includes('__IMG__') || text.includes('__SVG__') ||
          text.includes('__DETAILS__')) {
        // Let the main renderMd handle these special markers
        if (typeof window.renderMd === 'function') {
          return window.renderMd(text);
        }
      }
      return '<p>' + inlineMd(text) + '</p>';
    }

    _renderCode(block) {
      const lang = block.meta.lang || '';
      const label = block.meta.label || lang || 'code';
      const code = escHtml(block.text());
      const lcls = lang ? ` class="language-${lang}"` : '';

      // Action buttons
      const id = block.id;
      const ll = lang.toLowerCase();
      const canRun = ['python', 'py', 'sh', 'bash'].includes(ll);
      const canPreview = ['html', 'htm', 'svg'].includes(ll);

      let actions = '';
      if (canPreview) actions += `<button class="code-action-btn code-preview-btn" onclick="OC.previewHtml('${id}')">${typeof icon === 'function' ? icon('eye', 14) : '👁'} Preview</button>`;
      actions += `<button class="code-action-btn code-save-btn" onclick="OC.saveToFiles('${id}','${escHtml(lang)}','${escHtml(label)}')">${typeof icon === 'function' ? icon('save', 14) : '💾'} Save</button>`;
      actions += `<button class="code-action-btn" onclick="OC.copyCode('${id}')">${typeof icon === 'function' ? icon('copy', 14) : '📋'} Copy</button>`;
      if (canRun) actions += `<button class="code-run-btn" onclick="OC.runCode('${id}')">${typeof icon === 'function' ? icon('terminal', 14) : '▶'} Run</button>`;

      return `<div class="code-block-header"><span>${escHtml(label)}</span>` +
             `<div class="code-block-actions">${actions}</div></div>` +
             `<pre id="${id}"><code${lcls}>${code}</code></pre>`;
    }

    _renderComponent(block) {
      const lang = block.meta.lang || '';
      const content = block.text();
      const id = block.id;

      // Delegate to ComponentRegistry if available
      if (window.ComponentRegistry) {
        const comp = window.ComponentRegistry.match(lang);
        if (comp) {
          // Create a container and let the component render into it
          return `<div class="component-container" id="${id}" data-component="${lang}" data-content="${escHtml(content)}"></div>`;
        }
      }

      // Fallback: render as code block
      return this._renderCode(block);
    }

    _renderTable(block) {
      const rows = block.lines.join('\n').trim().split('\n').filter(r => r.trim());
      if (rows.length < 2) return '<p>' + escHtml(block.text()) + '</p>';

      const tableId = block.id;
      let html = `<div class="dynamic-table-wrapper"><div class="dynamic-table-scroll"><table class="dynamic-table" id="${tableId}">`;

      rows.forEach((row, i) => {
        if (row.match(/^\|[\s-:|]+\|$/)) return; // skip separator
        const cells = row.split('|').filter(c => c.trim() !== '');
        const tag = i === 0 ? 'th' : 'td';
        if (i === 0) html += '<thead>';
        if (i === 1) html += '</thead><tbody>';
        html += '<tr>' + cells.map(c => {
          let cell = inlineMd(c.trim());
          return `<${tag}>${cell}</${tag}>`;
        }).join('') + '</tr>';
      });

      html += '</tbody></table></div></div>';
      return html;
    }

    _renderHeading(block) {
      const level = Math.min(block.meta.level + 1, 6); // h1 → h2, etc.
      return `<h${level}>${inlineMd(block.text())}</h${level}>`;
    }

    _renderList(block) {
      const tag = block.meta.listType === 'ol' ? 'ol' : 'ul';
      const items = block.lines.map(l => `<li>${inlineMd(l)}</li>`).join('');
      return `<${tag}>${items}</${tag}>`;
    }

    _renderQuote(block) {
      return `<blockquote>${block.lines.map(l => inlineMd(l)).join('<br>')}</blockquote>`;
    }

    _renderThinking(block) {
      const content = escHtml(block.text());
      let toolLabel = 'tool';

      // Try to detect tool name from JSON
      try {
        const raw = block.text().trim();
        const parsed = JSON.parse(raw);
        if (parsed && parsed.tool) toolLabel = parsed.tool;
      } catch (e) {
        // Not JSON — that's fine
      }

      return `<details class="tool-thinking">` +
             `<summary> <em>Thinking… </em><span class="tool-thinking-label">${escHtml(toolLabel)}</span></summary>` +
             `<pre style="margin:8px 0;background:var(--bg-primary);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;overflow-x:auto;">` +
             `<code>${content}</code></pre></details>`;
    }

    /* ---- Post-render hooks ---- */

    _postRender(block) {
      if (!block.el) return;

      // Syntax highlighting for code blocks
      if (block.type === BLOCK_CODE && window.hljs) {
        block.el.querySelectorAll('pre code').forEach(codeEl => {
          if (!codeEl.dataset.highlighted) {
            window.hljs.highlightElement(codeEl);
            // Add line numbers
            const lines = codeEl.innerHTML.split('\n');
            if (lines[lines.length - 1] === '') lines.pop();
            codeEl.innerHTML = lines.map(l => `<span class="ln"></span>${l}`).join('\n');
          }
        });
      }

      // Component initialization
      if (block.type === BLOCK_COMPONENT && window.ComponentRegistry) {
        const container = block.el.querySelector('.component-container');
        if (container) {
          const lang = container.dataset.component;
          const content = container.dataset.content;
          // Decode HTML entities
          const decoded = content.replace(/&amp;/g, '&').replace(/&lt;/g, '<')
                                  .replace(/&gt;/g, '>').replace(/&quot;/g, '"');
          window.ComponentRegistry.renderOrUpdate(lang, container, decoded, block.id);
        }
      }
    }
  }

  /* ------------------------------------------------------------------ */
  /*  Export                                                              */
  /* ------------------------------------------------------------------ */

  window.StreamingParser = StreamingParser;
})();
