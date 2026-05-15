/* Clawzd v2.0 — Main Application JS */
(function () {
  'use strict';
  function $(s, c) { return (c || document).querySelector(s); }
  function $$(s, c) { return Array.from((c || document).querySelectorAll(s)); }
  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    if (attrs) Object.entries(attrs).forEach(([k, v]) => {
      if (k === 'class') e.className = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else if (k === 'html') e.innerHTML = v;
      else if (k === 'text') e.textContent = v;
      else e.setAttribute(k, v);
    });
    if (children) children.forEach(c => { if (c) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return e;
  }
  // Local toast history — accessible by NotificationBadge
  window._toastHistory = window._toastHistory || [];

  function toast(msg, duration = 5000) {
    const t = el('div', { class: 'toast', html: msg });
    document.body.appendChild(t);
    // Apply dynamic exit animation based on duration (duration minus 300ms for the animation length)
    const delay = Math.max(0, (duration / 1000) - 0.3);
    t.style.animation = `toastIn .3s ease forwards, toastOut .3s ease ${delay}s forwards`;
    setTimeout(() => t.remove(), duration);

    // Store in local notification history for the NotificationBadge dropdown
    const plainText = msg.replace(/<[^>]*>/g, '').trim();
    if (plainText) {
      window._toastHistory.push({
        title: plainText.length > 60 ? plainText.slice(0, 60) + '…' : plainText,
        body: plainText,
        timestamp: new Date().toISOString(),
        read: false,
        local: true,
      });
      // Cap history at 50 items
      if (window._toastHistory.length > 50) window._toastHistory.shift();

      // Update notification badge count in real-time
      const countEl = document.getElementById('notif-count');
      if (countEl) {
        const unread = window._toastHistory.filter(n => !n.read).length;
        if (unread > 0) {
          countEl.textContent = unread > 9 ? '9+' : unread;
          countEl.style.display = 'inline-flex';
        }
      }
    }
  }
  function escHtml(s) {
    if (s == null) return '';
    s = String(s);
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function timeAgo(iso) {
    const d = new Date(iso), now = new Date(), diff = (now - d) / 1000;
    if (diff < 60) return 'now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h';
    return Math.floor(diff / 86400) + 'd';
  }

  // Expose utilities for extracted modules (EditorMode, MediaStudio, etc.)
  window.$ = $; window.$$ = $$; window.el = el;
  window.toast = toast; window.escHtml = escHtml; window.timeAgo = timeAgo;

  // ---- Markdown renderer ----
  // Initialize mermaid if available
  if (window.mermaid) {
    const isLightMode = localStorage.getItem('omniclaw-theme') === 'light';
    const darkVars = {
      fontFamily: 'inherit',
      primaryColor: '#252532',
      primaryTextColor: '#f8fafc',
      primaryBorderColor: '#3d3d4e',
      lineColor: '#6366f1',
      secondaryColor: '#2b2b36',
      tertiaryColor: '#1a1a24',
      mainBkg: '#1e1e2d',
      nodeBorder: '#4f46e5',
      clusterBkg: 'transparent',
      clusterBorder: '#4f46e5',
      defaultLinkColor: '#818cf8',
      textColor: '#e2e8f0',
      edgeLabelBackground: '#2b2b36'
    };
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'loose',
      theme: isLightMode ? 'default' : 'base',
      themeCSS: '.cluster rect { fill: transparent !important; stroke-dasharray: 6 4 !important; stroke-width: 2px !important; }',
      themeVariables: isLightMode ? {} : darkVars
    });
  }

  function renderMd(text) {
    // ---- Phase 0: Extract structured UI markers from RAW text (before escHtml) ----
    // __TABLE__, __CHART__, __PROGRESS__, __CARD__, __ALERT__, __ARTIFACT__
    // These contain JSON that would be corrupted by escHtml.
    const _suiBlocks = [];
    function _suiPh(html) { const k = '\x00SUI' + _suiBlocks.length + '\x00'; _suiBlocks.push(html); return k; }
    text = text.replace(/__(TABLE|CHART|PROGRESS|CARD|ALERT|ARTIFACT)__(\{[\s\S]*?\})__\1__/g, (_, type, jsonStr) => {
      try {
        if (window.StructuredUI) {
          const marker = `__${type}__${jsonStr}__${type}__`;
          return _suiPh(window.StructuredUI.renderComponents(marker));
        }
        // Fallback: try to render inline
        const config = JSON.parse(jsonStr);
        if (type === 'TABLE') {
          const title = config.title ? `<div class="sui-table-title">${config.title}</div>` : '';
          const headers = (config.headers || []).map(h => `<th>${h}</th>`).join('');
          const rows = (config.rows || []).map(row =>
            '<tr>' + row.map(cell => `<td>${cell}</td>`).join('') + '</tr>'
          ).join('');
          return _suiPh(`<div class="sui-table-wrapper">${title}<div class="sui-table-scroll"><table class="sui-table"><thead><tr>${headers}</tr></thead><tbody>${rows}</tbody></table></div></div>`);
        }
        if (type === 'CHART') {
          const id = 'sui-chart-' + Math.random().toString(36).slice(2, 8);
          setTimeout(() => {
            if (window.StructuredUI) window.StructuredUI.renderComponents(`__CHART__${jsonStr}__CHART__`);
          }, 200);
          return _suiPh(`<div class="sui-chart-wrapper"><canvas id="${id}"></canvas></div>`);
        }
        return _suiPh(`<div class="sui-error">⚠️ Unsupported marker: ${type}</div>`);
      } catch (e) {
        return _suiPh(`<div class="sui-error">⚠️ Invalid ${type} data: ${e.message}</div>`);
      }
    });

    let h = escHtml(text);

    // ---- Phase 1: Extract block elements into placeholders ----
    // This prevents the \n → <br> replacement from destroying
    // newlines inside <pre>, <div>, and <table> blocks.
    const blocks = [];
    function ph(html) { const k = '\x00BLK' + blocks.length + '\x00'; blocks.push(html); return k; }

    // Mermaid diagrams — also match ```mermaid with varied whitespace
    h = h.replace(/```mermaid\s*\n([\s\S]*?)```/g, (_, code) => {
      const id = 'mm-' + Math.random().toString(36).slice(2, 8);
      const decoded = code.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"');
      // Detect unsupported diagram types before rendering
      const unsupportedTypes = ['architecture-beta', 'architecture'];
      const firstLine = decoded.trim().split('\n')[0].trim().toLowerCase();
      const isUnsupported = unsupportedTypes.some(t => firstLine.startsWith(t));

      // --- Mermaid Sanitizer: fix common cycle-causing issues ---
      function sanitizeMermaid(src) {
        // 0. Strip HTML tags from node labels (<br>, <br/>, etc.)
        let fixed = src.replace(/<br\s*\/?>/gi, ' ');
        // Auto-quote node labels with special chars: A[text (with parens)] → A["text (with parens)"]
        fixed = fixed.replace(/(\w+)(\[)([^\]"]+[()\/<>][^\]"]*)(\])/g, (m, id, open, label, close) => {
          return `${id}["${label.trim()}"]`;
        });
        fixed = fixed.replace(/(\w+)(\()([^)"]+[\[\]\/<>][^)"]*)(\))/g, (m, id, open, label, close) => {
          return `${id}("${label.trim()}")`;
        });
        fixed = fixed.replace(/(\w+)(\{)([^}"]+[()\[\]\/<>][^}"]*)(\})/g, (m, id, open, label, close) => {
          return `${id}{"${label.trim()}"}`;
        });

        const lines = fixed.split('\n');
        // 1. Collect all subgraph IDs
        const subgraphIds = new Set();
        const subgraphLineMap = new Map(); // lineIndex -> subgraphId
        lines.forEach((line, i) => {
          const m = line.match(/^\s*subgraph\s+(\w+)/);
          if (m) { subgraphIds.add(m[1]); subgraphLineMap.set(i, m[1]); }
        });
        // 2. Collect all node IDs (simple heuristic: ID followed by [, (, {, etc.)
        const nodeIds = new Set();
        lines.forEach((line, i) => {
          if (subgraphLineMap.has(i)) return; // skip subgraph lines
          const trimmed = line.trim();
          if (!trimmed || trimmed === 'end' || trimmed.startsWith('%%') ||
            trimmed.startsWith('classDef') || trimmed.startsWith('class ') ||
            trimmed.startsWith('style ') || trimmed.startsWith('linkStyle') ||
            /^(flowchart|graph|sequenceDiagram|classDiagram|erDiagram|gantt|pie|mindmap|timeline|stateDiagram)/i.test(trimmed)) return;
          // Extract node IDs from arrows: A --> B, A --- B, etc.
          const arrowParts = trimmed.split(/\s*(?:-->|==>|-\.->|---->|---|===|~~~|-\.-|--\s|--\||<-->)\s*/);
          arrowParts.forEach(part => {
            const nodeMatch = part.match(/^(\w+)/);
            if (nodeMatch) nodeIds.add(nodeMatch[1]);
          });
          // Standalone node definitions: A["label"] or A("label") etc.
          const standaloneMatch = trimmed.match(/^(\w+)\s*[\[({]/);
          if (standaloneMatch) nodeIds.add(standaloneMatch[1]);
        });
        // 3. Fix conflicts: rename subgraph IDs that clash with node IDs
        subgraphIds.forEach(sgId => {
          if (nodeIds.has(sgId)) {
            const newId = sgId + '_grp';
            // Replace "subgraph <id>" and "subgraph <id>[" patterns
            fixed = fixed.replace(
              new RegExp('(\\bsubgraph\\s+)' + sgId + '(\\s|\\[|$)', 'gm'),
              '$1' + newId + '$2'
            );
            console.info(`[Mermaid sanitizer] Renamed subgraph "${sgId}" → "${newId}" to avoid cycle`);
          }
        });
        // 4. Remove self-referencing arrows (A --> A)
        fixed = fixed.replace(/^(\s*)(\w+)\s*(?:-->|==>|-\.->|---)\s*\2\s*$/gm, (match, indent, id) => {
          console.info(`[Mermaid sanitizer] Removed self-reference: ${id} --> ${id}`);
          return '';
        });
        return fixed;
      }

      const sanitized = sanitizeMermaid(decoded);

      const renderMermaid = async (attempt) => {
        const el2 = document.getElementById(id);
        if (!el2) {
          if (attempt < 3) { setTimeout(() => renderMermaid(attempt + 1), 300); return; }
          return;
        }
        const showError = (title, detail) => {
          el2.innerHTML = '<div class="mermaid-error" style="color:#f87171;padding:12px;border:1px solid #f8717133;border-radius:8px;font-family:monospace;font-size:13px;margin-bottom:8px;">⚠️ ' + title + '</div>' +
            (detail ? '<div style="color:var(--text-muted);font-size:12px;margin-bottom:8px;padding:0 12px;">' + detail + '</div>' : '') +
            '<pre style="margin:0;background:var(--bg-primary);border:1px solid var(--border);border-radius:8px;padding:12px;overflow-x:auto;font-family:monospace;font-size:12px;color:var(--text-secondary);"><code>' + escHtml(sanitized) + '</code></pre>';
        };
        // Step 1: Static check — reject known unsupported diagram types
        if (isUnsupported) {
          showError('Unsupported diagram type: <strong>' + escHtml(firstLine) + '</strong>',
            'Supported types: flowchart, sequenceDiagram, classDiagram, erDiagram, gantt, pie, mindmap, timeline, etc.');
          return;
        }
        if (!window.mermaid) { showError('Mermaid library not loaded'); return; }
        // Step 2: Pre-validate syntax with mermaid.parse() before rendering
        try {
          await mermaid.parse(sanitized);
        } catch (parseErr) {
          console.warn('Mermaid parse validation failed:', parseErr);
          showError('Diagram syntax error: ' + escHtml(parseErr.message || String(parseErr)),
            'The diagram code contains syntax errors and cannot be rendered.');
          return;
        }
        // Step 3: Syntax valid — proceed to full render
        try {
          const r = await mermaid.render('mmr-' + id, sanitized);
          el2.innerHTML = r.svg;
        } catch (e) {
          console.warn('Mermaid render error:', e);
          showError('Diagram render error: ' + escHtml(e.message || String(e)));
        }
      };
      setTimeout(() => renderMermaid(0), 200);

      return ph(
        `<div class="mermaid-wrapper" style="position:relative; margin: 16px 0;">` +
        `<div style="text-align:right;margin-bottom:4px; display:flex; gap:8px; justify-content:flex-end;">` +
        `<button class="code-action-btn" onclick="OC.sendMermaidToPresentation('${id}')">${icon('presentation', 14)} To Presentation</button>` +
        `<button class="code-action-btn" onclick="OC.exportMermaidMd('${id}')">${icon('download', 14)} Export MD</button>` +
        `<button class="code-action-btn" onclick="OC.exportMermaidSvg('${id}')">${icon('download', 14)} Export SVG</button>` +
        `</div>` +
        `<div class="mermaid-container" id="${id}" data-code="${escHtml(sanitized)}" style="background:var(--bg-secondary); border-radius:8px; padding:16px;">Loading diagram...</div>` +
        `</div>`
      );
    });

    // Chart.js data visualizations — ```chart { type, labels, datasets } ```
    h = h.replace(/```chart\s*\n([\s\S]*?)```/g, (_, jsonStr) => {
      const id = 'chart-' + Math.random().toString(36).slice(2, 8);
      const raw = jsonStr.trim()
        .replace(/&amp;/g, '&').replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>').replace(/&quot;/g, '"');
      let config;
      try {
        config = JSON.parse(raw);
      } catch (e) {
        return ph(`<div style="color:#f87171;padding:12px;border:1px solid #f8717133;border-radius:8px;font-family:monospace;font-size:13px;margin:12px 0;">⚠️ Chart JSON error: ${escHtml(e.message)}</div>`);
      }
      // Support simplified format: { type, data: { label: value } }
      if (config.data && !config.labels && !config.datasets) {
        const simplified = config.data;
        if (typeof simplified === 'object' && !Array.isArray(simplified)) {
          config.labels = Object.keys(simplified);
          config.datasets = [{ label: config.title || 'Data', data: Object.values(simplified) }];
        }
      }
      const chartType = config.type || 'bar';
      const title = config.title || '';
      // Palette matching the dark UI theme
      const palette = [
        'rgba(99, 102, 241, 0.85)', 'rgba(16, 185, 129, 0.85)',
        'rgba(245, 158, 11, 0.85)', 'rgba(239, 68, 68, 0.85)',
        'rgba(139, 92, 246, 0.85)', 'rgba(6, 182, 212, 0.85)',
        'rgba(236, 72, 153, 0.85)', 'rgba(34, 197, 94, 0.85)',
        'rgba(251, 146, 60, 0.85)', 'rgba(168, 85, 247, 0.85)'
      ];
      const borderPalette = palette.map(c => c.replace('0.85', '1'));
      const isPie = ['pie', 'doughnut', 'polarArea'].includes(chartType);
      const datasets = (config.datasets || []).map((ds, di) => ({
        label: ds.label || `Dataset ${di + 1}`,
        data: ds.data || [],
        backgroundColor: isPie ? palette : (ds.color || palette[di % palette.length]),
        borderColor: isPie ? borderPalette : (ds.color ? ds.color.replace('0.85', '1') : borderPalette[di % borderPalette.length]),
        borderWidth: isPie ? 2 : 2,
        tension: chartType === 'line' ? 0.35 : undefined,
        fill: chartType === 'line' ? (ds.fill !== undefined ? ds.fill : false) : undefined,
        pointRadius: chartType === 'line' ? 4 : undefined,
        pointHoverRadius: chartType === 'line' ? 6 : undefined,
      }));
      const chartConfig = JSON.stringify({
        type: chartType,
        data: { labels: config.labels || [], datasets },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            title: { display: !!title, text: title, color: '#e1e5eb', font: { size: 15, weight: '600' } },
            legend: { labels: { color: '#9ca3af', font: { size: 12 } } },
            tooltip: { backgroundColor: 'rgba(30,34,43,0.95)', titleColor: '#e1e5eb', bodyColor: '#d1d5db', borderColor: 'rgba(99,102,241,0.4)', borderWidth: 1 }
          },
          scales: isPie ? {} : {
            x: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(255,255,255,0.06)' } },
            y: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(255,255,255,0.06)' }, beginAtZero: true }
          }
        }
      });
      setTimeout(() => {
        const canvas = document.getElementById(id);
        if (canvas && window.Chart) {
          try { new Chart(canvas.getContext('2d'), JSON.parse(canvas.dataset.chartConfig)); }
          catch (e) { console.warn('Chart render error:', e); }
        }
      }, 200);
      return ph(
        `<div class="chart-wrapper" style="position:relative;margin:16px 0;">` +
        `<div style="text-align:right;margin-bottom:4px;display:flex;gap:8px;justify-content:flex-end;">` +
        `<button class="code-action-btn" onclick="OC.exportChartPng('${id}')">${icon('download', 14)} Export PNG</button>` +
        `<button class="code-action-btn" onclick="OC.sendChartToPresentation('${id}')">${icon('presentation', 14)} To Presentation</button>` +
        `</div>` +
        `<div style="background:var(--bg-secondary);border-radius:8px;padding:16px;min-height:250px;max-height:420px;position:relative;">` +
        `<canvas id="${id}" data-chart-config='${chartConfig.replace(/'/g, "&#39;")}'></canvas>` +
        `</div>` +
        `</div>`
      );
    });

    // Diff blocks — ```diff with colored +/- lines and Apply button
    h = h.replace(/```diff\s*\n([\s\S]*?)```/g, (_, diffContent) => {
      const id = 'diff-' + Math.random().toString(36).slice(2, 8);
      const lines = diffContent.split('\n').map(line => {
        const escaped = escHtml(line);
        if (line.startsWith('+')) return `<span class="diff-add">${escaped}</span>`;
        if (line.startsWith('-')) return `<span class="diff-del">${escaped}</span>`;
        if (line.startsWith('@@')) return `<span class="diff-hunk">${escaped}</span>`;
        return `<span class="diff-ctx">${escaped}</span>`;
      }).join('\n');
      return ph(
        `<div class="diff-block" id="${id}">` +
        `<div class="code-block-header"><span>diff</span>` +
        `<div class="code-block-actions">` +
        `<button class="code-action-btn" onclick="OC.copyCode('${id}')">${icon('copy', 14)} Copy</button>` +
        `</div></div>` +
        `<pre id="${id}"><code class="language-diff">${lines}</code></pre>` +
        `</div>`
      );
    });

    // Progress blocks — ```progress { label, value, max?, color? }
    h = h.replace(/```progress\s*\n([\s\S]*?)```/g, (_, jsonStr) => {
      const raw = jsonStr.trim()
        .replace(/&amp;/g, '&').replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>').replace(/&quot;/g, '"');
      try {
        const items = JSON.parse(raw);
        const list = Array.isArray(items) ? items : [items];
        const html = list.map(item => {
          const pct = Math.min(100, Math.max(0, ((item.value || 0) / (item.max || 100)) * 100));
          const color = item.color || 'var(--primary)';
          const label = escHtml(item.label || '');
          return (
            `<div class="progress-item">` +
            `<div class="progress-label"><span>${label}</span><span>${pct.toFixed(0)}%</span></div>` +
            `<div class="progress-bar"><div class="progress-fill" style="width:${pct}%;background:${color}"></div></div>` +
            `</div>`
          );
        }).join('');
        return ph(`<div class="progress-block">${html}</div>`);
      } catch (e) {
        return ph(`<div style="color:#f87171;padding:12px;">⚠️ Progress JSON error: ${escHtml(e.message)}</div>`);
      }
    });

    // Form blocks — ```form { fields: [{name, type, label, placeholder?, options?}], action? }
    h = h.replace(/```form\s*\n([\s\S]*?)```/g, (_, jsonStr) => {
      const id = 'form-' + Math.random().toString(36).slice(2, 8);
      const raw = jsonStr.trim()
        .replace(/&amp;/g, '&').replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>').replace(/&quot;/g, '"');
      try {
        const config = JSON.parse(raw);
        const fields = (config.fields || []).map(f => {
          const fieldId = id + '-' + (f.name || Math.random().toString(36).slice(2, 6));
          const label = f.label || f.name || '';
          const placeholder = f.placeholder || '';
          let input = '';
          switch (f.type) {
            case 'textarea':
              input = `<textarea id="${fieldId}" name="${escHtml(f.name)}" placeholder="${escHtml(placeholder)}" class="form-field-input" rows="3"></textarea>`;
              break;
            case 'select':
              const opts = (f.options || []).map(o => `<option value="${escHtml(o)}">${escHtml(o)}</option>`).join('');
              input = `<select id="${fieldId}" name="${escHtml(f.name)}" class="form-field-input">${opts}</select>`;
              break;
            case 'checkbox':
              input = `<label class="form-checkbox"><input type="checkbox" id="${fieldId}" name="${escHtml(f.name)}"> ${escHtml(label)}</label>`;
              return `<div class="form-field">${input}</div>`;
            default:
              input = `<input type="${f.type || 'text'}" id="${fieldId}" name="${escHtml(f.name)}" placeholder="${escHtml(placeholder)}" class="form-field-input">`;
          }
          return `<div class="form-field"><label for="${fieldId}">${escHtml(label)}</label>${input}</div>`;
        }).join('');
        const title = config.title ? `<div class="form-title">${escHtml(config.title)}</div>` : '';
        const submit = config.submit || 'Submit';
        return ph(
          `<div class="chat-form" id="${id}">` +
          title + fields +
          `<button class="chat-form-submit" onclick="OC.submitChatForm('${id}')">${escHtml(submit)}</button>` +
          `</div>`
        );
      } catch (e) {
        return ph(`<div style="color:#f87171;padding:12px;">⚠️ Form JSON error: ${escHtml(e.message)}</div>`);
      }
    });

    // Helper: build a code block with header, copy, run, save, and preview buttons
    function codeBlock(lang, label, code) {
      const id = 'cb-' + Math.random().toString(36).slice(2, 8);
      const ll = (lang || '').toLowerCase();
      const run = ['python', 'py', 'sh', 'bash'].includes(ll);
      const preview = ['html', 'htm', 'svg'].includes(ll);
      const isEditor = window.editor && window.editor.activeTab;

      const rb = run ? `<button class="code-run-btn" onclick="OC.runCode('${id}')">${icon('terminal', 14)} Run</button>` : '';
      const pb = preview ? `<button class="code-action-btn code-preview-btn" onclick="OC.previewHtml('${id}')">${icon('eye', 14)} Preview</button>` : '';
      const sb = `<button class="code-action-btn code-save-btn" onclick="OC.saveToFiles('${id}','${escHtml(lang)}','${escHtml(label)}')">${icon('save', 14)} Save</button>`;
      const ab = isEditor ? `<button class="code-action-btn code-apply-btn" onclick="OC.applyToEditor('${id}')" title="Apply to active editor file">${icon('check', 14)} Apply</button>` : '';

      const lcls = lang ? ` class="language-${lang}"` : '';
      return ph(
        `<div class="code-block-header"><span>${escHtml(label)}</span>` +
        `<div class="code-block-actions">${ab}${pb}${sb}<button class="code-action-btn" onclick="OC.copyCode('${id}')">${icon('copy', 14)} Copy</button>${rb}</div></div>` +
        `<pre id="${id}"><code${lcls}>${code}</code></pre>`
      );
    }

    // Tool call blocks — render as collapsible "Thinking..." sections
    // Uses regex literal to avoid new RegExp double-escaping issues. Requires \n before closing ``` to prevent breaking on inner escaped fences
    const toolFenceRe = /```(?:tool_call|tool|json|execute_python|search_web|screenshot_remote|screenshot_local|generate_image|run_command|browse_web|audit_code|rag_search|create_app|update_app|analyze_data|fetch_market_data)\s*\n([\s\S]*?)\n```/g;
    h = h.replace(toolFenceRe, (match, content) => {
      let raw = content.trim()
        .replace(/&amp;/g, '&').replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>').replace(/&quot;/g, '"');

      if (raw.toLowerCase().startsWith("tool_call\n")) {
        raw = raw.substring(10).trim();
      } else if (raw.toLowerCase().startsWith("json\n")) {
        raw = raw.substring(5).trim();
      }

      let toolLabel = 'tool';
      let detailContent = content; // fallback: show raw (still escaped)
      let isTool = false;
      try {
        const call = JSON.parse(raw);
        if (call && typeof call === 'object' && call.tool) {
          isTool = true;
          toolLabel = call.tool;
          const params = call.params || {};
          if (params.code) {
            // Show the Python code inside the collapsible
            const safeCode = params.code
              .replace(/&/g, '&amp;').replace(/</g, '&lt;')
              .replace(/>/g, '&gt;');
            detailContent = `<pre style="margin:8px 0;background:var(--bg-primary);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;overflow-x:auto;"><code class="language-python">${safeCode}</code></pre>`;
          } else if (toolLabel === 'create_app' || toolLabel === 'update_app') {
            let filesHtml = '';
            const files = params.files || {};
            for (const [fname, content] of Object.entries(files)) {
              let lang = 'html';
              if (fname.endsWith('.css')) lang = 'css';
              if (fname.endsWith('.js')) lang = 'javascript';
              const safeContent = (typeof content === 'string' ? content : JSON.stringify(content))
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
              filesHtml += `<div style="font-weight:bold;margin:8px 0 4px 0;color:var(--text-secondary);font-size:12px;">📄 ${escHtml(fname)}</div>`;
              filesHtml += `<pre style="margin:0 0 12px 0;background:var(--bg-primary);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;overflow-x:auto;"><code class="language-${lang}">${safeContent}</code></pre>`;
            }
            if (!filesHtml) {
              const safeJson = JSON.stringify(params, null, 2)
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
              detailContent = `<pre style="margin:8px 0;background:var(--bg-primary);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;overflow-x:auto;font-size:12px;"><code>${safeJson}</code></pre>`;
            } else {
              detailContent = filesHtml;
            }
          } else {
            // Show params as formatted JSON
            const safeJson = JSON.stringify(params, null, 2)
              .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            detailContent = `<pre style="margin:8px 0;background:var(--bg-primary);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;overflow-x:auto;font-size:12px;"><code>${safeJson}</code></pre>`;
          }
        }
      } catch (e) {
        // Not valid JSON — show raw content but clean up escaped newlines so it's readable during streaming
        isTool = true; // Still treat as tool if it's truncated/streaming
        if (match.includes('```create_app') || match.includes('```update_app')) {
          toolLabel = match.includes('```create_app') ? 'create_app' : 'update_app';
        } else if (match.includes('```execute_python') || match.includes('```python')) {
          toolLabel = 'execute_python';
        }
        let readableContent = content.replace(/\\n/g, '\n').replace(/\\"/g, '"');
        let langClass = '';
        if (toolLabel === 'create_app' || toolLabel === 'update_app') {
          langClass = ' class="language-html"';
          if (readableContent.trim().toLowerCase().startsWith('html\n')) readableContent = readableContent.trim().substring(5);
        } else if (toolLabel === 'execute_python') {
          langClass = ' class="language-python"';
        }
        const safeContent = readableContent.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        detailContent = `<pre style="margin:8px 0;background:var(--bg-primary);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;overflow-x:auto;"><code${langClass}>${safeContent}</code></pre>`;
      }

      if (!isTool) return match; // Fallback to normal code block rendering for non-tool JSON

      return ph(
        `<details class="tool-thinking">` +
        `<summary> <em>Thinking… </em><span class="tool-thinking-label">${escHtml(toolLabel)}</span></summary>` +
        detailContent +
        `</details>`
      );
    });

    // Terminal output details
    h = h.replace(/__DETAILS__([\s\S]*?)__DETAILS__/g, (_, content) => {
      return ph(`<details class="tool-thinking"><summary>Terminal Output</summary><pre style="margin:8px 0;background:var(--bg-primary);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;overflow-x:auto;"><code>${content.trim()}</code></pre></details>`);
    });

    // Handle inline tool approval requests (HITL)
    h = h.replace(/__TOOL_APPROVAL__([\s\S]+?)__TOOL_APPROVAL__/g, (m, content) => {
      try {
        if (window.toolApproval) window.toolApproval._show(JSON.parse(content));
      } catch (e) { }
      return '';
    });

    // Remove internal file edit markers so they aren't rendered as plain text
    h = h.replace(/__FILE_EDIT__({.+?})__/g, "");

    // Code blocks: supports ```lang:filename, ```lang filename, ```lang, and bare ```
    // Order: most specific first; each pattern consumes matches so later ones skip them.
    // 1. lang:filename  OR  lang<space>filename  (filename must contain a dot)
    h = h.replace(/```(\w+)(?::|\s)([\w.\/][^\n]*?\.[\w]+)[ \t]*\n([\s\S]*?)```/g, (_, lang, fname, code) => {
      return codeBlock(lang, fname.trim(), code);
    });
    // 2. lang:filename without dot (e.g. ```python:Makefile)
    h = h.replace(/```(\w+):([\w.\/]+)[ \t]*\n([\s\S]*?)```/g, (_, lang, fname, code) => {
      return codeBlock(lang, fname.trim() || lang || 'code', code);
    });
    // 3. Simple code blocks with just a language (```python\n...)
    h = h.replace(/```(\w+)[ \t]*\n([\s\S]*?)```/g, (_, lang, code) => {
      return codeBlock(lang, lang || 'code', code);
    });
    // 4. Bare code fences (``` without language, content may not start with \n)
    h = h.replace(/```[ \t]*\n?([\s\S]*?)```/g, (_, code) => {
      return codeBlock('', 'code', code);
    });

    // Deepseek <think> tags — wrap in collapsible (supports streaming / unclosed tags)
    h = h.replace(/&lt;think&gt;/g, '<details class="tool-thinking" open><summary> <em>Thinking…</em></summary><div style="padding:12px;color:var(--text-muted);font-style:italic;overflow-x:auto;">');
    h = h.replace(/&lt;\/think&gt;/g, '</div></details>');

    // Tables (| col | col |)
    h = h.replace(/((?:\|[^\n]+\|\s*\n){2,})/g, (table) => {
      const rows = table.trim().split('\n').filter(r => r.trim());
      if (rows.length < 2) return table;
      const tableId = 'tbl-' + Math.random().toString(36).slice(2, 8);
      const encodedMd = encodeURIComponent(table.trim());
      let html = `<div class="dynamic-table-wrapper"><div class="dynamic-table-actions"><button class="code-action-btn" onclick="OC.sendToPresentation('table', decodeURIComponent('${encodedMd}'))">${icon('presentation', 14)} To Presentation</button><button class="code-action-btn" onclick="OC.exportTableToExcel('${tableId}')">${icon('download', 14)} Export Excel</button></div><div class="dynamic-table-scroll"><table class="dynamic-table" id="${tableId}" data-md="${encodedMd}">`;
      rows.forEach((row, i) => {
        if (row.match(/^\|[\s-:|]+\|$/)) return; // skip separator
        const cells = row.split('|').filter(c => c.trim() !== '');
        const tag = i === 0 ? 'th' : 'td';
        const wrap = i === 0 ? 'thead' : (i === 1 ? 'tbody' : '');
        if (wrap === 'thead') html += '<thead>';
        if (wrap === 'tbody') html += '</thead><tbody>';
        html += '<tr>' + cells.map(c => {
          let cell = c.trim();
          cell = cell.replace(/`([^`]+)`/g, '<code>$1</code>');
          cell = cell.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
          cell = cell.replace(/\*(.+?)\*/g, '<em>$1</em>');
          cell = cell.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img src="$2" alt="$1" style="max-width:100px;border-radius:4px;margin:2px 0;">');
          cell = cell.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:underline;">$1</a>');
          return `<${tag}>${cell}</${tag}>`;
        }).join('') + '</tr>';
      });
      html += '</tbody></table></div></div>';
      return ph(html);
    });

    // ---- Phase 2: Inline markdown (safe — no block elements left) ----
    // Tool-generated images: __IMG__url|label|filename__IMG__
    h = h.replace(/__IMG__([^|]+)\|([^|]+)\|(.+?)__IMG__/g, (_, url, label, fname) => {
      const imgId = 'timg-' + Math.random().toString(36).slice(2, 8);
      return ph(
        `<div class="tool-result-image" style="margin:12px 0;">` +
        `<div class="tool-img-toolbar">` +
        `<button class="tool-img-btn" onclick="OC.openLightbox('${url}', '${label.replace(/'/g, "\\'")}', '${fname.replace(/'/g, "\\'")}')">${icon('search', 14)} Zoom</button>` +
        `<button class="tool-img-btn" onclick="OC.downloadUrl('${url}', '${fname.replace(/'/g, "\\'")}')">${icon('save', 14)} Save</button>` +
        ((fname.toLowerCase().endsWith('.gif') || fname.toLowerCase().endsWith('.mp4') || fname.toLowerCase().endsWith('.webm') || fname.toLowerCase().endsWith('.svg')) ? '' : `<button class="tool-img-btn" onclick="OC.removeBg('${fname.replace(/'/g, "\\'")}','${imgId}')">${icon('palette', 14)} Remove BG</button><button class="tool-img-btn" onclick="OC.makeColoring('${fname.replace(/'/g, "\\'")}','${imgId}')">${icon('edit', 14)} Crayons</button>`) +
        `</div>` +
        `<img id="${imgId}" src="${url}" alt="${escHtml(label)}" ` +
        `style="max-width:100%;border-radius:8px;margin:8px 0;box-shadow:0 4px 20px rgba(0,0,0,0.4);cursor:zoom-in;" ` +
        `onclick="OC.openLightbox('${url}', '${label.replace(/'/g, "\\'")}', '${fname.replace(/'/g, "\\'")}')" ` +
        `onerror="this.style.display='none';this.nextElementSibling.style.display='block'" ` +
        `>` +
        `<div style="display:none;padding:12px;background:var(--bg-secondary);border-radius:8px;color:var(--text-secondary);">⏳ Image loading...</div>` +
        `<div class="tool-result-meta" style="font-size:12px;color:var(--text-muted);margin-top:4px;"> ${escHtml(fname)}</div>` +
        `</div>`
      );
    });
    // Tool-generated SVG images: __SVG__url|label|filename__SVG__
    h = h.replace(/__SVG__([^|]+)\|([^|]+)\|(.+?)__SVG__/g, (_, url, label, fname) => {
      const svgId = 'tsvg-' + Math.random().toString(36).slice(2, 8);
      return ph(
        `<div class="tool-result-image tool-result-svg" style="margin:12px 0;">` +
        `<div class="tool-img-toolbar">` +
        `<button class="tool-img-btn" onclick="OC.openLightbox('${url}', '${label.replace(/'/g, "\\'")}', '${fname.replace(/'/g, "\\'")}')">${icon('search', 14)} Zoom</button>` +
        `<button class="tool-img-btn" onclick="OC.sendToPresentation('image', '${url}')">${icon('presentation', 14)} To Presentation</button>` +
        `<button class="tool-img-btn" onclick="OC.downloadUrl('${url}', '${fname.replace(/'/g, "\\'")}')">${icon('save', 14)} Save SVG</button>` +
        `<button class="tool-img-btn" onclick="OC.viewSvgCode('${url}','${fname.replace(/'/g, "\\'")}')">${icon('code', 14)} View Code</button>` +
        `</div>` +
        `<div class="svg-preview-container" id="${svgId}" ` +
        `onclick="OC.openLightbox('${url}', '${label.replace(/'/g, "\\'")}', '${fname.replace(/'/g, "\\'")}')" ` +
        `style="background:var(--bg-secondary);border-radius:8px;padding:16px;margin:8px 0;display:flex;align-items:center;justify-content:center;min-height:120px;box-shadow:0 4px 20px rgba(0,0,0,0.4);cursor:zoom-in;">` +
        `<img src="${url}" alt="${escHtml(label)}" style="max-width:100%;max-height:300px;" ` +
        `onerror="this.parentElement.innerHTML='<div style=&quot;color:var(--text-muted);&quot;>️ SVG loading error</div>'" />` +
        `</div>` +
        `<div class="tool-result-meta" style="font-size:12px;color:var(--text-muted);margin-top:4px;">` +
        `<span style="background:linear-gradient(135deg,#7c3aed,#2563eb);color:#fff;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;margin-right:6px;">SVG</span>` +
        ` ${escHtml(fname)}</div>` +
        `</div>`
      );
    });
    // Images: ![alt](url)
    h = h.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (m, alt, url) => {
      const escapedAlt = alt.replace(/'/g, "\\'");
      return `<img src="${url}" alt="${alt}" style="max-width:100%;border-radius:8px;margin:8px 0;cursor:zoom-in;" onclick="OC.openLightbox('${url}', '${escapedAlt}', 'image')">`;
    });
    // Links: [text](url)
    h = h.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:underline;text-underline-offset:2px">$1</a>');
    // Auto-link bare URLs (skip those already inside href="..." or markdown [](url))
    h = h.replace(/(^|[^"(=])(\bhttps?:\/\/[^\s<>&)\]"]+)/g, (m, pre, url) => {
      // Trim trailing punctuation
      const clean = url.replace(/[.,;:!?)]+$/, '');
      return pre + `<a href="${clean}" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:underline;text-underline-offset:2px">${clean}</a>`;
    });
    h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
    h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/\*(.+?)\*/g, '<em>$1</em>');
    // Horizontal rules
    h = h.replace(/^---+$/gm, '<hr>');
    // Headings with id attributes for ToC anchor navigation
    h = h.replace(/^### (.+)$/gm, (_, title) => {
      const anchor = title.toLowerCase().replace(/[^\w]+/g, '-').replace(/^-|-$/g, '');
      return `<h4 id="${anchor}">${title}</h4>`;
    });
    h = h.replace(/^## (.+)$/gm, (_, title) => {
      const anchor = title.toLowerCase().replace(/[^\w]+/g, '-').replace(/^-|-$/g, '');
      return `<h3 id="${anchor}">${title}</h3>`;
    });
    h = h.replace(/^# (.+)$/gm, (_, title) => {
      const anchor = title.toLowerCase().replace(/[^\w]+/g, '-').replace(/^-|-$/g, '');
      return `<h2 id="${anchor}">${title}</h2>`;
    });
    // Blockquotes (> lines — group consecutive > lines into a single blockquote)
    h = h.replace(/^&gt; (.+)$/gm, '<bq-line>$1</bq-line>');
    h = h.replace(/((?:<bq-line>[\s\S]*?<\/bq-line>\s*)+)/g, m => {
      const inner = m.replace(/<\/?bq-line>/g, '').trim();
      return ph('<blockquote>' + inner + '</blockquote>');
    });
    // Numbered lists (1. 2. 3. etc.)
    h = h.replace(/^(\d+)\. (.+)$/gm, '<li value="$1">$2</li>');
    h = h.replace(/((?:<li value="\d+">[\s\S]*?<\/li>\s*)+)/g, m => '<ol>' + m + '</ol>');
    // Unordered lists (- item)
    h = h.replace(/^[\-\*] (.+)$/gm, '<li class="ul-item">$1</li>');
    h = h.replace(/((?:<li class="ul-item">[\s\S]*?<\/li>\s*)+)/g, m => {
      return '<ul>' + m.replace(/ class="ul-item"/g, '') + '</ul>';
    });

    // ---- Phase 3: Convert remaining newlines to <br> (block content is safe) ----
    // Double newlines → paragraph break with spacing
    h = h.replace(/\n\n+/g, '<br><div style="margin-top:8px"></div>');
    h = h.replace(/\n/g, '<br>');
    // Clean spurious <br> before/after block elements
    h = h.replace(/<br>\s*(<\/?(?:ul|ol|li|h[2-4]|img|hr|blockquote|div|details|summary))/g, '$1');
    h = h.replace(/(<\/(?:ul|ol|li|h[2-4]|blockquote|div|details|summary)>)\s*<br>/g, '$1');

    // ---- Phase 4: Restore block placeholders ----
    h = h.replace(/\x00BLK(\d+)\x00/g, (_, i) => blocks[parseInt(i)]);

    // ---- Phase 5: Restore structured UI placeholders (from Phase 0) ----
    h = h.replace(/\x00SUI(\d+)\x00/g, (_, i) => _suiBlocks[parseInt(i)]);

    return h;
  }

  // Apply highlight.js to code blocks after render
  // When a scope element is provided, only highlight within that element
  // to avoid re-scanning the entire document during streaming.
  function highlightAll(scope) {
    if (window.hljs) {
      const root = scope || document;
      root.querySelectorAll('pre code').forEach(b => {
        const pre = b.parentElement;
        if (pre && pre.id === 'code-highlight') return; // Skip editor

        if (!b.dataset.highlighted) {
          hljs.highlightElement(b);
          // Add line numbers
          const lines = b.innerHTML.split('\n');
          if (lines[lines.length - 1] === '') lines.pop(); // Remove trailing empty line
          b.innerHTML = lines.map(line => `<span class="ln"></span>${line}`).join('\n');
        }
      });
    }
  }

  // ---- ZIP builder (pure JS — STORE method, no compression) ----
  const Zip = {
    _t: null,
    _crcT() {
      if (this._t) return this._t;
      const t = new Uint32Array(256);
      for (let i = 0; i < 256; i++) { let c = i; for (let j = 0; j < 8; j++)c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[i] = c; }
      return (this._t = t);
    },
    _crc(d) { const t = this._crcT(); let c = 0xFFFFFFFF; for (let i = 0; i < d.length; i++)c = t[(c ^ d[i]) & 0xFF] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; },
    build(files) {
      const enc = new TextEncoder(), entries = files.map(f => ({ name: enc.encode(f.path), data: enc.encode(f.content) }));
      const parts = [], cd = []; let off = 0;
      entries.forEach(e => {
        const crc = this._crc(e.data), h = new Uint8Array(30 + e.name.length), v = new DataView(h.buffer);
        v.setUint32(0, 0x04034b50, true); v.setUint16(4, 20, true); v.setUint16(8, 0, true); v.setUint32(14, crc, true);
        v.setUint32(18, e.data.length, true); v.setUint32(22, e.data.length, true); v.setUint16(26, e.name.length, true);
        h.set(e.name, 30); parts.push(h, e.data);
        const c = new Uint8Array(46 + e.name.length), cv = new DataView(c.buffer);
        cv.setUint32(0, 0x02014b50, true); cv.setUint16(4, 20, true); cv.setUint16(6, 20, true); cv.setUint16(8, 0, true);
        cv.setUint32(16, crc, true); cv.setUint32(20, e.data.length, true); cv.setUint32(24, e.data.length, true);
        cv.setUint16(28, e.name.length, true); cv.setUint32(42, off, true); c.set(e.name, 46); cd.push(c); off += h.length + e.data.length;
      });
      const cdOff = off; let cdSz = 0; cd.forEach(c => { parts.push(c); cdSz += c.length; });
      const end = new Uint8Array(22), ev = new DataView(end.buffer);
      ev.setUint32(0, 0x06054b50, true); ev.setUint16(8, entries.length, true); ev.setUint16(10, entries.length, true);
      ev.setUint32(12, cdSz, true); ev.setUint32(16, cdOff, true); parts.push(end);
      return new Blob(parts, { type: 'application/zip' });
    }
  };
  window.Zip = Zip;
  window.renderMd = renderMd;
  window.highlightAll = highlightAll;

  // ---- File Tree ----
  class FileTree {
    constructor(el) { this.el = el; this.files = new Map(); this.active = null; this.collapsed = new Set(); this.render(); }
    add(p, c) { this.files.set(p, c); this.render(); }
    remove(p) { this.files.delete(p); if (this.active === p) this.active = null; this.render(); }
    get(p) { return this.files.get(p) || ''; }
    update(p, c) { this.files.set(p, c); }
    clear() { this.files.clear(); this.active = null; this.collapsed.clear(); this.render(); }
    select(p) {
      this.active = p; this.render();
      // Open file viewer modal
      OC.viewFile(p, this.files.get(p));
    }
    icon(p) {
      const ext = p.split('.').pop().toLowerCase();
      const codeExts = ['py', 'js', 'ts', 'html', 'htm', 'css', 'json', 'sh', 'bash', 'sql', 'java', 'cpp', 'c', 'go', 'rs', 'rb', 'php', 'xml', 'svg', 'yaml', 'yml', 'toml', 'ini', 'dockerfile'];
      const textExts = ['txt', 'md', 'log', 'csv', 'env', 'cfg'];
      const imageExts = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'ico', 'svg'];
      if (imageExts.includes(ext)) return '️';
      if (codeExts.includes(ext)) return icon('code');
      if (textExts.includes(ext)) return '';
      return '◻️';
    }
    // Build a directory tree structure from flat file paths
    _buildTree() {
      const tree = {};
      [...this.files.keys()].sort().forEach(p => {
        const parts = p.split('/');
        let node = tree;
        for (let i = 0; i < parts.length - 1; i++) {
          const dir = parts[i];
          if (!node[dir]) node[dir] = {};
          node = node[dir];
        }
        node['__file__' + parts[parts.length - 1]] = p;
      });
      return tree;
    }
    _renderNode(node, parentPath, depth) {
      const entries = Object.entries(node).sort(([a, va], [b, vb]) => {
        const aIsDir = typeof va === 'object' && !a.startsWith('__file__');
        const bIsDir = typeof vb === 'object' && !b.startsWith('__file__');
        if (aIsDir !== bIsDir) return aIsDir ? -1 : 1;
        return a.localeCompare(b);
      });
      entries.forEach(([key, val]) => {
        if (key.startsWith('__file__')) {
          // File entry
          const fname = key.slice(8); // remove '__file__' prefix
          const fullPath = val;
          const indent = depth * 16;
          const item = el('div', {
            class: 'file-tree-item' + (this.active === fullPath ? ' active' : ''),
            style: `padding-left: ${16 + indent}px`,
            onclick: () => this.select(fullPath)
          }, [
            el('span', { class: 'file-icon', html: this.icon(fname) }),
            el('span', { class: 'file-name', text: fname }),
            el('span', { class: 'file-delete icon-btn', text: '', onclick: e => { e.stopPropagation(); this.remove(fullPath); } })
          ]);
          this.el.appendChild(item);
        } else {
          // Directory entry
          const dirPath = parentPath ? parentPath + '/' + key : key;
          const isCollapsed = this.collapsed.has(dirPath);
          const indent = depth * 16;
          const dirEl = el('div', {
            class: 'file-tree-dir' + (isCollapsed ? '' : ' open'),
            style: `padding-left: ${12 + indent}px`,
            onclick: () => {
              if (this.collapsed.has(dirPath)) this.collapsed.delete(dirPath);
              else this.collapsed.add(dirPath);
              this.render();
            }
          }, [
            el('span', { class: 'dir-arrow', text: '►' }),
            el('span', { class: 'dir-icon', html: isCollapsed ? icon('folder') : icon('folderOpen') }),
            el('span', { class: 'dir-name', text: key })
          ]);
          this.el.appendChild(dirEl);
          if (!isCollapsed) {
            this._renderNode(val, dirPath, depth + 1);
          }
        }
      });
    }
    render() {
      this.el.innerHTML = '';
      if (!this.files.size) { this.el.innerHTML = '<div class="file-tree-empty">AI-generated files will appear here</div>'; return; }
      // Check if any files have directory paths
      const hasSubDirs = [...this.files.keys()].some(p => p.includes('/'));
      if (hasSubDirs) {
        const tree = this._buildTree();
        this._renderNode(tree, '', 0);
      } else {
        // Simple flat list (no directories)
        [...this.files.keys()].sort().forEach(p => {
          const item = el('div', { class: 'file-tree-item' + (this.active === p ? ' active' : ''), onclick: () => this.select(p) }, [
            el('span', { class: 'file-icon', html: this.icon(p) }),
            el('span', { class: 'file-name', text: p }),
            el('span', { class: 'file-delete icon-btn', text: '', onclick: e => { e.stopPropagation(); this.remove(p); } })
          ]);
          this.el.appendChild(item);
        });
      }
    }
    exportZip() {
      if (!this.files.size) { toast('No files to export'); return; }
      const fs = [...this.files.entries()].map(([p, c]) => ({ path: p, content: c }));
      const blob = Zip.build(fs), url = URL.createObjectURL(blob);
      const a = el('a', { href: url, download: 'clawzd_project.zip' });
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
      toast(icon('download') + ' ZIP exported!');
    }
    async transferToEditor() {
      if (!this.files.size) { toast('No files to transfer'); return; }
      // Suggest a project name based on session or timestamp
      const defaultName = 'project-' + new Date().toISOString().slice(0, 10).replace(/-/g, '');
      const projectName = prompt('Project folder name in workspace:', defaultName);
      if (!projectName || !projectName.trim()) return;

      const files = [...this.files.entries()]
        .filter(([, c]) => !c.startsWith('[Generated image:') && !c.startsWith('[Generated SVG:'))
        .map(([p, c]) => ({ path: p, content: c }));

      if (!files.length) { toast('No transferable files'); return; }

      try {
        const resp = await fetch('/workspace/transfer', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project: projectName.trim(), files }),
        });
        const data = await resp.json();
        if (!resp.ok) { toast(' ' + (data.detail || 'Transfer failed')); return; }

        toast(icon('check') + ` ${data.written} file(s) transferred to ${data.project}`);

        // Switch to Editor mode and select the project
        $$('#mode-toggle .mode-btn').forEach(b => b.classList.remove('active'));
        const editorBtn = document.querySelector('#mode-toggle .mode-btn[data-mode="editor"]');
        if (editorBtn) editorBtn.classList.add('active');
        window.editor.toggle(true);
        if (window.mediaStudio) window.mediaStudio.toggle(false);

        // Wait for projects to load, then select the new project
        await window.editor.loadProjects();
        const select = $('#project-select');
        if (select) {
          select.value = data.project;
          select.dispatchEvent(new Event('change'));
        }
      } catch (e) {
        toast(' Transfer error: ' + e.message);
      }
    }
  }

  // ---- Chat Manager ----
  class Chat {
    constructor() {
      this.msgEl = $('#chat-messages'); this.inputEl = $('#chat-input');
      this.sendBtn = $('#chat-send'); this.stopBtn = $('#chat-stop'); this.sessionId = null;
      this.es = null; this.streaming = false; this.bubble = null; this.text = '';
      this.fileTree = null;
      // WebSocket transport (preferred) with SSE fallback
      this.transport = null;
      // Token tracking
      this.tokensSent = 0;
      this.tokensReceived = 0;
      // Streaming parser (incremental rendering — replaces throttled full re-render)
      this._streamParser = null;
      // Legacy throttle fallback (kept for edge cases)
      this._renderPending = false;
      this._renderTimer = null;
      this.sendBtn.addEventListener('click', () => this.send());
      if (this.stopBtn) this.stopBtn.addEventListener('click', () => this.stopGeneration());
      this.inputEl.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.send(); } });
      this.inputEl.addEventListener('input', () => this.resize());
    }
    resize() { this.inputEl.style.height = 'auto'; this.inputEl.style.height = Math.min(this.inputEl.scrollHeight, 150) + 'px'; }
    async newSession() {
      // Reset UI to welcome state — no server session created until first message
      this.sessionId = null;
      if (this.es) { this.es.close(); this.es = null; }
      if (this.transport) { this.transport.disconnect(); this.transport = null; }
      this.msgEl.innerHTML = '';
      if (this.fileTree) this.fileTree.clear();
      // Reset token counters
      if (window.tokenTracker) window.tokenTracker.reset();
      this.showWelcome();
      this.status('connected');
      loadSessions();
    }
    async loadSession(id) {
      try {
        const r = await fetch(`/chat/sessions/${id}`); const d = await r.json();
        this.sessionId = id; this.msgEl.innerHTML = '';
        // Clear files from previous session
        if (this.fileTree) this.fileTree.clear();
        if (d.messages && d.messages.length) {
          d.messages.forEach(m => {
            const meta = m.metadata || {};
            if (m.id) meta._msgId = m.id;  // For branch fork support
            const bubble = this.addMsg(m.role, m.content, meta);
            if (m.timestamp === 'in-progress') {
              this.streaming = true;
              this.text = m.content;
              this.bubble = bubble;
              this.status('streaming');
            }
          });
          // Extract files from all assistant messages of this session
          d.messages.filter(m => m.role === 'assistant').forEach(m => this.extractFiles(m.content));
          highlightAll();
        }
        else { this.showWelcome(); }
        this.connectSSE(); this.status('connected'); loadSessions();
        if (window.branchManager) window.branchManager.setSession(id);
      } catch (e) { console.error(e); toast('Failed to load session'); }
    }
    connectSSE() {
      // Prefer WebSocket transport if available
      if (window.ChatTransport) {
        if (this.transport) this.transport.disconnect();
        this.transport = new ChatTransport(this.sessionId);
        this.transport.onToken = (tok) => this.handleToken(tok);
        this.transport.onDone = () => this.handleToken('[DONE]');
        this.transport.onError = (err) => { console.error('[WS]', err); this.handleToken('[DONE]'); };
        this.transport.connect();
        return;
      }
      // Legacy SSE fallback
      if (this.es) this.es.close();
      this.es = new EventSource(`/stream/${this.sessionId}`);
      this.es.onmessage = e => this.handleToken(e.data);
      this.es.onerror = () => { };
    }
    handleToken(tok) {
      if (!this.streaming) {
        this.streaming = true; this.text = ''; this.bubble = this.addMsg('assistant', ''); this.status('streaming');
        if (this.stopBtn) { this.stopBtn.style.display = ''; this.sendBtn.style.display = 'none'; }
        // StreamingParser v2 — hybrid approach:
        // Uses lightweight livePreview during streaming, then full renderMd on finish()
        if (window.StreamingParser && this.bubble) {
          this._streamParser = new StreamingParser(this.bubble, { showCursor: true });
        }
      }
      if (tok === '[DONE]') {
        // Cancel any pending throttled render and do a final render in finish()
        if (this._renderTimer) { clearTimeout(this._renderTimer); this._renderTimer = null; }
        this._renderPending = false;
        this.finish(); return;
      }
      // Intercept suggestion chips from SSE stream
      if (window.ChatEnhancements && tok.includes('__SUGGESTIONS__')) {
        this._pendingSuggestions = window.ChatEnhancements.extractSuggestions(tok);
        return; // Don't append suggestions marker to visible text
      }
      // Intercept todo plan updates from SSE stream (Claude Code TodoWriteTool pattern)
      if (window.ChatEnhancements && tok.includes('__TODO_UPDATE__')) {
        const todoData = window.ChatEnhancements.parseTodoUpdate(tok);
        if (todoData) {
          window.ChatEnhancements.renderTodoPanel(todoData);
          return; // Don't append todo marker to visible text
        }
      }
      this.text += tok;
      if (window.tokenTracker) window.tokenTracker.addOutput(1);

      // ---- Incremental streaming parser (OpenUI-inspired) ----
      // Replaces the old throttled full re-render that rebuilt all HTML every 150ms.
      // The StreamingParser maintains a block-level AST and only updates dirty blocks.
      if (this._streamParser) {
        this._streamParser.pushToken(tok);
        return; // Skip legacy rendering path
      }

      // ---- Legacy fallback (if StreamingParser not available) ----
      if (!this._renderPending) {
        this._renderPending = true;
        this._renderTimer = setTimeout(() => {
          this._renderPending = false;
          this._renderTimer = null;
          if (!this.bubble) return;

          // Capture scroll state before modifying DOM
          const isAtBottom = this.msgEl.scrollHeight - this.msgEl.scrollTop - this.msgEl.clientHeight < 50;

          // Capture open details state before re-render
          const openDetails = [];
          this.bubble.querySelectorAll('details').forEach((d, i) => {
            if (d.hasAttribute('open')) openDetails.push(i);
          });

          // Auto-close unclosed code fences for live preview
          let preview = this.text;
          const fenceCount = (preview.match(/```/g) || []).length;
          if (fenceCount % 2 !== 0) preview += '\n```';
          this.bubble.innerHTML = renderMd(preview) + '<span class="streaming-cursor"></span>';

          // Restore open details
          if (openDetails.length > 0) {
            this.bubble.querySelectorAll('details').forEach((d, i) => {
              if (openDetails.includes(i)) d.setAttribute('open', '');
            });
          }

          if (isAtBottom) {
            this.msgEl.scrollTop = this.msgEl.scrollHeight;
          }
          // Scope highlight to current bubble only (avoid scanning entire DOM)
          if (typeof highlightAll === 'function') highlightAll(this.bubble);
        }, 150);
      }
    }
    finish() {
      this.streaming = false;

      // Handle Auto-Plan workflow
      if (this.autoPlanState === 'planning') {
        const capturedPlan = this.text;

        if (this.bubble) {
          const safeHtml = renderMd(capturedPlan);
          this.bubble.innerHTML = `
            <details class="tool-thinking" open>
              <summary><em>🧠 Auto-Planning Phase</em></summary>
              <div style="padding:10px">${safeHtml}</div>
            </details>
            <div class="auto-plan-confirm" style="margin-top:10px; display:flex; gap:10px; padding: 10px; background: var(--bg-secondary); border-radius: 8px;">
              <button class="btn primary confirm-build-btn" style="flex: 1;">${icon('check', 14)} Validate and Launch Generation</button>
              <button class="btn cancel-build-btn" style="flex: 1;">${icon('x', 14)} Annuler</button>
            </div>
          `;

          const confirmBtn = this.bubble.querySelector('.confirm-build-btn');
          const cancelBtn = this.bubble.querySelector('.cancel-build-btn');
          const btnContainer = this.bubble.querySelector('.auto-plan-confirm');

          confirmBtn.addEventListener('click', async () => {
            this.autoPlanState = 'building';
            confirmBtn.disabled = true;
            cancelBtn.style.display = 'none';
            confirmBtn.innerHTML = '⏳ Work in progress...';

            toast('Starting...');
            const buildMsg = `[Auto-Generated Implementation Plan:\n${capturedPlan}]\n\nPlease execute and build the code for this plan exactly as described. Output ONLY the code and required actions.`;

            try {
              // Drop context by generating a new session id
              const r = await fetch('/chat/new', {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
                  provider: $('#provider-select').value, model: $('#model-select').value, preprompt: this.originalPreprompt || 'developer'
                })
              });
              const d = await r.json();
              this.sessionId = d.id;
              if (window.tokenTracker) window.tokenTracker.setSession(d.id);
              this.connectSSE();

              await fetch(`/send/${this.sessionId}`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  message: buildMsg,
                  provider: $('#provider-select').value,
                  model: $('#model-select').value,
                  preprompt: this.originalPreprompt || 'developer'
                })
              });
              btnContainer.remove();
            } catch (e) { toast(icon('x', 14) + ' Build phase error'); this.sendBtn.disabled = false; }
          });

          cancelBtn.addEventListener('click', () => {
            btnContainer.remove();
            this.autoPlanState = null;
            toast('Cancelled.');
          });
        }

        this.bubble = null;
        this.text = '';
        this.status('connected');
        return; // wait for next stream
      }

      if (this.autoPlanState === 'building') {
        this.autoPlanState = null;
        toast(ICONS.check(14) + ' Auto-Plan & Build Complete');
      }

      if (this.bubble) {
        // Finalize streaming parser if it was used
        if (this._streamParser) {
          this._streamParser.finish();
          // Use the parser's accumulated text for file extraction
          const text = this._streamParser.getText() || this.text;
          this.extractFiles(text);
          this._streamParser = null;
        } else {
          // Legacy path: full re-render
          let text = this.text;
          const fenceCount = (text.match(/```/g) || []).length;
          if (fenceCount % 2 !== 0) text += '\n```';
          this.bubble.innerHTML = renderMd(text);
          this.extractFiles(text);
          highlightAll(this.bubble);
        }
        // NOTE: Tool calls are now executed server-side in the agent loop
        // (gateway.py generate()). Do NOT re-execute them client-side.
        // this.executeToolCalls(text, this.bubble);
      }
      this.bubble = null; this.text = ''; this.status('connected'); this.sendBtn.disabled = false;
      if (this.stopBtn) { this.stopBtn.style.display = 'none'; this.sendBtn.style.display = ''; }
      loadSessions();
      if (window.editor) window.editor.loadTree();

      // Render Roo Code-inspired enhancements
      if (window.ChatEnhancements) {
        // Suggestion chips
        if (this._pendingSuggestions) {
          window.ChatEnhancements.renderSuggestionChips(this._pendingSuggestions, this);
          this._pendingSuggestions = null;
        }
        // Mode switch hint detection
        const lastBubble = document.querySelector('#chat-messages .msg-row.assistant:last-child .msg-bubble');
        if (lastBubble) window.ChatEnhancements.renderModeSwitchHint(lastBubble.textContent || '');
      }
    }
    async executeToolCalls(text, bubble) {
      // Find all ```tool_call or ```tool blocks in the response
      const re = /```(?:tool_call|tool)\n([\s\S]*?)```/g;
      let match;
      while ((match = re.exec(text)) !== null) {
        try {
          const call = JSON.parse(match[1].trim());
          const tool = call.tool;
          const params = call.params || {};
          console.log('[Clawzd] Auto-executing tool:', tool, params);

          // Map tool name to API endpoint
          const TOOL_ENDPOINTS = {
            'screenshot_remote': { url: '/screenshot/remote', method: 'POST' },
            'screenshot_local': { url: '/screenshot/local', method: 'POST' },
            'generate_image': { url: '/image/generate', method: 'POST' },
            'search_web': { url: '/web/search', method: 'POST' },
            'execute_python': { url: '/api/execute', method: 'POST' },
            'run_command': { url: '/local/run', method: 'POST' },
            'browse_web': { url: '/browser/navigate', method: 'POST' },
            'audit_code': { url: '/quality/audit', method: 'POST' },
            'rag_search': { url: '/rag/search', method: 'POST' },
          };

          const endpoint = TOOL_ENDPOINTS[tool];
          if (!endpoint) { console.warn('[Clawzd] Unknown tool:', tool); continue; }

          // Show loading indicator in chat
          const loader = document.createElement('div');
          loader.className = 'tool-call-status';
          loader.innerHTML = `<div class="tool-loader"><span class="tool-spinner"></span> Executing <strong>${escHtml(tool)}</strong>...</div>`;
          bubble.appendChild(loader);

          const resp = await fetch(endpoint.url, {
            method: endpoint.method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params),
          });
          const result = await resp.json();

          // Replace loader with result
          if (result.base64 && (tool === 'screenshot_remote' || tool === 'screenshot_local' || tool === 'generate_image')) {
            const imgId = 'img-' + Date.now();
            const fname = result.filename || `${tool}_${Date.now()}.png`;
            const dataUrl = `data:image/png;base64,${result.base64}`;

            loader.innerHTML = `
              <div class="tool-result-image">
                <div class="tool-img-toolbar">
                  <button class="tool-img-btn" data-action="zoom" title="Agrandir">${icon('search', 14)} Zoom</button>
                  <button class="tool-img-btn" data-action="save" title="Sauvegarder">${icon('save', 14)} Save</button>
                </div>
                <img id="${imgId}" src="${dataUrl}" alt="${escHtml(tool)}" style="max-width:100%;border-radius:8px;margin:8px 0;box-shadow:0 4px 20px rgba(0,0,0,0.4);cursor:zoom-in;">
              </div>`;
            if (result.url) loader.innerHTML += `<div class="tool-result-meta"> ${escHtml(result.url)}</div>`;

            // Zoom lightbox — click image or zoom button
            const openLightbox = () => {
              const overlay = document.createElement('div');
              overlay.className = 'lightbox-overlay';
              overlay.innerHTML = `
                <div class="lightbox-toolbar">
                  <button class="lightbox-btn" data-action="save">${icon('save', 14)} Sauvegarder</button>
                  <button class="lightbox-btn lightbox-close">${icon('x', 14)}</button>
                </div>
                <img src="${dataUrl}" alt="Screenshot" class="lightbox-img">`;
              overlay.addEventListener('click', (e) => {
                if (e.target === overlay || e.target.classList.contains('lightbox-close')) overlay.remove();
                if (e.target.dataset?.action === 'save') {
                  const a = document.createElement('a'); a.href = dataUrl; a.download = fname; a.click();
                }
              });
              document.body.appendChild(overlay);
            };

            const imgEl = loader.querySelector(`#${imgId}`);
            if (imgEl) imgEl.addEventListener('click', openLightbox);

            // Toolbar buttons
            loader.querySelectorAll('.tool-img-btn').forEach(btn => {
              btn.addEventListener('click', () => {
                if (btn.dataset.action === 'zoom') openLightbox();
                if (btn.dataset.action === 'save') {
                  const a = document.createElement('a'); a.href = dataUrl; a.download = fname; a.click();
                }
              });
            });

            // Register in file tree
            if (this.fileTree) {
              this.fileTree.add(fname, `[Screenshot: ${result.url || 'local'}]\nBase64 image — ${(result.base64.length / 1024).toFixed(0)} KB`);
            }

          } else if (result.error) {
            loader.innerHTML = `<div class="tool-result-error">${icon('x', 14)} <strong>${escHtml(tool)}</strong>: ${escHtml(result.error || result.detail || 'Unknown error')}</div>`;
          } else {
            // Generic JSON result
            loader.innerHTML = `<div class="tool-result-json"><pre><code>${escHtml(JSON.stringify(result, null, 2))}</code></pre></div>`;
          }
        } catch (e) {
          console.error('[Clawzd] Tool execution error:', e);
        }
      }
    }
    extractFiles(t) {
      if (!this.fileTree) return;

      // Extract generated images from __IMG__ markers and add to file tree
      const imgRe = /__IMG__([^|]+)\|([^|]+)\|(.+?)__IMG__/g;
      let imgMatch;
      while ((imgMatch = imgRe.exec(t)) !== null) {
        const [, url, label, fname] = imgMatch;
        if (fname && !this.fileTree.files.has(fname)) {
          this.fileTree.add(fname, `[Generated image: ${label}]\nURL: ${url}`);
        }
      }

      // Extract generated SVGs from __SVG__ markers and add to file tree
      const svgRe = /__SVG__([^|]+)\|([^|]+)\|(.+?)__SVG__/g;
      let svgMatch;
      while ((svgMatch = svgRe.exec(t)) !== null) {
        const [, url, label, fname] = svgMatch;
        if (fname && !this.fileTree.files.has(fname)) {
          this.fileTree.add(fname, `[Generated SVG: ${label}]\nURL: ${url}`);
        }
      }

      // Extract file edits from __FILE_EDIT__ markers and sync IDE
      const editRe = /__FILE_EDIT__({.+?})__/g;
      let editMatch;
      while ((editMatch = editRe.exec(t)) !== null) {
        try {
          const editData = JSON.parse(editMatch[1]);
          if (editData.path && window.editor && window.editor.active) {
            // Only trigger if we are in IDE mode
            window.editor.loadTree().then(() => {
              window.editor.openFile(editData.path).then(() => {
                if (editData.diff) {
                  window.editor.highlightDiff(editData.path, editData.diff);
                }
              });
            });
          }
        } catch (e) { console.error('Failed to parse file edit marker', e); }
      }

      // ---- Parse directory tree listings (├──, └──) to build expected file map ----
      const treeFiles = [];
      const treeRe = /^[\s│]*[├└]──\s+(.+)$/gm;
      let treeMatch;
      const treeParts = [];
      while ((treeMatch = treeRe.exec(t)) !== null) {
        treeParts.push({ text: treeMatch[1].trim(), pos: treeMatch.index, fullLine: treeMatch[0] });
      }
      // Build paths from tree indentation
      if (treeParts.length > 0) {
        const treeLines = t.split('\n');
        const pathStack = [];
        for (const line of treeLines) {
          const tm = line.match(/^([\s│]*)[├└]──\s+(.+)$/);
          if (!tm) continue;
          const indent = tm[1].replace(/[│]/g, ' ').length;
          const name = tm[2].trim().replace(/\s*#.*$/, ''); // remove inline comments
          const depth = Math.floor(indent / 4); // 4-char indent per level
          pathStack.length = depth;
          pathStack[depth] = name;
          // Only register files (contain a dot and don't end with /)
          if (name.includes('.') && !name.endsWith('/')) {
            treeFiles.push(pathStack.join('/'));
          }
        }
      }

      // Language → default extension mapping
      const extMap = {
        python: 'py', py: 'py', javascript: 'js', js: 'js', typescript: 'ts', ts: 'ts',
        html: 'html', htm: 'html', css: 'css', json: 'json', yaml: 'yml', yml: 'yml',
        sh: 'sh', bash: 'sh', sql: 'sql', java: 'java', cpp: 'cpp', c: 'c',
        go: 'go', rust: 'rs', ruby: 'rb', php: 'php', markdown: 'md', md: 'md',
        xml: 'xml', svg: 'svg', toml: 'toml', ini: 'ini', dockerfile: 'Dockerfile'
      };
      // Track used names to avoid duplicates
      const used = new Set([...this.fileTree.files.keys()]);
      const extracted = new Set(); // track positions already handled
      let m;

      // 1. Explicit filenames: ```lang:filename OR ```lang filename (with path)
      const r1 = /```(\w+)(?::|\s)([\w.\/-][^\n]*?\.[\w]+)\n([\s\S]*?)```/g;
      while ((m = r1.exec(t)) !== null) {
        const fname = m[2].trim();
        if (fname && !used.has(fname)) { this.fileTree.add(fname, m[3]); used.add(fname); extracted.add(m.index); }
      }

      // 2. Comment-based filenames: first line has # file: xxx, // file: xxx, /* file: xxx */, etc.
      const r2 = /```(\w+)\n(?:#|\/{2}|\*|\/\*)\s*(?:file|filename|File|example-file|example_file)[:\s]+([^\n*\/]+)/g;
      while ((m = r2.exec(t)) !== null) {
        if (extracted.has(m.index)) continue;
        let fname = m[2].trim().replace(/\*\/\s*$/, '').trim();
        if (fname) {
          const codeRe = new RegExp('```' + m[1] + '\\n([\\s\\S]*?)```', 'g');
          codeRe.lastIndex = m.index;
          const cm = codeRe.exec(t);
          if (cm && !used.has(fname)) {
            this.fileTree.add(fname, cm[1].trim());
            used.add(fname);
            extracted.add(m.index);
          }
        }
      }

      // 3. Auto-extract: any code block with a known language
      const r3 = /```(\w+)\n([\s\S]*?)```/g;
      let fileCount = 0;
      while ((m = r3.exec(t)) !== null) {
        if (extracted.has(m.index)) { fileCount++; continue; }
        const lang = m[1].toLowerCase();
        const code = m[2];
        if (!code.trim() || code.trim().length < 20) continue;
        const ext = extMap[lang];
        if (!ext) continue;

        let fname = null;
        const firstLine = code.split('\n')[0].trim();
        const commentFileRe = /^(?:#|\/{2}|\*|\/\*)\s*(?:file[:\s]+)?([\w.\/-]+\.\w+)/i;
        const cfm = firstLine.match(commentFileRe);
        if (cfm) {
          fname = cfm[1].replace(/\*\/\s*$/, '').trim();
        }

        // Try to detect filename from markdown text BEFORE this code block
        if (!fname) {
          const preceding = t.substring(Math.max(0, m.index - 300), m.index);
          const contextPatterns = [
            /[`*]{1,2}([\w.\/-]+\.\w+)[`*]{1,2}\s*(?::|\n|$)/,
            /(?:file|create\s+(?:the\s+)?(?:file\s+)?)[:\s]*[`*]?([\w.\/-]+\.\w+)[`*]?\s*$/i,
            /(?:file)\s*:\s*[`*]?([\w.\/-]+\.\w+)/i,
            /([\w.\/-]+\.\w+)\s*:\s*$/,
          ];
          for (const pat of contextPatterns) {
            const cm2 = preceding.match(pat);
            if (cm2) {
              const candidate = cm2[1].trim();
              const candExt = candidate.split('.').pop().toLowerCase();
              if (candExt === ext || extMap[candExt] === ext || (ext === 'py' && candExt === 'py') || (ext === 'js' && candExt === 'js')) {
                fname = candidate;
                break;
              }
              if (candidate.includes('/')) {
                fname = candidate;
                break;
              }
            }
          }
        }

        // Try to match against tree-listed files by extension
        if (!fname && treeFiles.length > 0) {
          const matchingTreeFiles = treeFiles.filter(tf => {
            const tfExt = tf.split('.').pop().toLowerCase();
            return tfExt === ext && !used.has(tf);
          });
          if (matchingTreeFiles.length === 1) {
            fname = matchingTreeFiles[0];
          } else if (matchingTreeFiles.length > 1) {
            const classRe = /^class\s+(\w+)/m;
            const classMatch = code.match(classRe);
            if (classMatch) {
              const className = classMatch[1].toLowerCase().replace(/([A-Z])/g, (m2, c, i) => (i ? '_' : '') + c.toLowerCase());
              const best = matchingTreeFiles.find(tf => tf.toLowerCase().includes(className));
              if (best) fname = best;
            }
            if (!fname) fname = matchingTreeFiles[0];
          }
        }

        if (!fname) {
          const classRe = /^class\s+(\w+)/m;
          const funcRe = /^(?:def|function|const|let|var)\s+(\w+)/m;
          const classMatch = code.match(classRe);
          const funcMatch = code.match(funcRe);
          if (classMatch) {
            fname = classMatch[1].replace(/([A-Z])/g, (m2, c, i) => (i ? '_' : '') + c.toLowerCase()) + '.' + ext;
          } else if (funcMatch && ext !== 'html' && ext !== 'css') {
            fname = funcMatch[1] + '.' + ext;
          } else {
            let base = ext === 'html' ? 'index' : ext === 'css' ? 'style' : ext === 'js' ? 'script' : ext === 'md' ? 'README' : 'main';
            fname = base + '.' + ext;
          }
        }

        let finalName = fname;
        let n = 1;
        while (used.has(finalName)) {
          const dot = fname.lastIndexOf('.');
          if (dot > 0) {
            finalName = fname.slice(0, dot) + '_' + (++n) + fname.slice(dot);
          } else {
            finalName = fname + '_' + (++n);
          }
        }
        this.fileTree.add(finalName, code);
        used.add(finalName);
        fileCount++;
      }

      if (fileCount > 0) {
        $$('.sidebar-tab').forEach(t => t.classList.remove('active'));
        $$('.sidebar-panel').forEach(p => p.classList.remove('active'));
        const ftab = $('#tab-files');
        if (ftab) { ftab.classList.add('active'); }
        const fpanel = $('#panel-files');
        if (fpanel) { fpanel.classList.add('active'); }
        toast(`${ICONS.folder(14)} ${fileCount} file(s) extracted`);
      }
    }
    updateTokenDisplay() {
      // Delegate to global tracker
      if (window.tokenTracker) window.tokenTracker._render();
    }

    async sendArena(msg) {
      if (window.arenaSelectedModels.length === 0) {
        toast('Please select at least 1 model in the picker');
        return;
      }

      // --- Close any stale streams from a previous run ---
      if (window.arenaStreams && window.arenaStreams.length > 0) {
        window.arenaStreams.forEach(s => { try { s.es.close(); } catch (_) {} });
      }
      window.arenaStreams = [];

      this.hideWelcome();
      this.inputEl.value = ''; this.resize(); this.sendBtn.disabled = true;
      $('#arena-container').style.display = 'grid';
      $('#arena-container').innerHTML = '';
      $('#arena-eval-panel').style.display = 'none';

      const cols = {};

      try {
        const r = await fetch('/arena/send', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: msg,
            models: window.arenaSelectedModels
          })
        });
        const d = await r.json();

        if (!r.ok) throw new Error(d.detail || 'Failed');

        let activeStreams = d.streams.length;

        d.streams.forEach(stream => {
          const col = document.createElement('div');
          col.className = 'arena-col';
          const title = window.arenaSelectedModels.find(m => m.model === stream.model && m.provider === stream.provider)?.label || stream.model;
          col.innerHTML = `
            <div class="arena-col-header">
              <span>${escHtml(title)}</span>
              <span style="font-size:10px; color:var(--text-muted)">${escHtml(stream.provider)}</span>
            </div>
            <div class="arena-col-body" id="col-${stream.stream_id}">
              <div class="arena-waiting" style="display:flex; align-items:center; gap:8px; padding:16px; color:var(--text-muted); font-size:13px;">
                <span class="tool-spinner"></span> Waiting in queue…
              </div>
            </div>
            <div class="arena-col-footer" id="footer-${stream.stream_id}" style="display:none; border-top: 1px solid var(--border); padding: 12px; background: rgba(124, 58, 237, 0.05); flex-shrink: 0;"></div>
          `;
          $('#arena-container').appendChild(col);
          cols[stream.stream_id] = { text: '', el: col.querySelector('.arena-col-body'), started: false };

          const es = new EventSource(`/arena/stream/${stream.stream_id}`);
          es.onerror = () => {
            es.close();
            if (!cols[stream.stream_id].started) {
              cols[stream.stream_id].text = '❌ Connection error — server unreachable or model failed to load.';
            } else {
              cols[stream.stream_id].text += `\n\n❌ Connection lost`;
            }
            cols[stream.stream_id].text += `\n\n<button id="retry-${stream.stream_id}" class="code-action-btn" style="margin-top:8px" onclick="OC.retryArenaStream('${stream.stream_id}', '${stream.model}', '${stream.provider}')">${icon('refresh', 14)} Retry</button>`;
            cols[stream.stream_id].el.innerHTML = renderMd(cols[stream.stream_id].text);
            activeStreams--;
            if (activeStreams <= 0) {
              this.sendBtn.disabled = false;
              $('#arena-eval-panel').style.display = 'flex';
              window.arenaLastPrompt = msg;
            }
          };
          // Ignore keepalive events (they have no useful data)
          es.addEventListener('keepalive', () => { /* noop — connection stays alive */ });
          es.onmessage = e => {
            if (e.data === '[DONE]') {
              es.close();
              activeStreams--;
              if (activeStreams <= 0) {
                this.sendBtn.disabled = false;
                $('#arena-eval-panel').style.display = 'flex';
                window.arenaLastPrompt = msg;
              }
              // Cancel pending throttled render and do final render
              const col = cols[stream.stream_id];
              if (col._renderTimer) { clearTimeout(col._renderTimer); col._renderTimer = null; }
              let finalPreview = col.text;

              let statsHtml = '';
              const statsRe = /__STATS__([\s\S]+?)__STATS__/;
              const statsMatch = finalPreview.match(statsRe);
              if (statsMatch) {
                try {
                  const stats = JSON.parse(statsMatch[1]);
                  const streamObj = window.arenaStreams.find(s => s.id === stream.stream_id);
                  if (streamObj) streamObj.stats = stats;
                  statsHtml = `<div class="arena-stats" style="margin-top:16px; padding:12px; border-radius:var(--radius-sm); background:var(--bg-tertiary); font-size:12px; border:1px solid var(--border);">
                    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                      <span style="color:var(--text-muted)">Response Time</span>
                      <strong>${stats.time}s</strong>
                    </div>
                    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                      <span style="color:var(--text-muted)">Tokens E/S</span>
                      <strong>${stats.tokens}</strong>
                    </div>
                    <div style="display:flex; justify-content:space-between;">
                      <span style="color:var(--text-muted)"> Vitesse</span>
                      <strong>${stats.tps} tokens/s</strong>
                    </div>
                  </div>`;
                  finalPreview = finalPreview.replace(statsRe, '');
                } catch (err) { }
              }

              const ffc = (finalPreview.match(/```/g) || []).length;
              if (ffc % 2 !== 0) finalPreview += '\n```';
              col.el.innerHTML = renderMd(finalPreview) + statsHtml;
              if (typeof highlightAll === 'function') highlightAll(col.el);
              return;
            }
            const col = cols[stream.stream_id];
            // Remove the "waiting" spinner on first real token
            if (!col.started) {
              col.started = true;
              const waitEl = col.el.querySelector('.arena-waiting');
              if (waitEl) waitEl.remove();
            }
            col.text += e.data;

            // Throttle DOM renders (~150ms interval)
            if (!col._renderPending) {
              col._renderPending = true;
              col._renderTimer = setTimeout(() => {
                col._renderPending = false;
                col._renderTimer = null;
                let preview = col.text;

                let statsHtml = '';
                const statsRe = /__STATS__([\s\S]+?)__STATS__/;
                const statsMatch = preview.match(statsRe);
                if (statsMatch) {
                  try {
                    const stats = JSON.parse(statsMatch[1]);
                    const streamObj = window.arenaStreams.find(s => s.id === stream.stream_id);
                    if (streamObj) streamObj.stats = stats;
                    statsHtml = `<div class="arena-stats" style="margin-top:16px; padding:12px; border-radius:var(--radius-sm); background:var(--bg-tertiary); font-size:12px; border:1px solid var(--border);">
                      <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                        <span style="color:var(--text-muted)">Response Time</span>
                        <strong>${stats.time}s</strong>
                      </div>
                      <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                        <span style="color:var(--text-muted)">Tokens E/S</span>
                        <strong>${stats.tokens}</strong>
                      </div>
                      <div style="display:flex; justify-content:space-between;">
                        <span style="color:var(--text-muted)"> Vitesse</span>
                        <strong>${stats.tps} tokens/s</strong>
                      </div>
                    </div>`;
                    preview = preview.replace(statsRe, '');
                  } catch (err) { }
                }

                const fc = (preview.match(/```/g) || []).length;
                if (fc % 2 !== 0) preview += '\n```';

                col.el.innerHTML = renderMd(preview) + statsHtml;
                col.el.scrollTop = col.el.scrollHeight;
                if (typeof highlightAll === 'function') highlightAll(col.el);
              }, 150);
            }
          };
          window.arenaStreams.push({ id: stream.stream_id, es: es, model: stream.model, provider: stream.provider });
        });

      } catch (e) {
        toast(' ' + e.message);
        this.sendBtn.disabled = false;
      }
    }

    async stopGeneration() {
      if (!this.sessionId || !this.streaming) return;
      // Use WS transport for instant stop if available
      if (this.transport && this.transport.isWebSocket) {
        this.transport.stop();
      } else {
        try {
          await fetch(`/stop/${this.sessionId}`, { method: 'POST' });
        } catch (e) { console.warn('Stop request failed:', e); }
        // Force close SSE
        if (this.es) { this.es.close(); this.es = null; }
      }
      // Cancel pending render
      if (this._renderTimer) { clearTimeout(this._renderTimer); this._renderTimer = null; }
      this._renderPending = false;
      // Finalize the bubble with what we have
      if (this.bubble && this.text) {
        this.bubble.innerHTML = renderMd(this.text) + '<div style="color:var(--text-muted);font-style:italic;margin-top:8px;">⏹️ Generation stopped by user</div>';
        highlightAll();
      }
      this.streaming = false;
      this.bubble = null; this.text = '';
      this.status('connected');
      this.sendBtn.disabled = false;
      if (this.stopBtn) { this.stopBtn.style.display = 'none'; this.sendBtn.style.display = ''; }
      toast(ICONS.check(14) + ' Generation stopped');
    }
    async send() {
      const msg = this.inputEl.value.trim();
      if (!msg || this.streaming) return;

      if (window.arenaMode) {
        return this.sendArena(msg);
      }

      // ---- Proactive Research Hook ----
      const researchKeywords = ['research', 'recherche', 'investigate', 'analyze', 'deep dive', 'internet search', 'find out', 'cherche', 'analyse', 'explore'];
      const msgLower = msg.toLowerCase();
      if (researchKeywords.some(kw => msgLower.includes(kw))) {
        if (confirm("It looks like your request involves research.\n\nWould you like to transition to the Research Studio for a comprehensive multi-step analysis?")) {
          this.inputEl.value = '';
          this.resize();
          if (window.researchStudio) {
            window.researchStudio.launchFromChat(msg);
          }
          return;
        }
      }
      // ---------------------------------

      if (!this.sessionId) {
        // Create a new server session on first message
        try {
          const r = await fetch('/chat/new', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
              provider: $('#provider-select').value, model: $('#model-select').value, preprompt: $('#preprompt-select').value
            })
          });
          const d = await r.json(); this.sessionId = d.id; this.connectSSE();
          if (window.tokenTracker) window.tokenTracker.setSession(d.id);
        } catch (e) { console.error(e); this.status('offline'); return; }
      } else if (!this.es || this.es.readyState === 2) {
        this.connectSSE();
      }
      this.hideWelcome(); this.addMsg('user', msg);

      // Auto-enrich prompt if enabled
      let enrichedMsg = msg;
      let active_project = null;
      let active_file = null;
      if ($('#settings-auto-enrich') && $('#settings-auto-enrich').checked && window.editor) {
        if (window.editor.projectPath) {
          active_project = window.editor.projectPath;
          enrichedMsg = `[Context: Working in project directory "${active_project}"]\n\n${enrichedMsg}`;
        }
        if (window.editor.activeTab) {
          active_file = window.editor.activeTab;
          const activeTab = window.editor.openTabs.find(t => t.path === active_file);
          if (activeTab && activeTab.content) {
            const maxCtx = 3000;
            const fileContent = activeTab.content.length > maxCtx ? activeTab.content.substring(0, maxCtx) + '\n... (truncated)' : activeTab.content;
            enrichedMsg = `[Currently editing: ${activeTab.path}]\n\`\`\`${window.editor._extToLang(activeTab.path)}\n${fileContent}\n\`\`\`\n\n${enrichedMsg}`;
          }
        }
      }

      // Estimate sent tokens (~4 chars per token)
      if (window.tokenTracker) window.tokenTracker.addInput(Math.ceil(enrichedMsg.length / 4));
      this.inputEl.value = ''; this.resize(); this.sendBtn.disabled = true;

      // Use action mode as primary preprompt, falling back to hidden preprompt-select
      const actionMode = ($('#action-mode-select') || {}).value || 'none';
      let requestPreprompt = actionMode;
      // For execution modes (auto, step-by-step), use base preprompt but pass mode separately
      if (actionMode === 'auto' || actionMode === 'step-by-step') {
        requestPreprompt = 'developer'; // Use developer as base for tool access
      } else if (actionMode === 'none') {
        requestPreprompt = $('#preprompt-select').value || 'none';
      }

      // Prefix message for step-by-step mode
      if (actionMode === 'step-by-step') {
        enrichedMsg = '[Step-by-Step Mode] Please first present a detailed numbered plan of the steps you will take. Wait for my confirmation before executing.\n\n' + enrichedMsg;
      } else if (actionMode === 'auto') {
        enrichedMsg = '[Auto Mode] Execute everything autonomously. Do NOT ask for permission. Use tools directly.\n\n' + enrichedMsg;
      }

      // ---- Auto Enhance Prompt via LLM (Roo Code-inspired) ----
      // Only runs if auto-enrich is explicitly enabled to avoid extra LLM calls
      if ($('#settings-auto-enrich') && $('#settings-auto-enrich').checked) {
        try {
          const enhRes = await fetch('/api/enhance', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              prompt: enrichedMsg,
              provider: $('#provider-select').value,
              model: $('#model-select').value
            }),
          });
          const enhData = await enhRes.json();
          if (enhData.enhanced && enhData.enhanced.trim()) {
            enrichedMsg = enhData.enhanced;
          }
        } catch (enhErr) {
          console.debug('Auto-enhance skipped:', enhErr);
        }
      }

      // Remove previous suggestion chips
      document.querySelectorAll('.suggestion-chips').forEach(el => el.remove());
      document.querySelectorAll('.mode-switch-hint').forEach(el => el.remove());

      // Collect vision images before sending
      const visionImages = (typeof visionChatGetImages === 'function') ? visionChatGetImages() : [];

      // Display uploaded images in the user bubble (inline preview)
      if (visionImages.length > 0) {
        const lastUserRow = this.msgEl.querySelector('.message.user:last-child .message-bubble');
        if (lastUserRow) {
          const imgHtml = visionImages.map(url =>
            `<img src="${url}" class="chat-vision-image" alt="Uploaded image">`
          ).join('');
          lastUserRow.insertAdjacentHTML('afterbegin', imgHtml);
        }
      }

      try {
        // Use WebSocket transport if connected
        if (this.transport && this.transport.isWebSocket) {
          this.transport.send({
            message: enrichedMsg,
            provider: $('#provider-select').value,
            model: $('#model-select').value,
            preprompt: requestPreprompt,
            active_project: active_project,
            active_file: active_file,
            rag_mode: window.ragMode || false,
            action_mode: actionMode,
            images: visionImages
          });
        } else {
          // Legacy SSE path
          await fetch(`/send/${this.sessionId}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              message: enrichedMsg,
              provider: $('#provider-select').value,
              model: $('#model-select').value,
              preprompt: requestPreprompt,
              active_project: active_project,
              active_file: active_file,
              rag_mode: window.ragMode || false,
              action_mode: actionMode,
              images: visionImages
            })
          });
        }
      } catch (e) { toast(ICONS.x(14) + ' Send error'); this.sendBtn.disabled = false; }
    }
    addMsg(role, content, metadata) {
      this.hideWelcome();
      const avatar = role === 'user' ? icon('chat') : icon('bolt');
      const author = role === 'user' ? 'You' : 'Clawzd';
      const bubble = el('div', { class: 'message-bubble' });
      let displayContent = content;
      if (role === 'user' && typeof displayContent === 'string' && displayContent.includes('[Auto-Generated Implementation Plan:')) {
        displayContent = '⚙️ *Auto-Plan execution triggered.*';
      }
      if (displayContent) bubble.innerHTML = renderMd(displayContent);
      const timestamp = new Date().toLocaleString([], { dateStyle: 'short', timeStyle: 'short' });

      // Message actions bar (visible on hover)
      const actionsBar = el('div', { class: 'msg-actions' });
      if (role === 'assistant') {
        // Copy response
        const copyBtn = el('button', { class: 'msg-action-btn', title: 'Copy response', html: `${icon('copy', 13)} Copy` });
        copyBtn.addEventListener('click', () => {
          const text = bubble.innerText || bubble.textContent || '';
          navigator.clipboard.writeText(text).then(() => {
            copyBtn.innerHTML = `${icon('check', 13)} Copied`;
            setTimeout(() => { copyBtn.innerHTML = `${icon('copy', 13)} Copy`; }, 1500);
          });
        });
        actionsBar.appendChild(copyBtn);
        // Regenerate
        const regenBtn = el('button', { class: 'msg-action-btn', title: 'Regenerate response', html: `${icon('refresh-cw', 13)} Regenerate` });
        regenBtn.addEventListener('click', () => {
          // Find the last user message and re-send it
          const messages = this.msgEl.querySelectorAll('.message.user .message-bubble');
          if (messages.length === 0) return;
          const lastUserMsg = messages[messages.length - 1].innerText;
          // Remove this assistant message
          const msgRow = bubble.closest('.message');
          if (msgRow) msgRow.remove();
          this.inputEl.value = lastUserMsg;
          this.send();
        });
        actionsBar.appendChild(regenBtn);
        // Humanize text (Abacus.ai-inspired)
        const humanizeBtn = el('button', { class: 'msg-action-btn', title: 'Rewrite to sound more human', html: `${icon('edit', 13)} Humanize` });
        humanizeBtn.addEventListener('click', async () => {
          const originalHtml = bubble.innerHTML;
          const originalText = bubble.innerText || bubble.textContent || '';
          if (!originalText.trim()) return;
          humanizeBtn.disabled = true;
          humanizeBtn.innerHTML = `${icon('clock', 13)} Humanizing...`;
          try {
            const r = await fetch('/chat/humanize', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                text: originalText,
                provider: $('#provider-select').value,
                model: $('#model-select').value
              })
            });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || 'Failed');
            if (d.humanized) {
              bubble.innerHTML = renderMd(d.humanized);
              highlightAll(bubble);
              humanizeBtn.innerHTML = `${icon('check', 13)} Humanized`;
              // Add undo button
              const undoBtn = el('button', { class: 'msg-action-btn', title: 'Undo humanization', html: `${icon('refresh-cw', 13)} Undo` });
              undoBtn.addEventListener('click', () => {
                bubble.innerHTML = originalHtml;
                highlightAll(bubble);
                undoBtn.remove();
                humanizeBtn.innerHTML = `${icon('edit', 13)} Humanize`;
              });
              actionsBar.insertBefore(undoBtn, humanizeBtn.nextSibling);
              setTimeout(() => { humanizeBtn.innerHTML = `${icon('edit', 13)} Humanize`; }, 2000);
            }
          } catch (e) {
            toast(ICONS.x(14) + ' Humanize failed: ' + e.message);
            humanizeBtn.innerHTML = `${icon('edit', 13)} Humanize`;
          } finally {
            humanizeBtn.disabled = false;
          }
        });
        actionsBar.appendChild(humanizeBtn);
        // Fork button (branching)
        if (window.branchManager && metadata && metadata._msgId) {
          window.branchManager.addForkButton(actionsBar, metadata._msgId);
        }
      } else {
        // Edit user message
        const editBtn = el('button', { class: 'msg-action-btn', title: 'Edit message', html: `${icon('edit', 13)} Edit` });
        editBtn.addEventListener('click', () => {
          const text = bubble.innerText || bubble.textContent || '';
          this.inputEl.value = text;
          this.inputEl.focus();
          this.inputEl.style.height = 'auto';
          this.inputEl.style.height = Math.min(this.inputEl.scrollHeight, 150) + 'px';
        });
        actionsBar.appendChild(editBtn);
      }

      // Resolve model tooltip for the avatar
      let avatarTitle = '';
      if (role === 'assistant') {
        if (metadata && metadata.model) {
          avatarTitle = metadata.model;
          if (metadata.provider) avatarTitle = metadata.provider + ' / ' + avatarTitle;
        } else {
          // Fallback to current model selector
          const modelSel = document.getElementById('model-select');
          if (modelSel && modelSel.value) avatarTitle = modelSel.value;
        }
      }

      const avatarEl = el('div', { class: 'message-avatar', html: avatar });
      if (avatarTitle) avatarEl.title = avatarTitle;

      const msgEl2 = el('div', { class: 'message ' + role }, [
        el('div', { class: 'message-header' }, [
          avatarEl,
          el('span', { class: 'message-author', text: author })
        ]),
        bubble,
        actionsBar,
        el('div', { class: 'message-timestamp', text: timestamp, style: 'font-size:10px; color:var(--text-muted); margin-top:4px; text-align:right;' })
      ]);
      this.msgEl.appendChild(msgEl2);
      this.msgEl.scrollTop = this.msgEl.scrollHeight;
      return bubble;
    }
    showWelcome() {
      if (!$('#chat-welcome')) {
        this.msgEl.innerHTML = `<div class="chat-welcome" id="chat-welcome">
          <div class="welcome-glow"></div><div class="chat-welcome-icon">${icon('bolt', 32)}</div>
          <h1>Clawzd</h1><p>Your local-first AI assistant. Ask anything, generate code, and export full projects.</p>
          <div class="welcome-cards">
            <div class="welcome-card" data-prompt="Write a Python FastAPI server with CRUD endpoints"><span class="welcome-card-icon">${icon('monitor')}</span><span>Build a FastAPI server</span></div>
            <div class="welcome-card" data-prompt="Design a modern dark dashboard in HTML/CSS"><span class="welcome-card-icon">${icon('palette')}</span><span>Design a dashboard</span></div>
            <div class="welcome-card" data-prompt="Explain microservices with a Mermaid diagram"><span class="welcome-card-icon">${icon('layers')}</span><span>Explain architecture</span></div>
            <div class="welcome-card" data-prompt="Review this code for security issues"><span class="welcome-card-icon">${icon('shield')}</span><span>Audit my code</span></div>
          </div></div>`;
      }
      this._bindWelcomeCards();
    }
    _bindWelcomeCards() {
      $$('.welcome-card').forEach(c => {
        if (c._bound) return;
        c._bound = true;
        c.addEventListener('click', async () => {
          this.inputEl.value = c.dataset.prompt;
          await this.send();
        });
      });
    }
    hideWelcome() { const w = $('#chat-welcome'); if (w) w.remove(); }
    status(s) {
      const dot = $('#status-dot'), lbl = $('#status-label');
      if (!dot || !lbl) return;
      dot.className = 'status-dot ' + (s === 'connected' ? '' : s === 'streaming' ? 'streaming' : 'offline');
      lbl.textContent = { connected: 'Connected', streaming: 'Generating...', offline: 'Disconnected' }[s] || s;
    }
  }

  // ---- Sessions sidebar ----
  async function loadSessions() {
    try {
      const r = await fetch('/chat/sessions'); const d = await r.json();
      const list = $('#session-list'); list.innerHTML = '';
      if (!d.sessions || !d.sessions.length) { list.innerHTML = '<div class="session-empty">No conversations yet</div>'; return; }
      d.sessions.forEach(s => {
        const item = el('div', {
          class: 'session-item' + (window.chat && window.chat.sessionId === s.id ? ' active' : ''),
          onclick: () => window.chat.loadSession(s.id)
        }, [
          el('span', { class: 'session-title', text: s.title || 'New Chat' }),
          el('span', { class: 'session-time', text: timeAgo(s.updated_at) }),
          el('span', {
            class: 'session-delete icon-btn', html: ICONS.trash(14), onclick: async e => {
              e.stopPropagation();
              await fetch(`/chat/sessions/${s.id}`, { method: 'DELETE' });
              loadSessions(); toast('Chat deleted');
            }
          })
        ]);
        list.appendChild(item);
      });
    } catch (e) { console.error(e); }
  }

  // ---- Load preprompts ----
  async function loadPreprompts() {
    try {
      const r = await fetch('/api/preprompts'); const d = await r.json();
      const sel = $('#preprompt-select'), ssel = $('#settings-preprompt');
      if (d.preprompts) {
        sel.innerHTML = ''; if (ssel) ssel.innerHTML = '';
        d.preprompts.forEach(p => {
          const opt = `<option value="${escHtml(p.key)}">${escHtml(p.icon)} ${escHtml(p.label)}</option>`;
          sel.innerHTML += opt; if (ssel) ssel.innerHTML += opt;
        });
      }
    } catch (e) { console.error(e); }
  }

  // ---- Load providers/models ----
  async function loadProviders() {
    try {
      const r = await fetch('/api/providers'); const d = await r.json();
      window._providers = d.providers || {};

      const savedProv = localStorage.getItem('hoc_last_provider');
      if (savedProv && window._providers[savedProv]) {
        $('#provider-select').value = savedProv;
      }
      updateModels(localStorage.getItem('hoc_last_model'));

      // Auto-select the active local model and update picker label
      try {
        const sr = await fetch('/api/llm-status'); const sd = await sr.json();
        if (sd.active_model) {
          window._activeLocalModel = sd.active_model;
          const localModels = (window._providers || {})['ollama'] || [];
          const match = localModels.find(m => m.id === sd.active_model);
          if (match && $('#provider-select').value === 'ollama') {
            // Auto-select the running model
            $('#model-select').value = match.id;
            const lbl = $('#model-picker-label');
            if (lbl) lbl.textContent = match.label || match.id;
          } else if ($('#provider-select').value === 'ollama') {
            // Show model name even if not in select (e.g. Default)
            const lbl = $('#model-picker-label');
            if (lbl) lbl.textContent = sd.active_model;
          }
        }
      } catch (e) { /* llm-status unavailable, no big deal */ }
    } catch (e) { console.error(e); }
  }
  function updateModels(savedModel) {
    if (savedModel instanceof Event) savedModel = null;
    const prov = $('#provider-select').value;
    const sel = $('#model-select');
    sel.innerHTML = '<option value="">Default</option>';
    const models = (window._providers || {})[prov] || [];
    models.forEach(m => { sel.innerHTML += `<option value="${escHtml(m.id)}">${escHtml(m.label)}</option>`; });

    if (savedModel && Array.from(sel.options).some(o => o.value === savedModel)) {
      sel.value = savedModel;
    }

    // Update picker label to reflect current selection
    const lbl = $('#model-picker-label');
    if (lbl) {
      const currentModel = sel.value;
      const match = models.find(m => m.id === currentModel);
      if (match) {
        lbl.textContent = match.label || match.id;
      } else if (prov === 'ollama' && window._activeLocalModel) {
        lbl.textContent = window._activeLocalModel;
      } else {
        const PNAMES = { google: 'Gemini', grok: 'Grok', groq: 'Groq', huggingface: 'HuggingFace', mistral: 'Mistral', ollama: 'Ollama', openai: 'OpenAI', openrouter: 'OpenRouter' };
        lbl.textContent = PNAMES[prov] || prov;
      }
    }
  }

  // ---- Global API ----
  window.OC = {
    async retryArenaStream(oldStreamId, model, provider) {
      if (!window.chat) return;
      const colEl = document.getElementById('col-' + oldStreamId);
      if (colEl) colEl.innerHTML = '<div style="color:var(--text-muted);font-style:italic;margin-top:8px;">⏳ Retrying...</div>';

      try {
        const r = await fetch('/arena/send', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: window.arenaLastPrompt || '',
            models: [{ model: model, provider: provider }]
          })
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || 'Failed');
        if (d.streams && d.streams.length > 0) {
          const newStream = d.streams[0];
          // Remove old stream from window.arenaStreams
          window.arenaStreams = window.arenaStreams.filter(s => s.id !== oldStreamId);

          const es = new EventSource(`/arena/stream/${newStream.stream_id}`);
          let text = '';
          const streamObj = { id: newStream.stream_id, es: es, model: newStream.model, provider: newStream.provider };
          window.arenaStreams.push(streamObj);

          // Update the column ID so it matches the new stream ID
          colEl.id = 'col-' + newStream.stream_id;
          const footerEl = colEl.parentElement.querySelector('.arena-col-footer');
          if (footerEl) {
            footerEl.id = 'footer-' + newStream.stream_id;
            footerEl.style.display = 'none';
            footerEl.innerHTML = '';
          }

          let renderPending = false;
          let renderTimer = null;

          es.onerror = () => {
            es.close();
            text += `\n\n❌ Connection error <br><button id="retry-${newStream.stream_id}" class="code-action-btn" style="margin-top:8px" onclick="OC.retryArenaStream('${newStream.stream_id}', '${newStream.model}', '${newStream.provider}')">${icon('refresh', 14)} Retry</button>`;
            colEl.innerHTML = renderMd(text);
          };

          es.onmessage = e => {
            if (e.data === '[DONE]') {
              es.close();
              if (renderTimer) clearTimeout(renderTimer);
              let finalPreview = text;

              let statsHtml = '';
              const statsRe = /__STATS__([\\s\\S]+?)__STATS__/;
              const statsMatch = finalPreview.match(statsRe);
              if (statsMatch) {
                try {
                  const stats = JSON.parse(statsMatch[1]);
                  streamObj.stats = stats;
                  statsHtml = `<div class="arena-stats" style="margin-top:16px; padding:12px; border-radius:var(--radius-sm); background:var(--bg-tertiary); font-size:12px; border:1px solid var(--border);">
                    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                      <span style="color:var(--text-muted)">Response Time</span>
                      <strong>${stats.time}s</strong>
                    </div>
                    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                      <span style="color:var(--text-muted)">Tokens E/S</span>
                      <strong>${stats.tokens}</strong>
                    </div>
                    <div style="display:flex; justify-content:space-between;">
                      <span style="color:var(--text-muted)"> Vitesse</span>
                      <strong>${stats.tps} tokens/s</strong>
                    </div>
                  </div>`;
                  finalPreview = finalPreview.replace(statsRe, '');
                } catch (err) { }
              }

              const ffc = (finalPreview.match(/```/g) || []).length;
              if (ffc % 2 !== 0) finalPreview += '\\n```';
              colEl.innerHTML = renderMd(finalPreview) + statsHtml;
              if (typeof highlightAll === 'function') highlightAll(colEl);
              return;
            }
            text += e.data;
            if (!renderPending) {
              renderPending = true;
              renderTimer = setTimeout(() => {
                renderPending = false;
                renderTimer = null;
                let preview = text;

                let statsHtml = '';
                const statsRe = /__STATS__([\\s\\S]+?)__STATS__/;
                const statsMatch = preview.match(statsRe);
                if (statsMatch) {
                  try {
                    const stats = JSON.parse(statsMatch[1]);
                    streamObj.stats = stats;
                    statsHtml = `<div class="arena-stats" style="margin-top:16px; padding:12px; border-radius:var(--radius-sm); background:var(--bg-tertiary); font-size:12px; border:1px solid var(--border);">
                      <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                        <span style="color:var(--text-muted)">Response Time</span>
                        <strong>${stats.time}s</strong>
                      </div>
                      <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                        <span style="color:var(--text-muted)">Tokens E/S</span>
                        <strong>${stats.tokens}</strong>
                      </div>
                      <div style="display:flex; justify-content:space-between;">
                        <span style="color:var(--text-muted)"> Vitesse</span>
                        <strong>${stats.tps} tokens/s</strong>
                      </div>
                    </div>`;
                    preview = preview.replace(statsRe, '');
                  } catch (err) { }
                }

                const fc = (preview.match(/```/g) || []).length;
                if (fc % 2 !== 0) preview += '\\n```';
                colEl.innerHTML = renderMd(preview) + statsHtml;
                colEl.scrollTop = colEl.scrollHeight;
                if (typeof highlightAll === 'function') highlightAll(colEl);
              }, 150);
            }
          };
        }
      } catch (e) {
        toast('Retry error: ' + e.message);
        colEl.innerHTML = '<div style="color:var(--text-muted);font-style:italic;margin-top:8px;">❌ Retry failed</div>';
      }
    },
    /** Submit an interactive chat form as a user message */
    submitChatForm(formId) {
      const form = document.getElementById(formId);
      if (!form) return;
      const fields = form.querySelectorAll('.form-field-input, input[type="checkbox"]');
      const data = {};
      fields.forEach(f => {
        const name = f.name || f.id;
        if (f.type === 'checkbox') {
          data[name] = f.checked;
        } else {
          data[name] = f.value;
        }
      });
      // Send as a structured message
      const summary = Object.entries(data)
        .map(([k, v]) => `**${k}**: ${v}`)
        .join('\n');
      if (window.chat) {
        window.chat.inputEl.value = `Form submission:\n${summary}`;
        window.chat.send();
      }
      // Disable the form to prevent double-submit
      form.querySelectorAll('button, input, select, textarea').forEach(el => { el.disabled = true; });
      form.style.opacity = '0.6';
    },
    downloadUrl(url, filename) {
      const a = document.createElement('a');
      a.href = url;
      a.download = filename || 'download';
      a.click();
    },
    openLightbox(url, label, filename) {
      const overlay = document.createElement('div');
      overlay.className = 'lightbox-overlay';
      overlay.innerHTML = `
        <div class="lightbox-toolbar">
          <button class="lightbox-btn" onclick="OC.downloadUrl('${url.replace(/'/g, "\\'")}', '${(filename || '').replace(/'/g, "\\'")}')">${icon('save', 14)} Save</button>
          <button class="lightbox-btn lightbox-close">${icon('x', 14)}</button>
        </div>
        <img src="${url.replace(/"/g, '&quot;')}" alt="${(label || '').replace(/"/g, '&quot;')}" class="lightbox-img">`;
      overlay.addEventListener('click', e => {
        if (e.target === overlay || e.target.classList.contains('lightbox-close')) overlay.remove();
      });
      document.body.appendChild(overlay);
    },
    exportChartPng(id) {
      const canvas = document.getElementById(id);
      if (!canvas) { toast('Chart not found'); return; }
      const a = document.createElement('a');
      a.href = canvas.toDataURL('image/png');
      a.download = `chart-${id}.png`;
      a.click();
    },
    sendChartToPresentation(id) {
      const canvas = document.getElementById(id);
      if (!canvas) { toast('Chart not found'); return; }
      const dataUrl = canvas.toDataURL('image/png');
      if (window.presentationStudio) {
        window.presentationStudio.addElement({ type: 'image', src: dataUrl, x: 50, y: 50, w: 500, h: 300 });
        toast(icon('check', 14) + ' Chart sent to Presentation');
      } else {
        toast('Presentation Studio is not initialized');
      }
    },
    exportMermaidMd(id) {
      const el = document.getElementById(id);
      if (!el) return;
      const code = el.getAttribute('data-code');
      if (!code) return;
      const blob = new Blob(["```mermaid\n" + code + "\n```"], { type: 'text/markdown' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `mermaid-export.md`;
      a.click();
      URL.revokeObjectURL(a.href);
    },
    exportMermaidSvg(id) {
      const el = document.getElementById(id);
      if (!el) return;
      const svg = el.querySelector('svg');
      if (!svg) { toast('Diagram not ready or invalid'); return; }
      const svgData = new XMLSerializer().serializeToString(svg);
      const blob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `mermaid-export.svg`;
      a.click();
      URL.revokeObjectURL(a.href);
    },
    sendToPresentation(type, data) {
      if (!window.presentationStudio) {
        toast('Presentation Studio is not initialized');
        return;
      }
      // Switch view
      const btn = document.querySelector('.mode-btn[data-mode="presentation"]');
      if (btn) btn.click();

      // Add Element
      window.presentationStudio.addElement(type, data);
      toast(ICONS.check(14) + ' Element added to presentation!');
    },
    sendMermaidToPresentation(id) {
      const el = document.getElementById(id);
      if (!el) return;
      const svg = el.querySelector('svg');
      if (!svg) { toast('Diagram not ready or invalid'); return; }
      const svgData = new XMLSerializer().serializeToString(svg);
      const b64 = btoa(unescape(encodeURIComponent(svgData)));
      this.sendToPresentation('image', 'data:image/svg+xml;base64,' + b64);
    },
    exportTableToExcel(id, filename = 'export.xls') {
      const b = document.getElementById(id); if (!b) return;
      const html = `<html xmlns:x="urn:schemas-microsoft-com:office:excel">
        <head><meta charset="utf-8"><!--[if gte mso 9]><xml><x:ExcelWorkbook><x:ExcelWorksheets><x:ExcelWorksheet>
        <x:Name>Sheet 1</x:Name><x:WorksheetOptions><x:DisplayGridlines/></x:WorksheetOptions></x:ExcelWorksheet>
        </x:ExcelWorksheets></x:ExcelWorkbook></xml><![endif]--></head><body>` + b.outerHTML + `</body></html>`;
      const url = 'data:application/vnd.ms-excel;base64,' + btoa(unescape(encodeURIComponent(html)));
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
    },
    copyCode(id) {
      const b = document.getElementById(id); if (!b) return;
      const c = b.querySelector('code');
      const text = c ? c.textContent : b.textContent;

      const fallbackCopy = (text) => {
        const textArea = document.createElement("textarea");
        textArea.value = text;
        textArea.style.top = "0";
        textArea.style.left = "0";
        textArea.style.position = "fixed";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        try {
          const successful = document.execCommand('copy');
          if (successful) toast(icon('copy') + ' Copied!');
          else toast('Copy failed');
        } catch (err) {
          toast('Copy failed');
        }
        document.body.removeChild(textArea);
      };

      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(() => {
          toast(icon('copy') + ' Copied!');
        }).catch(() => fallbackCopy(text));
      } else {
        fallbackCopy(text);
      }
    },
    applyToEditor(id) {
      if (!window.editor || !window.editor.activeTab) {
        toast('No active file in editor');
        return;
      }
      const b = document.getElementById(id);
      if (!b) return;
      const c = b.querySelector('code');
      const code = c ? c.textContent : b.textContent;
      window.editor._applyFileContent(window.editor.activeTab, code);
      toast(icon('check') + ' Applied to Editor');
    },
    refreshPreviewIfOpen(path) {
      const overlay = document.getElementById('preview-overlay');
      if (overlay && overlay.classList.contains('open')) {
        const iframe = document.getElementById('preview-iframe');
        if (iframe && iframe.src) {
          const urlObj = new URL(iframe.src, window.location.origin);
          const currentPath = urlObj.searchParams.get('path');
          if (!path || currentPath === path) {
            iframe.src = '/workspace/file-raw?path=' + encodeURIComponent(currentPath) + '&_t=' + new Date().getTime();
          }
        }
      }
    },
    async runCode(id) {
      const b = document.getElementById(id); if (!b) return;
      const c = b.querySelector('code'), code = c ? c.textContent : b.textContent;
      if (!code.trim()) { toast('No code to run'); return; }
      let rd = b.nextElementSibling;
      if (!rd || !rd.classList.contains('code-exec-result')) {
        rd = document.createElement('div'); rd.className = 'code-exec-result';
        b.parentNode.insertBefore(rd, b.nextSibling);
      }
      rd.innerHTML = `${icon('clock', 14)} Running...`; rd.className = 'code-exec-result';
      const hdr = b.previousElementSibling, rb = hdr ? hdr.querySelector('.code-run-btn') : null;
      if (rb) rb.classList.add('running');
      try {
        const r = await fetch('/api/execute', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }) });
        const d = await r.json();
        if (d.error) { rd.innerHTML = `${icon('x', 14)} ${escHtml(d.error)}`; rd.className = 'code-exec-result error'; }
        else if (d.returncode !== 0) { rd.textContent = d.stderr || 'Unknown error'; rd.className = 'code-exec-result error'; }
        else {
          rd.className = 'code-exec-result success';
          if (d.stdout) rd.textContent = d.stdout;
          else rd.innerHTML = `${icon('check', 14)} Success (no output)`;
          // Render captured matplotlib plots
          if (d.images && d.images.length) {
            d.images.forEach((b64, i) => {
              const img = document.createElement('img');
              img.src = 'data:image/png;base64,' + b64;
              img.alt = 'Plot ' + (i + 1);
              img.style.cssText = 'max-width:100%;border-radius:8px;margin:8px 0;box-shadow:0 4px 20px rgba(0,0,0,0.4);cursor:zoom-in;display:block;';
              img.addEventListener('click', () => {
                const overlay = document.createElement('div');
                overlay.className = 'lightbox-overlay';
                overlay.innerHTML = `<div class="lightbox-toolbar"><button class="lightbox-btn" data-action="save">${icon('save', 14)} Save</button><button class="lightbox-btn lightbox-close">${icon('x', 14)}</button></div><img src="${img.src}" alt="Plot" class="lightbox-img">`;
                overlay.addEventListener('click', e => {
                  if (e.target === overlay || e.target.classList.contains('lightbox-close')) overlay.remove();
                  if (e.target.dataset && e.target.dataset.action === 'save') {
                    const a = document.createElement('a'); a.href = img.src; a.download = 'plot_' + (i + 1) + '.png'; a.click();
                  }
                });
                document.body.appendChild(overlay);
              });
              rd.appendChild(img);
            });
          }
        }
      } catch (e) { rd.textContent = ' Network error: ' + e.message; rd.className = 'code-exec-result error'; }
      finally { if (rb) rb.classList.remove('running'); }
    },
    // Save code block content to the Files panel
    saveToFiles(id, lang, label) {
      const b = document.getElementById(id); if (!b) return;
      const c = b.querySelector('code');
      const code = c ? c.textContent : b.textContent;
      if (!code.trim()) { toast('No code to save'); return; }
      const extMap = {
        python: 'py', py: 'py', javascript: 'js', js: 'js', typescript: 'ts', ts: 'ts',
        html: 'html', htm: 'html', css: 'css', json: 'json', sh: 'sh', bash: 'sh',
        sql: 'sql', java: 'java', cpp: 'cpp', c: 'c', go: 'go', rust: 'rs',
        ruby: 'rb', php: 'php', markdown: 'md', md: 'md', xml: 'xml', svg: 'svg'
      };
      const ll = (lang || '').toLowerCase();
      const ext = extMap[ll] || 'txt';
      // Use label if it looks like a filename, else generate one
      let fname = label && label.includes('.') ? label : null;
      if (!fname) {
        const base = ext === 'html' ? 'index' : ext === 'css' ? 'style' : ext === 'js' ? 'script' : 'main';
        fname = base + '.' + ext;
      }
      // Ask user for confirmation / rename
      const final = prompt('Save as:', fname);
      if (!final || !final.trim()) return;
      window.ft.add(final.trim(), code);
      // Switch to Files tab
      $$('.sidebar-tab').forEach(t => t.classList.remove('active'));
      $$('.sidebar-panel').forEach(p => p.classList.remove('active'));
      const ftab = $('#tab-files'); if (ftab) ftab.classList.add('active');
      const fpanel = $('#panel-files'); if (fpanel) fpanel.classList.add('active');
      toast(icon('save') + ' Saved: ' + final.trim());
    },
    // Remove background from an image
    async removeBg(fname, imgElId) {
      const btn = event && event.target;
      const originalHtml = btn ? btn.innerHTML : '';
      if (btn) { btn.disabled = true; btn.innerHTML = (window.icon ? window.icon('hourglass', 14) : '') + ' Removing...'; }
      try {
        const resp = await fetch('/image/remove-bg', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filenames: [fname] }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Failed');
        if (!data.processed || !data.processed.length) throw new Error('Background removal failed');

        const newFname = data.processed[0];
        const newUrl = `/data/images/${newFname}`;

        // Update the image element if found
        if (imgElId) {
          const img = document.getElementById(imgElId);
          if (img) img.src = newUrl;
        }

        // Add to file tree
        if (window.ft) {
          window.ft.add(newFname, `[Generated image: no background]\nURL: ${newUrl}`);
        }

        toast(ICONS.check(14) + ' Background removed → ' + newFname);
        if (btn) { btn.innerHTML = (window.icon ? window.icon('check', 14) : '') + ' Done'; btn.disabled = false; }
      } catch (e) {
        toast(ICONS.x(14) + ' ' + e.message);
        if (btn) { btn.innerHTML = originalHtml || ((window.icon ? window.icon('sparkles', 14) : '') + ' Remove BG'); btn.disabled = false; }
      }
    },
    // Make a children's coloring page
    async makeColoring(fname, imgElId) {
      const btn = event && event.target;
      const originalHtml = btn ? btn.innerHTML : '';
      if (btn) { btn.disabled = true; btn.innerHTML = (window.icon ? window.icon('hourglass', 14) : '') + ' Drawing...'; }
      try {
        const resp = await fetch('/image/make-coloring', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename: fname }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Failed');

        const newFname = data.filename;
        const newUrl = data.url;

        // Update the image element if found
        if (imgElId) {
          const img = document.getElementById(imgElId);
          if (img) img.src = newUrl;
        }

        // Add to file tree
        if (window.ft) {
          window.ft.add(newFname, `[Generated image: coloring page]\nURL: ${newUrl}`);
        }

        toast(ICONS.check(14) + ' Coloring page created → ' + newFname);
        if (btn) { btn.innerHTML = (window.icon ? window.icon('check', 14) : '') + ' Done'; btn.disabled = false; }
      } catch (e) {
        toast(ICONS.x(14) + ' ' + e.message);
        if (btn) { btn.innerHTML = originalHtml || ((window.icon ? window.icon('edit', 14) : '') + ' Crayons'); btn.disabled = false; }
      }
    },
    // View SVG source code in a lightbox
    async viewSvgCode(url, fname) {
      try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error('Failed to fetch SVG');
        const svgText = await resp.text();
        const safeCode = svgText
          .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

        const overlay = document.createElement('div');
        overlay.className = 'lightbox-overlay';
        overlay.style.cssText = 'display:flex;align-items:center;justify-content:center;';
        overlay.innerHTML = `
          <div style="background:var(--bg-primary, #1a1a2e);border-radius:12px;padding:20px;max-width:80vw;max-height:85vh;overflow:auto;position:relative;box-shadow:0 8px 32px rgba(0,0,0,0.6);">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
              <div>
                <span style="background:linear-gradient(135deg,#7c3aed,#2563eb);color:#fff;padding:3px 10px;border-radius:4px;font-size:11px;font-weight:600;margin-right:8px;">SVG</span>
                <span style="color:var(--text-secondary, #ccc);font-size:14px;">${escHtml(fname)}</span>
              </div>
              <div style="display:flex;gap:8px;">
                <button class="tool-img-btn" style="font-size:12px;" onclick="(function(){navigator.clipboard.writeText(document.getElementById('svg-code-view').textContent);this.textContent=' Copied!'}).call(this)"> Copy</button>
                <button class="tool-img-btn" style="font-size:12px;" onclick="(function(){const a=document.createElement('a');a.href='${url}';a.download='${fname}';a.click()})()"> Save</button>
                <button class="lightbox-btn lightbox-close" style="font-size:18px;"></button>
              </div>
            </div>
            <pre style="margin:0;background:var(--bg-secondary, #16213e);border:1px solid var(--border, #333);border-radius:8px;padding:16px;overflow:auto;max-height:70vh;font-size:12px;line-height:1.5;"><code id="svg-code-view" class="language-xml">${safeCode}</code></pre>
          </div>`;
        overlay.addEventListener('click', e => {
          if (e.target === overlay || e.target.classList.contains('lightbox-close')) overlay.remove();
        });
        document.body.appendChild(overlay);
        // Highlight if available
        if (window.hljs) {
          const codeEl = document.getElementById('svg-code-view');
          if (codeEl && !codeEl.dataset.highlighted) hljs.highlightElement(codeEl);
        }
      } catch (e) {
        toast(' ' + e.message);
      }
    },
    // View file content in a modal (code viewer or HTML preview)
    viewFile(name, content) {
      if (!content) { toast('File is empty'); return; }
      const ext = name.split('.').pop().toLowerCase();
      const isHtml = ['html', 'htm'].includes(ext);
      const isSvg = ext === 'svg';
      const isImage = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'].includes(ext);

      let overlay = document.getElementById('file-viewer-overlay');
      if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'file-viewer-overlay';
        overlay.className = 'preview-overlay';
        overlay.innerHTML = `
          <div class="preview-container">
            <div class="preview-header">
              <span class="preview-title" id="file-viewer-title"></span>
              <div class="preview-actions">
                <button class="preview-size-btn" id="fv-btn-save" onclick="OC.downloadFile()">${icon('save', 14)} Save</button>
                <button class="preview-size-btn" id="fv-btn-preview" onclick="OC.fileViewMode('preview')">${icon('eye', 14)} Preview</button>
                <button class="preview-size-btn" id="fv-btn-code" onclick="OC.fileViewMode('code')">${icon('code', 14)} Code</button>
                <button class="preview-size-btn" data-size="desktop" onclick="OC.resizePreview('desktop','fv-iframe')">${icon('monitor', 14)}</button>
                <button class="preview-size-btn" data-size="tablet" onclick="OC.resizePreview('tablet','fv-iframe')">${icon('tablet', 14)}</button>
                <button class="preview-size-btn" data-size="mobile" onclick="OC.resizePreview('mobile','fv-iframe')">${icon('smartphone', 14)}</button>
                <button class="preview-open-btn" id="fv-open-tab">${icon('externalLink', 14)} Open in Tab</button>
                <button class="preview-close-btn" onclick="OC.closeFileViewer()">${icon('x', 14)}</button>
              </div>
            </div>
            <div class="preview-body" id="fv-body">
              <pre class="file-viewer-code" id="fv-code"><code id="fv-code-content"></code></pre>
              <iframe id="fv-iframe" sandbox="allow-scripts" class="preview-iframe" style="display:none"></iframe>
              <div id="fv-image-view" style="display:none;text-align:center;padding:20px;"></div>
            </div>
          </div>`;
        document.body.appendChild(overlay);
        overlay.addEventListener('click', e => { if (e.target === overlay) OC.closeFileViewer(); });
      }

      // Set title
      document.getElementById('file-viewer-title').textContent = name;
      // Store content for mode switching
      overlay.dataset.content = content;
      overlay.dataset.name = name;

      document.getElementById('fv-btn-preview').style.display = (isHtml || isSvg) ? '' : 'none';
      document.getElementById('fv-btn-code').style.display = (isHtml || isSvg) ? '' : 'none';
      document.querySelectorAll('#file-viewer-overlay .preview-size-btn[data-size]').forEach(b => b.style.display = (isHtml || isSvg) ? '' : 'none');
      document.getElementById('fv-open-tab').style.display = (isHtml || isSvg) ? '' : 'none';

      // Handle SVG files — inline preview with code view
      if (isSvg) {
        const codeEl = document.getElementById('fv-code');
        const iframe = document.getElementById('fv-iframe');
        const imgView = document.getElementById('fv-image-view');
        codeEl.style.display = 'none';
        iframe.style.display = 'none';
        imgView.style.display = 'block';

        // Get SVG URL
        let svgUrl = '';
        const urlMatch = content.match(/URL:\s*(.+)/);
        if (urlMatch) {
          svgUrl = urlMatch[1].trim();
        } else if (content.trim().startsWith('<svg') || content.trim().startsWith('<?xml')) {
          // Raw SVG content — render inline
          svgUrl = '';
        } else {
          svgUrl = `/data/images/${name}`;
        }

        if (svgUrl) {
          imgView.innerHTML = `
            <div style="background:var(--bg-secondary);border-radius:8px;padding:24px;display:flex;align-items:center;justify-content:center;min-height:200px;">
              <img src="${svgUrl}" alt="${escHtml(name)}" style="max-width:100%;max-height:60vh;"
                   onerror="this.parentElement.innerHTML='<div style=&quot;color:var(--text-muted);&quot;>️ SVG loading error</div>'" />
            </div>
            <div style="margin-top:12px;display:flex;gap:12px;justify-content:center;align-items:center;flex-wrap:wrap;">
              <a href="${svgUrl}" download="${name}" style="color:var(--accent);text-decoration:underline;"> Download SVG</a>
              <button class="tool-img-btn" onclick="OC.viewSvgCode('${svgUrl}','${name}')" style="font-size:13px;"> View SVG Code</button>
            </div>
            <div style="margin-top:8px;color:var(--text-muted);font-size:12px;">
              <span style="background:linear-gradient(135deg,#7c3aed,#2563eb);color:#fff;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;margin-right:6px;">SVG</span>
               ${escHtml(name)}
            </div>`;
        } else {
          // Raw SVG content
          imgView.innerHTML = `
            <div style="background:var(--bg-secondary);border-radius:8px;padding:24px;display:flex;align-items:center;justify-content:center;min-height:200px;">
              ${content}
            </div>
            <div style="margin-top:8px;color:var(--text-muted);font-size:12px;">
              <span style="background:linear-gradient(135deg,#7c3aed,#2563eb);color:#fff;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;margin-right:6px;">SVG</span>
               ${escHtml(name)}
            </div>`;
        }

        document.getElementById('fv-btn-save').onclick = () => {
          if (svgUrl) {
            const a = document.createElement('a'); a.href = svgUrl; a.download = name; a.click();
          } else {
            const blob = new Blob([content], { type: 'image/svg+xml' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a'); a.href = url; a.download = name; a.click();
            URL.revokeObjectURL(url);
          }
        };

        overlay.classList.add('open');
        return;
      }

      // Handle image files
      if (isImage) {
        const codeEl = document.getElementById('fv-code');
        const iframe = document.getElementById('fv-iframe');
        const imgView = document.getElementById('fv-image-view');
        codeEl.style.display = 'none';
        iframe.style.display = 'none';
        imgView.style.display = 'block';

        // Extract URL from stored content (format: "[Generated image: ...]\nURL: /data/images/...")
        let imgUrl = '';
        const urlMatch = content.match(/URL:\s*(.+)/);
        if (urlMatch) {
          imgUrl = urlMatch[1].trim();
        } else if (content.startsWith('data:image') || content.startsWith('/data/')) {
          imgUrl = content.trim();
        } else {
          imgUrl = `/data/images/${name}`;
        }

        const fvImgId = 'fv-img-' + Math.random().toString(36).slice(2, 8);
        imgView.innerHTML = `
          <img id="${fvImgId}" src="${imgUrl}" alt="${escHtml(name)}"
               style="max-width:100%;max-height:70vh;border-radius:8px;box-shadow:0 4px 20px rgba(0,0,0,0.4);cursor:zoom-in;"
               onclick="OC.openLightbox('${imgUrl}', '${name}', '${name}')">`;

        // Update save button for images
        document.getElementById('fv-btn-save').onclick = () => {
          const a = document.createElement('a'); a.href = imgUrl; a.download = name; a.click();
        };

        overlay.classList.add('open');
        return;
      }

      // Default: show code for non-HTML, show preview for HTML
      // Hide image view if it was shown before
      const imgView = document.getElementById('fv-image-view');
      if (imgView) imgView.style.display = 'none';
      OC.fileViewMode(isHtml ? 'preview' : 'code');
      overlay.classList.add('open');
    },
    fileViewMode(mode) {
      const overlay = document.getElementById('file-viewer-overlay');
      if (!overlay) return;
      const content = overlay.dataset.content || '';
      const name = overlay.dataset.name || '';
      const codeEl = document.getElementById('fv-code');
      const codeContent = document.getElementById('fv-code-content');
      const iframe = document.getElementById('fv-iframe');
      const btnPreview = document.getElementById('fv-btn-preview');
      const btnCode = document.getElementById('fv-btn-code');

      if (mode === 'code') {
        codeEl.style.display = 'block';
        iframe.style.display = 'none';
        if (btnPreview) btnPreview.classList.remove('active');
        if (btnCode) btnCode.classList.add('active');
        // Detect language from extension
        const ext = name.split('.').pop().toLowerCase();
        const langMap = { py: 'python', js: 'javascript', ts: 'typescript', html: 'html', css: 'css', json: 'json', sh: 'bash', sql: 'sql', java: 'java', cpp: 'cpp', go: 'go', rs: 'rust', rb: 'ruby', php: 'php', md: 'markdown', xml: 'xml' };
        const lang = langMap[ext] || '';
        codeContent.className = lang ? 'language-' + lang : '';
        codeContent.textContent = content;
        if (window.hljs) hljs.highlightElement(codeContent);
      } else {
        codeEl.style.display = 'none';
        iframe.style.display = 'block';
        if (btnPreview) btnPreview.classList.add('active');
        if (btnCode) btnCode.classList.remove('active');
        // Build HTML with all dependencies from file tree (CSS + JS)
        let html = OC._buildPreviewHtml(content);
        iframe.srcdoc = html;
        // Open in tab
        document.getElementById('fv-open-tab').onclick = () => {
          const w = window.open('', '_blank');
          w.document.write(html);
          w.document.close();
        };
      }
    },
    closeFileViewer() {
      const overlay = document.getElementById('file-viewer-overlay');
      if (overlay) overlay.classList.remove('open');
    },
    // Download the current file from the file viewer modal
    downloadFile() {
      const overlay = document.getElementById('file-viewer-overlay');
      if (!overlay) return;
      const content = overlay.dataset.content || '';
      const name = overlay.dataset.name || 'file.txt';
      const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = name;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      toast(' Downloaded: ' + name);
    },
    // Build a full preview HTML from source code, resolving all project dependencies
    _buildPreviewHtml(code) {
      if (!code || !code.trim()) return code;
      const ft = window.ft;

      // Helper: find a file in the file tree by matching its basename or path
      function findFile(ref) {
        if (!ft || !ft.files) return null;
        // Normalize: strip leading ./ or /
        const normalized = ref.replace(/^\.?\//, '');
        // Try exact match first
        if (ft.files.has(normalized)) return ft.files.get(normalized);
        if (ft.files.has(ref)) return ft.files.get(ref);
        // Try matching by basename
        const basename = normalized.split('/').pop();
        for (const [name, content] of ft.files) {
          if (name === basename || name.endsWith('/' + basename)) return content;
        }
        return null;
      }

      if (!code.match(/<html|<body|<!DOCTYPE/i)) {
        // --- Partial HTML: wrap with all CSS and JS from file tree ---
        let css = '', js = '';
        if (ft && ft.files) {
          ft.files.forEach((content, name) => {
            if (name.endsWith('.css')) css += content + '\n';
            else if (name.endsWith('.js') && !content.startsWith('[')) js += content + '\n';
          });
        }
        const styleTag = css ? `<style>${css}</style>` : '';
        const scriptTag = js ? `<script>${js}<\/script>` : '';
        return `<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">${styleTag}</head><body>${code}${scriptTag}</body></html>`;
      }

      // --- Full HTML: resolve <link href> and <script src> references ---
      let html = code;

      // Resolve <link rel="stylesheet" href="..."> → inline <style>
      html = html.replace(/<link\s+[^>]*href=["']([^"']+\.css)["'][^>]*>/gi, (match, href) => {
        const content = findFile(href);
        if (content && !content.startsWith('[')) return `<style>/* ${href} */\n${content}</style>`;
        return match; // keep original if not found
      });

      // Resolve <script src="..."> → inline <script>
      html = html.replace(/<script\s+[^>]*src=["']([^"']+\.js)["'][^>]*>\s*<\/script>/gi, (match, src) => {
        const content = findFile(src);
        if (content && !content.startsWith('[')) return `<script>/* ${src} */\n${content}<\/script>`;
        return match; // keep original if not found
      });

      return html;
    },
    // Preview HTML code from a code block
    previewHtml(id) {
      const b = document.getElementById(id); if (!b) return;
      const c = b.querySelector('code');
      let code = c ? c.textContent : b.textContent;
      if (!code.trim()) { toast('No HTML to preview'); return; }

      // Build preview HTML with all dependencies resolved
      code = OC._buildPreviewHtml(code);

      // Create or reuse the preview overlay
      let overlay = document.getElementById('preview-overlay');
      if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'preview-overlay';
        overlay.className = 'preview-overlay';
        overlay.innerHTML = `
          <div class="preview-container">
            <div class="preview-header">
              <span class="preview-title">${icon('eye', 14)} HTML Preview</span>
              <div class="preview-actions">
                <button class="preview-size-btn active" data-size="desktop" onclick="OC.resizePreview('desktop')">${icon('monitor', 14)} Desktop</button>
                <button class="preview-size-btn" data-size="tablet" onclick="OC.resizePreview('tablet')">${icon('tablet', 14)} Tablet</button>
                <button class="preview-size-btn" data-size="mobile" onclick="OC.resizePreview('mobile')">${icon('smartphone', 14)} Mobile</button>
                <button class="preview-open-btn" id="preview-open-tab">${icon('externalLink', 14)} Open in Tab</button>
                <button class="preview-close-btn" onclick="OC.closePreview()">${icon('x', 14)}</button>
              </div>
            </div>
            <div class="preview-body">
              <iframe id="preview-iframe" sandbox="allow-scripts" class="preview-iframe"></iframe>
            </div>
          </div>`;
        document.body.appendChild(overlay);
        overlay.addEventListener('click', e => { if (e.target === overlay) OC.closePreview(); });
      }

      const iframe = document.getElementById('preview-iframe');
      // Use srcdoc instead of blob URL — more reliable for sandboxed iframes
      iframe.srcdoc = code;
      // Open in new tab
      const openBtn = document.getElementById('preview-open-tab');
      openBtn.onclick = () => {
        const w = window.open('', '_blank');
        w.document.write(code);
        w.document.close();
      };

      overlay.classList.add('open');
    },
    resizePreview(size, iframeId) {
      const iframe = document.getElementById(iframeId || 'preview-iframe');
      if (!iframe) return;
      const container = iframe.closest('.preview-overlay') || document;
      container.querySelectorAll('.preview-size-btn[data-size]').forEach(b => b.classList.remove('active'));
      const btn = container.querySelector(`.preview-size-btn[data-size="${size}"]`);
      if (btn) btn.classList.add('active');
      const sizes = { desktop: '100%', tablet: '768px', mobile: '375px' };
      iframe.style.maxWidth = sizes[size] || '100%';
    },
    closePreview() {
      const overlay = document.getElementById('preview-overlay');
      if (overlay) overlay.classList.remove('open');
    },
    // Model Manager proxy methods (called from rendered card onclick handlers)
    downloadModel(id) { if (window.modelManager) window.modelManager.downloadModel(id); },
    deleteModel(filename, name) { if (window.modelManager) window.modelManager.deleteModel(filename, name); },
    activateModel(filename) { if (window.modelManager) window.modelManager.activateModel(filename); },
  };

  // ---- VoiceInput ---- (extracted to components/voice_input.js)

  // ---- ModelManager ---- (extracted to components/model_manager.js)

  // ---- EditorMode ---- (extracted to studios/editor.js)

  // ---- MediaStudio ---- (extracted to studios/media.js)

  // ---- PresentationStudio ---- (extracted to studios/presentation.js)

  // ---- AutomationStudio ---- (extracted to studios/automation.js)

  // ---- TwitterWatch ---- (extracted to components/twitter_watch.js)


  function applyToolVisibility(settings) {
    const tools = ['automation', 'research', 'media', 'presentation', 'project', 'editor', 'analytics'];
    let currentModeHidden = false;
    const currentMode = sessionStorage.getItem('pt-active-mode') || 'chat';

    tools.forEach(t => {
      const btn = $(`#mode-btn-${t}`);
      const isVisible = settings[`show_${t}`] !== false;
      if (btn) {
        btn.style.display = isVisible ? '' : 'none';
        if (!isVisible && currentMode === t) {
          currentModeHidden = true;
        }
      }
    });

    if (currentModeHidden) {
      const chatBtn = $('#mode-btn-chat');
      if (chatBtn) chatBtn.click();
    }
  }

  // ---- Init ----
  document.addEventListener('DOMContentLoaded', () => {
    // File Tree
    window.ft = new FileTree($('#file-tree'));

    // Expose renderMd/highlightAll for StreamingParser v2 hybrid render
    window._clawzdRenderMd = renderMd;
    window._clawzdHighlightAll = highlightAll;

    // Chat
    window.chat = new Chat();
    window.chat.fileTree = window.ft;

    // Model Manager
    window.modelManager = new ModelManager();

    // Editor Mode
    window.editor = new EditorMode();

    // Media Studio
    window.mediaStudio = new MediaStudio();

    // Presentation Studio
    window.presentationStudio = new PresentationStudio();

    // Automation Studio
    window.automationStudio = new AutomationStudio();

    // Clone Studio (My Clone — sub-mode of Automation)
    window.cloneStudio = new CloneStudio();

    // Vault Studio (Knowledge Vault — sub-mode of Automation)
    if (window.VaultStudio) window.vaultStudio = new VaultStudio();

    // Automation sub-tab toggle (Workflows vs My Clone vs Knowledge Vault)
    $$('#auto-subtab-bar .auto-subtab').forEach(tab => {
      tab.addEventListener('click', () => {
        $$('#auto-subtab-bar .auto-subtab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const sub = tab.dataset.submode;
        window.automationStudio?.toggle(sub === 'workflows');
        window.cloneStudio?.toggle(sub === 'clone');
        window.vaultStudio?.toggle(sub === 'vault');
      });
    });

    // Research Studio
    window.researchStudio = new ResearchStudioV2();

    // Sync token usage from backend
    if (window.tokenTracker) window.tokenTracker.syncFromBackend();

    // --- Shadow Tokenization Prefetch Hook ---
    function attachPrefetchHook(inputElement) {
      if (!inputElement) return;
      let debounceTimer;
      inputElement.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
          const text = inputElement.value || inputElement.innerText || '';
          if (text && text.trim().length > 3) {
            // Assume model from selector or default
            const model = document.getElementById('model-selector')?.value || 'gpt-4o';
            fetch('/api/tokenize/prefetch', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ text: text, model: model })
            }).catch(e => console.debug('Prefetch error:', e));
          }
        }, 300);
      });
    }

    attachPrefetchHook($('#chat-input'));
    attachPrefetchHook($('#editor-chat-input'));

    // Twitter Watch
    // Removed as per user request

    // Project Studio
    if (window.ProjectStudio) window.projectStudio = new ProjectStudio();

    // Analytics Studio
    if (window.AnalyticsStudio) window.analyticsStudio = new AnalyticsStudio();

    // Task Indicator (persistent task badges on mode buttons)
    if (window.TaskIndicator) window.taskIndicator = new TaskIndicator();

    // Auto-select mode from URL if present
    const urlParams = new URLSearchParams(window.location.search);
    const initialMode = urlParams.get('mode') || sessionStorage.getItem('pt-active-mode');
    if (initialMode) {
      setTimeout(() => {
        const initBtn = document.querySelector(`.mode-btn[data-mode="${initialMode}"]`);
        if (initBtn) initBtn.click();
      }, 50);
    }

    // Mode toggle (5 modes: chat, editor, media, presentation, automation)
    $$('#mode-toggle .mode-btn').forEach(btn => {
      btn.addEventListener('mouseup', e => {
        if (e.button === 1) { // Middle click
          e.preventDefault();
          const mode = btn.dataset.mode;
          window.open(`/?mode=${mode}`, '_blank');
        }
      });
      btn.addEventListener('click', () => {
        $$('#mode-toggle .mode-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const mode = btn.dataset.mode;

        // Update URL to preserve state per browser tab
        const url = new URL(window.location);
        if (mode === 'chat') url.searchParams.delete('mode');
        else url.searchParams.set('mode', mode);
        window.history.replaceState({}, '', url);

        sessionStorage.setItem('pt-active-mode', mode);
        window.editor.toggle(mode === 'editor');
        window.mediaStudio.toggle(mode === 'media');
        window.presentationStudio?.toggle(mode === 'presentation');
        // Automation: show sub-tab bar + active sub-mode
        const autoSubBar = $('#auto-subtab-bar');
        if (mode === 'automation') {
          if (autoSubBar) autoSubBar.style.display = 'flex';
          const activeSub = document.querySelector('#auto-subtab-bar .auto-subtab.active');
          const subMode = activeSub?.dataset.submode || 'workflows';
          window.automationStudio?.toggle(subMode === 'workflows');
          window.cloneStudio?.toggle(subMode === 'clone');
          window.vaultStudio?.toggle(subMode === 'vault');
        } else {
          if (autoSubBar) autoSubBar.style.display = 'none';
          window.automationStudio?.toggle(false);
          window.cloneStudio?.toggle(false);
          window.vaultStudio?.toggle(false);
        }
        window.researchStudio?.toggle(mode === 'research');
        window.projectStudio?.toggle(mode === 'project');
        window.analyticsStudio?.toggle(mode === 'analytics');

        // Handle chat visibility globally
        const chatPanel = $('#chat-panel');
        const sidebar = $('#sidebar');
        if (mode === 'chat') {
          if (chatPanel) chatPanel.style.display = '';
          if (sidebar) sidebar.style.display = '';
        } else {
          if (chatPanel) chatPanel.style.display = 'none';
          if (sidebar) sidebar.style.display = 'none';
        }
      });
    });

    // Theme toggle — delegates to ThemeEngine if available
    const themeBtn = $('#btn-theme-toggle');
    const themeIconDark = $('#theme-icon-dark');
    const themeIconLight = $('#theme-icon-light');
    const hljsTheme = $('#hljs-theme');

    // Initialize ThemeEngine (handles saved theme, mermaid re-init, etc.)
    if (window.ThemeEngine) {
      window.ThemeEngine.init();
    }

    // Check local storage for theme (icon sync)
    const savedTheme = localStorage.getItem('omniclaw-theme') || 'dark';
    if (savedTheme === 'light') {
      document.documentElement.classList.add('theme-light');
      if (themeIconDark) themeIconDark.style.display = '';
      if (themeIconLight) themeIconLight.style.display = 'none';
      if (hljsTheme) hljsTheme.href = '/static/css/github.min.css';
    }

    if (themeBtn) {
      themeBtn.addEventListener('click', () => {
        // Use ThemeEngine for full theme management
        if (window.ThemeEngine) {
          window.ThemeEngine.toggle();
        }
        // Still toggle the CSS class and icons for backward compat
        const isLight = document.documentElement.classList.toggle('theme-light');
        localStorage.setItem('omniclaw-theme', isLight ? 'light' : 'dark');
        if (themeIconDark) themeIconDark.style.display = isLight ? '' : 'none';
        if (themeIconLight) themeIconLight.style.display = isLight ? 'none' : '';
        if (hljsTheme) hljsTheme.href = isLight ? '/static/css/github.min.css' : '/static/css/github-dark.min.css';

        // Re-render mermaid diagrams if they exist
        if (window.mermaid) {
          const darkVars = {
            fontFamily: 'inherit', primaryColor: '#252532', primaryTextColor: '#f8fafc', primaryBorderColor: '#3d3d4e',
            lineColor: '#6366f1', secondaryColor: '#2b2b36', tertiaryColor: '#1a1a24', mainBkg: '#1e1e2d', nodeBorder: '#4f46e5',
            clusterBkg: 'transparent', clusterBorder: '#4f46e5', defaultLinkColor: '#818cf8', textColor: '#e2e8f0', edgeLabelBackground: '#2b2b36'
          };
          mermaid.initialize({ theme: isLight ? 'default' : 'base', themeCSS: '.cluster rect { fill: transparent !important; stroke-dasharray: 6 4 !important; stroke-width: 2px !important; }', themeVariables: isLight ? {} : darkVars });
          document.querySelectorAll('.mermaid-container').forEach(el => {
            const id = el.id;
            const code = el.getAttribute('data-code');
            if (code) {
              const decoded = code.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
              try { mermaid.render('mmr-' + id + '-updated', decoded).then(r => { el.innerHTML = r.svg; }); } catch (e) { }
            }
          });
        }
      });
    }

    // Editor file tree buttons
    const eftNew = $('#eft-new-file');
    if (eftNew) eftNew.addEventListener('click', () => window.editor.createFile());
    const eftRefresh = $('#eft-refresh');
    if (eftRefresh) eftRefresh.addEventListener('click', () => window.editor.loadTree());
    const eftFolder = $('#eft-new-folder');
    if (eftFolder) eftFolder.addEventListener('click', () => {
      const name = prompt('Folder name (e.g. src):');
      if (name && name.trim()) {
        // Create folder by creating a .gitkeep file in it
        fetch('/workspace/file', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: name.trim() + '/.gitkeep', content: '' }) })
          .then(() => window.editor.loadTree());
      }
    });

    // Terminal (enhanced with history + help)
    const termInput = $('#editor-terminal-input');
    if (termInput) {
      window.editor.initCommandHistory();
      termInput.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
          const cmd = termInput.value;
          if (cmd === '?' || cmd === 'help') { window.editor.showTerminalHelp(); termInput.value = ''; return; }
          window.editor.pushHistory(cmd);
          window.editor.runCommand(cmd);
          termInput.value = '';
          // Close help popup if open
          const hp = $('#term-help-popup'); if (hp) hp.classList.remove('open');
        }
        if (e.key === 'ArrowUp') { e.preventDefault(); termInput.value = window.editor.historyUp(); }
        if (e.key === 'ArrowDown') { e.preventDefault(); termInput.value = window.editor.historyDown(); }
        if (e.key === 'Escape') { const hp = $('#term-help-popup'); if (hp) hp.classList.remove('open'); }
      });
    }
    const termToggle = $('#editor-terminal-toggle');
    if (termToggle) termToggle.addEventListener('click', e => { e.stopPropagation(); $('#editor-terminal').classList.toggle('collapsed'); });
    const termHeader = $('#editor-terminal-header');
    if (termHeader) termHeader.addEventListener('click', () => $('#editor-terminal').classList.toggle('collapsed'));
    const termClear = $('#editor-terminal-clear');
    if (termClear) termClear.addEventListener('click', e => { e.stopPropagation(); $('#editor-terminal-body').innerHTML = ''; });
    // Terminal help button
    const termHelp = $('#editor-terminal-help');
    if (termHelp) termHelp.addEventListener('click', () => window.editor.showTerminalHelp());

    // Terminal resize handle
    const termResize = $('#editor-terminal-resize');
    const termPanel = $('#editor-terminal');
    if (termResize && termPanel) {
      let resizing = false, startY = 0, startH = 0;
      termResize.addEventListener('mousedown', e => {
        e.preventDefault();
        resizing = true;
        startY = e.clientY;
        startH = termPanel.offsetHeight;
        termResize.classList.add('active');
        document.body.style.cursor = 'ns-resize';
        document.body.style.userSelect = 'none';
      });
      document.addEventListener('mousemove', e => {
        if (!resizing) return;
        const dy = startY - e.clientY;
        const newH = Math.max(60, Math.min(startH + dy, window.innerHeight * 0.7));
        termPanel.style.height = newH + 'px';
        termPanel.classList.remove('collapsed');
      });
      document.addEventListener('mouseup', () => {
        if (!resizing) return;
        resizing = false;
        termResize.classList.remove('active');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      });
    }

    // Terminal copy button
    const termCopy = $('#editor-terminal-copy');
    if (termCopy) termCopy.addEventListener('click', e => {
      e.stopPropagation();
      const body = $('#editor-terminal-body');
      const text = body ? body.innerText : '';
      if (text) {
        navigator.clipboard.writeText(text).then(() => toast('Terminal content copied'));
      } else {
        toast('Terminal is empty');
      }
    });

    // ---- Left/Right Panel Resize ----
    const editorLayout = $('#editor-layout');
    function setupPanelResize(handleId, cssVar, side) {
      const handle = $(handleId);
      if (!handle || !editorLayout) return;
      let dragging = false, startX = 0, startW = 0;
      handle.addEventListener('mousedown', e => {
        e.preventDefault();
        dragging = true;
        startX = e.clientX;
        const panel = side === 'left' ? $('#editor-file-tree') : $('#editor-right');
        startW = panel ? panel.offsetWidth : 240;
        handle.classList.add('active');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
      });
      document.addEventListener('mousemove', e => {
        if (!dragging) return;
        const dx = e.clientX - startX;
        const newW = side === 'left' ? Math.max(140, Math.min(startW + dx, 500)) : Math.max(200, Math.min(startW - dx, 600));
        editorLayout.style.setProperty(cssVar, newW + 'px');
      });
      document.addEventListener('mouseup', () => {
        if (!dragging) return;
        dragging = false;
        const handle2 = $(handleId);
        if (handle2) handle2.classList.remove('active');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      });
    }
    setupPanelResize('#editor-resize-left', '--left-w', 'left');
    setupPanelResize('#editor-resize-right', '--right-w', 'right');

    // ---- Project Switcher ----
    const projSelect = $('#project-select');
    if (projSelect) projSelect.addEventListener('change', () => window.editor.switchProject(projSelect.value));
    const projHistory = $('#project-history-btn');
    if (projHistory) projHistory.addEventListener('click', () => window.editor.showProjectHistory());
    const projClose = $('#project-close-btn');
    if (projClose) projClose.addEventListener('click', () => window.editor.closeProject());
    // Init project list
    window.editor.loadProjects();

    // Right panel tabs (Activity / Chat / Todo / Git / Twitter)
    // Right panel tabs (Activity / Chat / Todo / Git)
    $$('.editor-right-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        $$('.editor-right-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const panel = tab.dataset.panel;
        $('#editor-activity').classList.toggle('active', panel === 'activity');
        $('#editor-chat').classList.toggle('active', panel === 'chat');
        $('#editor-todo')?.classList.toggle('active', panel === 'todo');
        $('#editor-git').classList.toggle('active', panel === 'git');
        // Load git data when switching to git tab
        if (panel === 'git') {
          window.editor.loadGitStatus();
          window.editor.loadGitLog();
        }
        // Render todos when switching to todo tab
        if (panel === 'todo') {
          window.editor.renderTodos();
        }
      });
    });

    // Agent Mode Toggle buttons
    $$('.agent-mode-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        window.editor.setAgentMode(btn.dataset.agent);
      });
    });

    // Reset Chat button
    const chatResetBtn = $('#editor-chat-reset');
    if (chatResetBtn) chatResetBtn.addEventListener('click', () => window.editor._cmdClear());

    // Todo Panel buttons
    const todoAddBtn = $('#todo-add-btn');
    if (todoAddBtn) todoAddBtn.addEventListener('click', () => {
      const text = prompt('New task:');
      if (text) window.editor.addTodo(text);
    });
    const todoClearBtn = $('#todo-clear-done');
    if (todoClearBtn) todoClearBtn.addEventListener('click', () => window.editor.clearDoneTodos());
    // Init todo render
    window.editor.renderTodos();

    // Context compact button
    const compactBtn = $('#ctx-bar-compact');
    if (compactBtn) compactBtn.addEventListener('click', () => window.editor._cmdCompact());

    // Git buttons
    const gitPull = $('#git-btn-pull');
    if (gitPull) gitPull.addEventListener('click', () => window.editor.gitPull());
    const gitPush = $('#git-btn-push');
    if (gitPush) gitPush.addEventListener('click', () => window.editor.gitPush());
    const gitStageAll = $('#git-btn-stage-all');
    if (gitStageAll) gitStageAll.addEventListener('click', () => window.editor.gitStageAll());
    const gitRefresh = $('#git-btn-refresh');
    if (gitRefresh) gitRefresh.addEventListener('click', () => { window.editor.loadGitStatus(); window.editor.loadGitLog(); });
    const gitCommit = $('#git-btn-commit');
    if (gitCommit) gitCommit.addEventListener('click', () => window.editor.gitCommit(false));
    const gitCommitPush = $('#git-btn-commit-push');
    if (gitCommitPush) gitCommitPush.addEventListener('click', () => window.editor.gitCommit(true));
    // Commit message Enter key
    const gitCommitMsg = $('#git-commit-msg');
    if (gitCommitMsg) gitCommitMsg.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) window.editor.gitCommit(false);
      if (e.key === 'Enter' && e.shiftKey) window.editor.gitCommit(true);
    });

    // Git view toggle (Status vs Graph)
    $$('.git-view-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        $$('.git-view-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const view = btn.dataset.view;
        $('#git-status-view').classList.toggle('active', view === 'status');
        $('#git-graph-view').classList.toggle('active', view === 'graph');
        if (view === 'graph') window.editor.loadGitLog();
      });
    });

    // Editor chat send
    const ecSend = $('#editor-chat-send');
    if (ecSend) ecSend.addEventListener('click', () => window.editor.sendEditorChat());
    const ecInput = $('#editor-chat-input');
    if (ecInput) {
      // Enhanced keydown: @file refs, popup navigation, Tab for mode switch
      ecInput.addEventListener('keydown', e => {
        const fileRefOpen = $('#file-ref-popup')?.classList.contains('open');

        // Tab key: if popup open, select; otherwise toggle agent mode
        if (e.key === 'Tab') {
          e.preventDefault();
          if (fileRefOpen) { window.editor.selectFileRef(); return; }
          // Toggle agent mode
          window.editor.setAgentMode(window.editor.agentMode === 'build' ? 'plan' : 'build');
          return;
        }

        // Arrow navigation in popups
        if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
          if (fileRefOpen) {
            e.preventDefault();
            window.editor.navigateFileRefPopup(e.key === 'ArrowUp' ? -1 : 1);
            return;
          }
        }

        // Enter: if popup open, select; otherwise send
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          if (fileRefOpen && window.editor.selectFileRef()) return;
          window.editor.sendEditorChat();
          return;
        }

        // Escape: close popups
        if (e.key === 'Escape') {
          if (fileRefOpen) { window.editor.hideFileRefPopup(); return; }
        }
      });

      // Input handler: @file detection
      ecInput.addEventListener('input', () => {
        ecInput.style.height = 'auto';
        ecInput.style.height = Math.min(ecInput.scrollHeight, 80) + 'px';
        const val = ecInput.value;
        // Check for @file references
        if (val.includes('@')) {
          window.editor._handleAtInput(val);
        } else {
          window.editor.hideFileRefPopup();
        }
      });
    }

    // Context modal
    const ctxBtn = $('#eft-context-btn');
    if (ctxBtn) ctxBtn.addEventListener('click', () => window.editor.loadContext());
    const ctxClose = $('#context-close');
    if (ctxClose) ctxClose.addEventListener('click', () => $('#context-overlay').classList.remove('open'));
    const ctxCancel = $('#context-cancel');
    if (ctxCancel) ctxCancel.addEventListener('click', () => $('#context-overlay').classList.remove('open'));
    const ctxSave = $('#context-save');
    if (ctxSave) ctxSave.addEventListener('click', () => window.editor.saveContext());
    const ctxOverlay = $('#context-overlay');
    if (ctxOverlay) ctxOverlay.addEventListener('click', e => { if (e.target === ctxOverlay) ctxOverlay.classList.remove('open'); });

    // Diff viewer
    const diffClose = $('#diff-close');
    if (diffClose) diffClose.addEventListener('click', () => $('#editor-diff-overlay').classList.remove('open'));
    const diffReject = $('#diff-reject');
    if (diffReject) diffReject.addEventListener('click', () => { window.editor._pendingDiff = null; $('#editor-diff-overlay').classList.remove('open'); });
    const diffAccept = $('#diff-accept');
    if (diffAccept) diffAccept.addEventListener('click', () => window.editor.acceptDiff());
    const diffOverlay = $('#editor-diff-overlay');
    if (diffOverlay) diffOverlay.addEventListener('click', e => { if (e.target === diffOverlay) diffOverlay.classList.remove('open'); });

    // Git Clone modal
    const gitCloneBtn = $('#eft-git-clone');
    if (gitCloneBtn) gitCloneBtn.addEventListener('click', () => window.editor.openGitClone());
    const gitCloneClose = $('#git-clone-close');
    if (gitCloneClose) gitCloneClose.addEventListener('click', () => $('#git-clone-overlay').classList.remove('open'));
    const gitCloneCancel = $('#git-clone-cancel');
    if (gitCloneCancel) gitCloneCancel.addEventListener('click', () => $('#git-clone-overlay').classList.remove('open'));
    const gitCloneSubmit = $('#git-clone-submit');
    if (gitCloneSubmit) gitCloneSubmit.addEventListener('click', () => window.editor.doGitClone());
    const gitCloneOverlay = $('#git-clone-overlay');
    if (gitCloneOverlay) gitCloneOverlay.addEventListener('click', e => { if (e.target === gitCloneOverlay) gitCloneOverlay.classList.remove('open'); });
    // Enter key in URL field triggers clone
    const gitCloneUrl = $('#git-clone-url');
    if (gitCloneUrl) gitCloneUrl.addEventListener('keydown', e => { if (e.key === 'Enter') window.editor.doGitClone(); });

    // File Search in Explorer is now handled by the central Editor search button

    const eftCreateLogoBtn = $('#eft-create-logo');
    if (eftCreateLogoBtn) eftCreateLogoBtn.addEventListener('click', async () => {
      const mediaBtn = document.querySelector('.mode-btn[data-mode="media"]');
      if (mediaBtn) {
        mediaBtn.click();
        const styleSelect = $('#media-style');
        if (styleSelect) styleSelect.value = 'logo';
        const promptInput = $('#media-prompt');
        if (promptInput) {
          promptInput.value = 'Generating perfect logo prompt from your project...';
          try {
            // Fetch context from API (more reliable than textarea which may not be loaded)
            let ctxVal = '';
            try {
              const ctxRes = await fetch('/workspace/context');
              const ctxData = await ctxRes.json();
              ctxVal = ctxData.content || '';
            } catch (_) { }
            const activeProject = $('#project-select')?.value || '.';
            const res = await fetch('/image/suggest-prompt', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ context: ctxVal, target: 'logo', project: activeProject })
            });
            const data = await res.json();
            promptInput.value = data.prompt;
            promptInput.focus();
            toast(ICONS.palette(14) + ' Ready to create your logo!');
          } catch (e) {
            promptInput.value = 'A professional logo for the project, minimal design, flat vector graphic, clean background';
            toast(ICONS.circle(14) + ' ️ Could not generate context prompt, using default.');
          }
        }
      }
    });

    const eftCreatePresBtn = $('#eft-create-pres');
    if (eftCreatePresBtn) eftCreatePresBtn.addEventListener('click', async () => {
      const presBtn = document.querySelector('.mode-btn[data-mode="presentation"]');
      if (presBtn) {
        presBtn.click();
        const promptInput = $('#pt-ai-prompt');
        if (promptInput) {
          promptInput.value = 'Generating perfect presentation topic from your project...';
          try {
            // Fetch context from API (more reliable than textarea which may not be loaded)
            let ctxVal = '';
            try {
              const ctxRes = await fetch('/workspace/context');
              const ctxData = await ctxRes.json();
              ctxVal = ctxData.content || '';
            } catch (_) { }
            const activeProject = $('#project-select')?.value || '.';
            const res = await fetch('/image/suggest-prompt', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ context: ctxVal, target: 'presentation', project: activeProject })
            });
            const data = await res.json();
            promptInput.value = data.prompt;
            promptInput.focus();
            toast(ICONS.barChart(14) + ' Ready to create your presentation!');
          } catch (e) {
            promptInput.value = 'Pitch deck for the new project';
            toast(ICONS.circle(14) + ' ️ Could not generate context prompt, using default.');
          }
        } else {
          toast(ICONS.barChart(14) + ' Ready to create your presentation!');
        }
      }
    });

    const eftImportMediaBtn = $('#eft-import-media');
    if (eftImportMediaBtn) {
      eftImportMediaBtn.addEventListener('click', async () => {
        try {
          const r = await fetch('/image/gallery');
          const d = await r.json();
          const images = (d.images || []).filter(i => !['mp4', 'gif'].includes(i.format));
          if (!images.length) {
            toast(ICONS.x(14) + ' No images found in media gallery.');
            return;
          }
          const modal = document.createElement('div');
          modal.className = 'settings-overlay open';
          modal.style.zIndex = '10000';
          let html = `
            <div class="settings-drawer" style="width:500px; max-width:90%; padding:20px; border-radius:8px;">
              <h3 style="margin-top:0;">Select Image to Import</h3>
              <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(100px, 1fr)); gap:10px; max-height:400px; overflow-y:auto; margin-bottom:20px;">
          `;
          images.forEach(img => {
            html += `<div class="media-import-item" data-filename="${escHtml(img.filename)}" style="cursor:pointer; border:2px solid transparent; border-radius:4px; overflow:hidden;">
              <img src="/data/images/${encodeURIComponent(img.filename)}" style="width:100%; height:100px; object-fit:cover;">
              <div style="font-size:10px; text-align:center; padding:2px; background:var(--bg-elevated); text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">${escHtml(img.filename)}</div>
            </div>`;
          });
          html += `
              </div>
              <div style="display:flex; justify-content:flex-end; gap:10px;">
                <button class="btn btn-secondary" id="media-import-cancel">Cancel</button>
              </div>
            </div>
          `;
          modal.innerHTML = html;
          document.body.appendChild(modal);

          modal.querySelector('#media-import-cancel').addEventListener('click', () => modal.remove());

          const items = modal.querySelectorAll('.media-import-item');
          items.forEach(item => {
            item.addEventListener('click', async () => {
              const filename = item.dataset.filename;
              modal.remove();
              try {
                const imgRes = await fetch(`/data/images/${filename}`);
                const blob = await imgRes.blob();
                const file = new File([blob], filename, { type: blob.type });
                if (window.editor) {
                  window.editor.uploadFiles([file]);
                  toast(`${ICONS.check(14)} Imported ${filename} into project.`);
                }
              } catch (err) {
                toast(ICONS.x(14) + ' Failed to import image');
              }
            });
            item.addEventListener('mouseover', () => item.style.borderColor = 'var(--accent)');
            item.addEventListener('mouseout', () => item.style.borderColor = 'transparent');
          });
        } catch (e) {
          toast(ICONS.x(14) + ' Failed to load media gallery');
        }
      });
    }
    const searchInput = $('#editor-search-input');
    if (searchInput) {
      let searchTimer = null;
      searchInput.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => window.editor.searchFiles(searchInput.value), 400);
      });
      searchInput.addEventListener('keydown', e => {
        if (e.key === 'Enter') { clearTimeout(searchTimer); window.editor.searchFiles(searchInput.value); }
        if (e.key === 'Escape') { $('#editor-search-bar').classList.remove('open'); }
      });
    }
    const searchClose = $('#editor-search-close');
    if (searchClose) searchClose.addEventListener('click', () => {
      $('#editor-search-bar').classList.remove('open');
      $('#editor-search-input').value = '';
      $('#editor-search-info').textContent = '';
    });
    // Ctrl+Shift+F global shortcut for search
    document.addEventListener('keydown', e => {
      if (e.ctrlKey && e.shiftKey && e.key === 'F' && window.editor.active) {
        e.preventDefault();
        $('#editor-search-bar').classList.add('open');
        $('#editor-search-input').focus();
      }
      // Ctrl+F for Find
      if (e.ctrlKey && e.key === 'f' && window.editor.active) {
        e.preventDefault();
        window.editor.openFindReplace();
      }
      // Ctrl+H for Find & Replace
      if (e.ctrlKey && e.key === 'h' && window.editor.active) {
        e.preventDefault();
        window.editor.openFindReplace();
      }
    });

    // Find & Replace buttons
    const findInput = $('#find-input');
    if (findInput) findInput.addEventListener('input', () => {
      if (window.editor && window.editor.active) window.editor._updateSearchHighlight();
    });
    const findNextBtn = $('#find-next-btn');
    if (findNextBtn) findNextBtn.addEventListener('click', () => window.editor.findNext());
    const replaceNextBtn = $('#replace-next-btn');
    if (replaceNextBtn) replaceNextBtn.addEventListener('click', () => window.editor.replaceNext());
    const replaceAllBtn = $('#replace-all-btn');
    if (replaceAllBtn) replaceAllBtn.addEventListener('click', () => window.editor.replaceAll());
    const findBarClose = $('#find-bar-close');
    if (findBarClose) findBarClose.addEventListener('click', () => window.editor.closeFindReplace());
    const findInputEl = $('#find-input');
    if (findInputEl) {
      findInputEl.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); window.editor.findNext(); }
        if (e.key === 'Escape') window.editor.closeFindReplace();
      });
    }
    const replaceInputEl = $('#replace-input');
    if (replaceInputEl) {
      replaceInputEl.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); window.editor.replaceNext(); }
        if (e.key === 'Escape') window.editor.closeFindReplace();
      });
    }

    // ---- Editor Toolbar (undo/redo/autocomplete) ----
    const etbFind = $('#etb-find');
    if (etbFind) etbFind.addEventListener('click', () => {
      if (window.editor) window.editor.openFindReplace();
    });
    const etbUndo = $('#etb-undo');
    if (etbUndo) etbUndo.addEventListener('click', () => {
      const ta = document.querySelector('#code-textarea');
      if (ta) { ta.focus(); document.execCommand('undo'); }
    });
    const etbRedo = $('#etb-redo');
    if (etbRedo) etbRedo.addEventListener('click', () => {
      const ta = document.querySelector('#code-textarea');
      if (ta) { ta.focus(); document.execCommand('redo'); }
    });
    const etbAc = $('#etb-autocomplete');
    if (etbAc) etbAc.addEventListener('click', () => {
      if (!window.editor) return;
      window.editor._acEnabled = !window.editor._acEnabled;
      etbAc.classList.toggle('active', window.editor._acEnabled);
      if (!window.editor._acEnabled) {
        window.editor._clearGhost();
        clearTimeout(window.editor._acTimer);
      }
      toast(window.editor._acEnabled ? ' Autocomplete ON' : ' Autocomplete OFF');
    });

    // ---- Preview Button ----
    const etbPreview = $('#etb-preview');
    if (etbPreview) {
      etbPreview.addEventListener('click', () => {
        if (!window.editor || !window.editor.activeTab) {
          toast(ICONS.x(14) + ' Open an HTML file to preview');
          return;
        }
        const path = window.editor.activeTab;
        if (!path.endsWith('.html') && !path.endsWith('.htm')) {
          toast(ICONS.x(14) + ' Only HTML files can be previewed');
          return;
        }
        let overlay = $('#editor-preview-overlay');
        if (!overlay) {
          overlay = document.createElement('div');
          overlay.id = 'editor-preview-overlay';
          overlay.className = 'settings-overlay';
          overlay.innerHTML = `
            <div class="settings-drawer" style="width: 80vw; max-width: 1200px; height: 90vh; display: flex; flex-direction: column; padding: 0;">
              <div class="settings-header" style="padding: 15px 20px; border-bottom: 1px solid var(--border);">
                <h3 style="margin: 0; display: flex; align-items: center; gap: 8px;">
                  <svg class="ic" width="16" height="16"><use href="#icon-play"></use></svg> 
                  <span id="preview-title">Preview</span>
                </h3>
                <button class="icon-btn" id="preview-close" style="margin-left:auto"><svg class="ic" width="20" height="20"><use href="#icon-x"></use></svg></button>
              </div>
              <div class="settings-body" style="flex: 1; padding: 0; overflow: hidden; background: #fff;">
                <iframe id="preview-iframe" style="width:100%; height:100%; border:none; background:#fff;"></iframe>
              </div>
            </div>
          `;
          document.body.appendChild(overlay);
          $('#preview-close').addEventListener('click', () => overlay.classList.remove('open'));
        }
        $('#preview-title').textContent = 'Preview: ' + path;

        // Add timestamp to prevent caching
        const ts = new Date().getTime();
        $('#preview-iframe').src = '/workspace/file-raw?path=' + encodeURIComponent(path) + '&_t=' + ts;
        overlay.classList.add('open');
      });
    }

    // ---- Export Button ----
    const etbExport = $('#etb-export');
    if (etbExport) {
      etbExport.addEventListener('click', () => {
        const projSelect = $('#project-select');
        const project = projSelect ? projSelect.value || '.' : '.';
        window.open('/workspace/export-zip?project=' + encodeURIComponent(project), '_blank');
        toast(ICONS.download(14) + ' Exporting project as ZIP...');
      });
    }

    // ---- Audit Button ----
    const etbAudit = $('#etb-audit');
    if (etbAudit) etbAudit.addEventListener('click', () => {
      const overlay = $('#audit-overlay');
      const body = $('#audit-body');
      if (!overlay || !body) return;
      overlay.classList.add('open');
      body.innerHTML = `
        <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; height:100%; text-align:center; padding: 2rem;">
          <svg class="ic" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="margin-bottom:1rem;">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
          </svg>
          <h3 style="margin-bottom:0.5rem;">Ready to Audit</h3>
          <p style="color:var(--text-muted); margin-bottom:1.5rem; max-width:400px;">
            Run a full security and quality audit on your workspace. This may take a few moments depending on the project size.
          </p>
          <button class="btn btn-primary" id="start-audit-btn" style="padding:10px 24px; font-size:14px;">
            <svg class="ic" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
            Start Audit
          </button>
        </div>
      `;

      $('#start-audit-btn').addEventListener('click', async () => {
        body.innerHTML = `
          <div class="audit-loading">
            <div class="spinner"></div>
            <div style="font-weight:600;margin-bottom:8px;">Running Project Audit...</div>
            <div id="audit-log" style="text-align:left; font-family:'JetBrains Mono', monospace; font-size:11px; color:var(--text-muted); background:var(--bg-primary); padding:10px; border-radius:4px; width:100%; max-width:500px; height:120px; overflow-y:auto; border:1px solid var(--border);"></div>
          </div>`;

        const logEl = body.querySelector('#audit-log');

        // Store prompt for later
        window._auditPrompt = '';
        try {
          const projSelect = $('#project-select');
          const target = projSelect ? projSelect.value || '.' : '.';
          const resp = await fetch('/code/audit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode: 'full', target, stream: true }),
          });

          const reader = resp.body.getReader();
          const decoder = new TextDecoder();
          let data = null;

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');
            for (const line of lines) {
              if (!line.trim()) continue;
              try {
                const msg = JSON.parse(line);
                if (msg.status === 'progress' && logEl) {
                  const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                  logEl.innerHTML += `<div><span style="opacity:0.5">[${timeStr}]</span> ${escHtml(msg.message)}</div>`;
                  logEl.scrollTop = logEl.scrollHeight;
                } else if (msg.status === 'done') {
                  data = msg.result;
                } else if (msg.status === 'error') {
                  throw new Error(msg.error);
                }
              } catch (e) {
                if (e.message !== "Unexpected end of JSON input" && !line.includes("{")) {
                  throw e; // rethrow actual errors, ignore json parse fragments if any (though ndjson shouldn't fragment across \n)
                }
              }
            }
          }

          if (!data) {
            body.innerHTML = `<div class="audit-empty"><div class="check">️</div><p>Audit failed to return results.</p></div>`;
            return;
          }

          if (data.error) {
            body.innerHTML = `<div class="audit-empty"><div class="check">️</div><p>${escHtml(data.error)}</p></div>`;
            return;
          }
          // Build report
          const findings = data.findings || [];
          const sev = data.severity || {};
          const total = data.total_findings || findings.length;
          if (total === 0) {
            body.innerHTML = '<div class="audit-empty"><div class="check">' + ICONS.check(24) + '</div><p>No issues found — your project looks clean!</p></div>';
            window._auditPrompt = 'Audit result: no issues found. The project code is clean.';
            return;
          }
          // Stats cards
          let html = '<div class="audit-stats">';
          html += `<div class="audit-stat total"><div class="audit-stat-value">${total}</div><div class="audit-stat-label">Total</div></div>`;
          html += `<div class="audit-stat critical"><div class="audit-stat-value">${sev.CRITICAL || 0}</div><div class="audit-stat-label">Critical</div></div>`;
          html += `<div class="audit-stat high"><div class="audit-stat-value">${sev.HIGH || 0}</div><div class="audit-stat-label">High</div></div>`;
          html += `<div class="audit-stat medium"><div class="audit-stat-value">${sev.MEDIUM || 0}</div><div class="audit-stat-label">Medium</div></div>`;
          html += `<div class="audit-stat low"><div class="audit-stat-value">${sev.LOW || 0}</div><div class="audit-stat-label">Low</div></div>`;
          html += '</div>';
          // Scanners used banner
          const scanners = data.scanners_used || [];
          if (scanners.length) {
            html += `<div style="margin-bottom:12px;font-size:12px;color:var(--text-muted);"> Scanners: <strong>${scanners.join(', ')}</strong></div>`;
          }
          // Sort findings by severity: CRITICAL > HIGH > MEDIUM > LOW
          const sevOrder = { critical: 0, high: 1, medium: 2, low: 3 };
          findings.sort((a, b) => {
            const sa = (a.severity || 'medium').toLowerCase();
            const sb = (b.severity || 'medium').toLowerCase();
            return (sevOrder[sa] ?? 99) - (sevOrder[sb] ?? 99);
          });
          // Findings table (max 50 rows)
          html += '<table class="audit-findings-table"><thead><tr>';
          html += '<th>Tool</th><th>Type</th><th>Severity</th><th>File</th><th>Line</th><th>Issue</th></tr></thead><tbody>';
          const shown = findings.slice(0, 50);
          for (const f of shown) {
            const s = (f.severity || 'medium').toLowerCase();
            const file = (f.file || '').split('/').slice(-2).join('/');
            html += `<tr>
            <td>${escHtml(f.tool || '')}</td>
            <td>${escHtml(f.type || '')}</td>
            <td><span class="audit-sev-badge ${s}">${s}</span></td>
            <td title="${escHtml(f.file || '')}">${escHtml(file)}</td>
            <td>${f.line || '—'}</td>
            <td>${escHtml((f.message || '').slice(0, 120))}</td>
          </tr>`;
          }
          if (findings.length > 50) {
            html += `<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:12px;">… and ${findings.length - 50} more findings</td></tr>`;
          }
          html += '</tbody></table>';
          // Build correction prompt
          let prompt = `You are a senior software engineer. The following project audit found ${total} issues:\n\n`;
          prompt += `**Severity breakdown:** CRITICAL: ${sev.CRITICAL || 0}, HIGH: ${sev.HIGH || 0}, MEDIUM: ${sev.MEDIUM || 0}, LOW: ${sev.LOW || 0}\n\n`;
          prompt += `**Top findings to fix (priority order):**\n`;
          // Group by severity, highest first
          const prio = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];
          let count = 0;
          for (const p of prio) {
            for (const f of findings) {
              if (count >= 20) break;
              if ((f.severity || '').toUpperCase() === p) {
                count++;
                prompt += `${count}. [${p}] ${f.file || 'unknown'}${f.line ? ':' + f.line : ''} — ${f.message || 'no description'}\n`;
              }
            }
          }
          prompt += `\nPlease analyze these issues and provide:\n1. A corrected version of the most critical files\n2. Explanations for each fix\n3. Security best practices to apply\n\nFocus on CRITICAL and HIGH severity issues first.`;
          window._auditPrompt = prompt;
          // Show export button if report URL available
          const reportUrl = data.report_html_url;
          if (reportUrl) {
            window._auditReportUrl = reportUrl;
            const exportBtn = $('#audit-export-html');
            if (exportBtn) exportBtn.style.display = '';
          }
          // Prompt section
          html += '<div class="audit-prompt-section">';
          html += '<h4>Correction Prompt</h4>';
          html += `<div class="audit-prompt-text">${escHtml(prompt)}</div>`;
          html += '</div>';
          body.innerHTML = html;
        } catch (err) {
          body.innerHTML = `<div class="audit-empty"><div class="check">' + ICONS.x(24) + '</div><p>Audit failed: ${escHtml(err.message)}</p></div>`;
        }
      });
    });
    // Audit overlay controls
    const auditClose = $('#audit-close');
    if (auditClose) auditClose.addEventListener('click', () => $('#audit-overlay').classList.remove('open'));
    const auditCopy = $('#audit-copy-prompt');
    if (auditCopy) auditCopy.addEventListener('click', () => {
      if (!window._auditPrompt) { toast(ICONS.x(14) + ' No prompt to copy'); return; }
      // Try modern clipboard API first, fallback to execCommand
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(window._auditPrompt)
          .then(() => toast(ICONS.copy(14) + ' Prompt copied to clipboard'))
          .catch(() => _fallbackCopy(window._auditPrompt));
      } else {
        _fallbackCopy(window._auditPrompt);
      }
    });
    function _fallbackCopy(text) {
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px;opacity:0;';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        toast(ok ? ICONS.copy(14) + ' Prompt copied to clipboard' : ICONS.x(14) + ' Copy failed — select text manually');
      } catch (e) {
        toast(ICONS.x(14) + ' Copy failed — select text manually');
      }
    }
    const auditSend = $('#audit-send-prompt');
    if (auditSend) auditSend.addEventListener('click', () => {
      if (window._auditPrompt && window.chat) {
        const input = $('#chat-input');
        if (input) {
          input.value = window._auditPrompt;
          input.dispatchEvent(new Event('input'));
        }
        // Switch to chat mode
        const chatBtn = $('[data-mode="chat"]');
        if (chatBtn) chatBtn.click();
        $('#audit-overlay').classList.remove('open');
        toast(ICONS.check(14) + ' Prompt sent to chat');
      }
    });
    const auditExport = $('#audit-export-html');
    if (auditExport) auditExport.addEventListener('click', () => {
      if (window._auditReportUrl) {
        window.open(window._auditReportUrl, '_blank');
      }
    });

    // ---- Audit History ----
    const auditHistoryBtn = $('#audit-history-btn');
    if (auditHistoryBtn) auditHistoryBtn.addEventListener('click', async () => {
      const overlay = $('#audit-history-overlay');
      const body = $('#audit-history-body');
      if (!overlay || !body) return;
      overlay.classList.add('open');
      body.innerHTML = '<div class="audit-loading"><div class="spinner"></div><div>Loading audit history…</div></div>';
      try {
        const resp = await fetch('/code/audit/history');
        const data = await resp.json();
        const reports = data.reports || [];
        if (!reports.length) {
          body.innerHTML = '<div class="audit-history-empty"><div class="icon">' + ICONS.folderOpen(24) + '</div><p>No previous audit reports found.<br><small>Run an audit to see results here.</small></p></div>';
          return;
        }
        let html = '<div class="audit-history-list">';
        for (const r of reports) {
          const sev = r.severity || {};
          const pathShort = (r.scanned_path || '').split('/').slice(-2).join('/') || '—';
          const ts = r.timestamp || r.report_id.replace(/_/g, ' ').slice(0, 15);
          html += `<div class="audit-history-card" data-report-id="${escHtml(r.report_id)}">
            <div class="audit-history-card-top">
              <div>
                <div class="audit-history-card-date">${ICONS.clock(14)} ${escHtml(ts)}</div>
                <div class="audit-history-card-path" title="${escHtml(r.scanned_path || '')}">${escHtml(pathShort)}</div>
              </div>
              <div class="audit-history-card-total">${r.total}<small>findings</small></div>
            </div>
            <div class="audit-history-card-badges">
              ${(sev.CRITICAL || 0) > 0 ? `<span class="audit-history-badge critical">${ICONS.circle(12)} ${sev.CRITICAL} Critical</span>` : ''}
              ${(sev.HIGH || 0) > 0 ? `<span class="audit-history-badge high">${ICONS.circle(12)} ${sev.HIGH} High</span>` : ''}
              ${(sev.MEDIUM || 0) > 0 ? `<span class="audit-history-badge medium">${ICONS.circle(12)} ${sev.MEDIUM} Medium</span>` : ''}
              ${(sev.LOW || 0) > 0 ? `<span class="audit-history-badge low">${ICONS.circle(12)} ${sev.LOW} Low</span>` : ''}
            </div>
            <div class="audit-history-card-actions">
              <button class="btn btn-primary btn-sm audit-hist-load" data-rid="${escHtml(r.report_id)}" title="Load this report">${ICONS.barChart(14)} View Report</button>
              ${r.has_html ? `<button class="btn btn-secondary btn-sm audit-hist-html" data-rid="${escHtml(r.report_id)}" title="Open HTML in new tab">${ICONS.fileText(14)} HTML</button>` : ''}
            </div>
          </div>`;
        }
        html += '</div>';
        body.innerHTML = html;

        // Bind card actions
        body.querySelectorAll('.audit-hist-load').forEach(btn => {
          btn.addEventListener('click', e => {
            e.stopPropagation();
            _loadPastAudit(btn.dataset.rid);
          });
        });
        body.querySelectorAll('.audit-hist-html').forEach(btn => {
          btn.addEventListener('click', e => {
            e.stopPropagation();
            window.open(`/code/audit/report/${btn.dataset.rid}?format=html`, '_blank');
          });
        });
        // Also allow clicking the whole card to load
        body.querySelectorAll('.audit-history-card').forEach(card => {
          card.addEventListener('click', () => {
            _loadPastAudit(card.dataset.reportId);
          });
        });
      } catch (err) {
        body.innerHTML = `<div class="audit-history-empty"><div class="icon">' + ICONS.x(24) + '</div><p>Failed to load history: ${escHtml(err.message)}</p></div>`;
      }
    });

    async function _loadPastAudit(reportId) {
      // Close history modal
      const histOverlay = $('#audit-history-overlay');
      if (histOverlay) histOverlay.classList.remove('open');
      // Open audit overlay with loading
      const overlay = $('#audit-overlay');
      const body = $('#audit-body');
      if (!overlay || !body) return;
      overlay.classList.add('open');
      body.innerHTML = '<div class="audit-loading"><div class="spinner"></div><div>Loading past report…</div></div>';
      try {
        const resp = await fetch(`/code/audit/report/${reportId}?format=json`);
        const data = await resp.json();
        const findings = data.findings || [];
        const total = data.total || findings.length;
        // Build severity counts
        const sev = {};
        for (const f of findings) {
          const s = (f.severity || 'MEDIUM').toUpperCase();
          sev[s] = (sev[s] || 0) + 1;
        }
        if (total === 0) {
          body.innerHTML = '<div class="audit-empty"><div class="check">' + ICONS.check(24) + '</div><p>No issues found in this report.</p></div>';
          window._auditPrompt = '';
          return;
        }
        // Stats cards
        let html = `<div style="margin-bottom:10px;font-size:11px;color:var(--text-muted);">${ICONS.folder(14)} Report: <strong>${escHtml(reportId)}</strong> — ${escHtml(data.timestamp || '')}</div>`;
        html += '<div class="audit-stats">';
        html += `<div class="audit-stat total"><div class="audit-stat-value">${total}</div><div class="audit-stat-label">Total</div></div>`;
        html += `<div class="audit-stat critical"><div class="audit-stat-value">${sev.CRITICAL || 0}</div><div class="audit-stat-label">Critical</div></div>`;
        html += `<div class="audit-stat high"><div class="audit-stat-value">${sev.HIGH || 0}</div><div class="audit-stat-label">High</div></div>`;
        html += `<div class="audit-stat medium"><div class="audit-stat-value">${sev.MEDIUM || 0}</div><div class="audit-stat-label">Medium</div></div>`;
        html += `<div class="audit-stat low"><div class="audit-stat-value">${sev.LOW || 0}</div><div class="audit-stat-label">Low</div></div>`;
        html += '</div>';
        // Sort findings by severity
        const sevOrder = { critical: 0, high: 1, medium: 2, low: 3 };
        findings.sort((a, b) => {
          const sa = (a.severity || 'medium').toLowerCase();
          const sb = (b.severity || 'medium').toLowerCase();
          return (sevOrder[sa] ?? 99) - (sevOrder[sb] ?? 99);
        });
        // Table
        html += '<table class="audit-findings-table"><thead><tr>';
        html += '<th>Tool</th><th>Type</th><th>Severity</th><th>File</th><th>Line</th><th>Issue</th></tr></thead><tbody>';
        const shown = findings.slice(0, 50);
        for (const f of shown) {
          const s = (f.severity || 'medium').toLowerCase();
          const file = (f.file || '').split('/').slice(-2).join('/');
          html += `<tr>
            <td>${escHtml(f.tool || '')}</td>
            <td>${escHtml(f.type || '')}</td>
            <td><span class="audit-sev-badge ${s}">${s}</span></td>
            <td title="${escHtml(f.file || '')}">${escHtml(file)}</td>
            <td>${f.line || '—'}</td>
            <td>${escHtml((f.message || '').slice(0, 120))}</td>
          </tr>`;
        }
        if (findings.length > 50) {
          html += `<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:12px;">… and ${findings.length - 50} more findings</td></tr>`;
        }
        html += '</tbody></table>';
        // Build correction prompt
        let prompt = `You are a senior software engineer. The following project audit found ${total} issues:\n\n`;
        prompt += `**Severity breakdown:** CRITICAL: ${sev.CRITICAL || 0}, HIGH: ${sev.HIGH || 0}, MEDIUM: ${sev.MEDIUM || 0}, LOW: ${sev.LOW || 0}\n\n`;
        prompt += `**Top findings to fix (priority order):**\n`;
        const prio = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];
        let count = 0;
        for (const p of prio) {
          for (const f of findings) {
            if (count >= 20) break;
            if ((f.severity || '').toUpperCase() === p) {
              count++;
              prompt += `${count}. [${p}] ${f.file || 'unknown'}${f.line ? ':' + f.line : ''} — ${f.message || 'no description'}\n`;
            }
          }
        }
        prompt += `\nPlease analyze these issues and provide:\n1. A corrected version of the most critical files\n2. Explanations for each fix\n3. Security best practices to apply\n\nFocus on CRITICAL and HIGH severity issues first.`;
        window._auditPrompt = prompt;
        window._auditReportUrl = `/code/audit/report/${reportId}?format=html`;
        const exportBtn = $('#audit-export-html');
        if (exportBtn) exportBtn.style.display = '';
        // Prompt section
        html += '<div class="audit-prompt-section">';
        html += '<h4>Correction Prompt</h4>';
        html += `<div class="audit-prompt-text">${escHtml(prompt)}</div>`;
        html += '</div>';
        body.innerHTML = html;
      } catch (err) {
        body.innerHTML = `<div class="audit-empty"><div class="check">' + ICONS.x(24) + '</div><p>Failed to load report: ${escHtml(err.message)}</p></div>`;
      }
    }

    // Audit history modal controls
    const auditHistoryClose = $('#audit-history-close');
    if (auditHistoryClose) auditHistoryClose.addEventListener('click', () => $('#audit-history-overlay').classList.remove('open'));
    const auditHistoryOverlay = $('#audit-history-overlay');
    if (auditHistoryOverlay) auditHistoryOverlay.addEventListener('click', e => { if (e.target === auditHistoryOverlay) auditHistoryOverlay.classList.remove('open'); });
    // File Upload
    const eftUploadBtn = $('#eft-upload');
    const eftUploadInput = $('#eft-upload-input');
    if (eftUploadBtn && eftUploadInput) {
      eftUploadBtn.addEventListener('click', () => eftUploadInput.click());
      eftUploadInput.addEventListener('change', e => {
        const files = Array.from(e.target.files);
        if (files.length) window.editor.uploadFiles(files);
        eftUploadInput.value = '';
      });
    }

    // Sidebar tabs
    $$('.sidebar-tab').forEach(tab => tab.addEventListener('click', () => {
      $$('.sidebar-tab').forEach(t => t.classList.remove('active'));
      $$('.sidebar-panel').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      $(`#panel-${tab.dataset.tab}`).classList.add('active');
    }));

    // Toggle sidebar
    // Sidebar & Menus Toggle
    $('#btn-toggle-sidebar').addEventListener('click', () => {
      $('#sidebar').classList.toggle('collapsed');
      const hc = document.querySelector('.header-center');
      const hr = document.querySelector('.header-right');
      if (hc) hc.style.display = hc.style.display === 'none' ? 'flex' : 'none';
      if (hr) hr.style.display = hr.style.display === 'none' ? 'flex' : 'none';
    });
    // Auto-collapse sidebar on tablet/small screens
    if (window.innerWidth <= 900) {
      const sb = $('#sidebar');
      if (sb && !sb.classList.contains('collapsed')) sb.classList.add('collapsed');
    }
    // New chat
    $('#btn-new-chat').addEventListener('click', () => window.chat.newSession());

    // Chat search
    $('#chat-search').addEventListener('input', e => {
      const q = e.target.value.toLowerCase();
      $$('.session-item').forEach(i => { i.style.display = i.textContent.toLowerCase().includes(q) ? '' : 'none'; });
      // Show/hide clear button
      const clearBtn = $('#search-clear');
      if (clearBtn) clearBtn.style.display = q ? 'block' : 'none';
    });

    // Search clear button
    const searchClear = $('#search-clear');
    if (searchClear) {
      searchClear.style.display = 'none';
      searchClear.addEventListener('click', () => {
        const input = $('#chat-search');
        input.value = '';
        input.dispatchEvent(new Event('input'));
        searchClear.style.display = 'none';
      });
    }

    // Logo click — go to welcome (SPA, no reload)
    const logoLink = $('#app-logo-link');
    if (logoLink) {
      logoLink.addEventListener('click', (e) => {
        e.preventDefault();
        window.chat.newSession();
      });
    }

    // Files
    $('#btn-export').addEventListener('click', () => window.ft.exportZip());
    $('#btn-transfer-editor').addEventListener('click', () => window.ft.transferToEditor());
    $('#btn-new-file').addEventListener('click', () => {
      const name = prompt('File name (e.g. main.py):');
      if (name && name.trim()) { window.ft.add(name.trim(), ''); window.ft.select(name.trim()); }
    });
    // Attach file button
    const attachBtn = $('#btn-attach');
    const chatFileInput = $('#chat-file-input');
    if (attachBtn && chatFileInput) {
      attachBtn.addEventListener('click', () => chatFileInput.click());
      chatFileInput.addEventListener('change', async (e) => {
        const files = Array.from(e.target.files);
        if (!files.length) return;
        const chatInput = $('#chat-input');
        for (const file of files) {
          const ext = file.name.split('.').pop().toLowerCase();
          const isImage = file.type.startsWith('image/');
          const isOfficeDoc = ext === 'pptx' || ext === 'docx';

          if (isOfficeDoc) {
            // ---- Document translation widget ----
            window.chat.hideWelcome();
            // Show user message bubble
            const userBubble = window.chat.addMsg('user', `${ICONS.paperclip(14)} **${file.name}** — Translate document`);
            // Build translation widget inside assistant bubble
            const asstBubble = window.chat.addMsg('assistant', '');
            const widgetId = 'doc-translate-' + Date.now();
            asstBubble.innerHTML = `
              <div class="doc-translate-widget" id="${widgetId}">
                <div class="dtw-header">
                  <span class="dtw-icon">${ext === 'pptx' ? ICONS.presentationIcon ? ICONS.presentationIcon(24) : ICONS.barChart(24) : ICONS.fileText(24)}</span>
                  <div>
                    <div class="dtw-title">${escHtml(file.name)}</div>
                    <div class="dtw-sub">${(file.size / 1024).toFixed(0)} KB · ${ext.toUpperCase()} document</div>
                  </div>
                </div>
                <div class="dtw-form">
                  <label class="dtw-label">Target language</label>
                  <select class="dtw-select" id="${widgetId}-lang">
                    <option value="French">French</option>
                    <option value="English">English</option>
                    <option value="Spanish">Spanish</option>
                    <option value="German">German</option>
                    <option value="Italian">Italian</option>
                    <option value="Portuguese">Portuguese</option>
                    <option value="Dutch">Dutch</option>
                    <option value="Polish">Polish</option>
                    <option value="Japanese">Japanese</option>
                    <option value="Chinese">Chinese</option>
                    <option value="Arabic">Arabic</option>
                  </select>
                  <button class="dtw-btn" id="${widgetId}-btn">
                    ${icon('globe', 14)} Translate
                  </button>
                </div>
                <div class="dtw-status" id="${widgetId}-status"></div>
              </div>`;

            // Bind translate button
            const btn = $(`#${widgetId}-btn`);
            const capturedFile = file;
            btn.addEventListener('click', async () => {
              const langSel = $(`#${widgetId}-lang`);
              const targetLang = langSel ? langSel.value : 'French';
              const status = $(`#${widgetId}-status`);
              const provider = $('#provider-select').value;
              const model = $('#model-select').value;

              btn.disabled = true;
              btn.innerHTML = `<span class="tool-spinner"></span> Translating…`;
              status.innerHTML = `<span style="color:var(--text-muted);font-size:12px">${ICONS.hourglass(14)} Sending to ${targetLang} via ${provider}…</span>`;

              try {
                const fd = new FormData();
                fd.append('file', capturedFile, capturedFile.name);
                fd.append('target_language', targetLang);
                fd.append('provider', provider);
                fd.append('model', model);

                const resp = await fetch('/document/translate-upload', { method: 'POST', body: fd });
                const data = await resp.json();

                if (!resp.ok) {
                  status.innerHTML = `<span style="color:#f87171">${ICONS.x(14)} Error: ${escHtml(data.detail || 'Translation failed')}</span>`;
                  btn.disabled = false;
                  btn.innerHTML = `${icon('globe', 14)} Retry`;
                  return;
                }

                const dlUrl = data.url;
                const outName = data.filename;
                const blocks = data.blocks_translated || '?';
                const total = data.total_blocks || '?';

                status.innerHTML = `
                  <div class="dtw-result">
                    <span style="color:#34d399">${ICONS.check(14)} Translated ${blocks}/${total} text blocks to <strong>${escHtml(targetLang)}</strong></span><br>
                    <a href="${escHtml(dlUrl)}" download="${escHtml(outName)}"
                       style="display:inline-flex;align-items:center;gap:6px;margin-top:8px;padding:6px 14px;
                              background:linear-gradient(135deg,#7c3aed,#2563eb);color:#fff;border-radius:6px;
                              text-decoration:none;font-size:13px;font-weight:600;">
                      ${icon('download', 14)} Download ${escHtml(outName)}
                    </a>
                  </div>`;
                btn.innerHTML = `${icon('check', 14)} Done`;
                toast(`${ICONS.check(14)} Translation ready: ${outName}`);
              } catch (err) {
                status.innerHTML = `<span style="color:#f87171">${ICONS.x(14)} ${escHtml(err.message)}</span>`;
                btn.disabled = false;
                btn.innerHTML = `${icon('globe', 14)} Retry`;
              }
            });

          } else if (isImage) {
            // Route image to vision chat pipeline for multimodal analysis
            if (window.visionChatAddImage) {
              window.visionChatAddImage(file);
            }
            toast(ICONS.paperclip(14) + ' ' + file.name + ' attached for vision');
          } else {
            // Read text content and inject into chat input
            try {
              const text = await file.text();
              const header = `

--- ${ICONS.paperclip(14)} ${file.name} ---
`;
              chatInput.value += header + text + '\n---\n';
              chatInput.dispatchEvent(new Event('input'));
              // Also add to file tree
              if (window.ft) window.ft.add(file.name, text);
              toast(ICONS.paperclip(14) + ' ' + file.name + ' attached');
            } catch (err) {
              toast(ICONS.x(14) + ' Read error: ' + file.name);
            }
          }
        }
        // Reset input so same file can be re-selected
        chatFileInput.value = '';
      });
    }


    // Provider change -> update models (for hidden selects backward compat)
    $('#provider-select').addEventListener('change', updateModels);

    // ---- Inline Model Picker ----
    const pickerBtn = $('#model-picker-btn');
    const pickerDrop = $('#model-picker-dropdown');
    const pickerLabel = $('#model-picker-label');

    // Provider display names (alphabetical)
    const PROVIDER_NAMES = {
      anthropic: 'Claude', google: 'Gemini', grok: 'Grok', groq: 'Groq',
      huggingface: 'HuggingFace', mistral: 'Mistral', ollama: 'Ollama',
      openai: 'OpenAI', openrouter: 'OpenRouter'
    };

    function renderModelPicker() {
      const provList = $('#mpd-provider-list');
      const modelList = $('#mpd-model-list');
      const currentProv = $('#provider-select').value;
      const currentModel = $('#model-select').value;

      // Providers
      provList.innerHTML = '';
      ['anthropic', 'google', 'grok', 'groq', 'huggingface', 'mistral', 'ollama', 'openai', 'openrouter'].forEach(p => {
        const opt = el('div', {
          class: 'mpd-option' + (currentProv === p ? ' active' : ''),
          onclick: () => {
            $('#provider-select').value = p;
            localStorage.setItem('hoc_last_provider', p);
            $('#provider-select').dispatchEvent(new Event('change'));
            pickerLabel.textContent = PROVIDER_NAMES[p] || p;
            renderModelPicker();
          }
        }, [
          document.createTextNode(PROVIDER_NAMES[p] || p),
          el('span', { class: 'mpd-check', html: ICONS.check(14) })
        ]);
        provList.appendChild(opt);
      });

      // Models
      const models = (window._providers || {})[currentProv] || [];
      modelList.innerHTML = '';

      if (!window.arenaMode) {
        // Default option
        const defOpt = el('div', {
          class: 'mpd-option' + (currentModel === '' ? ' active' : ''),
          onclick: () => {
            $('#model-select').value = '';
            localStorage.removeItem('hoc_last_model');
            renderModelPicker();
            pickerDrop.classList.remove('open');
          }
        }, [
          document.createTextNode('Default'),
          el('span', { class: 'mpd-check', html: ICONS.check(14) })
        ]);
        modelList.appendChild(defOpt);
      }

      models.forEach(m => {
        if (window.arenaMode) {
          const isSelected = window.arenaSelectedModels.find(x => x.provider === currentProv && x.model === m.id);
          const opt = el('div', {
            class: 'mpd-option checkbox-mode',
            onclick: (e) => {
              if (e.target.tagName === 'INPUT') return; // let default event handle
              const cb = opt.querySelector('input');
              cb.checked = !cb.checked;
              cb.dispatchEvent(new Event('change'));
            }
          });
          const cb = document.createElement('input');
          cb.type = 'checkbox';
          cb.checked = !!isSelected;
          cb.addEventListener('change', () => {
            if (cb.checked) {
              if (window.arenaSelectedModels.length >= 10) {
                toast('Max 10 models for Arena mode');
                cb.checked = false;
                return;
              }
              window.arenaSelectedModels.push({ provider: currentProv, model: m.id, label: m.label || m.id });
            } else {
              window.arenaSelectedModels = window.arenaSelectedModels.filter(x => !(x.provider === currentProv && x.model === m.id));
            }
            pickerLabel.textContent = `Arena (${window.arenaSelectedModels.length})`;
          });
          opt.appendChild(cb);
          opt.appendChild(document.createTextNode(m.label || m.id));
          modelList.appendChild(opt);
        } else {
          const opt = el('div', {
            class: 'mpd-option' + (currentModel === m.id ? ' active' : ''),
            onclick: () => {
              $('#model-select').value = m.id;
              localStorage.setItem('hoc_last_model', m.id);
              pickerLabel.textContent = m.label || m.id;
              renderModelPicker();
              pickerDrop.classList.remove('open');
            }
          }, [
            document.createTextNode(m.label || m.id),
            el('span', { class: 'mpd-check', html: ICONS.check(14) })
          ]);
          modelList.appendChild(opt);
        }
      });

      // Update label
      const selModel = models.find(m => m.id === currentModel);
      if (selModel) {
        pickerLabel.textContent = selModel.label || selModel.id;
      } else if (currentProv === 'ollama' && window._activeLocalModel) {
        pickerLabel.textContent = window._activeLocalModel;
      } else {
        pickerLabel.textContent = PROVIDER_NAMES[currentProv] || currentProv;
      }
    }

    // Toggle dropdown
    pickerBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      renderModelPicker();
      pickerDrop.classList.toggle('open');
    });
    // Close on outside click
    document.addEventListener('click', (e) => {
      if (!e.target.closest('#input-model-picker')) {
        pickerDrop.classList.remove('open');
      }
    });

    // ---- Editor Inline Model Picker ----
    const edPickerBtn = $('#editor-model-picker-btn');
    const edPickerDrop = $('#editor-model-picker-dropdown');
    const edPickerLabel = $('#editor-model-picker-label');

    function renderEditorModelPicker() {
      const provList = $('#editor-mpd-provider-list');
      const modelList = $('#editor-mpd-model-list');
      const currentProv = $('#provider-select').value;
      const currentModel = $('#model-select').value;
      if (!provList || !modelList) return;

      // Providers
      provList.innerHTML = '';
      ['anthropic', 'google', 'grok', 'groq', 'huggingface', 'mistral', 'ollama', 'openai', 'openrouter'].forEach(p => {
        const opt = el('div', {
          class: 'mpd-option' + (currentProv === p ? ' active' : ''),
          onclick: () => {
            $('#provider-select').value = p;
            localStorage.setItem('hoc_last_provider', p);
            $('#provider-select').dispatchEvent(new Event('change'));
            edPickerLabel.textContent = PROVIDER_NAMES[p] || p;
            if (pickerLabel) pickerLabel.textContent = PROVIDER_NAMES[p] || p;
            renderEditorModelPicker();
            renderModelPicker();
          }
        }, [
          document.createTextNode(PROVIDER_NAMES[p] || p),
          el('span', { class: 'mpd-check', html: ICONS.check(14) })
        ]);
        provList.appendChild(opt);
      });

      // Models
      const models = (window._providers || {})[currentProv] || [];
      modelList.innerHTML = '';

      const defOpt = el('div', {
        class: 'mpd-option' + (currentModel === '' ? ' active' : ''),
        onclick: () => {
          $('#model-select').value = '';
          localStorage.removeItem('hoc_last_model');
          renderEditorModelPicker();
          renderModelPicker();
          edPickerDrop.classList.remove('open');
        }
      }, [
        document.createTextNode('Default'),
        el('span', { class: 'mpd-check', html: ICONS.check(14) })
      ]);
      modelList.appendChild(defOpt);

      models.forEach(m => {
        const opt = el('div', {
          class: 'mpd-option' + (currentModel === m.id ? ' active' : ''),
          onclick: () => {
            $('#model-select').value = m.id;
            localStorage.setItem('hoc_last_model', m.id);
            edPickerLabel.textContent = m.label || m.id;
            if (pickerLabel) pickerLabel.textContent = m.label || m.id;
            renderEditorModelPicker();
            renderModelPicker();
            edPickerDrop.classList.remove('open');
          }
        }, [
          document.createTextNode(m.label || m.id),
          el('span', { class: 'mpd-check', html: ICONS.check(14) })
        ]);
        modelList.appendChild(opt);
      });

      // Update label
      const selModel = models.find(m => m.id === currentModel);
      if (selModel) {
        edPickerLabel.textContent = selModel.label || selModel.id;
      } else if (currentProv === 'ollama' && window._activeLocalModel) {
        edPickerLabel.textContent = window._activeLocalModel;
      } else {
        edPickerLabel.textContent = PROVIDER_NAMES[currentProv] || currentProv;
      }
    }

    if (edPickerBtn) {
      edPickerBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        renderEditorModelPicker();
        edPickerDrop.classList.toggle('open');
      });
      document.addEventListener('click', (e) => {
        if (!e.target.closest('#editor-model-picker')) {
          edPickerDrop.classList.remove('open');
        }
      });

      // Update editor label if provider select changes elsewhere
      $('#provider-select').addEventListener('change', () => {
        renderEditorModelPicker();
      });
    }

    // ---- Action Mode Select (preprompt shortcuts) ----
    window.arenaMode = false;
    window.arenaSelectedModels = [];
    window.ragMode = false;

    const actionModeSelect = $('#action-mode-select');
    if (actionModeSelect) {
      actionModeSelect.addEventListener('change', (e) => {
        const pp = e.target.value;

        if (pp === 'arena') {
          window.arenaMode = true;
          window.ragMode = false;
          $('#preprompt-select').value = 'none';
          pickerLabel.textContent = `Arena (${window.arenaSelectedModels.length})`;
          $('#chat-messages').innerHTML = '<div class="arena-container" id="arena-container" style="display:none"></div><div class="arena-eval-panel" id="arena-eval-panel" style="display:none; gap: 8px; justify-content: center;"><button class="arena-eval-btn" id="arena-eval-btn">Ask AI to Judge</button><button class="arena-eval-btn" id="arena-restart-btn" style="background: linear-gradient(135deg, #f59e0b, #d97706);"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:6px; vertical-align:middle"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path><path d="M3 3v5h5"></path></svg>Restart</button><button class="arena-eval-btn" id="arena-export-btn" style="background: linear-gradient(135deg, #10b981, #059669);"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:6px; vertical-align:middle"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>Export Excel</button></div>';
        } else if (pp === 'rag') {
          window.arenaMode = false;
          window.ragMode = true;
          $('#preprompt-select').value = 'none';
          if ($('#arena-container')) $('#arena-container').style.display = 'none';
          if ($('#arena-eval-panel')) $('#arena-eval-panel').style.display = 'none';
          const selModel = (window._providers || {})[$('#provider-select').value]?.find(m => m.id === $('#model-select').value);
          pickerLabel.textContent = selModel ? (selModel.label || selModel.id) : $('#provider-select').value;
          toast(ICONS.layers(14) + ' RAG mode — search your knowledge base');
        } else {
          window.arenaMode = false;
          window.ragMode = false;
          $('#preprompt-select').value = pp;
          if ($('#arena-container')) $('#arena-container').style.display = 'none';
          if ($('#arena-eval-panel')) $('#arena-eval-panel').style.display = 'none';
          const selModel = (window._providers || {})[$('#provider-select').value]?.find(m => m.id === $('#model-select').value);
          pickerLabel.textContent = selModel ? (selModel.label || selModel.id) : $('#provider-select').value;
        }
        renderModelPicker();
      });
    }

    // Arena Eval Logic
    document.addEventListener('click', async (e) => {
      if (e.target && e.target.id === 'arena-eval-btn') {
        const btn = e.target;
        btn.disabled = true;
        btn.textContent = 'Judging...';

        try {
          const responses = {};
          window.arenaStreams.forEach(s => {
            responses[s.id] = document.getElementById(`col-${s.id}`)?.innerText || '';
          });

          const streamKeys = Object.keys(responses);
          const total = streamKeys.length;
          let completed = 0;

          if (total === 0) {
            toast('No models to evaluate.');
            btn.textContent = 'Ask AI to Judge';
            btn.disabled = false;
            return;
          }

          const evalPanel = document.getElementById('arena-eval-panel');
          let progressContainer = document.getElementById('arena-eval-progress');
          if (!progressContainer) {
            progressContainer = document.createElement('div');
            progressContainer.id = 'arena-eval-progress';
            progressContainer.style = 'width: 100%; max-width: 400px; margin: 12px auto 0; background: var(--bg-primary); border: 1px solid var(--border); border-radius: 6px; overflow: hidden; height: 8px; position: relative;';
            const progressBar = document.createElement('div');
            progressBar.id = 'arena-eval-progress-bar';
            progressBar.style = 'width: 0%; height: 100%; background: linear-gradient(90deg, var(--accent), var(--green)); transition: width 0.3s ease;';
            progressContainer.appendChild(progressBar);
            evalPanel.appendChild(progressContainer);
          }
          document.getElementById('arena-eval-progress-bar').style.width = '0%';
          progressContainer.style.display = 'block';

          btn.textContent = `Judging (0/${total})...`;
          let hasError = false;

          for (const s_id of streamKeys) {
            const singleResponse = {};
            singleResponse[s_id] = responses[s_id];

            let attempt = 0;
            let success = false;
            let lastInfo = null;

            while (attempt < 3 && !success) {
              attempt++;
              if (attempt > 1) {
                btn.textContent = `Judging (${completed}/${total}) - Retry ${attempt}/3...`;
              }
              try {
                const r = await fetch('/arena/evaluate', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                    prompt: window.arenaLastPrompt || '',
                    responses: singleResponse,
                    provider: $('#provider-select').value,
                    model: $('#model-select').value
                  })
                });

                let d = {};
                try { d = await r.json(); } catch (e) { }

                if (r.ok && d.ratings && Object.keys(d.ratings).length > 0) {
                  const info = d.ratings[s_id];
                  if (info) {
                    lastInfo = info;
                    if (info.error || info.score === '-') {
                      success = false;
                    } else {
                      success = true;
                    }
                  }
                } else {
                  success = false;
                }
              } catch (err) {
                console.error('Eval error for', s_id, err);
                success = false;
              }
            }

            if (!success) {
              hasError = true;
            }

            if (lastInfo) {
              const streamObj = window.arenaStreams.find(s => s.id === s_id);
              if (streamObj) streamObj.eval = lastInfo;

              const footerEl = document.getElementById(`footer-${s_id}`);
              if (footerEl) {
                footerEl.style.display = 'block';
                footerEl.innerHTML = `<div class="arena-score" style="margin:0; border:none; background:transparent; padding:0;"><strong>Score: ${lastInfo.score}/10</strong><div style="font-size:13px; margin-top:6px; color:var(--text-secondary); line-height:1.4;">${escHtml(lastInfo.rationale)}</div></div>`;
              } else {
                const colBody = document.getElementById(`col-${s_id}`);
                if (colBody) {
                  const scoreDiv = document.createElement('div');
                  scoreDiv.className = 'arena-score';
                  scoreDiv.innerHTML = `<strong>Score: ${lastInfo.score}/10</strong>${escHtml(lastInfo.rationale)}`;
                  colBody.appendChild(scoreDiv);
                  colBody.scrollTop = colBody.scrollHeight;
                }
              }
            } else {
              hasError = true;
            }

            completed++;
            document.getElementById('arena-eval-progress-bar').style.width = `${(completed / total) * 100}%`;
            btn.textContent = `Judging (${completed}/${total})...`;
          }

          if (hasError) {
            toast('Some evaluations encountered errors. Check individual columns.');
          }
          btn.textContent = 'Evaluation Complete';

          setTimeout(() => {
            if (progressContainer) progressContainer.style.display = 'none';
            btn.disabled = false;
            btn.textContent = 'Ask AI to Judge';
          }, 3000);

        } catch (err) {
          toast('Evaluation error: ' + err.message);
          btn.textContent = 'Ask AI to Judge';
          btn.disabled = false;
        }
      }

      if (e.target && e.target.closest('#arena-restart-btn')) {
        const prompt = window.arenaLastPrompt || '';
        if (!prompt) {
          toast('No prompt to restart.');
          return;
        }
        const chatInput = document.getElementById('chat-input');
        if (chatInput) {
          chatInput.value = prompt;
          window.chat.send();
        }
      }

      if (e.target && e.target.closest('#arena-export-btn')) {
        const exportExcel = () => {
          const wsData = [['Modèle', 'Provider', 'Requête', 'Temps (s)', 'Tokens', 'TPS', 'Score / 10', 'Justification']];

          if (window.arenaStreams) {
            window.arenaStreams.forEach(s => {
              const m = window.arenaSelectedModels.find(mod => mod.model === s.model && mod.provider === s.provider) || s;
              const modelName = m.label || s.model;
              const provider = s.provider || '';
              const prompt = window.arenaLastPrompt || '';
              const time = s.stats ? s.stats.time : '';
              const tokens = s.stats ? s.stats.tokens : '';
              const tps = s.stats ? s.stats.tps : '';
              const score = s.eval ? s.eval.score : '';
              const rationale = s.eval ? s.eval.rationale : '';
              wsData.push([modelName, provider, prompt, time, tokens, tps, score, rationale]);
            });
          }

          const wb = XLSX.utils.book_new();
          const ws = XLSX.utils.aoa_to_sheet(wsData);
          XLSX.utils.book_append_sheet(wb, ws, "Arena Results");
          XLSX.writeFile(wb, `arena_results_${new Date().toISOString().split('T')[0]}.xlsx`);
        };

        if (typeof XLSX === 'undefined') {
          const script = document.createElement('script');
          script.src = 'https://cdn.sheetjs.com/xlsx-latest/package/dist/xlsx.full.min.js';
          script.onload = exportExcel;
          document.head.appendChild(script);
        } else {
          exportExcel();
        }
      }
    });

    // Settings
    $('#btn-settings').addEventListener('click', () => {
      $('#settings-overlay').classList.add('open');
      // Load tool permissions into the HITL grid
      _loadToolPermsGrid();
      // Load model selectors
      _loadSettingsModelSelects();
    });
    $('#settings-close').addEventListener('click', () => $('#settings-overlay').classList.remove('open'));
    $('#settings-overlay').addEventListener('click', e => { if (e.target === e.currentTarget) e.currentTarget.classList.remove('open'); });

    // Performance
    $('#btn-open-performance').addEventListener('click', () => {
      $('#settings-overlay').classList.remove('open');
      $('#performance-overlay').style.display = 'flex';
      loadPerformance();
    });
    $('#performance-close').addEventListener('click', () => $('#performance-overlay').style.display = 'none');
    $('#performance-overlay').addEventListener('click', e => { if (e.target === e.currentTarget) e.currentTarget.style.display = 'none'; });
    // Model Manager button
    $('#btn-models').addEventListener('click', () => window.modelManager.open());

    // Skill Catalog button
    $('#btn-skills-catalog').addEventListener('click', () => window.skillCatalog.open());
    $('#skills-catalog-close').addEventListener('click', () => window.skillCatalog.close());
    $('#skills-catalog-overlay').addEventListener('click', e => { if (e.target === e.currentTarget) window.skillCatalog.close(); });
    const skillIndicator = $('#input-skill-indicator');
    if (skillIndicator) skillIndicator.addEventListener('click', () => window.skillCatalog.open());


    // Save settings
    $('#btn-save-settings').addEventListener('click', async () => {
      const s = {
        default_provider: $('#settings-provider').value,
        default_preprompt: $('#settings-preprompt').value,
        code_execution_timeout: parseInt($('#settings-timeout').value) || 30,
        code_max_memory_mb: parseInt($('#settings-memory').value) || 512,
        require_command_confirmation: $('#settings-confirm-commands') ? $('#settings-confirm-commands').checked : true,
        auto_enrich_prompt: $('#settings-auto-enrich') ? $('#settings-auto-enrich').checked : true,
        show_automation: $('#settings-show-automation')?.checked ?? true,
        show_research: $('#settings-show-research')?.checked ?? true,
        show_media: $('#settings-show-media')?.checked ?? true,
        show_presentation: $('#settings-show-presentation')?.checked ?? true,
        show_project: $('#settings-show-project')?.checked ?? true,
        show_editor: $('#settings-show-editor')?.checked ?? true,
        enable_cloud_models: $('#settings-enable-cloud-models')?.checked ?? true,
      };
      await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(s) });
      applyToolVisibility(s);

      const envData = {};
      $$('#env-settings-container input[data-env-key]').forEach(inp => {
        envData[inp.dataset.envKey] = inp.value;
      });
      if (Object.keys(envData).length > 0) {
        await fetch('/api/env', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(envData) });
      }

      // Persist cloud models toggle and model selections to .env
      const cloudEnabled = $('#settings-enable-cloud-models')?.checked ?? true;
      const defaultModel = $('#settings-default-model')?.value || '';
      const enhanceModel = $('#settings-enhance-model')?.value || '';
      const codeModel = $('#settings-code-model')?.value || '';
      
      const newEnvData = { ENABLE_CLOUD_MODELS: cloudEnabled ? 'true' : 'false' };
      if (defaultModel) newEnvData['OLLAMA_MODEL'] = defaultModel;
      if (enhanceModel) newEnvData['ENHANCE_MODEL'] = enhanceModel;
      if (codeModel) newEnvData['CODE_MODEL'] = codeModel;
      
      await fetch('/api/env', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newEnvData)
      });
      toast(ICONS.check(14) + ' Settings saved'); $('#settings-overlay').classList.remove('open');
      // Reload providers immediately to reflect cloud toggle change
      loadProviders();
    });

    // --- Tool Permissions Grid (HITL) ---
    async function _loadToolPermsGrid() {
      const grid = $('#tool-perms-grid');
      if (!grid) return;
      try {
        const res = await fetch('/api/tool-permissions');
        const data = await res.json();
        const perms = data.permissions || {};
        const tools = Object.keys(perms).sort();
        if (tools.length === 0) {
          grid.innerHTML = '<div style="color:var(--text-muted);font-size:11px;">No tools configured</div>';
          return;
        }
        const toolIcons = {
          search_web: '🔍', execute_python: '🐍', run_command: '⚙️',
          edit_file: '✏️', read_file: '📄', generate_image: '🎨',
          generate_animation: '🎬', browse_web: '🌐', audit_code: '🛡️',
          send_email: '📧', post_to_twitter: '🐦', post_to_linkedin: '💼',
          trigger_n8n: '🔗', create_app: '📱', screenshot_remote: '📸',
          create_skill: '⚡', memory: '🧠', undo: '↩️',
        };
        grid.innerHTML = tools.map(tool => {
          const level = perms[tool];
          const icon = toolIcons[tool] || '🔧';
          return `<div style="display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px solid var(--border);">
            <span style="font-size:14px;width:20px;text-align:center;">${icon}</span>
            <span style="flex:1;font-size:12px;font-family:'SF Mono','Fira Code',monospace;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${tool}">${tool}</span>
            <select data-tool-perm="${tool}" style="padding:2px 6px;font-size:11px;background:var(--bg-elevated);color:var(--text-primary);border:1px solid var(--border);border-radius:4px;cursor:pointer;">
              <option value="always"${level === 'always' ? ' selected' : ''}>✅ Always</option>
              <option value="ask"${level === 'ask' ? ' selected' : ''}>⏳ Ask</option>
              <option value="deny"${level === 'deny' ? ' selected' : ''}>🚫 Deny</option>
            </select>
          </div>`;
        }).join('');
        // Auto-save on change
        grid.querySelectorAll('select[data-tool-perm]').forEach(sel => {
          sel.addEventListener('change', async () => {
            const toolName = sel.dataset.toolPerm;
            const newLevel = sel.value;
            await fetch('/api/tool-permissions', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ [toolName]: newLevel }),
            });
          });
        });
      } catch (e) {
        grid.innerHTML = '<div style="color:var(--red);font-size:11px;">Failed to load permissions</div>';
      }
    }
    window._loadToolPermsGrid = _loadToolPermsGrid;

    // RAG multi-file upload
    const ragUp = $('#rag-upload');
    if (ragUp) ragUp.addEventListener('change', async e => {
      const files = e.target.files; if (!files || !files.length) return;
      const fd = new FormData();
      for (const file of files) fd.append('files', file);
      try {
        toast(ICONS.layers(14) + ` Indexing ${files.length} file(s)...`);
        const r = await fetch('/rag/upload-multi', { method: 'POST', body: fd });
        const d = await r.json();
        toast(`${ICONS.check(14)} Indexed: ${d.indexed}/${d.total} files`);
        loadRagStats();
      } catch (err) { toast(ICONS.x(14) + ' Upload failed'); }
      ragUp.value = '';
    });

    // RAG scan folder
    const ragScanBtn = $('#rag-scan-btn');
    if (ragScanBtn) ragScanBtn.addEventListener('click', async () => {
      ragScanBtn.disabled = true;
      ragScanBtn.innerHTML = `<span class="tool-spinner"></span> Scanning…`;
      try {
        const r = await fetch('/rag/scan', { method: 'POST' });
        const d = await r.json();
        const added = (d.added || []).length;
        const updated = (d.updated || []).length;
        const errors = (d.errors || []).length;
        toast(`${ICONS.check(14)} Scan: ${added} added, ${updated} updated${errors ? ', ' + errors + ' errors' : ''}`);
        loadRagStats();
      } catch (err) { toast(ICONS.x(14) + ' Scan failed'); }
      ragScanBtn.disabled = false;
      ragScanBtn.innerHTML = `${icon('search', 14)} Scan Folder`;
    });

    // RAG clear all
    const ragClearBtn = $('#rag-clear-btn');
    if (ragClearBtn) ragClearBtn.addEventListener('click', async () => {
      if (!confirm('Clear entire knowledge base? This cannot be undone.')) return;
      try {
        const r = await fetch('/rag/clear', { method: 'DELETE' });
        const d = await r.json();
        toast(`${ICONS.check(14)} Knowledge base cleared (${d.chunks_removed} chunks)`);
        loadRagStats();
      } catch (err) { toast(ICONS.x(14) + ' Clear failed'); }
    });

    // Voice input
    window.voice = new VoiceInput($('#chat-input'), () => window.chat.send());

    // Skill catalog
    window.skillCatalog = new SkillCatalog();

    // Load data
    loadSessions(); loadPreprompts(); loadProviders(); loadRagStats(); loadSettings(); loadEnvSettings(); loadRagProfiles();
    window.skillCatalog.refreshBadge();
    window.chat.showWelcome();
  });

  async function loadRagStats() {
    try {
      const r = await fetch('/rag/stats'); const d = await r.json();
      const el2 = $('#rag-stats');
      if (el2) {
        const chunks = d.total_chunks || 0;
        const sources = d.source_count || Object.keys(d.sources || {}).length || 0;
        el2.textContent = `${chunks} chunks · ${sources} source(s)`;
      }
      // Load sources list
      try {
        const sr = await fetch('/rag/sources'); const sd = await sr.json();
        const list = $('#rag-sources-list');
        if (list && sd.sources) {
          if (sd.sources.length === 0) {
            list.innerHTML = '<div style="color:var(--text-muted); font-size:12px;">No sources indexed yet. Upload files or scan the RAG folder.</div>';
          } else {
            list.innerHTML = sd.sources.map(s => `
              <div style="display:flex; justify-content:space-between; align-items:center; padding:5px 8px; background:var(--bg-default); border-radius:4px; font-size:12px;">
                <div style="display:flex; align-items:center; gap:6px; overflow:hidden; flex:1;">
                  ${icon('fileText', 12)}
                  <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escHtml(s.name)}">${escHtml(s.name)}</span>
                  <span style="color:var(--text-muted); flex-shrink:0;">${s.chunks} chunks</span>
                  <span style="font-size:10px; color:var(--text-muted); background:var(--bg-elevated); padding:1px 6px; border-radius:10px; flex-shrink:0;">${escHtml(s.file_type || '')}</span>
                </div>
                <button class="icon-btn rag-del-src" data-source="${escHtml(s.name)}" title="Delete source" style="flex-shrink:0; padding:2px;">
                  ${icon('x', 12)}
                </button>
              </div>
            `).join('');
            // Bind delete buttons
            list.querySelectorAll('.rag-del-src').forEach(btn => {
              btn.addEventListener('click', async () => {
                const src = btn.dataset.source;
                if (!confirm(`Delete "${src}" from knowledge base?`)) return;
                try {
                  await fetch(`/rag/source/${encodeURIComponent(src)}`, { method: 'DELETE' });
                  toast(`${ICONS.check(14)} Deleted: ${src}`);
                  loadRagStats();
                } catch (err) { toast(ICONS.x(14) + ' Delete failed'); }
              });
            });
          }
        }
      } catch (e) { /* sources list non-critical */ }
    } catch (e) { /* ignore */ }
  }

  // ---- SkillCatalog ---- (extracted to components/skill_catalog.js)

  async function loadPerformance() {
    try {
      const r = await fetch('/api/metrics');
      const d = await r.json();

      const totalTokens = d.llm?.total_tokens || 0;
      $('#perf-total-tokens').textContent = totalTokens.toLocaleString();

      const savedTokens = d.token_savings?.total_saved_chars || 0;
      $('#perf-tokens-saved').textContent = savedTokens.toLocaleString();

      const pct = d.token_savings?.overall_savings_pct || 0;
      $('#perf-savings-pct').textContent = pct + '% reduction';

      const totalTools = d.token_savings?.total_compressions || 0;
      $('#perf-total-tools').textContent = totalTools.toLocaleString();

      // Models
      const mList = $('#perf-model-latency-list');
      if (mList && d.llm?.by_model) {
        mList.innerHTML = Object.entries(d.llm.by_model)
          .sort((a, b) => b[1].calls - a[1].calls)
          .map(([model, stats]) => {
            return `
              <div style="display:flex; justify-content:space-between; padding:8px; background:var(--bg-default); border-radius:6px;">
                <div style="display:flex; align-items:center; gap:8px;">
                  <svg class="ic" width="14" height="14" style="color:var(--text-muted)"><use href="#icon-cpu"></use></svg>
                  <span style="font-weight:500;">${escHtml(model)}</span>
                  <span style="font-size:10px; color:var(--text-muted); background:var(--bg-elevated); padding:2px 6px; border-radius:10px;">${escHtml(stats.provider)}</span>
                </div>
                <div style="display:flex; gap:16px; font-size:12px;">
                  <span style="color:var(--text-muted);">${stats.calls} calls</span>
                  <span style="color:var(--accent); font-weight:600;">${stats.avg_latency_s.toFixed(2)}s avg</span>
                </div>
              </div>
            `;
          }).join('') || '<div style="color:var(--text-muted); font-size:12px;">No model data yet.</div>';
      }

      // Tools
      const tList = $('#perf-tool-usage-list');
      if (tList && d.token_savings?.by_tool) {
        tList.innerHTML = Object.entries(d.token_savings.by_tool)
          .sort((a, b) => b[1].count - a[1].count)
          .map(([tool, stats]) => {
            return `
              <div style="display:flex; justify-content:space-between; padding:8px; background:var(--bg-default); border-radius:6px;">
                <div style="display:flex; align-items:center; gap:8px;">
                  <svg class="ic" width="14" height="14" style="color:var(--text-muted)"><use href="#icon-tool"></use></svg>
                  <span style="font-weight:500;">${escHtml(tool)}</span>
                </div>
                <div style="display:flex; gap:16px; font-size:12px;">
                  <span style="color:var(--text-muted);">${stats.count} calls</span>
                  <span style="color:var(--green); font-weight:600;">-${stats.savings_pct}% tokens</span>
                </div>
              </div>
            `;
          }).join('') || '<div style="color:var(--text-muted); font-size:12px;">No tool data yet.</div>';
      }
    } catch (e) {
      console.error('Failed to load performance metrics', e);
    }
  }

  async function loadSettings() {
    try {
      const r = await fetch('/api/settings'); const d = await r.json();
      if (d.default_provider) { $('#provider-select').value = d.default_provider; updateModels(); }
      if (d.default_preprompt) $('#preprompt-select').value = d.default_preprompt;
      if ($('#settings-provider')) $('#settings-provider').value = d.default_provider || 'ollama';
      if ($('#settings-preprompt')) $('#settings-preprompt').value = d.default_preprompt || 'none';
      if ($('#settings-timeout')) $('#settings-timeout').value = d.code_execution_timeout || 30;
      if ($('#settings-memory')) $('#settings-memory').value = d.code_max_memory_mb || 512;
      if ($('#settings-confirm-commands')) $('#settings-confirm-commands').checked = d.require_command_confirmation !== false;
      if ($('#settings-auto-enrich')) $('#settings-auto-enrich').checked = d.auto_enrich_prompt !== false;
      if ($('#settings-show-automation')) $('#settings-show-automation').checked = d.show_automation !== false;
      if ($('#settings-show-research')) $('#settings-show-research').checked = d.show_research !== false;
      if ($('#settings-show-media')) $('#settings-show-media').checked = d.show_media !== false;
      if ($('#settings-show-presentation')) $('#settings-show-presentation').checked = d.show_presentation !== false;
      if ($('#settings-show-project')) $('#settings-show-project').checked = d.show_project !== false;
      if ($('#settings-show-editor')) $('#settings-show-editor').checked = d.show_editor !== false;
      if ($('#settings-enable-cloud-models')) $('#settings-enable-cloud-models').checked = d.enable_cloud_models !== false;
      applyToolVisibility(d);
    } catch (e) { /* ignore */ }
  }

  async function _loadSettingsModelSelects() {
    try {
      const defaultSel = $('#settings-default-model');
      const enhanceSel = $('#settings-enhance-model');
      const codeSel = $('#settings-code-model');
      
      if (!defaultSel || !enhanceSel || !codeSel) return;
      
      // Fetch available models
      const rProv = await fetch('/api/providers');
      const dProv = await rProv.json();
      const ollamaModels = dProv.providers?.ollama || [];
      
      // Fetch current .env settings
      const rEnv = await fetch('/api/env');
      const env = await rEnv.json();
      
      // Populate dropdowns
      const populateDropdown = (sel, currentVal, emptyLabel) => {
        sel.innerHTML = `<option value="">${emptyLabel}</option>` + 
          ollamaModels.map(m => `<option value="${m.id}">${escHtml(m.label || m.id)}</option>`).join('');
        if (currentVal && ollamaModels.some(m => m.id === currentVal)) {
          sel.value = currentVal;
        } else if (currentVal) {
          // If the model exists in .env but not in the list, add it as a custom option
          sel.innerHTML += `<option value="${escHtml(currentVal)}">${escHtml(currentVal)} (Remote/Offline)</option>`;
          sel.value = currentVal;
        }
      };
      
      populateDropdown(defaultSel, env['OLLAMA_MODEL'], 'System default');
      populateDropdown(enhanceSel, env['ENHANCE_MODEL'], 'System default');
      populateDropdown(codeSel, env['CODE_MODEL'], 'System default');
      
    } catch(e) {
      console.error('Failed to load settings models', e);
    }
  }

  async function loadEnvSettings() {
    try {
      const r = await fetch('/api/env');
      const d = await r.json();

      const container = $('#env-modal-table-container');
      const perfProvidersContainer = $('#perf-providers-container');

      if (container) container.innerHTML = '';
      if (perfProvidersContainer) perfProvidersContainer.innerHTML = '';

      // Sync cloud models toggle from .env (source of truth for persistence)
      const cloudEnvVal = d['ENABLE_CLOUD_MODELS'];
      if (cloudEnvVal !== undefined) {
        const cloudOn = !['0', 'false', 'no', 'off'].includes(String(cloudEnvVal).toLowerCase());
        if ($('#settings-enable-cloud-models')) $('#settings-enable-cloud-models').checked = cloudOn;
      }

      // Populate general env variables in the main settings drawer
      const keys = Object.keys(d).sort();
      const groups = {};
      const sensitiveKeywords = ['KEY', 'SECRET', 'TOKEN', 'PASSWORD'];

      // Explicit key → group overrides for keys that don't match a prefix pattern
      const KEY_GROUP_OVERRIDES = {
        'NOTIFICATION_EMAIL': 'SMTP',
        'SLACK_WEBHOOK_URL': 'SMTP',
        'N8N_WEBHOOK_URL': 'System / Other'
      };

      for (const key of keys) {
        let groupName = KEY_GROUP_OVERRIDES[key] || null;
        if (!groupName) {
          groupName = 'System / Other';
          const prefixes = ['GOOGLE', 'GROQ', 'OPENAI', 'ANTHROPIC', 'HUGGINGFACE', 'MISTRAL', 'OPENROUTER', 'GROK', 'TAVILY', 'APP', 'OLLAMA', 'TELEGRAM', 'DISCORD', 'TWITTER', 'LINKEDIN', 'MEDIUM', 'SMTP'];
          for (const prefix of prefixes) {
            if (key.startsWith(prefix + '_')) {
              groupName = prefix;
              break;
            }
          }
        }
        if (!groups[groupName]) groups[groupName] = [];
        groups[groupName].push(key);
      }

      // ── Ensure connector/integration keys ALWAYS appear (even if not in .env) ──
      const REQUIRED_CONNECTOR_KEYS = {
        'TELEGRAM': ['TELEGRAM_BOT_TOKEN'],
        'DISCORD': ['DISCORD_BOT_TOKEN', 'DISCORD_CHANNEL_IDS'],
        'SMTP': ['SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASSWORD', 'NOTIFICATION_EMAIL'],
        'TWITTER': ['TWITTER_API_KEY', 'TWITTER_API_SECRET', 'TWITTER_ACCESS_TOKEN', 'TWITTER_ACCESS_SECRET'],
        'LINKEDIN': ['LINKEDIN_ACCESS_TOKEN', 'LINKEDIN_AUTHOR_ID'],
        'MEDIUM': ['MEDIUM_INTEGRATION_TOKEN', 'MEDIUM_AUTHOR_ID'],
      };
      for (const [group, requiredKeys] of Object.entries(REQUIRED_CONNECTOR_KEYS)) {
        if (!groups[group]) groups[group] = [];
        for (const rk of requiredKeys) {
          if (!groups[group].includes(rk)) {
            groups[group].push(rk);
          }
          // Ensure the key exists in `d` so the input gets a value attribute
          if (d[rk] === undefined) d[rk] = '';
        }
      }

      let tableHtml = `<div style="display:flex; flex-direction:column; gap:24px;">`;

      // Provider documentation for help links in the env modal
      const PROVIDER_DOCS = {
        ANTHROPIC: {
          name: 'Anthropic (Claude)',
          url: 'https://console.anthropic.com/settings/keys',
          subscription: '❌ Pay-as-you-go only — no free tier. Requires billing setup.',
          keyFormat: 'sk-ant-...'
        },
        GOOGLE: {
          name: 'Google Gemini',
          url: 'https://aistudio.google.com/apikey',
          subscription: '✅ Free tier available (15 RPM). Pay-as-you-go for higher limits.',
          keyFormat: 'AIzaSy...'
        },
        GROK: {
          name: 'Grok (xAI)',
          url: 'https://console.x.ai/team/default/api-keys',
          subscription: '✅ Free tier with $25/month free credits.',
          keyFormat: 'xai-...'
        },
        GROQ: {
          name: 'Groq',
          url: 'https://console.groq.com/keys',
          subscription: '✅ Free tier available (30 RPM, 14,400 req/day).',
          keyFormat: 'gsk_...'
        },
        HUGGINGFACE: {
          name: 'HuggingFace',
          url: 'https://huggingface.co/settings/tokens',
          subscription: '✅ Free tier available. PRO ($9/mo) for priority access.',
          keyFormat: 'hf_...'
        },
        MISTRAL: {
          name: 'Mistral',
          url: 'https://console.mistral.ai/api-keys',
          subscription: '✅ Limited free tier. Pay-as-you-go for full access.',
          keyFormat: ''
        },
        OLLAMA: {
          name: 'Ollama (Local)',
          url: 'https://ollama.com/',
          subscription: '✅ Free & self-hosted. No API key needed (unless remote instance).',
          keyFormat: ''
        },
        OPENAI: {
          name: 'OpenAI',
          url: 'https://platform.openai.com/api-keys',
          subscription: 'Pay-as-you-go. Free $5 trial credit for new accounts.',
          keyFormat: 'sk-...'
        },
        OPENROUTER: {
          name: 'OpenRouter',
          url: 'https://openrouter.ai/settings/keys',
          subscription: '✅ Free models available. Pay-as-you-go for premium models.',
          keyFormat: 'sk-or-...'
        },
        TAVILY: {
          name: 'Tavily (Web Search)',
          url: 'https://app.tavily.com/home',
          subscription: '✅ Free: 1,000 searches/month. Paid plans from $50/mo.',
          keyFormat: 'tvly-...'
        },
        TELEGRAM: {
          name: 'Telegram Bot',
          url: 'https://core.telegram.org/bots#botfather',
          subscription: '✅ Free. Create a bot via @BotFather on Telegram to get your token.',
          keyFormat: '123456:ABC-DEF1234...',
          fields: [
            { key: 'TELEGRAM_BOT_TOKEN', label: 'Bot Token', hint: 'Token from @BotFather (e.g. 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11)' }
          ]
        },
        DISCORD: {
          name: 'Discord Bot',
          url: 'https://discord.com/developers/applications',
          subscription: '✅ Free. Create an application in the Discord Developer Portal and add a Bot.',
          keyFormat: 'MTk4NjIz...',
          fields: [
            { key: 'DISCORD_BOT_TOKEN', label: 'Bot Token', hint: 'Token from Discord Developer Portal → Bot → Token' }
          ]
        },
        TWITTER: {
          name: 'X (Twitter)',
          url: 'https://developer.x.com/en/portal/dashboard',
          subscription: '⚠️ Free tier allows posting only (1,500 tweets/mo). Basic plan $100/mo for read access.',
          keyFormat: '',
          fields: [
            { key: 'TWITTER_API_KEY', label: 'API Key (Consumer Key)', hint: 'From X Developer Portal → Project → Keys and Tokens' },
            { key: 'TWITTER_API_SECRET', label: 'API Secret (Consumer Secret)', hint: 'Keep this secret — used to sign requests' },
            { key: 'TWITTER_ACCESS_TOKEN', label: 'Access Token', hint: 'OAuth 1.0a access token for your account' },
            { key: 'TWITTER_ACCESS_SECRET', label: 'Access Token Secret', hint: 'OAuth 1.0a access token secret' }
          ]
        },
        LINKEDIN: {
          name: 'LinkedIn',
          url: 'https://www.linkedin.com/developers/apps',
          subscription: '✅ Free. Create an app in LinkedIn Developer Portal. Requires OAuth 2.0 access token.',
          keyFormat: 'AQV...',
          fields: [
            { key: 'LINKEDIN_ACCESS_TOKEN', label: 'Access Token', hint: 'OAuth 2.0 token — generate via 3-legged OAuth flow or LinkedIn token tool' },
            { key: 'LINKEDIN_AUTHOR_ID', label: 'Author ID (URN)', hint: 'Your LinkedIn member URN (e.g. urn:li:person:XXXXX) or organization URN' }
          ]
        },
        MEDIUM: {
          name: 'Medium',
          url: 'https://medium.com/me/settings/security',
          subscription: '✅ Free. Generate an Integration Token in Medium Settings → Security and apps.',
          keyFormat: '',
          fields: [
            { key: 'MEDIUM_INTEGRATION_TOKEN', label: 'Integration Token', hint: 'From Medium → Settings → Security and apps → Integration tokens' },
            { key: 'MEDIUM_AUTHOR_ID', label: 'Author ID', hint: 'Your Medium user ID (visible in API response or profile URL)' }
          ]
        },
        SMTP: {
          name: 'SMTP (Email)',
          url: 'https://support.google.com/a/answer/176600',
          subscription: '✅ Use any SMTP provider (Gmail, SendGrid, Mailgun, etc.). Gmail requires App Password with 2FA enabled.',
          keyFormat: '',
          fields: [
            { key: 'SMTP_HOST', label: 'SMTP Host', hint: 'e.g. smtp.gmail.com, smtp.sendgrid.net, smtp.mailgun.org' },
            { key: 'SMTP_PORT', label: 'SMTP Port', hint: '587 (TLS/STARTTLS) or 465 (SSL) — 587 recommended' },
            { key: 'SMTP_USER', label: 'Username / Email', hint: 'Your email address or SMTP username' },
            { key: 'SMTP_PASSWORD', label: 'Password / App Password', hint: 'For Gmail: use an App Password (not your regular password)' },
            { key: 'NOTIFICATION_EMAIL', label: 'Notification Recipient', hint: 'Email address to receive system notifications' }
          ]
        }
      };

      for (const [groupName, groupKeys] of Object.entries(groups).sort()) {
        const doc = PROVIDER_DOCS[groupName];
        const displayName = doc ? doc.name : groupName;
        const linkLabel = ['SMTP', 'TELEGRAM', 'DISCORD', 'MEDIUM'].includes(groupName)
          ? `🔗 ${doc.name} setup guide →`
          : `🔑 Get your ${doc ? doc.name : groupName} API key →`;
        const helpRow = doc ? `
          <div style="padding:8px 10px; margin-bottom:6px; background:var(--bg-elevated); border-radius:6px; border-left:3px solid var(--accent); font-size:11px; line-height:1.6; color:var(--text-muted);">
            <div style="margin-bottom:2px;">
              <span>${doc.subscription}</span>
            </div>
            <div>
              <a href="${doc.url}" target="_blank" rel="noopener noreferrer" style="color:var(--accent); text-decoration:underline; font-weight:500;">
                ${linkLabel}
              </a>
              ${doc.keyFormat ? `<span style="margin-left:8px; opacity:0.7;">Format: <code style="font-size:10px; padding:1px 4px; background:var(--bg-default); border-radius:3px;">${doc.keyFormat}</code></span>` : ''}
            </div>
          </div>
        ` : '';

        tableHtml += `
          <div>
            <h3 style="font-size:13px; color:var(--text-primary); margin-bottom:8px; border-bottom:1px solid var(--border); padding-bottom:4px;">${displayName}</h3>
            ${helpRow}
            <table style="width:100%; border-collapse:collapse; font-size:12px; text-align:left;">
              <tbody>
        `;
        for (const key of groupKeys) {
          const isSensitive = sensitiveKeywords.some(kw => key.toUpperCase().includes(kw));
          const inputType = isSensitive ? 'password' : 'text';
          const toggleBtn = isSensitive ? `
            <button class="icon-btn btn-toggle-visibility" type="button" style="padding:4px; margin-left:4px;" title="Toggle visibility">
              <svg class="ic" width="14" height="14"><use href="#icon-eye"></use></svg>
            </button>
          ` : '';

          // Look up human-readable label + hint from doc.fields if available
          const fieldMeta = doc?.fields?.find(f => f.key === key);
          const displayLabel = fieldMeta ? fieldMeta.label : key;
          const hintText = fieldMeta?.hint || '';
          const placeholderAttr = hintText ? ` placeholder="${hintText}"` : '';

          tableHtml += `
            <tr style="border-bottom:1px solid var(--border);">
              <td style="padding:8px 4px; color:var(--text-muted); font-size:11px; width:40%;">
                <div style="font-weight:500; color:var(--text-secondary);">${displayLabel}</div>
                ${fieldMeta ? `<div style="font-family:var(--font-mono); font-size:10px; opacity:0.6; margin-top:1px;">${key}</div>` : ''}
              </td>
              <td style="padding:8px 4px; display:flex; align-items:center;">
                <input type="${inputType}" class="settings-input" data-env-key="${key}" value="${d[key] || ''}"${placeholderAttr} style="flex:1; font-family:var(--font-mono); font-size:11px; padding:4px 8px; border:1px solid transparent; background:var(--bg-elevated); outline:none;">
                ${toggleBtn}
              </td>
            </tr>
          `;
        }
        tableHtml += `</tbody></table></div>`;
      }
      tableHtml += `</div>`;
      if (container) {
        container.innerHTML = tableHtml;
        container.querySelectorAll('.btn-toggle-visibility').forEach(btn => {
          btn.addEventListener('click', (e) => {
            const input = e.currentTarget.previousElementSibling;
            input.type = input.type === 'password' ? 'text' : 'password';
          });
        });
      }

      // Populate cloud providers in the performance dashboard
      const providers = [
        { id: 'OLLAMA', name: 'Ollama', keyField: 'OLLAMA_HOST', keyPlaceholder: 'http://localhost:11434', defRate: '1000', rateUnit: 'RPM' },
        { id: 'OPENAI', name: 'OpenAI', keyField: 'OPENAI_API_KEY', keyPlaceholder: 'sk-...', defRate: '500', rateUnit: 'RPM' },
        { id: 'GOOGLE', name: 'Google (Gemini)', keyField: 'GOOGLE_API_KEY', keyPlaceholder: 'AIzaSy...', defRate: '15', rateUnit: 'RPM' },
        { id: 'ANTHROPIC', name: 'Anthropic', keyField: 'ANTHROPIC_API_KEY', keyPlaceholder: 'sk-ant-...', defRate: '5', rateUnit: 'RPM' },
        { id: 'GROK', name: 'Grok', keyField: 'GROK_API_KEY', keyPlaceholder: 'xai-...', defRate: '0', rateUnit: 'RPM' },
        { id: 'GROQ', name: 'Groq', keyField: 'GROQ_API_KEY', keyPlaceholder: 'gsk-...', defRate: '30', rateUnit: 'RPM' },
        { id: 'MISTRAL', name: 'Mistral', keyField: 'MISTRAL_API_KEY', keyPlaceholder: '...', defRate: '60', rateUnit: 'RPM' },
        { id: 'HUGGINGFACE', name: 'HuggingFace', keyField: 'HUGGINGFACE_API_KEY', keyPlaceholder: 'hf_...', defRate: '100', rateUnit: 'RPM' },
        { id: 'OPENROUTER', name: 'OpenRouter', keyField: 'OPENROUTER_API_KEY', keyPlaceholder: 'sk-or-...', defRate: '200', rateUnit: 'RPM' }
      ];

      if (perfProvidersContainer) {
        providers.forEach(p => {
          const apiVal = d[p.keyField] || '';
          const rateVal = d[`${p.id}_RATE_LIMIT`] || p.defRate;
          const creditsVal = parseFloat(d[`${p.id}_CREDITS_USED`] || '0').toFixed(2);

          const cardHtml = `
            <div style="background:var(--bg-default); padding:12px; border-radius:6px; border:1px solid var(--border); display:flex; align-items:center; gap:16px;">
              <h4 style="margin:0; font-size:13px; font-weight:600; display:flex; align-items:center; gap:6px; min-width:140px;">
                <svg class="ic" width="14" height="14" style="color:var(--text-muted)"><use href="#icon-cpu"></use></svg>
                ${p.name}
              </h4>
              <div style="display:flex; gap:16px; flex:1;">
                <div style="flex:1; display:flex; flex-direction:column; gap:4px;">
                  <label style="font-size:11px; color:var(--text-muted);">Rate Limit (${p.rateUnit})</label>
                  <input type="number" class="settings-input perf-provider-input" data-env-key="${p.id}_RATE_LIMIT" value="${rateVal}" style="padding:4px 8px; font-size:12px;">
                </div>
                <div style="flex:1; display:flex; flex-direction:column; gap:4px;">
                  <label style="font-size:11px; color:var(--text-muted);">Credits Used ($)</label>
                  <input type="number" class="settings-input perf-provider-input" data-env-key="${p.id}_CREDITS_USED" value="${creditsVal}" step="0.01" style="padding:4px 8px; font-size:12px; background:transparent;" readonly>
                </div>
              </div>
            </div>
          `;
          perfProvidersContainer.insertAdjacentHTML('beforeend', cardHtml);
        });
      }
    } catch (e) {
      console.error(e);
    }
  }


  // Save Performance Provider Settings
  const btnSavePerfEnv = $('#btn-save-perf-env');
  if (btnSavePerfEnv) {
    btnSavePerfEnv.addEventListener('click', async () => {
      const envData = {};
      $$('#perf-providers-container .perf-provider-input').forEach(inp => {
        // Only save if it's not readonly (we don't want to overwrite credits manually)
        if (!inp.readOnly) {
          envData[inp.dataset.envKey] = inp.value;
        }
      });
      if (Object.keys(envData).length > 0) {
        btnSavePerfEnv.textContent = 'Saving...';
        btnSavePerfEnv.disabled = true;
        try {
          await fetch('/api/env', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(envData) });
          toast(ICONS.check(14) + ' Provider Settings saved');
          loadEnvSettings(); // refresh containers
        } catch (e) {
          toast(ICONS.x(14) + ' Save failed');
        } finally {
          btnSavePerfEnv.textContent = 'Save Provider Settings';
          btnSavePerfEnv.disabled = false;
        }
      }
    });
  }
  // ---- Env Modal management ----
  const btnOpenEnvModal = $('#btn-open-env-modal');
  const envModalOverlay = $('#env-modal-overlay');
  if (btnOpenEnvModal && envModalOverlay) {
    btnOpenEnvModal.addEventListener('click', () => {
      $('#settings-overlay').classList.remove('open');
      envModalOverlay.style.display = 'flex';
      loadEnvSettings();
    });

    const closeEnvModal = () => { envModalOverlay.style.display = 'none'; };
    $('#env-modal-close')?.addEventListener('click', closeEnvModal);
    $('#env-modal-cancel')?.addEventListener('click', closeEnvModal);

    const btnEnvSave = $('#env-modal-save');
    if (btnEnvSave) {
      btnEnvSave.addEventListener('click', async () => {
        const envData = {};
        $$('#env-modal-table-container .settings-input[data-env-key]').forEach(inp => {
          envData[inp.dataset.envKey] = inp.value;
        });
        if (Object.keys(envData).length > 0) {
          btnEnvSave.textContent = 'Saving...';
          btnEnvSave.disabled = true;
          try {
            await fetch('/api/env', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(envData) });
            toast(ICONS.check(14) + ' Environment variables saved');
            closeEnvModal();
          } catch (e) {
            toast(ICONS.x(14) + ' Save failed');
          } finally {
            btnEnvSave.innerHTML = `<svg class="ic" width="14" height="14" style="margin-right: 6px;"><use href="#icon-save"></use></svg> Save Changes`;
            btnEnvSave.disabled = false;
          }
        }
      });
    }
  }

  // ---- RAG Profil management ----

  window.loadRagProfiles = async function () {
    try {
      const r = await fetch('/api/rag-profiles');
      const d = await r.json();
      const container = $('#rag-profiles-container');
      if (container) {
        container.innerHTML = (d.profiles || []).map(p => `
          <button class="btn btn-secondary btn-sm rag-profile-btn" data-profile="${escHtml(p)}" style="justify-content:flex-start">
            <svg class="ic" width="14" height="14" style="margin-right: 6px;">
              <use href="#icon-file-text"></use>
            </svg>
            Open ${escHtml(p)}
          </button>
        `).join('');

        container.querySelectorAll('.rag-profile-btn').forEach(btn => {
          btn.addEventListener('click', async () => {
            await openRagProfilEditor(btn.dataset.profile);
          });
        });
      }
    } catch (e) {
      console.error("Failed to load RAG profiles", e);
    }
  };



  async function openRagProfilEditor(filename) {
    const overlay = $('#rag-profil-editor-overlay');
    const title = $('#rag-profil-editor-title');
    const textarea = $('#rag-profil-editor-textarea');
    const btnSave = $('#rag-profil-editor-save');
    const btnCancel = $('#rag-profil-editor-cancel');
    const btnClose = $('#rag-profil-editor-close');

    if (!overlay) return;
    $('#settings-overlay').classList.remove('open');

    title.textContent = `Edit ${filename}`;
    textarea.value = 'Loading...';
    overlay.style.display = 'flex';

    try {
      const r = await fetch(`/api/rag-profil/${filename}`);
      const d = await r.json();
      textarea.value = d.content || '';
    } catch (e) {
      textarea.value = '';
      toast(ICONS.x(14) + ' Failed to load file');
    }

    const closeHandler = () => { overlay.style.display = 'none'; };
    btnCancel.onclick = closeHandler;
    btnClose.onclick = closeHandler;

    btnSave.onclick = async () => {
      btnSave.disabled = true;
      const originalText = btnSave.innerHTML;
      btnSave.textContent = 'Saving...';
      try {
        await fetch(`/api/rag-profil/${filename}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: textarea.value })
        });
        toast(ICONS.check(14) + ` ${filename} saved successfully`);
        closeHandler();
      } catch (e) {
        toast(ICONS.x(14) + ' Failed to save');
      } finally {
        btnSave.disabled = false;
        btnSave.innerHTML = originalText;
      }
    };
  }

  const btnOptimizeRag = $('#btn-optimize-rag-profil');
  if (btnOptimizeRag) btnOptimizeRag.addEventListener('click', async () => {
    btnOptimizeRag.disabled = true;
    const originalText = btnOptimizeRag.innerHTML;
    btnOptimizeRag.innerHTML = `<span class="tool-spinner"></span> Optimizing...`;
    try {
      const r = await fetch('/api/memory/optimize', { method: 'POST' });
      const d = await r.json();
      if (d.success) toast(ICONS.check(14) + ' Optimization started in background');
      else toast(ICONS.x(14) + ' Optimization failed');
    } catch (e) {
      toast(ICONS.x(14) + ' Error starting optimization');
    } finally {
      btnOptimizeRag.disabled = false;
      btnOptimizeRag.innerHTML = originalText;
    }
  });

  // Clear All History
  const btnClearAllHistory = $('#btn-clear-all-history');
  if (btnClearAllHistory) btnClearAllHistory.addEventListener('click', async () => {
    if (!confirm('Are you sure you want to delete ALL chat sessions? This cannot be undone.')) return;
    try {
      await fetch('/chat/sessions', { method: 'DELETE' });
      toast(ICONS.trash(14) + ' All chat histories deleted');
      window.chat.session_id = null;
      loadSessions();
      $('#chat-history-list').innerHTML = '';
      window.chat.showWelcome();
    } catch (e) { toast(ICONS.x(14) + ' Clear history error'); }
  });

  // ---- Initialize OpenUI-inspired core modules ----

  // Performance indicators (TTFT + tokens/sec) via EventBus
  if (window.EventBus) {
    window.EventBus.on('perf:ttft', (data) => {
      const perfEl = document.getElementById('perf-indicators');
      if (!perfEl) return;
      const ttft = data.ms;
      let existing = perfEl.querySelector('.perf-ttft');
      if (!existing) {
        existing = document.createElement('div');
        existing.className = 'perf-item perf-ttft';
        perfEl.appendChild(existing);
      }
      existing.innerHTML = `⏱️ <span class="perf-value">${ttft < 1000 ? ttft + 'ms' : (ttft / 1000).toFixed(1) + 's'}</span> TTFT`;
    });

    window.EventBus.on('perf:tps', (data) => {
      const perfEl = document.getElementById('perf-indicators');
      if (!perfEl) return;
      let existing = perfEl.querySelector('.perf-tps');
      if (!existing) {
        existing = document.createElement('div');
        existing.className = 'perf-item perf-tps';
        perfEl.appendChild(existing);
      }
      existing.innerHTML = `⚡ <span class="perf-value">${data.tps}</span> tok/s`;
    });

    // Clear perf indicators when a new session starts
    window.EventBus.on('chat:session-new', () => {
      const perfEl = document.getElementById('perf-indicators');
      if (perfEl) perfEl.innerHTML = '';
    });
  }

  // Register built-in components in the ComponentRegistry
  if (window.ComponentRegistry) {
    // Chart.js component
    window.ComponentRegistry.register('chart', {
      detect: (lang) => lang === 'chart',
      render: (container, content, id) => {
        if (!window.Chart) { container.textContent = 'Chart.js not loaded'; return; }
        try {
          const config = JSON.parse(content);
          // Support simplified format: { type, data: { label: value } }
          if (config.data && !config.labels && !config.datasets) {
            const simplified = config.data;
            if (typeof simplified === 'object' && !Array.isArray(simplified)) {
              config.labels = Object.keys(simplified);
              config.datasets = [{ label: config.title || 'Data', data: Object.values(simplified) }];
            }
          }
          const palette = [
            'rgba(99, 102, 241, 0.85)', 'rgba(16, 185, 129, 0.85)',
            'rgba(245, 158, 11, 0.85)', 'rgba(239, 68, 68, 0.85)',
            'rgba(139, 92, 246, 0.85)', 'rgba(6, 182, 212, 0.85)'
          ];
          const chartType = config.type || 'bar';
          const isPie = ['pie', 'doughnut', 'polarArea'].includes(chartType);
          const datasets = (config.datasets || []).map((ds, di) => ({
            label: ds.label || 'Dataset ' + (di + 1),
            data: ds.data || [],
            backgroundColor: isPie ? palette : palette[di % palette.length],
            borderWidth: 2, tension: chartType === 'line' ? 0.35 : undefined,
          }));
          container.style.cssText = 'background:var(--bg-secondary);border-radius:8px;padding:16px;min-height:250px;max-height:420px;position:relative;';
          const canvas = document.createElement('canvas');
          container.appendChild(canvas);
          new Chart(canvas.getContext('2d'), {
            type: chartType, data: { labels: config.labels || [], datasets },
            options: {
              responsive: true, maintainAspectRatio: false,
              plugins: {
                title: { display: !!config.title, text: config.title || '', color: '#e1e5eb' },
                legend: { labels: { color: '#9ca3af' } }
              },
              scales: isPie ? {} : {
                x: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(255,255,255,0.06)' } },
                y: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(255,255,255,0.06)' }, beginAtZero: true }
              }
            }
          });
        } catch (e) {
          container.innerHTML = '<div style="color:#f87171;padding:12px;">⚠️ Chart error: ' + e.message + '</div>';
        }
      },
      destroy: (container) => {
        const canvas = container.querySelector('canvas');
        if (canvas) {
          const chart = Chart.getChart(canvas);
          if (chart) chart.destroy();
        }
      }
    });

    // Mermaid diagram component
    window.ComponentRegistry.register('mermaid', {
      detect: (lang) => lang === 'mermaid',
      render: async (container, content, id) => {
        if (!window.mermaid) { container.textContent = 'Mermaid not loaded'; return; }
        container.style.cssText = 'background:var(--bg-secondary);border-radius:8px;padding:16px;';
        container.textContent = 'Loading diagram...';
        try {
          const r = await mermaid.render('mmr-' + id, content);
          container.innerHTML = r.svg;
        } catch (e) {
          container.innerHTML = '<div style="color:#f87171;">⚠️ Diagram error: ' + e.message + '</div>';
        }
      }
    });

    console.log('[Clawzd] ComponentRegistry initialized:', window.ComponentRegistry.list().join(', '));
  }

  console.log('[Clawzd] Core modules loaded:', [
    window.EventBus ? 'EventBus' : null,
    window.ComponentRegistry ? 'ComponentRegistry' : null,
    window.StreamingParser ? 'StreamingParser' : null,
    window.ThemeEngine ? 'ThemeEngine' : null,
  ].filter(Boolean).join(', '));

})();
