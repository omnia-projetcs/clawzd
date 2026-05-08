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
  function toast(msg) {
    const t = el('div', { class: 'toast', html: msg });
    document.body.appendChild(t); setTimeout(() => t.remove(), 20300);
  }
  function escHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function timeAgo(iso) {
    const d = new Date(iso), now = new Date(), diff = (now - d) / 1000;
    if (diff < 60) return 'now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h';
    return Math.floor(diff / 86400) + 'd';
  }

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
      setTimeout(async () => {
        const el2 = document.getElementById(id);
        if (el2 && window.mermaid) {
          try {
            const r = await mermaid.render('mmr-' + id, decoded);
            el2.innerHTML = r.svg;
          } catch (e) {
            console.warn('Mermaid render error:', e);
            el2.innerHTML = '<div class="mermaid-error" style="color:#f87171;padding:12px;border:1px solid #f8717133;border-radius:8px;font-family:monospace;font-size:13px;margin-bottom:8px;">⚠️ Diagram error: ' + (e.message || e) + '</div><pre style="margin:0;background:var(--bg-primary);border:1px solid var(--border);border-radius:8px;padding:12px;overflow-x:auto;font-family:monospace;font-size:12px;color:var(--text-secondary);"><code>' + escHtml(decoded) + '</code></pre>';
          }
        }
      }, 150);
      return ph(
        `<div class="mermaid-wrapper" style="position:relative; margin: 16px 0;">` +
        `<div style="text-align:right;margin-bottom:4px; display:flex; gap:8px; justify-content:flex-end;">` +
        `<button class="code-action-btn" onclick="OC.sendMermaidToPresentation('${id}')">${icon('presentation', 14)} To Presentation</button>` +
        `<button class="code-action-btn" onclick="OC.exportMermaidMd('${id}')">${icon('download', 14)} Export MD</button>` +
        `<button class="code-action-btn" onclick="OC.exportMermaidSvg('${id}')">${icon('download', 14)} Export SVG</button>` +
        `</div>` +
        `<div class="mermaid-container" id="${id}" data-code="${escHtml(decoded)}" style="background:var(--bg-secondary); border-radius:8px; padding:16px;">Loading diagram...</div>` +
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

    // Helper: build a code block with header, copy, run, save, and preview buttons
    function codeBlock(lang, label, code) {
      const id = 'cb-' + Math.random().toString(36).slice(2, 8);
      const ll = (lang || '').toLowerCase();
      const run = ['python', 'py', 'sh', 'bash'].includes(ll);
      const preview = ['html', 'htm', 'svg'].includes(ll);
      const rb = run ? `<button class="code-run-btn" onclick="OC.runCode('${id}')">${icon('terminal', 14)} Run</button>` : '';
      const pb = preview ? `<button class="code-action-btn code-preview-btn" onclick="OC.previewHtml('${id}')">${icon('eye', 14)} Preview</button>` : '';
      const sb = `<button class="code-action-btn code-save-btn" onclick="OC.saveToFiles('${id}','${escHtml(lang)}','${escHtml(label)}')">${icon('save', 14)} Save</button>`;
      const lcls = lang ? ` class="language-${lang}"` : '';
      return ph(
        `<div class="code-block-header"><span>${escHtml(label)}</span>` +
        `<div class="code-block-actions">${pb}${sb}<button class="code-action-btn" onclick="OC.copyCode('${id}')">${icon('copy', 14)} Copy</button>${rb}</div></div>` +
        `<pre id="${id}"><code${lcls}>${code}</code></pre>`
      );
    }

    // Tool call blocks — render as collapsible "Thinking..." sections
    // Uses regex literal to avoid new RegExp double-escaping issues. Requires \n before closing ``` to prevent breaking on inner escaped fences
    const toolFenceRe = /```(?:tool_call|tool|json|execute_python|search_web|screenshot_remote|screenshot_local|generate_image|run_command|browse_web|audit_code|rag_search)\s*\n([\s\S]*?)\n```/g;
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
        const readableContent = content.replace(/\\n/g, '\n').replace(/\\"/g, '"');
        detailContent = `<pre style="margin:8px 0;background:var(--bg-primary);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;overflow-x:auto;"><code>${readableContent}</code></pre>`;
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
    h = h.replace(/&lt;think&gt;([\s\S]*?)(?:&lt;\/think&gt;|$)/g, (_, content) => {
      return ph(`<details class="tool-thinking" open><summary> <em>Thinking…</em></summary><div style="padding:12px;color:var(--text-muted);font-style:italic;overflow-x:auto;">${content.trim()}</div></details>`);
    });

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
    h = h.replace(/^### (.+)$/gm, '<h4>$1</h4>');
    h = h.replace(/^## (.+)$/gm, '<h3>$1</h3>');
    h = h.replace(/^# (.+)$/gm, '<h2>$1</h2>');
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
    h = h.replace(/<br>\s*(<\/?(?:ul|ol|li|h[2-4]|img|hr|blockquote|div))/g, '$1');
    h = h.replace(/(<\/(?:ul|ol|li|h[2-4]|blockquote|div)>)\s*<br>/g, '$1');

    // ---- Phase 4: Restore block placeholders ----
    h = h.replace(/\x00BLK(\d+)\x00/g, (_, i) => blocks[parseInt(i)]);

    return h;
  }

  // Apply highlight.js to code blocks after render
  function highlightAll() {
    if (window.hljs) {
      document.querySelectorAll('pre code').forEach(b => {
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
      // Token tracking
      this.tokensSent = 0;
      this.tokensReceived = 0;
      // Streaming render throttle (memory optimization)
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
            const bubble = this.addMsg(m.role, m.content);
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
      } catch (e) { console.error(e); toast('Failed to load session'); }
    }
    connectSSE() {
      if (this.es) this.es.close();
      this.es = new EventSource(`/stream/${this.sessionId}`);
      this.es.onmessage = e => this.handleToken(e.data);
      this.es.onerror = () => { };
    }
    handleToken(tok) {
      if (!this.streaming) {
        this.streaming = true; this.text = ''; this.bubble = this.addMsg('assistant', ''); this.status('streaming');
        if (this.stopBtn) { this.stopBtn.style.display = ''; this.sendBtn.style.display = 'none'; }
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
      this.text += tok;
      if (window.tokenTracker) window.tokenTracker.addOutput(1);

      // Throttle DOM renders to avoid memory saturation (~80ms interval)
      if (!this._renderPending) {
        this._renderPending = true;
        this._renderTimer = setTimeout(() => {
          this._renderPending = false;
          this._renderTimer = null;
          if (!this.bubble) return;

          // Capture open details
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

          this.msgEl.scrollTop = this.msgEl.scrollHeight;
          if (typeof highlightAll === 'function') highlightAll();
        }, 80);
      }
    }
    finish() {
      this.streaming = false;

      // Handle Auto-Plan workflow
      if (this.autoPlanState === 'planning') {
        this.autoPlanState = 'building';
        const capturedPlan = this.text;

        if (this.bubble) {
          const safeHtml = renderMd(capturedPlan);
          this.bubble.innerHTML = `<details class="tool-thinking"><summary><em>🧠 Auto-Planning Phase</em></summary><div style="padding:10px">${safeHtml}</div></details>`;
        }

        this.bubble = null;
        this.text = '';
        this.status('connected');

        // Start Build phase
        setTimeout(async () => {
          toast('Executing the architectural plan...');
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
          } catch (e) { toast(ICONS.x(14) + ' Build phase error'); this.sendBtn.disabled = false; }
        }, 500);
        return; // wait for next stream
      }

      if (this.autoPlanState === 'building') {
        this.autoPlanState = null;
        toast(ICONS.check(14) + ' Auto-Plan & Build Complete');
      }

      if (this.bubble) {
        // Auto-close any unclosed code fences from truncated LLM output
        let text = this.text;
        const fenceCount = (text.match(/```/g) || []).length;
        if (fenceCount % 2 !== 0) text += '\n```';
        this.bubble.innerHTML = renderMd(text);
        this.extractFiles(text);
        highlightAll();
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
      this.hideWelcome();
      this.inputEl.value = ''; this.resize(); this.sendBtn.disabled = true;
      $('#arena-container').style.display = 'grid';
      $('#arena-container').innerHTML = '';
      $('#arena-eval-panel').style.display = 'none';

      const cols = {};
      window.arenaStreams = [];

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
            <div class="arena-col-body" id="col-${stream.stream_id}"></div>
          `;
          $('#arena-container').appendChild(col);
          cols[stream.stream_id] = { text: '', el: col.querySelector('.arena-col-body') };

          const es = new EventSource(`/arena/stream/${stream.stream_id}`);
          es.onerror = () => {
            es.close();
            cols[stream.stream_id].text += "\n\n❌ Connection error";
            cols[stream.stream_id].el.innerHTML = renderMd(cols[stream.stream_id].text);
            activeStreams--;
            if (activeStreams <= 0) {
              this.sendBtn.disabled = false;
              $('#arena-eval-panel').style.display = 'block';
              window.arenaLastPrompt = msg;
            }
          };
          es.onmessage = e => {
            if (e.data === '[DONE]') {
              es.close();
              activeStreams--;
              if (activeStreams <= 0) {
                this.sendBtn.disabled = false;
                $('#arena-eval-panel').style.display = 'block';
                window.arenaLastPrompt = msg;
              }
              if (typeof highlightAll === 'function') highlightAll();
              return;
            }
            cols[stream.stream_id].text += e.data;
            let preview = cols[stream.stream_id].text;

            let statsHtml = '';
            const statsRe = /__STATS__({.+?})__STATS__/;
            const statsMatch = preview.match(statsRe);
            if (statsMatch) {
              try {
                const stats = JSON.parse(statsMatch[1]);
                statsHtml = `<div class="arena-stats" style="margin-top:16px; padding:12px; border-radius:var(--radius-sm); background:var(--bg-tertiary); font-size:12px; border:1px solid var(--border);">
                  <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                    <span style="color:var(--text-muted)">⏱️ Temps de réponse</span>
                    <strong>${stats.time}s</strong>
                  </div>
                  <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                    <span style="color:var(--text-muted)"> Tokens E/S</span>
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

            cols[stream.stream_id].el.innerHTML = renderMd(preview) + statsHtml;
            cols[stream.stream_id].el.scrollTop = cols[stream.stream_id].el.scrollHeight;
            if (typeof highlightAll === 'function') highlightAll();
          };
          window.arenaStreams.push({ id: stream.stream_id, es: es });
        });

      } catch (e) {
        toast(' ' + e.message);
        this.sendBtn.disabled = false;
      }
    }

    async stopGeneration() {
      if (!this.sessionId || !this.streaming) return;
      try {
        await fetch(`/stop/${this.sessionId}`, { method: 'POST' });
      } catch (e) { console.warn('Stop request failed:', e); }
      // Force close SSE
      if (this.es) { this.es.close(); this.es = null; }
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

      // Remove previous suggestion chips
      document.querySelectorAll('.suggestion-chips').forEach(el => el.remove());
      document.querySelectorAll('.mode-switch-hint').forEach(el => el.remove());

      try {
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
            action_mode: actionMode
          })
        });
      } catch (e) { toast(ICONS.x(14) + ' Send error'); this.sendBtn.disabled = false; }
    }
    addMsg(role, content) {
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
      const msgEl2 = el('div', { class: 'message ' + role }, [
        el('div', { class: 'message-header' }, [
          el('div', { class: 'message-avatar', html: avatar }),
          el('span', { class: 'message-author', text: author })
        ]),
        bubble,
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
          const opt = `<option value="${p.key}">${p.icon} ${p.label}</option>`;
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
    models.forEach(m => { sel.innerHTML += `<option value="${m.id}">${m.label}</option>`; });

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
      navigator.clipboard.writeText(c ? c.textContent : b.textContent);
      toast(icon('copy') + ' Copied!');
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

  // ---- Voice Input (Web Speech API / Backend Fallback) ----
  class VoiceInput {
    constructor(inputEl, sendFn) {
      this.inputEl = inputEl;
      this.sendFn = sendFn;
      this.btn = $('#btn-voice');
      if (!this.btn) return;
      this.isRecording = false;

      this.supported = !!(window.SpeechRecognition || window.webkitSpeechRecognition);

      if (this.supported) {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        this.recognition = new SR();
        this.recognition.continuous = true;
        this.recognition.interimResults = true;
        this.recognition.lang = 'fr-FR';
        this.recognition.onresult = (e) => this.onResult(e);
        this.recognition.onerror = (e) => this.onError(e);
        this.recognition.onend = () => this.onEnd();
      } else {
        this.mediaRecorder = null;
        this.audioChunks = [];
      }

      this.btn.addEventListener('click', () => this.toggle());
    }
    async toggle() {
      if (this.isRecording) this.stop(); else await this.start();
    }
    async start() {
      if (this.isRecording) return;

      // Check for secure context (HTTPS required for microphone in most browsers)
      if (!window.isSecureContext && location.protocol !== 'https:' && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
        toast(ICONS.x(14) + ' Microphone requires HTTPS. Use localhost or enable HTTPS in your server.');
        return;
      }

      // Pre-check microphone permission state
      try {
        const perm = await navigator.permissions.query({ name: 'microphone' });
        if (perm.state === 'denied') {
          toast(ICONS.x(14) + ' Microphone blocked by browser. Click the 🔒 icon in the address bar to allow access.');
          return;
        }
      } catch (e) { /* permissions API not supported — proceed anyway */ }

      if (this.supported && this.recognition) {
        try {
          this.recognition.start();
          this.isRecording = true;
          this.btn.classList.add('recording');
          this.btn.title = 'Click to stop recording';
          toast(ICONS.circle(14) + ' Listening...');
        } catch (e) { console.error('Voice error:', e); toast(ICONS.x(14) + ' Voice recognition failed: ' + e.message); }
      } else {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          this.mediaRecorder = new MediaRecorder(stream);
          this.audioChunks = [];
          this.mediaRecorder.ondataavailable = e => { if (e.data.size > 0) this.audioChunks.push(e.data); };
          this.mediaRecorder.onstop = async () => {
            const blob = new Blob(this.audioChunks, { type: 'audio/webm' });
            this.audioChunks = [];
            toast(ICONS.loader ? ICONS.loader(14) + ' Transcribing...' : 'Transcribing...');
            const fd = new FormData();
            fd.append('file', blob, 'audio.webm');
            try {
              const r = await fetch('/api/transcribe', { method: 'POST', body: fd });
              const d = await r.json();
              if (d.text) {
                const val = this.inputEl.value;
                this.inputEl.value = val ? val + ' ' + d.text : d.text;
                this.inputEl.dispatchEvent(new Event('input'));
              } else if (d.error) {
                toast(ICONS.x(14) + ' Transcription error: ' + d.error);
              }
            } catch (e) { toast(ICONS.x(14) + ' Transcription failed'); }
          };
          this.mediaRecorder.start();
          this.isRecording = true;
          this.btn.classList.add('recording');
          this.btn.title = 'Click to stop recording';
          toast(ICONS.circle(14) + ' Recording audio...');
        } catch (e) {
          const msg = e.name === 'NotAllowedError'
            ? ' Microphone blocked. Click 🔒 in address bar to allow.'
            : (e.name === 'NotFoundError' ? ' No microphone found.' : ' Microphone error: ' + e.message);
          toast(ICONS.x(14) + msg);
        }
      }
    }
    stop() {
      if (!this.isRecording) return;
      if (this.supported && this.recognition) {
        this.recognition.stop();
      } else if (this.mediaRecorder) {
        this.mediaRecorder.stop();
        this.mediaRecorder.stream.getTracks().forEach(t => t.stop());
      }
      this.isRecording = false;
      this.btn.classList.remove('recording');
      this.btn.title = 'Voice input';
    }
    onResult(e) {
      let interim = '', final = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) final += t; else interim += t;
      }
      if (final) {
        this.inputEl.value += (this.inputEl.value ? ' ' : '') + final;
        this.inputEl.dispatchEvent(new Event('input'));
      }
    }
    onError(e) {
      console.error('Speech error:', e.error);
      if (e.error !== 'no-speech') toast('Error: ' + e.error);
      this.stop();
    }
    onEnd() {
      if (this.isRecording && this.supported) {
        try { this.recognition.start(); } catch (e) { this.stop(); }
      }
    }
  }

  // ---- Model Manager ----
  class ModelManager {
    constructor() {
      this.overlay = $('#models-overlay');
      this.grid = $('#models-grid');
      this.hwInfo = $('#models-hw-info');
      this.dlBar = $('#models-download-bar');
      this.catalog = [];
      this.hardware = {};
      this.activeVendor = 'all';
      this.pollInterval = null;

      // Close modal
      $('#models-close').addEventListener('click', () => this.close());
      this.overlay.addEventListener('click', e => { if (e.target === this.overlay) this.close(); });

      // Cancel download
      $('#dl-cancel').addEventListener('click', () => this.cancelDownload());
    }

    _bindTabs() {
      $$('#models-tabs .models-tab').forEach(tab => {
        tab.addEventListener('click', () => {
          $$('#models-tabs .models-tab').forEach(t => t.classList.remove('active'));
          tab.classList.add('active');
          this.activeVendor = tab.dataset.vendor;
          this.render();
        });
      });
    }

    renderTabs() {
      // Build dynamic vendor tabs from catalog
      const tabsEl = $('#models-tabs');
      const vendors = [...new Set(this.catalog.map(m => m.vendor))].sort();
      tabsEl.innerHTML = '<button class="models-tab active" data-vendor="all">All</button>';
      vendors.forEach(v => {
        tabsEl.innerHTML += `<button class="models-tab" data-vendor="${escHtml(v)}">${escHtml(v)}</button>`;
      });
      this.activeVendor = 'all';
      this._bindTabs();
    }

    async open() {
      this.overlay.classList.add('open');
      await Promise.all([this.loadCatalog(), this.loadHardware()]);
      this.renderTabs();
      this.render();
      this.startPollDownload();
    }

    close() {
      this.overlay.classList.remove('open');
      this.stopPollDownload();
    }

    async loadCatalog() {
      try {
        const r = await fetch('/models/catalog');
        const d = await r.json();
        this.catalog = d.catalog || [];
      } catch (e) { console.error('Failed to load model catalog:', e); }
    }

    async loadHardware() {
      try {
        const r = await fetch('/models/hardware');
        this.hardware = await r.json();
        const gpu = this.hardware.gpu_name || 'No GPU';
        const vram = this.hardware.vram_total_mib ? `${(this.hardware.vram_total_mib / 1024).toFixed(0)} Go VRAM` : 'VRAM ?';
        const vramFree = this.hardware.vram_free_mib ? `(${(this.hardware.vram_free_mib / 1024).toFixed(1)} Go libre)` : '';
        const ram = this.hardware.ram_total_mib ? `${(this.hardware.ram_total_mib / 1024).toFixed(0)} Go RAM` : '';
        this.hwInfo.textContent = `${gpu} — ${vram} ${vramFree} • ${ram}`;
      } catch (e) {
        this.hwInfo.textContent = 'Hardware info unavailable';
      }
    }

    render() {
      const filtered = this.activeVendor === 'all'
        ? this.catalog
        : this.catalog.filter(m => m.vendor === this.activeVendor);

      if (!filtered.length) {
        this.grid.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-muted);font-size:13px;">No models in this category</div>';
        return;
      }

      const vramTotal = this.hardware.vram_total_mib || 0;
      const CAP_ICONS = { txt: '', image: '️', video: '', mcp: '', code: ICONS.monitor(14) };

      this.grid.innerHTML = filtered.map(m => {
        const canFit = vramTotal > 0 ? (m.vram_min_gb * 1024) <= vramTotal : true;
        const fitClass = canFit ? '' : ' style="opacity:.7"';
        const fitBadge = !canFit ? '<span class="model-meta-tag" style="color:var(--red)"> VRAM insuffisant</span>' : '';
        const downloadedClass = m.downloaded ? ' downloaded' : '';
        const recClass = m.recommended ? ' recommended' : '';
        const activeClass = m.active ? ' active-model' : '';

        // Capability tags
        const caps = (m.capabilities || []).map(c =>
          `<span class="model-cap-tag cap-${escHtml(c)}" title="${escHtml(c)}">${CAP_ICONS[c] || '•'} ${escHtml(c)}</span>`
        ).join('');

        let actions = '';
        const modelRef = m.ollama_id || m.id;
        if (m.downloaded) {
          if (m.active) {
            actions = `
              <button class="btn btn-active-indicator" disabled> Active</button>
              <button class="btn btn-danger" onclick="OC.deleteModel('${escHtml(modelRef)}','${escHtml(m.name)}')"> Delete</button>`;
          } else {
            actions = `
              <button class="btn btn-success" onclick="OC.activateModel('${escHtml(modelRef)}')"> Activate</button>
              <button class="btn btn-danger" onclick="OC.deleteModel('${escHtml(modelRef)}','${escHtml(m.name)}')"> Delete</button>`;
          }
        } else {
          actions = `
            <button class="btn btn-download" onclick="OC.downloadModel('${escHtml(m.id)}')">⬇ Download</button>`;
        }

        const statusHtml = m.active
          ? `<div class="model-card-status active-status"> Active${m.local_size_gb ? ` (${m.local_size_gb} GB)` : ''}</div>`
          : m.downloaded
            ? `<div class="model-card-status downloaded"> Downloaded${m.local_size_gb ? ` (${m.local_size_gb} GB)` : ''}</div>`
            : `<div class="model-card-status not-downloaded">○ Not downloaded</div>`;

        return `
          <div class="model-card${downloadedClass}${recClass}${activeClass}"${fitClass}>
            <div class="model-card-header">
              <span class="model-card-vendor vendor-${m.vendor}">${escHtml(m.vendor)}</span>
              <span class="model-card-name">${escHtml(m.name)}</span>
            </div>
            <div class="model-card-desc">${escHtml(m.description)}</div>
            <div class="model-card-caps">${caps}</div>
            <div class="model-card-meta">
              <span class="model-meta-tag params">${m.params}</span>
              <span class="model-meta-tag size">${m.size_gb} Go</span>
              <span class="model-meta-tag vram">≥ ${m.vram_min_gb} Go VRAM</span>
              <span class="model-meta-tag">${m.quant}</span>
              ${m.release_date ? `<span class="model-meta-tag date"> ${m.release_date}</span>` : ''}
              ${fitBadge}
            </div>
            ${statusHtml}
            <div class="model-card-actions">${actions}</div>
          </div>`;
      }).join('');
    }

    async downloadModel(modelId) {
      try {
        const r = await fetch('/models/download', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model_id: modelId }),
        });
        const d = await r.json();
        if (!r.ok) { toast(' ' + (d.detail || 'Download failed')); return; }
        toast('⬇ Download started: ' + (d.ollama_id || d.model_id || d.filename));
        this.dlBar.style.display = 'flex';
        this.startPollDownload();
      } catch (e) { toast('${ICONS.x(14)} Error: ' + e.message); }
    }

    async cancelDownload() {
      try {
        await fetch('/models/download/cancel', { method: 'POST' });
        toast('Download cancelled');
        this.dlBar.style.display = 'none';
      } catch (e) { /* ignore */ }
    }

    startPollDownload() {
      this.stopPollDownload();
      this.pollInterval = setInterval(() => this.pollDownload(), 1000);
    }

    stopPollDownload() {
      if (this.pollInterval) {
        clearInterval(this.pollInterval);
        this.pollInterval = null;
      }
    }

    async pollDownload() {
      try {
        const r = await fetch('/models/download/status');
        const d = await r.json();

        // Check for errors first — even if download already stopped
        if (d.error) {
          toast(' Download error: ' + d.error);
          this.dlBar.style.display = 'none';
          this.stopPollDownload();
          return;
        }

        if (d.active || d.completed) {
          this.dlBar.style.display = 'flex';
          $('#dl-filename').textContent = d.ollama_id || d.model_id || d.status_text || '—';
          $('#dl-fill').style.width = d.progress + '%';
          $('#dl-stats').textContent = `${d.downloaded_mb || 0} / ${d.total_mb || '?'} MB — ${d.speed_mbps || 0} MB/s — ${Math.round(d.progress || 0)}%`;

          if (d.completed) {
            toast(' Model downloaded: ' + (d.ollama_id || d.model_id));
            this.dlBar.style.display = 'none';
            this.stopPollDownload();
            await this.loadCatalog();
            this.render();
          }
        } else {
          this.dlBar.style.display = 'none';
          this.stopPollDownload();
        }
      } catch (e) { /* ignore */ }
    }

    async deleteModel(filename, name) {
      if (!confirm(`Delete model "${name}" (${filename})?`)) return;
      try {
        const r = await fetch('/models/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename }),
        });
        if (r.ok) {
          const d = await r.json();
          if (d.was_active && d.fallback_model) {
            toast(`${ICONS.circle(14)} Deleted active model. Switched to: ${d.fallback_model}`);
          } else if (d.was_active) {
            toast(ICONS.circle(14) + ' Active model deleted — no fallback available');
          } else {
            toast(' Model deleted: ' + filename);
          }
          await this.loadCatalog();
          this.render();
          loadProviders();
        } else {
          const d = await r.json();
          toast(' ' + (d.detail || 'Delete failed'));
        }
      } catch (e) { toast('${ICONS.x(14)} Error: ' + e.message); }
    }

    async activateModel(filename) {
      try {
        const r = await fetch('/models/activate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename }),
        });
        const d = await r.json();
        if (r.ok) {
          toast(' ' + d.message);
          await this.loadCatalog();
          this.render();
          // Refresh provider/model picker to show the new active model
          loadProviders();
        } else {
          toast(' ' + (d.detail || 'Activation failed'));
        }
      } catch (e) { toast('${ICONS.x(14)} Error: ' + e.message); }
    }
  }

  // ---- Editor Mode (Claude Code-style IDE) ----
  class EditorMode {
    constructor() {
      this.active = false;
      this.files = [];
      this.openTabs = []; // [{path, content, modified}]
      this.activeTab = null;
      this.cmView = null;
      this.collapsed = new Set();
      this.editorSessionId = null;
      this.editorES = null;
      this.editorStreaming = false;
      this.editorText = '';
      this.editorBubble = null;
      // --- OpenCode features ---
      this.agentMode = 'build'; // 'build' | 'plan'
      this.changeHistory = []; // [{path, oldContent, newContent, timestamp}]
      this.changeHistoryIdx = -1;
      this.todoItems = JSON.parse(localStorage.getItem('hoc-todo') || '[]');
      this.attachedFiles = []; // [{path, content}]
      this.fileRefIndex = -1;
      this.editorTokenCount = 0; // approximate context token count
      this.TOKEN_LIMIT = 30000;
    }

    toggle(on) {
      this.active = on;
      const editorLayout = $('#editor-layout');
      if (on) {
        editorLayout.classList.add('active');
        this.loadTree();
      } else {
        editorLayout.classList.remove('active');
      }
    }

    // ---- File Tree ----
    async loadTree() {
      try {
        const r = await fetch('/workspace/tree');
        const d = await r.json();
        this.files = d.files || [];
        this.renderTree();
      } catch (e) { toast(ICONS.x(14) + ' Failed to load workspace'); }
    }

    _fileIcon(name) {
      const ext = name.split('.').pop().toLowerCase();
      // Language-specific SVG icons
      const pyIcon = '<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#3572A5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>';
      const jsIcon = '<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#F7DF1E" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>';
      const htmlIcon = '<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#E34F26" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>';
      const cssIcon = '<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#1572B6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="13.5" cy="6.5" r="1.5"/><circle cx="17.5" cy="10.5" r="1.5"/><circle cx="8.5" cy="7.5" r="1.5"/><circle cx="6.5" cy="12.5" r="1.5"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.93 0 1.5-.67 1.5-1.5 0-.38-.14-.74-.39-1.02-.24-.27-.37-.63-.37-1.01 0-.83.67-1.5 1.5-1.5H16c3.31 0 6-2.69 6-6 0-5.5-4.5-9.97-10-9.97z"/></svg>';
      const mdIcon = '<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>';
      const configIcon = '<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4"/></svg>';
      const defaultIcon = '<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
      const jsonIcon = '<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#F5A623" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
      const map = { py: pyIcon, js: jsIcon, jsx: jsIcon, ts: jsIcon, tsx: jsIcon, html: htmlIcon, htm: htmlIcon, css: cssIcon, scss: cssIcon, json: jsonIcon, md: mdIcon, sh: configIcon, yml: configIcon, yaml: configIcon, toml: configIcon, sql: configIcon, txt: mdIcon, csv: mdIcon, xml: htmlIcon, svg: cssIcon, java: jsIcon, go: jsIcon, rs: jsIcon, rb: jsIcon, php: jsIcon };
      return map[ext] || defaultIcon;
    }

    _buildDirTree() {
      const tree = {};
      this.files.sort((a, b) => a.path.localeCompare(b.path)).forEach(f => {
        const parts = f.path.split('/');
        let node = tree;
        for (let i = 0; i < parts.length - 1; i++) {
          if (!node[parts[i]]) node[parts[i]] = {};
          node = node[parts[i]];
        }
        node['__f__' + parts[parts.length - 1]] = f;
      });
      return tree;
    }

    _renderTreeNode(node, parentPath, depth, container) {
      const entries = Object.entries(node).sort(([a, va], [b, vb]) => {
        const aD = typeof va === 'object' && !a.startsWith('__f__');
        const bD = typeof vb === 'object' && !b.startsWith('__f__');
        if (aD !== bD) return aD ? -1 : 1;
        return a.localeCompare(b);
      });
      entries.forEach(([key, val]) => {
        if (key.startsWith('__f__')) {
          const f = val;
          const name = key.slice(5);
          const indent = depth * 14;
          const isActive = this.activeTab === f.path;
          const div = el('div', {
            class: 'eft-file' + (isActive ? ' active' : ''),
            style: `padding-left:${20 + indent}px`,
            onclick: () => this.openFile(f.path)
          }, [
            el('span', { class: 'eft-file-icon', html: this._fileIcon(name) }),
            el('span', { class: 'eft-file-name', text: name }),
            el('span', { class: 'eft-file-size', text: f.size > 1024 ? (f.size / 1024).toFixed(0) + 'K' : f.size + 'B' }),
            el('div', { class: 'eft-file-actions' }, [
              el('button', { class: 'eft-file-btn rename', html: ICONS.pen(12), title: 'Rename', onclick: e => { e.stopPropagation(); this.renameFile(f.path); } }),
              el('button', { class: 'eft-file-btn delete', html: ICONS.trash(12), title: 'Delete', onclick: e => { e.stopPropagation(); this.deleteFile(f.path); } })
            ])
          ]);
          container.appendChild(div);
        } else {
          const dirPath = parentPath ? parentPath + '/' + key : key;
          const isOpen = !this.collapsed.has(dirPath);
          const indent = depth * 14;
          const div = el('div', {
            class: 'eft-dir' + (isOpen ? ' open' : ''),
            style: `padding-left:${8 + indent}px`,
          }, [
            el('span', { class: 'eft-dir-arrow', text: '►', onclick: e => { e.stopPropagation(); if (this.collapsed.has(dirPath)) this.collapsed.delete(dirPath); else this.collapsed.add(dirPath); this.renderTree(); } }),
            el('span', { text: isOpen ? '' : '', style: 'font-size:13px', onclick: () => { if (this.collapsed.has(dirPath)) this.collapsed.delete(dirPath); else this.collapsed.add(dirPath); this.renderTree(); } }),
            el('span', { text: key, style: 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer', onclick: () => { if (this.collapsed.has(dirPath)) this.collapsed.delete(dirPath); else this.collapsed.add(dirPath); this.renderTree(); } }),
            el('div', { class: 'eft-file-actions' }, [
              el('button', { class: 'eft-file-btn rename', html: ICONS.pen(12), title: 'Rename folder', onclick: e => { e.stopPropagation(); this.renameFile(dirPath); } }),
              el('button', { class: 'eft-file-btn delete', html: ICONS.trash(12), title: 'Delete folder', onclick: e => { e.stopPropagation(); this.deleteDir(dirPath); } })
            ])
          ]);
          container.appendChild(div);
          if (isOpen) this._renderTreeNode(val, dirPath, depth + 1, container);
        }
      });
    }

    renderTree() {
      const list = $('#eft-list');
      list.innerHTML = '';
      if (!this.files.length) { list.innerHTML = '<div class="eft-empty">Workspace is empty.<br>Create a file or ask the AI to generate code.</div>'; return; }
      const tree = this._buildDirTree();
      this._renderTreeNode(tree, '', 0, list);
    }

    // ---- File Operations ----
    _isBinaryExt(path) {
      const ext = path.split('.').pop().toLowerCase();
      const binaryExts = new Set(['png', 'jpg', 'jpeg', 'gif', 'bmp', 'ico', 'svg', 'webp', 'mp4', 'webm', 'mp3', 'wav', 'ogg', 'pdf', 'zip', 'tar', 'gz', '7z', 'rar', 'woff', 'woff2', 'ttf', 'otf', 'eot', 'exe', 'dll', 'so', 'dylib', 'pyc', 'pyo', 'class', 'o', 'obj']);
      return binaryExts.has(ext);
    }

    _isImageExt(path) {
      const ext = path.split('.').pop().toLowerCase();
      return ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'ico', 'svg', 'webp'].includes(ext);
    }

    async openFile(path) {
      // Handle binary files — show preview instead of editor
      if (this._isBinaryExt(path)) {
        this.activeTab = path;
        this.renderTabs();
        this.renderTree();
        const area = $('#editor-code-area');
        const welcome = $('#editor-welcome');
        if (welcome) welcome.style.display = 'none';
        if (this._isImageExt(path)) {
          area.innerHTML = `
            <div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:24px;gap:16px;overflow:auto;">
              <div style="font-size:12px;color:var(--text-muted);font-weight:600;">${escHtml(path)}</div>
              <img src="/workspace/file-raw?path=${encodeURIComponent(path)}"
                   alt="${escHtml(path)}"
                   style="max-width:90%;max-height:70vh;border-radius:8px;border:1px solid var(--border);box-shadow:0 4px 20px rgba(0,0,0,.3);object-fit:contain;">
              <div style="font-size:11px;color:var(--text-muted);">Image preview</div>
            </div>`;
        } else {
          const ext = path.split('.').pop().toUpperCase();
          area.innerHTML = `
            <div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;color:var(--text-muted);padding:40px;">
              <div style="font-size:48px;opacity:.4;"></div>
              <div style="font-size:14px;font-weight:600;">${escHtml(path.split('/').pop())}</div>
              <div style="font-size:12px;">Binary file (.${ext.toLowerCase()}) — cannot be edited</div>
            </div>`;
        }
        return;
      }

      let tab = this.openTabs.find(t => t.path === path);
      if (!tab) {
        try {
          const r = await fetch('/workspace/file?path=' + encodeURIComponent(path));
          if (!r.ok) { toast(ICONS.x(14) + ' Cannot read file'); return; }
          const d = await r.json();
          tab = { path, content: d.content, original: d.content, modified: false };
          this.openTabs.push(tab);
        } catch (e) { toast(ICONS.x(14) + ' Read error'); return; }
      }
      this.activeTab = path;
      this.renderTabs();
      this.renderTree();
      this.loadIntoEditor(tab);
    }

    async saveFile(path) {
      const tab = this.openTabs.find(t => t.path === path);
      if (!tab) return;
      try {
        await fetch('/workspace/file', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: tab.path, content: tab.content })
        });
        tab.original = tab.content;
        tab.modified = false;
        this.renderTabs();
        toast(icon('save') + ' Saved: ' + path.split('/').pop());
        this.addActivity(icon('save'), 'File saved', path);
      } catch (e) { toast(ICONS.x(14) + ' Save error'); }
    }

    async createFile() {
      const name = prompt('File name (e.g. src/main.py):');
      if (!name || !name.trim()) return;

      const project = $('#project-select') ? $('#project-select').value : '.';
      let fullPath = name.trim();
      if (project && project !== '.' && !fullPath.startsWith(project + '/')) {
        fullPath = project + '/' + fullPath;
      }

      try {
        await fetch('/workspace/file', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: fullPath, content: '' })
        });
        await this.loadTree();
        this.openFile(fullPath);
        this.addActivity(icon('filePlus'), 'File created', fullPath);
      } catch (e) { toast(ICONS.x(14) + ' Create error'); }
    }

    async deleteFile(path) {
      if (!confirm('Delete ' + path + '?')) return;
      try {
        await fetch('/workspace/file?path=' + encodeURIComponent(path), { method: 'DELETE' });
        this.openTabs = this.openTabs.filter(t => t.path !== path);
        if (this.activeTab === path) {
          this.activeTab = this.openTabs.length ? this.openTabs[this.openTabs.length - 1].path : null;
        }
        await this.loadTree();
        if (this.activeTab) this.openFile(this.activeTab);
        else { this.renderTabs(); this.showWelcome(); }
        this.addActivity(icon('trash'), 'File deleted', path);
      } catch (e) { toast(ICONS.x(14) + ' Delete error'); }
    }

    async deleteDir(dirPath) {
      if (!confirm('Delete folder "' + dirPath + '" and all its contents?')) return;
      try {
        const resp = await fetch('/workspace/dir?path=' + encodeURIComponent(dirPath), { method: 'DELETE' });
        if (!resp.ok) {
          const d = await resp.json();
          toast(' ' + (d.detail || 'Delete failed'));
          return;
        }
        // Close any open tabs inside the deleted directory
        this.openTabs = this.openTabs.filter(t => !t.path.startsWith(dirPath + '/') && t.path !== dirPath);
        if (this.activeTab && (this.activeTab.startsWith(dirPath + '/') || this.activeTab === dirPath)) {
          this.activeTab = this.openTabs.length ? this.openTabs[this.openTabs.length - 1].path : null;
        }
        await this.loadTree();
        if (this.activeTab) this.openFile(this.activeTab);
        else { this.renderTabs(); this.showWelcome(); }
        this.addActivity(icon('trash'), 'Folder deleted', dirPath);
      } catch (e) { toast(' Delete error: ' + e.message); }
    }

    closeTab(path) {
      const tab = this.openTabs.find(t => t.path === path);
      if (tab && tab.modified && !confirm('Discard unsaved changes?')) return;
      this.openTabs = this.openTabs.filter(t => t.path !== path);
      if (this.activeTab === path) {
        this.activeTab = this.openTabs.length ? this.openTabs[this.openTabs.length - 1].path : null;
      }
      this.renderTabs();
      this.renderTree();
      if (this.activeTab) { const t = this.openTabs.find(t2 => t2.path === this.activeTab); if (t) this.loadIntoEditor(t); }
      else this.showWelcome();
    }

    closeAllTabs() {
      const hasUnsaved = this.openTabs.some(t => t.modified);
      if (hasUnsaved && !confirm('Discard all unsaved changes?')) return;
      this.openTabs = [];
      this.activeTab = null;
      this.renderTabs();
      this.renderTree();
      this.showWelcome();
    }


    renderTabs() {
      const tabsEl = $('#editor-tabs');
      tabsEl.innerHTML = '';
      this.openTabs.forEach((tab, tabIndex) => {
        const name = tab.path.split('/').pop();
        const tabEl = el('div', {
          class: 'editor-tab' + (tab.path === this.activeTab ? ' active' : '') + (tab.modified ? ' modified' : ''),
          onclick: () => { this.activeTab = tab.path; this.renderTabs(); this.renderTree(); this.loadIntoEditor(tab); }
        }, [
          el('span', { class: 'editor-tab-icon', html: this._fileIcon(name) }),
          el('span', { class: 'editor-tab-name', text: name }),
          el('span', { class: 'editor-tab-modified' }),
          el('button', { class: 'editor-tab-close', text: '', onclick: e => { e.stopPropagation(); this.closeTab(tab.path); } })
        ]);
        // Right-click context menu
        tabEl.addEventListener('contextmenu', e => {
          e.preventDefault();
          this._showTabContextMenu(e, tab.path, tabIndex);
        });
        tabsEl.appendChild(tabEl);
      });
      // Update breadcrumb
      const bc = $('#editor-breadcrumb');
      if (this.activeTab) {
        const parts = this.activeTab.split('/');
        bc.innerHTML = '<span>workspace</span>' + parts.map(p => '<span class="editor-breadcrumb-sep">›</span><span>' + escHtml(p) + '</span>').join('');
      } else {
        bc.innerHTML = '<span>workspace</span>';
      }

      // Scroll active tab into view & update scroll buttons
      requestAnimationFrame(() => {
        const activeEl = tabsEl.querySelector('.editor-tab.active');
        if (activeEl) activeEl.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
        this._updateTabScrollButtons();
      });

      // Wire up scroll buttons once
      if (!this._tabScrollWired) {
        this._tabScrollWired = true;
        const leftBtn = $('#editor-tabs-scroll-left');
        const rightBtn = $('#editor-tabs-scroll-right');
        const closeAllBtn = $('#editor-tabs-close-all');
        if (leftBtn) leftBtn.addEventListener('click', (e) => {
          e.preventDefault(); e.stopPropagation();
          const t = $('#editor-tabs');
          if (t) { t.scrollLeft -= 150; }
          setTimeout(() => this._updateTabScrollButtons(), 250);
        });
        if (rightBtn) rightBtn.addEventListener('click', (e) => {
          e.preventDefault(); e.stopPropagation();
          const t = $('#editor-tabs');
          if (t) { t.scrollLeft += 150; }
          setTimeout(() => this._updateTabScrollButtons(), 250);
        });
        if (closeAllBtn) closeAllBtn.addEventListener('click', () => this.closeAllTabs());
        // Update buttons on scroll and resize
        const tabsContainer = $('#editor-tabs');
        if (tabsContainer) {
          tabsContainer.addEventListener('scroll', () => this._updateTabScrollButtons());
          if (window.ResizeObserver) {
            new ResizeObserver(() => this._updateTabScrollButtons()).observe(tabsContainer);
          }
        }
      }
    }

    _updateTabScrollButtons() {
      const tabsEl = $('#editor-tabs');
      const leftBtn = $('#editor-tabs-scroll-left');
      const rightBtn = $('#editor-tabs-scroll-right');
      if (!tabsEl || !leftBtn || !rightBtn) return;
      const atLeft = tabsEl.scrollLeft <= 1;
      const atRight = tabsEl.scrollLeft + tabsEl.clientWidth >= tabsEl.scrollWidth - 1;
      leftBtn.disabled = atLeft;
      rightBtn.disabled = atRight;
    }

    _showTabContextMenu(e, path, index) {
      // Remove any existing menu
      const old = document.querySelector('.editor-tab-context');
      if (old) old.remove();

      const isFirst = index === 0;
      const isLast = index === this.openTabs.length - 1;
      const name = path.split('/').pop();

      const menu = document.createElement('div');
      menu.className = 'editor-tab-context';
      menu.style.left = e.clientX + 'px';
      menu.style.top = e.clientY + 'px';

      const items = [
        { label: '◄ Move Left', icon: '◄', action: () => this._moveTab(index, -1), disabled: isFirst },
        { label: '► Move Right', icon: '►', action: () => this._moveTab(index, 1), disabled: isLast },
        { sep: true },
        { label: ' Close', action: () => this.closeTab(path) },
        {
          label: ' Close Others', action: () => {
            const hasUnsaved = this.openTabs.some(t => t.path !== path && t.modified);
            if (hasUnsaved && !confirm('Discard unsaved changes in other tabs?')) return;
            this.openTabs = this.openTabs.filter(t => t.path === path);
            this.activeTab = path;
            this.renderTabs(); this.renderTree();
            const t = this.openTabs.find(t2 => t2.path === path);
            if (t) this.loadIntoEditor(t);
          }
        },
        { label: ' Close All', action: () => this.closeAllTabs(), cls: 'danger' },
      ];

      items.forEach(item => {
        if (item.sep) {
          const sep = document.createElement('div');
          sep.className = 'editor-tab-context-sep';
          menu.appendChild(sep);
          return;
        }
        const row = document.createElement('div');
        row.className = 'editor-tab-context-item' + (item.cls ? ' ' + item.cls : '');
        row.textContent = item.label;
        if (item.disabled) {
          row.style.opacity = '0.3';
          row.style.pointerEvents = 'none';
        } else {
          row.addEventListener('click', () => { menu.remove(); item.action(); });
        }
        menu.appendChild(row);
      });

      document.body.appendChild(menu);

      // Keep menu in viewport
      requestAnimationFrame(() => {
        const rect = menu.getBoundingClientRect();
        if (rect.right > window.innerWidth) menu.style.left = (window.innerWidth - rect.width - 8) + 'px';
        if (rect.bottom > window.innerHeight) menu.style.top = (window.innerHeight - rect.height - 8) + 'px';
      });

      // Dismiss on click outside
      const dismiss = (ev) => {
        if (!menu.contains(ev.target)) { menu.remove(); document.removeEventListener('mousedown', dismiss); }
      };
      setTimeout(() => document.addEventListener('mousedown', dismiss), 10);
    }

    _moveTab(index, direction) {
      const newIndex = index + direction;
      if (newIndex < 0 || newIndex >= this.openTabs.length) return;
      const temp = this.openTabs[index];
      this.openTabs[index] = this.openTabs[newIndex];
      this.openTabs[newIndex] = temp;
      this.renderTabs();
    }

    // ---- CodeMirror 6 Editor ----
    loadIntoEditor(tab) {
      const area = $('#editor-code-area');
      const welcome = $('#editor-welcome');
      if (welcome) welcome.style.display = 'none';

      // Try CodeMirror 6 first, fallback to textarea
      if (window.cm6) {
        this._loadCM6Editor(tab, area);
      } else {
        this._loadTextareaEditor(tab, area);
      }

      // Update breadcrumb
      const bc = $('#editor-breadcrumb');
      if (bc) bc.innerHTML = tab.path.split('/').map((p, i, arr) =>
        i === arr.length - 1 ? `<span class="bc-file">${escHtml(p)}</span>` : `<span>${escHtml(p)}</span><span class="bc-sep">/</span>`
      ).join('');
    }

    _loadCM6Editor(tab, area) {
      // Destroy previous CM6 view if switching tabs
      if (this._cmView && this._cmActiveTab !== tab.path) {
        this._cmView.destroy();
        this._cmView = null;
        clearInterval(this._cmChangeInterval);
        this._cmClearGhost();
      }

      if (!this._cmView) {
        area.innerHTML = '';
        const container = document.createElement('div');
        container.className = 'code-editor-wrap cm6-editor-wrap';
        container.style.cssText = 'flex:1;display:flex;flex-direction:column;overflow:hidden;position:relative;';
        area.appendChild(container);

        // Ghost text overlay for CM6
        const ghostOverlay = document.createElement('div');
        ghostOverlay.className = 'cm6-ghost-overlay';
        ghostOverlay.id = 'cm6-ghost';
        container.appendChild(ghostOverlay);

        const builder = cm6.load();
        const view = builder.newEditor(container, tab.content, {
          dark: true,
          lineWrapping: true,
          focus: { value: tab.content },
        });

        this._cmView = view;
        this._cmActiveTab = tab.path;
        this._currentLang = this._extToLang(tab.path);
        this._cmGhostText = '';
        this._cmGhostCursorPos = -1;
        this._cmLastContent = tab.content;

        const editorInstance = this;

        // Track changes + trigger autocomplete
        this._cmChangeInterval = setInterval(() => {
          if (!editorInstance._cmView || !editorInstance.activeTab) return;
          const currentContent = editorInstance._cmView.state.doc.toString();
          const t = editorInstance.openTabs.find(t2 => t2.path === editorInstance.activeTab);
          if (t && t.content !== currentContent) {
            t.content = currentContent;
            t.modified = t.content !== t.original;
            editorInstance.renderTabs();
            // Content changed — clear ghost and schedule autocomplete
            editorInstance._cmClearGhost();
            clearTimeout(editorInstance._autoSaveTimer);
            editorInstance._autoSaveTimer = setTimeout(() => {
              const tab2 = editorInstance.openTabs.find(t2 => t2.path === editorInstance.activeTab);
              if (tab2 && tab2.modified) {
                editorInstance.saveFile(tab2.path);
                editorInstance._showAutoSaveIndicator();
              }
            }, 2000);
            // Debounced AI autocomplete (500ms after last change)
            clearTimeout(editorInstance._cmAcTimer);
            if (editorInstance._acEnabled) {
              editorInstance._cmAcTimer = setTimeout(() => editorInstance._cmTriggerAutocomplete(), 500);
            }
            editorInstance._cmLastContent = currentContent;
          }
        }, 200);

        // Key handlers for ghost text + save
        container.addEventListener('keydown', e => {
          // Ctrl+S save
          if (e.ctrlKey && e.key === 's') {
            e.preventDefault();
            editorInstance.saveFile(editorInstance.activeTab);
            return;
          }
          // Tab: accept full ghost text
          if (e.key === 'Tab' && !e.shiftKey && editorInstance._cmGhostText) {
            e.preventDefault();
            editorInstance._cmAcceptGhost();
            return;
          }
          // Ctrl+Right: accept next word of ghost text
          if (e.ctrlKey && e.key === 'ArrowRight' && editorInstance._cmGhostText) {
            e.preventDefault();
            editorInstance._cmAcceptGhostWord();
            return;
          }
          // Escape: dismiss ghost
          if (e.key === 'Escape' && editorInstance._cmGhostText) {
            editorInstance._cmClearGhost();
            return;
          }
          // Any other key that isn't a modifier — dismiss ghost
          if (editorInstance._cmGhostText && !['Shift', 'Control', 'Alt', 'Meta'].includes(e.key)) {
            editorInstance._cmClearGhost();
          }
        });

        // Click dismisses ghost
        container.addEventListener('mousedown', () => {
          if (editorInstance._cmGhostText) editorInstance._cmClearGhost();
        });

      } else {
        // Same tab reload — just update content if different
        const currentContent = this._cmView.state.doc.toString();
        if (currentContent !== tab.content) {
          this._cmView.dispatch({
            changes: { from: 0, to: currentContent.length, insert: tab.content }
          });
        }
      }
    }

    // ---- CM6 Ghost Text Autocomplete ----
    _cmGhostText = '';
    _cmGhostCursorPos = -1;
    _cmAcTimer = null;
    _cmAcAbort = null;

    _cmClearGhost() {
      this._cmGhostText = '';
      this._cmGhostCursorPos = -1;
      const ghost = document.getElementById('cm6-ghost');
      if (ghost) { ghost.innerHTML = ''; ghost.style.display = 'none'; }
    }

    _cmAcceptGhost() {
      if (!this._cmView || !this._cmGhostText) return;
      const cursor = this._cmView.state.selection.main.head;
      this._cmView.dispatch({
        changes: { from: cursor, insert: this._cmGhostText }
      });
      // Move cursor to end of inserted text
      const newPos = cursor + this._cmGhostText.length;
      this._cmView.dispatch({ selection: { anchor: newPos } });
      this._cmClearGhost();
    }

    _cmAcceptGhostWord() {
      if (!this._cmView || !this._cmGhostText) return;
      const wordMatch = this._cmGhostText.match(/^(\S+\s?)/);
      if (!wordMatch) return;
      const word = wordMatch[1];
      const cursor = this._cmView.state.selection.main.head;
      this._cmView.dispatch({
        changes: { from: cursor, insert: word }
      });
      const newPos = cursor + word.length;
      this._cmView.dispatch({ selection: { anchor: newPos } });
      this._cmGhostText = this._cmGhostText.substring(word.length);
      if (!this._cmGhostText.trim()) {
        this._cmClearGhost();
      } else {
        this._cmGhostCursorPos = newPos;
        this._cmRenderGhost();
      }
    }

    async _cmTriggerAutocomplete() {
      if (!this._cmView || !this._acEnabled) return;
      const doc = this._cmView.state.doc.toString();
      if (!doc.trim()) return;
      const cursor = this._cmView.state.selection.main.head;
      // Don't trigger if selection
      if (this._cmView.state.selection.main.anchor !== cursor) return;

      const prefix = doc.substring(Math.max(0, cursor - 1500), cursor);
      const suffix = doc.substring(cursor, Math.min(doc.length, cursor + 500));
      const lastLine = prefix.split('\n').pop();
      if (!lastLine.trim() && prefix.trim().length < 20) return;

      const intent = this._detectCompletionIntent(prefix, suffix);
      const maxTokens = intent === 'comment_generate' ? 250 : 120;

      if (this._cmAcAbort) { this._cmAcAbort.abort(); this._cmAcAbort = null; }
      const controller = new AbortController();
      this._cmAcAbort = controller;
      this._cmGhostCursorPos = cursor;

      try {
        const r = await fetch('/api/autocomplete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prefix, suffix, intent,
            language: this._currentLang || 'plaintext',
            file_path: this.activeTab || '',
            provider: $('#provider-select').value,
            model: $('#model-select').value,
            max_tokens: maxTokens
          }),
          signal: controller.signal
        });
        if (!r.ok) return;
        const d = await r.json();
        let completion = (d.completion || '').trimEnd();
        if (!completion || completion.length < 2) return;
        // Don't show if cursor has moved
        if (this._cmView.state.selection.main.head !== cursor) return;

        this._cmGhostText = completion;
        this._cmRenderGhost();
      } catch (e) {
        if (e.name === 'AbortError') return;
      }
    }

    _cmRenderGhost() {
      const ghost = document.getElementById('cm6-ghost');
      if (!ghost || !this._cmView || !this._cmGhostText) return;
      const cursor = this._cmView.state.selection.main.head;
      const coords = this._cmView.coordsAtPos(cursor);
      if (!coords) return;
      // Position relative to editor container
      const cmEditor = this._cmView.dom;
      const cmRect = cmEditor.getBoundingClientRect();
      const wrapRect = ghost.parentElement.getBoundingClientRect();
      ghost.innerHTML = '';
      ghost.style.display = 'block';
      ghost.style.position = 'absolute';
      ghost.style.left = (coords.left - wrapRect.left) + 'px';
      ghost.style.top = (coords.top - wrapRect.top) + 'px';
      ghost.style.pointerEvents = 'none';
      ghost.style.zIndex = '10';
      // Render the ghost text with matching font
      const span = document.createElement('span');
      span.className = 'cm6-ghost-text';
      span.textContent = this._cmGhostText;
      ghost.appendChild(span);
    }

    _loadTextareaEditor(tab, area) {
      // Fallback: original textarea-based editor
      let editorWrap = area.querySelector('.code-editor-wrap');
      if (!editorWrap) {
        area.innerHTML = '';
        editorWrap = document.createElement('div');
        editorWrap.className = 'code-editor-wrap';
        editorWrap.innerHTML = `
          <div class="code-editor-gutter" id="code-gutter"></div>
          <div class="code-editor-content">
            <textarea class="code-editor-textarea" id="code-textarea" spellcheck="false" autocomplete="off" autocorrect="off" autocapitalize="off"></textarea>
            <pre class="code-editor-search-hl" id="code-search-hl" aria-hidden="true"></pre>
            <pre class="code-editor-highlight" id="code-highlight" aria-hidden="true"><code></code></pre>
            <pre class="code-editor-ghost" id="code-ghost" aria-hidden="true"></pre>
          </div>`;
        area.appendChild(editorWrap);

        const textarea = editorWrap.querySelector('#code-textarea');
        const pre = editorWrap.querySelector('#code-highlight');
        const gutter = editorWrap.querySelector('#code-gutter');

        // Sync scroll
        textarea.addEventListener('scroll', () => {
          pre.scrollTop = textarea.scrollTop;
          pre.scrollLeft = textarea.scrollLeft;
          gutter.scrollTop = textarea.scrollTop;
          const ghost = document.querySelector('#code-ghost');
          if (ghost) { ghost.scrollTop = textarea.scrollTop; ghost.scrollLeft = textarea.scrollLeft; }
          const diffBg = document.querySelector('#code-diff-bg');
          if (diffBg) { diffBg.scrollTop = textarea.scrollTop; diffBg.scrollLeft = textarea.scrollLeft; }
        });

        // Input handler
        textarea.addEventListener('input', () => {
          const t = this.openTabs.find(t2 => t2.path === this.activeTab);
          if (t) { t.content = textarea.value; t.modified = t.content !== t.original; this.renderTabs(); }
          clearTimeout(this._hlTimer);
          this._hlTimer = setTimeout(() => {
            this._updateHighlight(textarea.value);
            this._updateSearchHighlight();
          }, 50);
          this._clearGhost();
          const currentTabPath = this.activeTab;
          clearTimeout(this._autoSaveTimer);
          this._autoSaveTimer = setTimeout(() => {
            const tab = this.openTabs.find(t2 => t2.path === currentTabPath);
            if (tab && tab.modified) { this.saveFile(tab.path); this._showAutoSaveIndicator(); }
          }, 2000);
          clearTimeout(this._acTimer);
          if (this._acEnabled) {
            this._acTimer = setTimeout(() => this._triggerAutocomplete(textarea), 500);
          }
        });

        // Key handlers
        textarea.addEventListener('keydown', e => {
          if (e.key === 'Tab' && !e.shiftKey) {
            if (this._ghostText) { e.preventDefault(); this._insertText(textarea, this._ghostText); this._clearGhost(); return; }
            e.preventDefault(); this._insertText(textarea, '  ');
          }
          if (e.ctrlKey && e.key === 'ArrowRight' && this._ghostText) {
            e.preventDefault();
            const wordMatch = this._ghostText.match(/^(\S+\s?)/);
            if (wordMatch) {
              const word = wordMatch[1];
              this._insertText(textarea, word);
              const t = this.openTabs.find(t2 => t2.path === this.activeTab);
              if (t) { t.content = textarea.value; t.modified = t.content !== t.original; this.renderTabs(); }
              this._updateHighlight(textarea.value);
              this._ghostText = this._ghostText.substring(word.length);
              this._ghostLines = this._ghostText.split('\n');
              if (!this._ghostText.trim()) { this._clearGhost(); }
              else { this._acCursorPos = textarea.selectionStart; this._renderGhost(textarea, this._acCursorPos); }
            }
            return;
          }
          if (e.ctrlKey && (e.key === 'z' || e.key === 'Z')) { if (this._ghostText) this._clearGhost(); return; }
          if (e.ctrlKey && e.key === 's') { e.preventDefault(); this.saveFile(this.activeTab); }
          if (e.key === 'Escape' && this._ghostText) { this._clearGhost(); }
          if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageUp', 'PageDown'].includes(e.key) && this._ghostText && !e.ctrlKey) {
            this._clearGhost();
          }
          if (e.key === 'Enter') {
            if (this._ghostText) this._clearGhost();
            e.preventDefault();
            const s = textarea.selectionStart;
            const lineStart = textarea.value.lastIndexOf('\n', s - 1) + 1;
            const currentLine = textarea.value.substring(lineStart, s);
            const indent = currentLine.match(/^(\s*)/)[0];
            let extra = '';
            if (currentLine.trimEnd().endsWith(':') || currentLine.trimEnd().endsWith('{')) extra = '  ';
            this._insertText(textarea, '\n' + indent + extra);
          }
        });

        textarea.addEventListener('click', () => { if (this._ghostText) this._clearGhost(); });
      }

      const textarea = editorWrap.querySelector('#code-textarea');
      textarea.value = tab.content;
      this._currentLang = this._extToLang(tab.path);
      this._updateHighlight(tab.content);
    }

    // Insert text at cursor using execCommand to preserve undo/redo stack (Ctrl+Z)
    _insertText(textarea, text) {
      textarea.focus();
      // execCommand('insertText') is the only way to insert text
      // into a textarea while keeping the native undo history intact.
      document.execCommand('insertText', false, text);
    }
    _extToLang(path) {
      const ext = path.split('.').pop().toLowerCase();
      const map = {
        py: 'python', js: 'javascript', ts: 'typescript', jsx: 'javascript', tsx: 'typescript',
        html: 'html', css: 'css', json: 'json', md: 'markdown', sh: 'bash', yml: 'yaml', yaml: 'yaml',
        rs: 'rust', go: 'go', java: 'java', cpp: 'cpp', c: 'c', rb: 'ruby', php: 'php', sql: 'sql',
        toml: 'toml', xml: 'xml', txt: 'plaintext'
      };
      return map[ext] || 'plaintext';
    }

    _updateHighlight(code) {
      const pre = document.querySelector('#code-highlight');
      const gutter = document.querySelector('#code-gutter');
      if (!pre || !gutter) return;

      const codeEl = pre.querySelector('code');
      const lang = this._currentLang || 'plaintext';
      // Use hljs.highlight() (returns HTML) — NOT highlightElement (refuses re-processing)
      try {
        if (window.hljs && lang !== 'plaintext') {
          const result = hljs.highlight(code + '\n', { language: lang, ignoreIllegals: true });
          codeEl.innerHTML = result.value;
        } else {
          codeEl.textContent = code + '\n';
        }
      } catch (e) {
        // Fallback: no highlight
        codeEl.textContent = code + '\n';
      }
      codeEl.className = 'language-' + lang;

      // Line numbers and diff background
      const lines = code.split('\n').length;
      let gutterHtml = '';
      let diffBgHtml = '';
      for (let i = 1; i <= lines; i++) {
        const isHl = this._highlightLines && this._highlightLines.includes(i);
        gutterHtml += `<div class="line-num${isHl ? ' diff-hl' : ''}">${i}</div>`;
        diffBgHtml += `<div class="diff-bg-line${isHl ? ' diff-hl' : ''}"></div>`;
      }
      gutter.innerHTML = gutterHtml;

      let diffBg = document.querySelector('#code-diff-bg');
      if (!diffBg) {
        diffBg = document.createElement('div');
        diffBg.id = 'code-diff-bg';
        diffBg.className = 'code-editor-diff-bg';
        document.querySelector('.code-editor-content').prepend(diffBg);
      }
      diffBg.innerHTML = diffBgHtml;
    }

    highlightDiff(path, diffStr) {
      if (this.activeTab !== path || !diffStr) return;
      const lines = diffStr.split('\n');
      let currentLine = 0;
      const addedLines = [];
      for (const line of lines) {
        const headerMatch = line.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
        if (headerMatch) {
          currentLine = parseInt(headerMatch[1], 10);
          continue;
        }
        if (line.startsWith('+') && !line.startsWith('+++')) {
          addedLines.push(currentLine);
          currentLine++;
        } else if (line.startsWith('-') && !line.startsWith('---')) {
          // removed line, doesn't advance currentLine in the new file
        } else if (!line.startsWith('\\')) { // context line
          currentLine++;
        }
      }
      this._highlightLines = addedLines;
      const tab = this.openTabs.find(t => t.path === path);
      if (tab) {
        this._updateHighlight(tab.content);
        // Scroll to the first changed line
        if (addedLines.length > 0) {
          const textarea = document.querySelector('#code-textarea');
          if (textarea) {
            // Approximate 21px line height (varies slightly by font, but close enough)
            textarea.scrollTop = Math.max(0, (addedLines[0] - 2) * 21);
          }
        }
      }
      // Clear highlight after 5 seconds to show it was a momentary diff
      setTimeout(() => {
        this._highlightLines = [];
        if (this.activeTab === path && tab) {
          this._updateHighlight(tab.content);
        }
      }, 5000);
    }

    // ---- AI Autocomplete (Copilot/Antigravity style) ----
    _ghostText = '';
    _ghostLines = [];
    _acTimer = null;
    _acAbort = null;
    _autoSaveTimer = null;
    _hlTimer = null;
    _acCursorPos = -1; // cursor position when autocomplete was triggered
    _acEnabled = true; // can be toggled

    _clearGhost() {
      this._ghostText = '';
      this._ghostLines = [];
      this._acCursorPos = -1;
      const ghost = document.querySelector('#code-ghost');
      if (ghost) {
        ghost.textContent = '';
        ghost.style.display = 'none';
      }
    }

    _showAutoSaveIndicator() {
      // Brief indicator on the tab bar
      const tabBar = document.querySelector('#editor-tabs');
      if (!tabBar) return;
      let ind = tabBar.querySelector('.auto-save-indicator');
      if (!ind) {
        ind = el('span', { class: 'auto-save-indicator', text: ' Saved' });
        tabBar.appendChild(ind);
      }
      ind.classList.add('visible');
      setTimeout(() => ind.classList.remove('visible'), 1500);
    }

    // ---- Rename File or Folder ----
    async renameFile(oldPath) {
      const oldName = oldPath.split('/').pop();
      const newName = prompt('Rename file or folder:', oldName);
      if (!newName || !newName.trim() || newName.trim() === oldName) return;
      // Build new path: replace the last segment
      const parts = oldPath.split('/');
      parts[parts.length - 1] = newName.trim();
      const newPath = parts.join('/');
      try {
        const r = await fetch('/workspace/rename', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ old_path: oldPath, new_path: newPath })
        });
        const d = await r.json();
        if (d.status === 'ok') {
          // Update open tab if renamed file is open
          const tab = this.openTabs.find(t => t.path === oldPath);
          if (tab) {
            tab.path = newPath;
            if (this.activeTab === oldPath) this.activeTab = newPath;
          }
          await this.loadTree();
          this.renderTabs();
          toast(' Renamed: ' + oldName + ' → ' + newName.trim());
          this.addActivity('', 'File renamed', oldPath + ' → ' + newPath);
        } else {
          toast(ICONS.x(14) + ' Rename failed');
        }
      } catch (e) { toast(ICONS.x(14) + ' Rename error'); }
    }

    /**
     * Detect the user's completion intent based on cursor context.
     * Returns: 'comment_generate' | 'correction' | 'continuation'
     */
    _detectCompletionIntent(prefix, suffix) {
      const lines = prefix.split('\n');
      const currentLine = lines[lines.length - 1];
      const prevLine = lines.length > 1 ? lines[lines.length - 2] : '';
      const trimCurrent = currentLine.trim();
      const trimPrev = prevLine.trim();

      // Comment patterns for various languages
      const commentPatterns = [
        /^#\s+\S/,           // Python: # do something
        /^\/\/\s+\S/,        // JS/C/Go: // do something
        /^\/\*.*\*\/$/,      // Single-line block comment: /* ... */
        /^\*\s+\S/,          // Inside block comment: * do something
        /^"""/,              // Python docstring open
        /^'''/,              // Python docstring open
        /^--\s+\S/,          // SQL/Lua: -- comment
      ];
      const isComment = (line) => commentPatterns.some(p => p.test(line.trim()));

      // 1. Comment-generate: cursor is on empty line after a comment,
      //    or cursor is at end of a comment line (comment is "complete")
      if (!trimCurrent && isComment(trimPrev)) return 'comment_generate';
      if (isComment(trimCurrent) && trimCurrent.length > 8) {
        // Check if we're at the end of the comment (not mid-typing)
        // — only trigger if the comment looks complete (ends with punctuation or word)
        if (/[.!?):\w]$/.test(trimCurrent)) return 'comment_generate';
      }
      // Multi-line docstring: """ or ''' just closed
      if (trimCurrent === '"""' || trimCurrent === "'''") return 'comment_generate';

      // 2. Correction: cursor is in the middle of a non-empty line
      //    (there is significant code after cursor on the same line)
      const afterCursorOnLine = suffix.split('\n')[0];
      if (afterCursorOnLine.trim().length > 2 && trimCurrent.length > 0) {
        return 'correction';
      }

      // 3. Default: continuation
      return 'continuation';
    }

    async _triggerAutocomplete(textarea) {
      if (!textarea.value.trim() || !this._acEnabled) return;
      const cursor = textarea.selectionStart;
      const fullText = textarea.value;

      // Don't trigger if there's a selection
      if (textarea.selectionStart !== textarea.selectionEnd) return;

      // Get prefix (up to 1500 chars before cursor) and suffix (up to 500 chars after)
      const prefix = fullText.substring(Math.max(0, cursor - 1500), cursor);
      const suffix = fullText.substring(cursor, Math.min(fullText.length, cursor + 500));

      // Minimal safety: skip truly empty contexts
      const lastLine = prefix.split('\n').pop();
      if (!lastLine.trim() && prefix.trim().length < 20) return;

      // Detect intent
      const intent = this._detectCompletionIntent(prefix, suffix);

      // Adaptive max_tokens: generate more code for comment→code generation
      const maxTokens = intent === 'comment_generate' ? 250 : 120;

      // Abort previous request
      if (this._acAbort) {
        this._acAbort.abort();
        this._acAbort = null;
      }
      const controller = new AbortController();
      this._acAbort = controller;
      this._acCursorPos = cursor;

      try {
        const r = await fetch('/api/autocomplete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prefix,
            suffix,
            intent,
            language: this._currentLang || 'plaintext',
            file_path: this.activeTab || '',
            provider: $('#provider-select').value,
            model: $('#model-select').value,
            max_tokens: maxTokens
          }),
          signal: controller.signal
        });
        if (!r.ok) return;
        const d = await r.json();
        let completion = (d.completion || '').trimEnd();
        if (!completion || completion.length < 2) return;

        // Don't show if cursor has moved since request
        if (textarea.selectionStart !== cursor) return;

        // Store and render ghost text
        this._ghostText = completion;
        this._ghostLines = completion.split('\n');
        this._renderGhost(textarea, cursor);
      } catch (e) {
        if (e.name === 'AbortError') return;
        /* silent fail */
      }
    }

    _renderGhost(textarea, cursor) {
      const ghost = document.querySelector('#code-ghost');
      if (!ghost || !this._ghostText) return;

      const fullText = textarea.value;
      const before = fullText.substring(0, cursor);
      const after = fullText.substring(cursor);

      // Full-text overlay technique: render entire document with
      // original text invisible, only ghost completion visible.
      // This guarantees pixel-perfect alignment because the <pre>
      // uses the exact same font/padding/layout as the textarea.
      ghost.textContent = ''; // clear

      // Invisible text before cursor
      const spanBefore = document.createElement('span');
      spanBefore.className = 'ghost-hidden';
      spanBefore.textContent = before;

      // Visible ghost completion
      const spanGhost = document.createElement('span');
      spanGhost.className = 'ghost-visible';
      spanGhost.textContent = this._ghostText;

      // Invisible text after cursor
      const spanAfter = document.createElement('span');
      spanAfter.className = 'ghost-hidden';
      spanAfter.textContent = after;

      ghost.appendChild(spanBefore);
      ghost.appendChild(spanGhost);
      ghost.appendChild(spanAfter);

      // Sync scroll position with textarea
      ghost.scrollTop = textarea.scrollTop;
      ghost.scrollLeft = textarea.scrollLeft;
      ghost.style.display = 'block';
    }


    showWelcome() {
      const area = $('#editor-code-area');
      area.innerHTML = '<div class="editor-welcome" id="editor-welcome"><div class="editor-welcome-icon"></div><h3>Clawzd Editor</h3><p>Open a file from the explorer or create a new one to start editing.</p></div>';
    }

    // ---- Activity Feed ----
    addActivity(iconStr, title, detail) {
      const list = $('#editor-activity-list');
      const empty = list.querySelector('.editor-activity-empty');
      if (empty) empty.remove();
      const now = new Date();
      const time = now.getHours().toString().padStart(2, '0') + ':' + now.getMinutes().toString().padStart(2, '0') + ':' + now.getSeconds().toString().padStart(2, '0');
      const item = el('div', { class: 'editor-activity-item' }, [
        el('span', { class: 'editor-activity-icon', html: iconStr }),
        el('div', { class: 'editor-activity-body' }, [
          el('div', { class: 'editor-activity-title', text: title }),
          detail ? el('div', { class: 'editor-activity-detail', text: detail }) : null
        ]),
        el('span', { class: 'editor-activity-time', text: time })
      ]);
      list.appendChild(item);
      list.scrollTop = list.scrollHeight;
    }

    // ---- Terminal ----
    async runCommand(cmd) {
      if (!cmd.trim()) return;
      const body = $('#editor-terminal-body');
      body.innerHTML += '<div class="term-line system">$ ' + escHtml(cmd) + '</div>';
      body.scrollTop = body.scrollHeight;
      this.addActivity('', 'Running command', cmd);
      try {
        const r = await fetch('/local/run', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: cmd, project: this.activeProject || '.' })
        });
        const d = await r.json();
        if (d.stdout) body.innerHTML += '<div class="term-line stdout">' + escHtml(d.stdout) + '</div>';
        if (d.stderr) body.innerHTML += '<div class="term-line stderr">' + escHtml(d.stderr) + '</div>';
        if (d.returncode === 0) {
          body.innerHTML += '<div class="term-line success"> Exit code: 0</div>';
          this.addActivity('', 'Command completed', cmd);
        } else {
          body.innerHTML += '<div class="term-line stderr"> Exit code: ' + (d.returncode || '?') + '</div>';
          this.addActivity('', 'Command failed', 'Exit ' + (d.returncode || '?'));
        }
      } catch (e) {
        body.innerHTML += '<div class="term-line stderr">${ICONS.x(14)} Error: ' + escHtml(e.message) + '</div>';
      }
      body.scrollTop = body.scrollHeight;
    }

    // ---- Editor Chat (AI) ----
    async sendEditorChat() {
      const input = $('#editor-chat-input');
      const msg = input.value.trim();
      if (!msg || this.editorStreaming) return;

      // Hide any open popups
      this.hideFileRefPopup();

      if (!this.editorSessionId) {
        try {
          const r = await fetch('/chat/new', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider: $('#provider-select').value, model: $('#model-select').value, preprompt: this._getAgentPreprompt() }) });
          const d = await r.json();
          this.editorSessionId = d.id;
          this.connectEditorSSE();
        } catch (e) { toast(ICONS.x(14) + ' Session error'); return; }
      } else if (!this.editorES || this.editorES.readyState === 2) {
        this.connectEditorSSE();
      }

      // Inject active file context if available
      let enrichedMsg = msg;

      // Inject project context
      if (this.projectPath) {
        enrichedMsg = `[Context: Working in project directory "${this.projectPath}"]\\n\\n${enrichedMsg}`;
      }

      // Inject attached files context
      if (this.attachedFiles.length) {
        const filesCtx = this.attachedFiles.map(f => {
          const maxLen = 2000;
          const content = f.content.length > maxLen ? f.content.substring(0, maxLen) + '\n... (truncated)' : f.content;
          return `[Attached: ${f.path}]\n\`\`\`${this._extToLang(f.path)}\n${content}\n\`\`\``;
        }).join('\n\n');
        enrichedMsg = `${filesCtx}\n\n${enrichedMsg}`;
      }

      const activeTab = this.openTabs.find(t => t.path === this.activeTab);
      if (activeTab && activeTab.content) {
        const maxCtx = 3000; // Limit context size
        const fileContent = activeTab.content.length > maxCtx
          ? activeTab.content.substring(0, maxCtx) + '\n... (truncated)'
          : activeTab.content;
        enrichedMsg = `[Currently editing: ${activeTab.path}]\n\`\`\`${this._extToLang(activeTab.path)}\n${fileContent}\n\`\`\`\n\n${enrichedMsg}`;
      }

      // Inject Active Implementation Plan if available
      if (this.activePlan) {
        enrichedMsg = `[Active Implementation Plan:\n${this.activePlan}]\n\n${enrichedMsg}`;
      }

      // Track tokens
      this.editorTokenCount += this._estimateTokens(enrichedMsg);
      this._updateContextBar();

      this.addEditorMsg('user', msg);
      this.addActivity(icon('chat'), 'You', msg.substring(0, 80) + (msg.length > 80 ? '...' : ''));
      input.value = '';
      // Clear attached files after sending
      this.attachedFiles = [];
      this._renderFileBadges();

      try {
        await fetch('/send/' + this.editorSessionId, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: enrichedMsg, provider: $('#provider-select').value, model: $('#model-select').value, preprompt: this._getAgentPreprompt(), active_project: this.projectPath, active_file: this.activeTab })
        });
      } catch (e) { toast(ICONS.x(14) + ' Send error'); }
    }

    connectEditorSSE() {
      if (this.editorES) this.editorES.close();
      this.editorES = new EventSource('/stream/' + this.editorSessionId);
      this.editorES.onmessage = e => this.handleEditorToken(e.data);
    }

    handleEditorToken(tok) {
      if (!this.editorStreaming) {
        this.editorStreaming = true;
        this.editorText = '';
        this.editorBubble = this.addEditorMsg('assistant', '');
        this.addActivity('', 'AI responding...', '');
      }
      if (tok === '[DONE]') {
        if (this._editorRenderTimer) { clearTimeout(this._editorRenderTimer); this._editorRenderTimer = null; }
        this._editorRenderPending = false;
        this.editorStreaming = false;
        if (this.editorBubble) {
          const content = this.editorBubble.querySelector('.msg-content');
          if (content) content.innerHTML = renderMd(this._formatThoughtsBeforeMd(this.editorText));
          this.editorBubble.dataset.raw = encodeURIComponent(this.editorText);
          highlightAll();
        }
        // Track received tokens
        this.editorTokenCount += this._estimateTokens(this.editorText);
        this._updateContextBar();
        // Extract todos from AI response
        this._extractTodos(this.editorText);
        // Auto-extract files from code blocks and save to workspace
        this._autoSaveFiles(this.editorText);
        this.editorBubble = null;
        this.editorText = '';
        this.addActivity(icon('check'), 'AI response complete', '');
        // Refresh file tree in case AI created files
        this.loadTree();
        return;
      }
      this.editorText += tok;
      if (!this._editorRenderPending) {
        this._editorRenderPending = true;
        this._editorRenderTimer = setTimeout(() => {
          this._editorRenderPending = false;
          this._editorRenderTimer = null;

          if (this.editorBubble) {
            const content = this.editorBubble.querySelector('.msg-content');
            if (content) {
              // Capture open details
              const openDetails = [];
              content.querySelectorAll('details').forEach((d, i) => {
                if (d.hasAttribute('open')) openDetails.push(i);
              });

              let preview = this._formatThoughtsBeforeMd(this.editorText);
              const fc = (preview.match(/```/g) || []).length;
              if (fc % 2 !== 0) preview += '\n```';
              content.innerHTML = renderMd(preview) + '<span class="streaming-cursor"></span>';

              // Restore open details
              if (openDetails.length > 0) {
                content.querySelectorAll('details').forEach((d, i) => {
                  if (openDetails.includes(i)) d.setAttribute('open', '');
                });
              }
            }
          }
          const msgs = $('#editor-chat-messages');
          msgs.scrollTop = msgs.scrollHeight;
          if (typeof highlightAll === 'function') highlightAll();
        }, 80);
      }
    }

    addEditorMsg(role, content) {
      const msgs = $('#editor-chat-messages');
      const modeLabel = this.agentMode === 'plan' ? ' Plan' : ' Build';
      const authorText = role === 'user' ? 'You' : `Clawzd · ${modeLabel}`;
      const div = el('div', { class: 'editor-chat-msg ' + role }, [
        el('div', { class: 'msg-author', text: authorText }),
        el('div', { class: 'msg-content', html: content ? renderMd(content) : '' })
      ]);
      msgs.appendChild(div);
      msgs.scrollTop = msgs.scrollHeight;
      return div;
    }

    _formatThoughtsBeforeMd(text) {
      if (!text) return text;
      let result = text.replace(/<thought>([\s\S]*?)<\/thought>/gi, (match, content) => {
        return `\n<details class="ai-thought"><summary>💭 Agent Reflections</summary>\n\n${content}\n\n</details>\n`;
      });
      if (result.includes('<thought>')) {
        result = result.replace(/<thought>([\s\S]*)$/i, (match, content) => {
          return `\n<details class="ai-thought" open><summary>💭 Agent Reflections (Thinking...)</summary>\n\n${content}\n\n</details>\n`;
        });
      }
      return result;
    }

    // ---- Agent Mode Toggle (Build / Plan) ----
    setAgentMode(mode) {
      if (mode === 'build' && this.agentMode === 'plan') {
        // Extract the last AI response as the active plan
        const msgs = document.querySelectorAll('#editor-chat-messages .editor-chat-msg.assistant');
        if (msgs.length > 0) {
          const lastMsg = msgs[msgs.length - 1];
          if (lastMsg.dataset.raw) {
            this.activePlan = decodeURIComponent(lastMsg.dataset.raw);
            toast(ICONS.check(14) + ' Plan captured! Context size optimized.');
          }
        }
      }

      this.agentMode = mode;
      $$('.agent-mode-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.agent === mode);
      });

      const indicator = $('#agent-mode-indicator');
      if (indicator) {
        indicator.innerHTML = this.activePlan ? '📋 Plan Active' : '';
      }

      // Force new session on mode change so preprompt switches
      this.editorSessionId = null;
      if (this.editorES) { this.editorES.close(); this.editorES = null; }
      const label = mode === 'plan' ? ' Switched to Plan mode — read-only analysis' : ' Switched to Build mode — full edit access';
      this.addEditorMsg('assistant', label);
      this.addActivity(mode === 'plan' ? '' : '', 'Mode changed', mode.charAt(0).toUpperCase() + mode.slice(1));
    }

    _getAgentPreprompt() {
      return this.agentMode === 'plan' ? 'ide_planner' : 'ide_developer';
    }


    _cmdClear() {
      this.editorSessionId = null;
      this.activePlan = null;
      if (this.editorES) { this.editorES.close(); this.editorES = null; }
      $('#editor-chat-messages').innerHTML = '';
      const indicator = $('#agent-mode-indicator');
      if (indicator) indicator.innerHTML = '';
      this.editorTokenCount = 0;
      this._updateContextBar();
      this.attachedFiles = [];
      this._renderFileBadges();
      toast(ICONS.circle(14) + ' ️ Chat cleared');
    }

    _cmdUndo() {
      if (!this.changeHistory.length) {
        this.addEditorMsg('assistant', ' No AI changes to undo.');
        return;
      }
      if (this.changeHistoryIdx < 0) this.changeHistoryIdx = this.changeHistory.length - 1;
      else if (this.changeHistoryIdx === 0) {
        this.addEditorMsg('assistant', ' Already at the oldest change.');
        return;
      } else {
        this.changeHistoryIdx--;
      }
      const change = this.changeHistory[this.changeHistoryIdx];
      this._applyFileContent(change.path, change.oldContent);
      this.addEditorMsg('assistant', `↩️ **Undone:** \`${change.path}\` reverted to previous version.`);
      this.addActivity('↩️', 'Undo', change.path);
    }

    _cmdRedo() {
      if (this.changeHistoryIdx < 0 || this.changeHistoryIdx >= this.changeHistory.length - 1) {
        this.addEditorMsg('assistant', ' Nothing to redo.');
        return;
      }
      this.changeHistoryIdx++;
      const change = this.changeHistory[this.changeHistoryIdx];
      this._applyFileContent(change.path, change.newContent);
      this.addEditorMsg('assistant', `↪️ **Redone:** \`${change.path}\` restored to AI version.`);
      this.addActivity('↪️', 'Redo', change.path);
    }

    async _applyFileContent(path, content) {
      try {
        await fetch('/workspace/file', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path, content })
        });
        const tab = this.openTabs.find(t => t.path === path);
        if (tab) {
          tab.content = content;
          tab.original = content;
          tab.modified = false;
          if (this.activeTab === path) this.loadIntoEditor(tab);
          this.renderTabs();
        }
        this.loadTree();
      } catch (e) { toast(ICONS.x(14) + ' Apply error'); }
    }

    async _cmdInit() {
      this.addEditorMsg('assistant', ' Analyzing project structure to generate context...');
      // Send a special message to AI to generate the context
      const msg = '/init — Please analyze the entire workspace file tree, identify the project type, main frameworks, dependencies, and architecture. Generate a comprehensive clawzd.md context file that describes this project for future AI interactions. Include: project overview, tech stack, directory structure, key files, and coding conventions.';
      if (!this.editorSessionId) {
        try {
          const r = await fetch('/chat/new', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider: $('#provider-select').value, model: $('#model-select').value, preprompt: this._getAgentPreprompt() }) });
          const d = await r.json();
          this.editorSessionId = d.id;
          this.connectEditorSSE();
        } catch (e) { toast(ICONS.x(14) + ' Session error'); return; }
      }
      try {
        await fetch('/send/' + this.editorSessionId, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: msg, provider: $('#provider-select').value, model: $('#model-select').value, preprompt: 'ide_developer', active_project: this.projectPath })
        });
      } catch (e) { toast(ICONS.x(14) + ' Send error'); }
    }

    _cmdTodo() {
      // Switch to Todo tab
      $$('.editor-right-tab').forEach(t => t.classList.remove('active'));
      const todoTab = $('#ert-todo');
      if (todoTab) todoTab.classList.add('active');
      $('#editor-activity')?.classList.remove('active');
      $('#editor-chat')?.classList.remove('active');
      $('#editor-git')?.classList.remove('active');
      $('#editor-todo')?.classList.add('active');
    }

    _cmdDiff() {
      if (!this.changeHistory.length) {
        this.addEditorMsg('assistant', ' No AI changes recorded in this session.');
        return;
      }
      const lines = this.changeHistory.map((c, i) => {
        const time = new Date(c.timestamp).toLocaleTimeString();
        return `${i + 1}. \`${c.path}\` — ${time}`;
      }).join('\n');
      this.addEditorMsg('assistant', `** AI Changes This Session (${this.changeHistory.length}):**\n\n${lines}\n\nUse \`/undo\` to revert changes.`);
    }

    async _cmdCompact() {
      this.addEditorMsg('assistant', '️ Compacting session context... Starting a fresh session while preserving key context.');
      // Simply reset session — the backend will handle new context
      this.editorSessionId = null;
      if (this.editorES) { this.editorES.close(); this.editorES = null; }
      this.editorTokenCount = 0;
      this._updateContextBar();
      toast(ICONS.circle(14) + ' ️ Session compacted');
    }

    // ---- @ File References ----
    _fileRefIcon(path) {
      // Reuse the same SVG icons as the file explorer
      return this._fileIcon(path.split('/').pop());
    }

    showFileRefPopup(query) {
      const popup = $('#file-ref-popup');
      if (!this.files.length) { this.hideFileRefPopup(); return; }
      const q = query.toLowerCase().trim();
      let matches;
      if (!q) {
        // Empty query: show first 15 files
        matches = this.files.slice(0, 15);
      } else {
        // Fuzzy match: check full path AND basename
        matches = this.files
          .filter(f => {
            const lower = f.path.toLowerCase();
            const basename = lower.split('/').pop();
            return lower.includes(q) || basename.includes(q);
          })
          .sort((a, b) => {
            // Prioritize basename matches
            const aBase = a.path.toLowerCase().split('/').pop().startsWith(q);
            const bBase = b.path.toLowerCase().split('/').pop().startsWith(q);
            if (aBase && !bBase) return -1;
            if (!aBase && bBase) return 1;
            return a.path.length - b.path.length;
          })
          .slice(0, 15);
      }
      if (!matches.length) { this.hideFileRefPopup(); return; }
      this.fileRefIndex = 0;
      popup.innerHTML = matches.map((f, i) => {
        const sizeStr = f.size > 1024 ? (f.size / 1024).toFixed(0) + 'K' : f.size + 'B';
        const icon = this._fileRefIcon(f.path);
        // Highlight matching part
        const pathHtml = q ? this._highlightMatch(f.path, q) : escHtml(f.path);
        return `
          <div class="file-ref-item${i === 0 ? ' active' : ''}" data-path="${escHtml(f.path)}" data-idx="${i}">
            <span class="file-ref-icon">${icon}</span>
            <span class="file-ref-path">${pathHtml}</span>
            <span class="file-ref-size">${sizeStr}</span>
          </div>`;
      }).join('');
      popup.classList.add('open');
      popup.querySelectorAll('.file-ref-item').forEach((el, i) => {
        el.addEventListener('click', () => {
          this._attachFile(matches[i].path);
          this.hideFileRefPopup();
          this._clearAtQuery();
        });
      });
    }

    _highlightMatch(text, query) {
      if (!query) return escHtml(text);
      const idx = text.toLowerCase().indexOf(query);
      if (idx < 0) return escHtml(text);
      return escHtml(text.substring(0, idx)) +
        '<mark>' + escHtml(text.substring(idx, idx + query.length)) + '</mark>' +
        escHtml(text.substring(idx + query.length));
    }

    hideFileRefPopup() {
      const popup = $('#file-ref-popup');
      popup.classList.remove('open');
      popup.innerHTML = '';
      this.fileRefIndex = -1;
    }

    navigateFileRefPopup(dir) {
      const items = $$('#file-ref-popup .file-ref-item');
      if (!items.length) return;
      items[this.fileRefIndex]?.classList.remove('active');
      this.fileRefIndex = (this.fileRefIndex + dir + items.length) % items.length;
      items[this.fileRefIndex]?.classList.add('active');
      items[this.fileRefIndex]?.scrollIntoView({ block: 'nearest' });
    }

    selectFileRef() {
      const items = $$('#file-ref-popup .file-ref-item');
      if (this.fileRefIndex >= 0 && items[this.fileRefIndex]) {
        items[this.fileRefIndex].click();
        return true;
      }
      return false;
    }

    async _attachFile(path) {
      if (this.attachedFiles.some(f => f.path === path)) return; // already attached
      try {
        const r = await fetch('/workspace/file?path=' + encodeURIComponent(path));
        if (!r.ok) { toast(ICONS.x(14) + ' Cannot read file'); return; }
        const d = await r.json();
        this.attachedFiles.push({ path, content: d.content });
        this._renderFileBadges();
        toast(' Attached: ' + path.split('/').pop());
      } catch (e) { toast(ICONS.x(14) + ' File read error'); }
    }

    _detachFile(path) {
      this.attachedFiles = this.attachedFiles.filter(f => f.path !== path);
      this._renderFileBadges();
    }

    _renderFileBadges() {
      const container = $('#editor-file-badges');
      if (!container) return;
      container.innerHTML = '';
      if (!this.attachedFiles.length) {
        container.classList.remove('has-badges');
        return;
      }
      container.classList.add('has-badges');
      this.attachedFiles.forEach(f => {
        const name = f.path.split('/').pop();
        const badge = el('span', { class: 'file-badge' }, [
          el('span', { text: ' ' + name }),
          el('button', { class: 'file-badge-remove', text: '', onclick: () => this._detachFile(f.path) })
        ]);
        container.appendChild(badge);
      });
    }

    _clearAtQuery() {
      const input = $('#editor-chat-input');
      // Remove the @query from input
      const val = input.value;
      const atIdx = val.lastIndexOf('@');
      if (atIdx >= 0) {
        input.value = val.substring(0, atIdx);
      }
      input.focus();
    }

    _handleAtInput(value) {
      const atIdx = value.lastIndexOf('@');
      if (atIdx >= 0 && (atIdx === 0 || value[atIdx - 1] === ' ' || value[atIdx - 1] === '\n')) {
        const query = value.substring(atIdx + 1);
        // Only show if no space after query (still typing)
        if (!query.includes(' ') && !query.includes('\n')) {
          this.showFileRefPopup(query);
          return true;
        }
      }
      this.hideFileRefPopup();
      return false;
    }

    // ---- AI Change History ----
    _recordChange(path, oldContent, newContent) {
      // Trim history if we're in the middle of undo
      if (this.changeHistoryIdx >= 0 && this.changeHistoryIdx < this.changeHistory.length - 1) {
        this.changeHistory = this.changeHistory.slice(0, this.changeHistoryIdx + 1);
      }
      this.changeHistory.push({ path, oldContent, newContent, timestamp: Date.now() });
      this.changeHistoryIdx = this.changeHistory.length - 1;
      // Cap at 50 entries
      if (this.changeHistory.length > 50) {
        this.changeHistory.shift();
        this.changeHistoryIdx = Math.max(0, this.changeHistoryIdx - 1);
      }
    }

    // ---- Todo Panel ----
    _saveTodos() {
      localStorage.setItem('hoc-todo', JSON.stringify(this.todoItems));
      this._updateTodoBadge();
    }

    _updateTodoBadge() {
      const badge = $('#ert-todo .todo-badge');
      const count = this.todoItems.filter(t => !t.done).length;
      // Add or update badge in the Todo tab
      const tab = $('#ert-todo');
      if (!tab) return;
      let b = tab.querySelector('.todo-badge');
      if (!b) {
        b = document.createElement('span');
        b.className = 'todo-badge';
        tab.appendChild(b);
      }
      b.textContent = count > 0 ? count : '';
    }

    renderTodos() {
      const list = $('#todo-list');
      if (!list) return;
      if (!this.todoItems.length) {
        list.innerHTML = '<div class="todo-empty">No tasks yet.<br>Add tasks manually or let the AI create them.</div>';
        this._updateTodoBadge();
        return;
      }
      list.innerHTML = '';
      this.todoItems.forEach((item, i) => {
        const div = el('div', { class: 'todo-item' + (item.done ? ' done' : '') }, [
          el('button', {
            class: 'todo-checkbox', text: item.done ? ICONS.check(14) : '', onclick: () => {
              this.todoItems[i].done = !this.todoItems[i].done;
              this._saveTodos();
              this.renderTodos();
            }
          }),
          el('span', { class: 'todo-text', text: item.text }),
          el('button', {
            class: 'todo-delete', text: '', onclick: () => {
              this.todoItems.splice(i, 1);
              this._saveTodos();
              this.renderTodos();
            }
          })
        ]);
        list.appendChild(div);
      });
      this._updateTodoBadge();
    }

    addTodo(text) {
      if (!text || !text.trim()) return;
      this.todoItems.push({ text: text.trim(), done: false, created: Date.now() });
      this._saveTodos();
      this.renderTodos();
    }

    clearDoneTodos() {
      this.todoItems = this.todoItems.filter(t => !t.done);
      this._saveTodos();
      this.renderTodos();
    }

    _extractTodos(text) {
      // Extract __TODO__ markers from AI responses
      const re = /__TODO__(.+?)__TODO__/g;
      let match;
      while ((match = re.exec(text)) !== null) {
        const todoText = match[1].trim();
        if (todoText && !this.todoItems.some(t => t.text === todoText)) {
          this.addTodo(todoText);
        }
      }
      // Also extract markdown task lists: - [ ] task
      const taskRe = /^[-*]\s+\[\s*\]\s+(.+)$/gm;
      while ((match = taskRe.exec(text)) !== null) {
        const todoText = match[1].trim();
        if (todoText && !this.todoItems.some(t => t.text === todoText)) {
          this.addTodo(todoText);
        }
      }
    }

    // ---- Context Token Tracking ----
    _updateContextBar() {
      const bar = $('#editor-context-bar');
      const fill = $('#ctx-bar-fill');
      const value = $('#ctx-bar-value');
      if (!bar || !fill || !value) return;
      const pct = Math.min(100, Math.round((this.editorTokenCount / this.TOKEN_LIMIT) * 100));
      if (this.editorTokenCount > 500) {
        bar.classList.add('visible');
      } else {
        bar.classList.remove('visible');
        return;
      }
      fill.style.width = pct + '%';
      fill.classList.toggle('warning', pct > 75);
      value.textContent = pct + '%';
    }

    _estimateTokens(text) {
      // Rough estimate: ~4 chars per token
      return Math.ceil((text || '').length / 4);
    }

    // ---- Auto-save files from AI response ----
    async _autoSaveFiles(text) {
      if (!text) return;
      // Match code blocks with filename headers:
      // ```lang  filename.ext   or   ### filename.ext   then ```code```
      const fileBlocks = [];

      // Pattern 1: filename before or after ``` lang marker
      //   ```python filename.py  or  filename.py\n```python
      const regex = /(?:^|\n)(?:(?:#{1,4}\s+)?(?:`([^`\n]+\.[a-z0-9]+)`|(\S+\.[a-z0-9]+))\s*\n)?```\w*\s*(?:([^\n]+\.[a-z0-9]+)\s*)?\n([\s\S]*?)```/g;
      let m;
      while ((m = regex.exec(text)) !== null) {
        let filename = (m[1] || m[2] || m[3] || '').trim();
        if (filename.startsWith(':')) filename = filename.substring(1);
        const code = m[4];
        if (filename && code && filename.length < 100 && !filename.includes(' ')) {
          fileBlocks.push({ filename, code });
        }
      }

      // Pattern 2: standalone fenced block with explicit filename in first line comment
      // e.g.  ```python\n# filename.py\n...```
      if (!fileBlocks.length) {
        const regex2 = /```(\w+)\n(?:#|\/\/|--|;)\s*(\S+\.[a-z0-9]+)\n([\s\S]*?)```/g;
        while ((m = regex2.exec(text)) !== null) {
          const filename = m[2].trim();
          const code = m[3];
          if (filename && code && filename.length < 100 && !filename.includes(' ')) {
            fileBlocks.push({ filename, code });
          }
        }
      }

      if (!fileBlocks.length) return;

      // Save each file to workspace
      let firstFile = null;
      for (const fb of fileBlocks) {
        try {
          // Record old content for undo history
          let oldContent = '';
          try {
            const existingResp = await fetch('/workspace/file?path=' + encodeURIComponent(fb.filename));
            if (existingResp.ok) {
              const existingData = await existingResp.json();
              oldContent = existingData.content || '';
            }
          } catch (_) { /* new file, no old content */ }

          await fetch('/workspace/file', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: fb.filename, content: fb.code })
          });
          // Record in change history for undo/redo
          this._recordChange(fb.filename, oldContent, fb.code);
          this.addActivity(icon('save'), 'File created', fb.filename);
          if (!firstFile) firstFile = fb.filename;
        } catch (e) {
          this.addActivity(icon('x'), 'Save failed', fb.filename);
        }
      }

      // Refresh tree and open first file
      await this.loadTree();
      if (firstFile) {
        this.openFile(firstFile);
        toast(icon('save') + ' ' + fileBlocks.length + ' file' + (fileBlocks.length > 1 ? 's' : '') + ' saved to workspace');
      }
    }

    // ---- Diff Viewer ----
    showDiff(filename, oldContent, newContent) {
      const overlay = $('#editor-diff-overlay');
      $('#diff-title').textContent = '️ Changes — ' + filename;
      const body = $('#diff-body');
      body.innerHTML = '';
      const oldLines = oldContent.split('\n');
      const newLines = newContent.split('\n');
      const maxLen = Math.max(oldLines.length, newLines.length);
      // Simple line-by-line diff
      for (let i = 0; i < maxLen; i++) {
        const ol = i < oldLines.length ? oldLines[i] : undefined;
        const nl = i < newLines.length ? newLines[i] : undefined;
        if (ol === nl) {
          body.innerHTML += '<div class="diff-line context"><span class="diff-line-num">' + (i + 1) + '</span><span class="diff-line-content">' + escHtml(ol) + '</span></div>';
        } else {
          if (ol !== undefined) body.innerHTML += '<div class="diff-line removed"><span class="diff-line-num">' + (i + 1) + '</span><span class="diff-line-content">' + escHtml(ol) + '</span></div>';
          if (nl !== undefined) body.innerHTML += '<div class="diff-line added"><span class="diff-line-num">' + (i + 1) + '</span><span class="diff-line-content">' + escHtml(nl) + '</span></div>';
        }
      }
      // Store pending diff for Accept button
      this._pendingDiff = { filename, newContent };
      overlay.classList.add('open');
    }

    async acceptDiff() {
      if (!this._pendingDiff) return;
      const { filename, newContent } = this._pendingDiff;
      try {
        await fetch('/workspace/file', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: filename, content: newContent })
        });
        // Update open tab if the file is already open
        const tab = this.openTabs.find(t => t.path === filename);
        if (tab) {
          tab.content = newContent;
          tab.original = newContent;
          tab.modified = false;
          if (this.activeTab === filename) this.loadIntoEditor(tab);
          this.renderTabs();
        }
        toast(' Changes applied: ' + filename.split('/').pop());
        this.addActivity(ICONS.check(14), 'Diff accepted', filename);
      } catch (e) { toast(ICONS.x(14) + ' Apply error'); }
      this._pendingDiff = null;
      $('#editor-diff-overlay').classList.remove('open');
    }

    // ---- Find & Replace ----
    _updateSearchHighlight() {
      const hlLayer = document.querySelector('#code-search-hl');
      if (!hlLayer) return;
      const findInput = document.querySelector('#find-input');
      const textarea = document.querySelector('#code-textarea');
      if (!findInput || !textarea) return;

      const query = findInput.value;
      const text = textarea.value;

      if (!query || !$('#editor-find-bar') || !$('#editor-find-bar').classList.contains('open')) {
        hlLayer.innerHTML = '';
        return;
      }

      const escapeRegExp = (string) => string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(escapeRegExp(query), 'gi');

      let result = '';
      let lastIndex = 0;
      let match;
      while ((match = regex.exec(text)) !== null) {
        result += escHtml(text.substring(lastIndex, match.index));
        result += `<mark class="search-match">${escHtml(match[0])}</mark>`;
        lastIndex = regex.lastIndex;
      }
      result += escHtml(text.substring(lastIndex));

      hlLayer.innerHTML = result + '\n';
    }

    openFindReplace() {
      const bar = $('#editor-find-bar');
      if (!bar) return;
      bar.classList.add('open');
      const findInput = bar.querySelector('#find-input');
      if (findInput) {
        // Pre-populate with current selection if any
        const textarea = document.querySelector('#code-textarea');
        if (textarea) {
          const sel = textarea.value.substring(textarea.selectionStart, textarea.selectionEnd);
          if (sel && sel.length < 200) findInput.value = sel;
        }
        findInput.focus();
        findInput.select();
        this._updateSearchHighlight();
      }
    }

    closeFindReplace() {
      const bar = $('#editor-find-bar');
      if (bar) {
        bar.classList.remove('open');
        this._updateSearchHighlight();
      }
    }

    findNext() {
      const textarea = document.querySelector('#code-textarea');
      const findInput = document.querySelector('#find-input');
      if (!textarea || !findInput) return;
      const query = findInput.value;
      if (!query) return;
      const text = textarea.value;
      const startPos = textarea.selectionEnd || 0;
      let idx = text.indexOf(query, startPos);
      if (idx === -1) idx = text.indexOf(query, 0); // Wrap around
      if (idx === -1) { toast('Not found'); return; }
      textarea.selectionStart = idx;
      textarea.selectionEnd = idx + query.length;
      textarea.focus();
      // Scroll into view
      const lineNum = text.substring(0, idx).split('\n').length;
      const lineHeight = 20.8;
      textarea.scrollTop = Math.max(0, (lineNum - 5) * lineHeight);
    }

    replaceNext() {
      const textarea = document.querySelector('#code-textarea');
      const findInput = document.querySelector('#find-input');
      const replaceInput = document.querySelector('#replace-input');
      if (!textarea || !findInput || !replaceInput) return;
      const query = findInput.value;
      const replacement = replaceInput.value;
      if (!query) return;
      // If current selection matches, replace it
      const selText = textarea.value.substring(textarea.selectionStart, textarea.selectionEnd);
      if (selText === query) {
        const start = textarea.selectionStart;
        textarea.value = textarea.value.substring(0, start) + replacement + textarea.value.substring(start + query.length);
        textarea.selectionStart = start;
        textarea.selectionEnd = start + replacement.length;
        textarea.dispatchEvent(new Event('input'));
      }
      this.findNext();
    }

    replaceAll() {
      const textarea = document.querySelector('#code-textarea');
      const findInput = document.querySelector('#find-input');
      const replaceInput = document.querySelector('#replace-input');
      if (!textarea || !findInput || !replaceInput) return;
      const query = findInput.value;
      const replacement = replaceInput.value;
      if (!query) return;
      const count = textarea.value.split(query).length - 1;
      if (count === 0) { toast('Not found'); return; }
      textarea.value = textarea.value.split(query).join(replacement);
      textarea.dispatchEvent(new Event('input'));
      toast(`Replaced ${count} occurrence${count > 1 ? 's' : ''}`);
    }

    // ---- Context ----
    async loadContext() {
      try {
        const r = await fetch('/workspace/context');
        const d = await r.json();
        $('#context-textarea').value = d.content || '';
      } catch (e) { }
      $('#context-overlay').classList.add('open');
    }

    async saveContext() {
      const content = $('#context-textarea').value;
      try {
        await fetch('/workspace/context', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content }) });
        toast(ICONS.download(14) + ' Context saved');
        this.addActivity('', 'Project context updated', '');
      } catch (e) { toast(ICONS.x(14) + ' Save error'); }
      $('#context-overlay').classList.remove('open');
    }

    // ---- Git Clone ----
    openGitClone() {
      $('#git-clone-url').value = '';
      $('#git-clone-folder').value = '';
      $('#git-clone-branch').value = '';
      $('#git-clone-username').value = '';
      $('#git-clone-token').value = '';
      const authSection = $('#git-clone-auth-section');
      if (authSection) authSection.removeAttribute('open');
      $('#git-clone-progress').classList.remove('active');
      $('#git-clone-submit').disabled = false;
      $('#git-clone-overlay').classList.add('open');
    }

    async doGitClone() {
      const url = $('#git-clone-url').value.trim();
      if (!url) { toast(ICONS.x(14) + ' Enter a repository URL'); return; }
      const folder = $('#git-clone-folder').value.trim();
      const branch = $('#git-clone-branch').value.trim();
      const username = ($('#git-clone-username') || {}).value?.trim() || '';
      const token = ($('#git-clone-token') || {}).value?.trim() || '';

      $('#git-clone-submit').disabled = true;
      const progress = $('#git-clone-progress');
      progress.classList.add('active');
      $('#git-clone-progress-text').textContent = 'Cloning repository...';
      $('#git-clone-progress-fill').style.width = '30%';

      this.addActivity('', 'Cloning repository', url);

      try {
        const payload = { url, folder, branch };
        if (username) payload.username = username;
        if (token) payload.token = token;

        const r = await fetch('/workspace/git-clone', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const d = await r.json();
        if (d.status === 'ok') {
          $('#git-clone-progress-fill').style.width = '100%';
          $('#git-clone-progress-text').textContent = ' ' + d.message;
          toast(ICONS.check(14) + ' Repository cloned');
          this.addActivity('', 'Repository cloned', url);
          // Save credentials for push/pull during this session
          if (token) {
            this._gitCredentials = { username, token };
          }
          await this.loadTree();
          setTimeout(() => $('#git-clone-overlay').classList.remove('open'), 1200);
        } else {
          $('#git-clone-progress-text').textContent = ' ' + d.error;
          $('#git-clone-progress-fill').style.width = '0%';
          toast(ICONS.x(14) + ' Clone failed');
          this.addActivity('', 'Clone failed', d.error);
          $('#git-clone-submit').disabled = false;
        }
      } catch (e) {
        $('#git-clone-progress-text').textContent = ' ' + e.message;
        toast(ICONS.x(14) + ' Clone error');
        $('#git-clone-submit').disabled = false;
      }
    }

    // ---- Terminal Help ----
    _terminalCommands() {
      return [
        {
          section: 'Files & Navigation', cmds: [
            { key: 'ls', desc: 'List files in current directory' },
            { key: 'ls -la', desc: 'List all files with details' },
            { key: 'cat <file>', desc: 'Display file contents' },
            { key: 'head -20 <file>', desc: 'Show first 20 lines' },
            { key: 'tail -20 <file>', desc: 'Show last 20 lines' },
            { key: 'find . -name "*.py"', desc: 'Find Python files' },
            { key: 'wc -l <file>', desc: 'Count lines in file' },
            { key: 'tree', desc: 'Show directory tree' },
          ]
        },
        {
          section: 'Git', cmds: [
            { key: 'git status', desc: 'Show working tree status' },
            { key: 'git log --oneline -10', desc: 'Recent commit history' },
            { key: 'git diff', desc: 'Show unstaged changes' },
            { key: 'git branch -a', desc: 'List all branches' },
            { key: 'git add .', desc: 'Stage all changes' },
            { key: 'git commit -m "msg"', desc: 'Commit with message' },
            { key: 'git pull', desc: 'Pull latest changes' },
            { key: 'git push', desc: 'Push commits to remote' },
          ]
        },
        {
          section: 'Python', cmds: [
            { key: 'python <file>', desc: 'Run a Python script' },
            { key: 'python -m pytest', desc: 'Run tests with pytest' },
            { key: 'pip install <pkg>', desc: 'Install a package' },
            { key: 'pip list', desc: 'List installed packages' },
            { key: 'python -m venv venv', desc: 'Create virtual env' },
          ]
        },
        {
          section: 'System', cmds: [
            { key: 'grep -r "text" .', desc: 'Search text in files' },
            { key: 'du -sh *', desc: 'Disk usage by folder' },
            { key: 'df -h', desc: 'Disk space overview' },
            { key: 'uname -a', desc: 'System information' },
            { key: 'whoami', desc: 'Current user' },
            { key: 'pwd', desc: 'Current directory' },
          ]
        }
      ];
    }

    showTerminalHelp() {
      const popup = $('#term-help-popup');
      const cmds = this._terminalCommands();
      popup.innerHTML = '<div class="term-help-title">⌨️ Terminal Commands</div>';
      cmds.forEach(section => {
        popup.innerHTML += `<div class="term-help-section">
          <div class="term-help-section-title">${escHtml(section.section)}</div>
          ${section.cmds.map(c => `<div class="term-help-cmd" data-cmd="${escHtml(c.key)}">
            <span class="term-help-cmd-key">${escHtml(c.key)}</span>
            <span class="term-help-cmd-desc">${escHtml(c.desc)}</span>
          </div>`).join('')}
        </div>`;
      });
      popup.classList.toggle('open');
      // Bind clicks
      popup.querySelectorAll('.term-help-cmd').forEach(el2 => {
        el2.addEventListener('click', () => {
          $('#editor-terminal-input').value = el2.dataset.cmd;
          $('#editor-terminal-input').focus();
          popup.classList.remove('open');
        });
      });
    }

    // ---- Command History ----
    initCommandHistory() {
      this._cmdHistory = [];
      this._cmdIdx = -1;
    }

    pushHistory(cmd) {
      if (!this._cmdHistory) this.initCommandHistory();
      if (cmd.trim() && (this._cmdHistory.length === 0 || this._cmdHistory[this._cmdHistory.length - 1] !== cmd)) {
        this._cmdHistory.push(cmd);
      }
      this._cmdIdx = this._cmdHistory.length;
    }

    historyUp() {
      if (!this._cmdHistory || !this._cmdHistory.length) return '';
      if (this._cmdIdx > 0) this._cmdIdx--;
      return this._cmdHistory[this._cmdIdx] || '';
    }

    historyDown() {
      if (!this._cmdHistory || !this._cmdHistory.length) return '';
      if (this._cmdIdx < this._cmdHistory.length - 1) this._cmdIdx++;
      else { this._cmdIdx = this._cmdHistory.length; return ''; }
      return this._cmdHistory[this._cmdIdx] || '';
    }

    // ---- Search ----
    async searchFiles(query) {
      if (!query.trim()) return;
      this.addActivity('', 'Searching files', query);
      try {
        const r = await fetch('/workspace/search?q=' + encodeURIComponent(query));
        const d = await r.json();
        const results = d.results || [];
        const info = $('#editor-search-info');
        info.textContent = results.length + ' result' + (results.length !== 1 ? 's' : '') + (d.truncated ? ' (truncated)' : '');

        // Show results in activity feed
        if (!results.length) {
          this.addActivity('', 'No results', 'for "' + query + '"');
          return;
        }
        this.addActivity('', results.length + ' results found', 'for "' + query + '"');

        // Group by file
        const byFile = {};
        results.forEach(r2 => {
          if (!byFile[r2.path]) byFile[r2.path] = [];
          byFile[r2.path].push(r2);
        });
        Object.entries(byFile).forEach(([path, hits]) => {
          const detail = hits.slice(0, 3).map(h => `L${h.line}: ${h.text.substring(0, 80)}`).join('\n');
          this.addActivity('', path + ' (' + hits.length + ' hits)', detail);
        });

        // Open first result file
        if (results.length > 0) {
          this.openFile(results[0].path);
        }
      } catch (e) { toast(ICONS.x(14) + ' Search error'); }
    }

    // ---- Upload Files ----
    async uploadFiles(files) {
      for (const file of files) {
        const fd = new FormData();
        fd.append('file', file);
        try {
          const r = await fetch('/workspace/upload', { method: 'POST', body: fd });
          const d = await r.json();
          if (d.status === 'ok') {
            this.addActivity('', 'File uploaded', d.path + ' (' + (d.size / 1024).toFixed(1) + ' KB)');
            toast(' Uploaded: ' + file.name);
          }
        } catch (e) { toast(' Upload error: ' + file.name); }
      }
      await this.loadTree();
    }

    // ---- Git Panel ----
    async loadGitStatus() {
      try {
        const r = await fetch('/workspace/git-status');
        const d = await r.json();
        if (!d.has_repo) {
          $('#git-no-repo').style.display = '';
          $('#git-panel-content').style.display = 'none';
          return;
        }
        $('#git-no-repo').style.display = 'none';
        $('#git-panel-content').style.display = 'flex';

        $('#git-branch-name').textContent = d.branch;
        const ae = $('#git-ahead'), be = $('#git-behind');
        if (d.ahead > 0) { ae.textContent = '↑' + d.ahead; ae.style.display = ''; } else ae.style.display = 'none';
        if (d.behind > 0) { be.textContent = '↓' + d.behind; be.style.display = ''; } else be.style.display = 'none';
        const ru = $('#git-remote-url');
        if (d.remote_url) { ru.textContent = d.remote_url; ru.style.display = ''; } else ru.style.display = 'none';

        // Split staged/unstaged
        const staged = d.files.filter(f => f.staged);
        const unstaged = d.files.filter(f => !f.staged);
        this._renderGitFileList($('#git-staged-list'), staged, true);
        this._renderGitFileList($('#git-unstaged-list'), unstaged, false);
      } catch (e) { toast(ICONS.x(14) + ' Git status error'); }
    }

    _renderGitFileList(container, files, isStaged) {
      container.innerHTML = '';
      if (!files.length && isStaged) return;

      const title = isStaged ? 'Staged Changes' : 'Changes';
      const icon = isStaged ? ICONS.check(14) : '●';
      container.innerHTML += `<div class="git-section-title">${icon} ${title}<span class="git-section-count">${files.length}</span></div>`;

      files.forEach(f => {
        const name = f.path.split('/').pop();
        const dir = f.path.includes('/') ? f.path.substring(0, f.path.lastIndexOf('/')) : '';
        const statusChar = f.index || f.working || (f.status === 'added' ? '?' : 'M');
        const item = el('div', { class: 'git-file-item' }, [
          el('span', { class: 'git-file-status ' + statusChar, text: statusChar }),
          el('span', { class: 'git-file-name', text: name }),
          dir ? el('span', { class: 'git-file-dir', text: dir }) : null,
          el('div', { class: 'git-file-actions' }, [
            isStaged
              ? el('button', { class: 'git-file-action-btn', text: '−', title: 'Unstage', onclick: e => { e.stopPropagation(); this._gitReset(f.path); } })
              : el('button', { class: 'git-file-action-btn', text: '+', title: 'Stage', onclick: e => { e.stopPropagation(); this.gitAdd([f.path]); } }),
            el('button', { class: 'git-file-action-btn', text: '⇄', title: 'View diff', onclick: e => { e.stopPropagation(); this._viewGitDiff(f.path, isStaged); } })
          ])
        ]);
        item.addEventListener('click', () => this.openFile(f.path));
        container.appendChild(item);
      });
    }

    async gitAdd(paths) {
      try {
        await fetch('/workspace/git-add', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paths }) });
        this.addActivity('＋', 'Staged', paths.join(', '));
        this.loadGitStatus();
      } catch (e) { toast(ICONS.x(14) + ' Stage error'); }
    }

    async gitStageAll() {
      try {
        await fetch('/workspace/git-add', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ all: true }) });
        this.addActivity('＋', 'Staged all changes', '');
        toast(ICONS.check(14) + ' All changes staged');
        this.loadGitStatus();
      } catch (e) { toast(ICONS.x(14) + ' Stage error'); }
    }

    async _gitReset(path) {
      try {
        await fetch('/local/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command: 'git reset HEAD -- ' + path }) });
        this.loadGitStatus();
      } catch (e) { }
    }

    async _viewGitDiff(path, staged) {
      try {
        const r = await fetch('/workspace/git-diff?path=' + encodeURIComponent(path) + '&staged=' + (staged ? 'true' : 'false'));
        const d = await r.json();
        if (d.diff) {
          // Show in diff viewer
          const overlay = $('#editor-diff-overlay');
          $('#diff-title').textContent = '️ Diff — ' + path;
          const body = $('#diff-body');
          body.innerHTML = '';
          d.diff.split('\n').forEach(line => {
            let cls = 'context';
            if (line.startsWith('+') && !line.startsWith('+++')) cls = 'added';
            else if (line.startsWith('-') && !line.startsWith('---')) cls = 'removed';
            else if (line.startsWith('@@')) cls = 'context';
            body.innerHTML += '<div class="diff-line ' + cls + '"><span class="diff-line-content">' + escHtml(line) + '</span></div>';
          });
          overlay.classList.add('open');
        } else {
          toast('No changes to show');
        }
      } catch (e) { toast(ICONS.x(14) + ' Diff error'); }
    }

    async gitCommit(andPush) {
      const msg = $('#git-commit-msg').value.trim();
      if (!msg) { toast(ICONS.x(14) + ' Enter a commit message'); return; }
      try {
        const r = await fetch('/workspace/git-commit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: msg }) });
        const d = await r.json();
        if (d.status === 'ok') {
          toast(ICONS.check(14) + ' Committed');
          this.addActivity(ICONS.check(14), 'Committed', msg);
          $('#git-commit-msg').value = '';
          if (andPush) await this.gitPush();
          this.loadGitStatus();
          this.loadGitLog();
        } else {
          toast(' ' + d.error);
        }
      } catch (e) { toast(ICONS.x(14) + ' Commit error'); }
    }

    async gitPush() {
      this.addActivity('⬆', 'Pushing...', '');
      try {
        const payload = {};
        // Inject saved credentials if available
        if (this._gitCredentials) {
          if (this._gitCredentials.username) payload.username = this._gitCredentials.username;
          if (this._gitCredentials.token) payload.token = this._gitCredentials.token;
        }
        const r = await fetch('/workspace/git-push', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        const d = await r.json();
        if (d.status === 'ok') {
          toast(ICONS.check(14) + ' Pushed to remote');
          this.addActivity('', 'Push successful', d.output || '');
        } else {
          toast(' Push failed: ' + d.error);
          this.addActivity('', 'Push failed', d.error);
        }
        this.loadGitStatus();
      } catch (e) { toast(ICONS.x(14) + ' Push error'); }
    }

    async gitPull() {
      this.addActivity('⬇', 'Pulling...', '');
      try {
        const payload = {};
        // Inject saved credentials if available
        if (this._gitCredentials) {
          if (this._gitCredentials.username) payload.username = this._gitCredentials.username;
          if (this._gitCredentials.token) payload.token = this._gitCredentials.token;
        }
        const r = await fetch('/workspace/git-pull', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        const d = await r.json();
        if (d.status === 'ok') {
          toast(ICONS.check(14) + ' Pulled from remote');
          this.addActivity('', 'Pull successful', d.output || '');
          this.loadTree();
        } else {
          toast(' Pull failed: ' + d.error);
          this.addActivity('', 'Pull failed', d.error);
        }
        this.loadGitStatus();
      } catch (e) { toast(ICONS.x(14) + ' Pull error'); }
    }

    // ---- Git Graph (VS Code-style) ----
    async loadGitLog() {
      try {
        const r = await fetch('/workspace/git-log?limit=80');
        const d = await r.json();
        this.renderGraph(d.commits || [], d.branches || []);
      } catch (e) { console.error('Git log error', e); }
    }

    renderGraph(commits, branches) {
      const container = $('#git-graph-container');
      if (!commits.length) {
        container.innerHTML = '<div class="git-no-repo" style="padding:40px"><p>No commits yet</p></div>';
        return;
      }

      const ROW_H = 32, LANE_W = 20, DOT_R = 5, MAX_LANES = 6;
      const COLORS = ['#7c5cfc', '#2ecc71', '#e74c3c', '#f1c40f', '#3498db', '#e67e22', '#1abc9c', '#9b59b6'];

      // Assign lanes to commits
      const hashIdx = {};
      commits.forEach((c, i) => hashIdx[c.hash] = i);
      const lanes = [];
      const commitLane = [];

      for (let i = 0; i < commits.length; i++) {
        const c = commits[i];
        let myLane = lanes.indexOf(c.hash);
        if (myLane === -1) {
          myLane = lanes.indexOf(null);
          if (myLane === -1) { myLane = lanes.length; lanes.push(null); }
          lanes[myLane] = c.hash;
        }
        commitLane[i] = { lane: myLane, merges: [] };
        if (c.parents.length > 0) lanes[myLane] = c.parents[0];
        else lanes[myLane] = null;
        for (let p = 1; p < c.parents.length; p++) {
          const ph = c.parents[p];
          let pLane = lanes.indexOf(ph);
          if (pLane === -1) {
            pLane = lanes.indexOf(null);
            if (pLane === -1) { pLane = lanes.length; lanes.push(null); }
            lanes[pLane] = ph;
          }
          commitLane[i].merges.push(pLane);
        }
        for (let l = 0; l < lanes.length; l++) {
          if (lanes[l] && !commits.slice(i + 1).some(fc => fc.hash === lanes[l])) {
            if (!c.parents.includes(lanes[l])) lanes[l] = null;
          }
        }
      }

      const maxLane = Math.min(Math.max(...commitLane.map(c => c.lane), ...commitLane.flatMap(c => c.merges), 0) + 1, MAX_LANES);
      const svgW = (maxLane + 1) * LANE_W + 10;

      // Build graph
      let html = '<div class="git-graph-list">';

      for (let i = 0; i < commits.length; i++) {
        const c = commits[i];
        const cl = commitLane[i];
        const lane = Math.min(cl.lane, MAX_LANES - 1);
        const color = COLORS[lane % COLORS.length];
        const isHead = c.refs.some(r => r.type === 'head');

        const cx = lane * LANE_W + LANE_W / 2 + 4;
        const cy = ROW_H / 2;
        let svg = `<svg width="${svgW}" height="${ROW_H}" viewBox="0 0 ${svgW} ${ROW_H}">`;

        // Active lanes
        const activeLanesHere = new Set();
        if (i < commits.length - 1) activeLanesHere.add(commitLane[i + 1].lane);
        activeLanesHere.add(lane);
        cl.merges.forEach(ml => activeLanesHere.add(ml));

        // Draw lane lines
        activeLanesHere.forEach(l => {
          if (l >= MAX_LANES) return;
          const lx = l * LANE_W + LANE_W / 2 + 4;
          const lcolor = COLORS[l % COLORS.length];
          svg += `<line x1="${lx}" y1="0" x2="${lx}" y2="${ROW_H}" stroke="${lcolor}" stroke-width="2" opacity="0.35"/>`;
        });

        // Merge lines (curved)
        cl.merges.forEach(ml => {
          if (ml >= MAX_LANES) return;
          const mx = Math.min(ml, MAX_LANES - 1) * LANE_W + LANE_W / 2 + 4;
          const mcolor = COLORS[ml % COLORS.length];
          svg += `<path d="M${cx},${cy} C${cx},${ROW_H} ${mx},${cy} ${mx},${ROW_H}" stroke="${mcolor}" stroke-width="2" fill="none" opacity="0.6"/>`;
        });

        // Commit dot
        svg += `<circle cx="${cx}" cy="${cy}" r="${DOT_R}" fill="${color}"/>`;
        if (isHead) {
          svg += `<circle cx="${cx}" cy="${cy}" r="${DOT_R + 3}" fill="none" stroke="${color}" stroke-width="1.5" opacity="0.4"/>`;
        }
        svg += '</svg>';

        // Refs badges
        let refHtml = '';
        c.refs.forEach(ref => {
          refHtml += `<span class="git-ref-badge ${ref.type}">${escHtml(ref.name)}</span>`;
        });

        // Relative date
        const dateStr = this._relativeDate(c.date);

        html += `<div class="git-graph-item${isHead ? ' head' : ''}" data-hash="${c.hash}" data-short="${c.short}">
          <div class="git-graph-main">
            <div class="git-graph-lane">${svg}</div>
            <div class="git-graph-info">
              <div class="git-graph-msg">${refHtml}<span class="git-graph-subject">${escHtml(c.subject)}</span></div>
              <div class="git-graph-meta">
                <span class="git-graph-author">${escHtml(c.author)}</span>
                <span class="git-graph-sep">·</span>
                <span class="git-graph-date">${dateStr}</span>
                <span class="git-graph-sep">·</span>
                <span class="git-graph-hash">${c.short}</span>
              </div>
            </div>
          </div>
          <div class="git-graph-detail" id="git-detail-${c.short}" style="display:none"></div>
        </div>`;
      }

      html += '</div>';
      container.innerHTML = html;

      // Click handlers
      container.querySelectorAll('.git-graph-item').forEach(item => {
        item.querySelector('.git-graph-main').addEventListener('click', () => {
          const hash = item.dataset.hash;
          const detail = item.querySelector('.git-graph-detail');
          if (detail.style.display !== 'none') {
            detail.style.display = 'none';
            return;
          }
          // Load commit details
          detail.innerHTML = '<div style="padding:8px;color:var(--text-muted);font-size:11px;">Loading...</div>';
          detail.style.display = 'block';
          fetch('/workspace/git-show?commit=' + hash)
            .then(r => r.json())
            .then(d => {
              if (d.error) { detail.innerHTML = `<div style="padding:8px;color:var(--red);font-size:11px;">${escHtml(d.error)}</div>`; return; }
              let fhtml = '<div class="git-detail-files">';
              if (d.summary) fhtml += `<div class="git-detail-summary">${escHtml(d.summary)}</div>`;
              (d.files || []).forEach(f => {
                const total = f.additions + f.deletions || 1;
                const addPct = Math.round((f.additions / total) * 100);
                fhtml += `<div class="git-detail-file git-detail-file-clickable" data-fname="${escHtml(f.name)}" data-hash="${hash}">
                  <span class="git-detail-fname">${escHtml(f.name)}</span>
                  <span class="git-detail-stat">
                    <span class="git-detail-changes">${f.changes}</span>
                    <span class="git-detail-bar">
                      <span class="git-detail-add" style="width:${addPct}%"></span>
                      <span class="git-detail-del" style="width:${100 - addPct}%"></span>
                    </span>
                  </span>
                </div>`;
              });
              if (!d.files || !d.files.length) fhtml += '<div style="padding:4px 8px;color:var(--text-muted);font-size:11px;">No file changes</div>';
              fhtml += '</div>';
              detail.innerHTML = fhtml;
              // Collect file list for navigation
              const commitFiles = (d.files || []).map(f => f.name);
              // Bind click on file rows
              detail.querySelectorAll('.git-detail-file-clickable').forEach(row => {
                row.addEventListener('click', e => {
                  e.stopPropagation();
                  this.openFileDiff(row.dataset.hash, row.dataset.fname, commitFiles);
                });
              });
            })
            .catch(() => { detail.innerHTML = '<div style="padding:8px;color:var(--red);font-size:11px;">Failed to load</div>'; });
        });
      });
    }

    // ---- Side-by-side Diff Viewer ----
    async openFileDiff(commit, filePath, commitFiles) {
      const area = $('#editor-code-area');
      // Store commit files for navigation
      this._diffCommitFiles = commitFiles || this._diffCommitFiles || [];
      this._diffCommit = commit;
      if (!area) return;

      // Show loading
      area.innerHTML = `<div class="diff-loading"><div style="text-align:center;padding:40px;color:var(--text-muted);">Loading diff for <strong>${escHtml(filePath)}</strong>...</div></div>`;

      try {
        const res = await fetch(`/workspace/git-file-diff?commit=${commit}&path=${encodeURIComponent(filePath)}`);
        const d = await res.json();
        if (d.error) {
          area.innerHTML = `<div style="padding:40px;text-align:center;color:var(--red);">${escHtml(d.error)}</div>`;
          return;
        }

        // Detect language for highlighting
        const lang = this._extToLang(filePath);

        // Compute aligned diff rows using the unified diff hunks
        const beforeLines = (d.before || '').split('\n');
        const afterLines = (d.after || '').split('\n');
        const diffRows = this._computeAlignedDiff(beforeLines, afterLines, d.diff || '');

        // Count changes
        const stats = { added: 0, removed: 0, modified: 0 };
        diffRows.forEach(r => {
          if (r.type === 'add') stats.added++;
          else if (r.type === 'del') stats.removed++;
          else if (r.type === 'mod') stats.modified++;
        });

        // File navigation context
        const fileList = this._diffCommitFiles;
        const fileIdx = fileList.indexOf(filePath);
        const hasPrevFile = fileIdx > 0;
        const hasNextFile = fileIdx >= 0 && fileIdx < fileList.length - 1;
        const fileCounter = fileList.length > 1 ? `<span class="diff-file-counter">${fileIdx + 1} / ${fileList.length}</span>` : '';

        let html = `
          <div class="diff-viewer">
            <div class="diff-header">
              <div class="diff-header-left">
                <button class="diff-file-nav-btn" id="diff-file-prev" title="Previous file" ${hasPrevFile ? '' : 'disabled'}>◄</button>
                <div class="diff-header-info">
                  ${icon('gitCommit')} <strong>${escHtml(filePath)}</strong>
                  <span class="diff-commit-hash">${commit.substring(0, 8)}</span>
                  ${fileCounter}
                  ${d.is_new ? '<span class="git-ref-badge head">NEW</span>' : ''}
                  ${d.is_deleted ? '<span class="git-ref-badge" style="background:rgba(244,63,94,.2);color:var(--red);border:1px solid rgba(244,63,94,.3);">DELETED</span>' : ''}
                </div>
                <button class="diff-file-nav-btn" id="diff-file-next" title="Next file" ${hasNextFile ? '' : 'disabled'}>►</button>
              </div>
              <div class="diff-header-actions">
                <div class="diff-stats-bar">
                  ${stats.added ? `<span class="diff-stat-badge diff-stat-add">+${stats.added}</span>` : ''}
                  ${stats.removed ? `<span class="diff-stat-badge diff-stat-del">−${stats.removed}</span>` : ''}
                  ${stats.modified ? `<span class="diff-stat-badge diff-stat-mod">→${stats.modified}</span>` : ''}
                </div>
                <button class="diff-nav-btn" id="diff-nav-prev" title="Previous change (↑)">▲</button>
                <button class="diff-nav-btn" id="diff-nav-next" title="Next change (↓)">▼</button>
                <button class="diff-close-btn" id="diff-viewer-close">${icon('x')} Close</button>
              </div>
            </div>
            <div class="diff-panels">
              <div class="diff-panel diff-panel-before">
                <div class="diff-panel-header">Before (${commit.substring(0, 8)}~1)</div>
                <div class="diff-panel-content" id="diff-panel-left">
                  <table class="diff-table"><tbody>`;

        // Track which rows are change boundaries for navigation
        let changeChunkId = 0;
        let lastWasChange = false;

        // Render LEFT panel (before)
        diffRows.forEach((row, idx) => {
          const isChange = row.type !== 'ctx';
          // Insert chunk separator for non-contiguous changes
          if (isChange && !lastWasChange && idx > 0) {
            changeChunkId++;
          }
          lastWasChange = isChange;

          if (row.type === 'ctx') {
            // Context (unchanged) line
            html += `<tr class="diff-line diff-line-ctx">
              <td class="diff-ln">${row.leftNum || ''}</td>
              <td class="diff-gutter"></td>
              <td class="diff-code">${this._highlightLine(row.leftText, lang)}</td>
            </tr>`;
          } else if (row.type === 'del' || row.type === 'mod') {
            // Removed or modified line (left side)
            const marker = row.type === 'mod' ? '→' : '−';
            const cls = row.type === 'mod' ? 'diff-line-modified' : 'diff-line-removed';
            const codeHtml = row.type === 'mod' && row.rightText !== undefined
              ? this._highlightWordDiff(row.leftText || '', row.rightText || '', 'del', lang)
              : this._highlightLine(row.leftText, lang);
            html += `<tr class="diff-line ${cls}" data-chunk="${changeChunkId}">
              <td class="diff-ln">${row.leftNum || ''}</td>
              <td class="diff-gutter"><span class="diff-marker">${marker}</span></td>
              <td class="diff-code">${codeHtml}</td>
            </tr>`;
          } else if (row.type === 'add') {
            // Padding on left for added lines
            html += `<tr class="diff-line diff-line-pad" data-chunk="${changeChunkId}">
              <td class="diff-ln"></td>
              <td class="diff-gutter"><span class="diff-marker diff-marker-pad">+</span></td>
              <td class="diff-code diff-code-pad"></td>
            </tr>`;
          }
        });

        html += `</tbody></table></div></div>
              <div class="diff-panel diff-panel-after">
                <div class="diff-panel-header">After (${commit.substring(0, 8)})</div>
                <div class="diff-panel-content" id="diff-panel-right">
                  <table class="diff-table"><tbody>`;

        // Render RIGHT panel (after)
        changeChunkId = 0;
        lastWasChange = false;
        diffRows.forEach((row, idx) => {
          const isChange = row.type !== 'ctx';
          if (isChange && !lastWasChange && idx > 0) {
            changeChunkId++;
          }
          lastWasChange = isChange;

          if (row.type === 'ctx') {
            html += `<tr class="diff-line diff-line-ctx">
              <td class="diff-ln">${row.rightNum || ''}</td>
              <td class="diff-gutter"></td>
              <td class="diff-code">${this._highlightLine(row.rightText, lang)}</td>
            </tr>`;
          } else if (row.type === 'add' || row.type === 'mod') {
            const marker = row.type === 'mod' ? '→' : '+';
            const cls = row.type === 'mod' ? 'diff-line-modified' : 'diff-line-added';
            const codeHtml = row.type === 'mod' && row.leftText !== undefined
              ? this._highlightWordDiff(row.leftText || '', row.rightText || '', 'add', lang)
              : this._highlightLine(row.rightText, lang);
            html += `<tr class="diff-line ${cls}" data-chunk="${changeChunkId}">
              <td class="diff-ln">${row.rightNum || ''}</td>
              <td class="diff-gutter"><span class="diff-marker">${marker}</span></td>
              <td class="diff-code">${codeHtml}</td>
            </tr>`;
          } else if (row.type === 'del') {
            // Padding on right for deleted lines
            html += `<tr class="diff-line diff-line-pad" data-chunk="${changeChunkId}">
              <td class="diff-ln"></td>
              <td class="diff-gutter"><span class="diff-marker diff-marker-pad">−</span></td>
              <td class="diff-code diff-code-pad"></td>
            </tr>`;
          }
        });

        html += `</tbody></table></div></div>
            </div>
          </div>`;

        area.innerHTML = html;

        // Close button
        const closeBtn = area.querySelector('#diff-viewer-close');
        if (closeBtn) {
          closeBtn.addEventListener('click', () => {
            const tab = this.openTabs.find(t => t.path === this.activeTab);
            if (tab) this.loadIntoEditor(tab);
            else this.showWelcome();
          });
        }

        // File navigation buttons (◄ ►)
        const filePrevBtn = area.querySelector('#diff-file-prev');
        const fileNextBtn = area.querySelector('#diff-file-next');
        if (filePrevBtn) {
          filePrevBtn.addEventListener('click', () => {
            const idx = this._diffCommitFiles.indexOf(filePath);
            if (idx > 0) this.openFileDiff(commit, this._diffCommitFiles[idx - 1]);
          });
        }
        if (fileNextBtn) {
          fileNextBtn.addEventListener('click', () => {
            const idx = this._diffCommitFiles.indexOf(filePath);
            if (idx >= 0 && idx < this._diffCommitFiles.length - 1) this.openFileDiff(commit, this._diffCommitFiles[idx + 1]);
          });
        }

        // Sync scroll between panels
        const panels = area.querySelectorAll('.diff-panel-content');
        if (panels.length === 2) {
          let syncing = false;
          panels.forEach((panel, idx) => {
            panel.addEventListener('scroll', () => {
              if (syncing) return;
              syncing = true;
              const other = panels[1 - idx];
              other.scrollTop = panel.scrollTop;
              other.scrollLeft = panel.scrollLeft;
              requestAnimationFrame(() => { syncing = false; });
            });
          });
        }

        // Navigation between change chunks
        let currentChunk = -1;
        const maxChunk = changeChunkId;
        const scrollToChunk = (chunkId) => {
          const targets = area.querySelectorAll(`[data-chunk="${chunkId}"]`);
          if (targets.length > 0) {
            // Scroll both panels to the first row of this chunk
            const leftTarget = area.querySelector(`#diff-panel-left [data-chunk="${chunkId}"]`);
            const rightTarget = area.querySelector(`#diff-panel-right [data-chunk="${chunkId}"]`);
            if (leftTarget) {
              const container = leftTarget.closest('.diff-panel-content');
              if (container) {
                container.scrollTop = leftTarget.offsetTop - container.offsetTop - 60;
              }
            }
            if (rightTarget) {
              const container = rightTarget.closest('.diff-panel-content');
              if (container) {
                container.scrollTop = rightTarget.offsetTop - container.offsetTop - 60;
              }
            }
            // Highlight active chunk briefly
            targets.forEach(t => {
              t.classList.add('diff-chunk-active');
              setTimeout(() => t.classList.remove('diff-chunk-active'), 1200);
            });
          }
        };
        const prevBtn = area.querySelector('#diff-nav-prev');
        const nextBtn = area.querySelector('#diff-nav-next');
        if (nextBtn) {
          nextBtn.addEventListener('click', () => {
            if (currentChunk < maxChunk) { currentChunk++; scrollToChunk(currentChunk); }
          });
        }
        if (prevBtn) {
          prevBtn.addEventListener('click', () => {
            if (currentChunk > 0) { currentChunk--; scrollToChunk(currentChunk); }
          });
        }

        // Auto-scroll to first change
        if (maxChunk >= 0) {
          setTimeout(() => { currentChunk = 0; scrollToChunk(0); }, 150);
        }

      } catch (e) {
        area.innerHTML = `<div style="padding:40px;text-align:center;color:var(--red);">Error: ${escHtml(e.message)}</div>`;
      }
    }

    /**
     * Compute aligned diff rows from before/after lines + unified diff.
     * Returns an array of { type: 'ctx'|'add'|'del'|'mod', leftNum, rightNum, leftText, rightText }
     */
    _computeAlignedDiff(beforeLines, afterLines, unifiedDiff) {
      const rows = [];
      if (!unifiedDiff) {
        // No diff — show all as context
        const max = Math.max(beforeLines.length, afterLines.length);
        for (let i = 0; i < max; i++) {
          rows.push({
            type: 'ctx',
            leftNum: i < beforeLines.length ? i + 1 : null,
            rightNum: i < afterLines.length ? i + 1 : null,
            leftText: i < beforeLines.length ? beforeLines[i] : '',
            rightText: i < afterLines.length ? afterLines[i] : '',
          });
        }
        return rows;
      }

      // Parse unified diff into hunks
      const hunks = [];
      let currentHunk = null;
      const lines = unifiedDiff.split('\n');
      for (const line of lines) {
        if (line.startsWith('@@')) {
          const m = line.match(/@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/);
          if (m) {
            currentHunk = {
              oldStart: parseInt(m[1]),
              oldCount: m[2] !== undefined ? parseInt(m[2]) : 1,
              newStart: parseInt(m[3]),
              newCount: m[4] !== undefined ? parseInt(m[4]) : 1,
              delLines: [],
              addLines: [],
              ops: []
            };
            hunks.push(currentHunk);
          }
        } else if (currentHunk) {
          if (line.startsWith('-') && !line.startsWith('---')) {
            currentHunk.ops.push({ type: 'del', text: line.substring(1) });
          } else if (line.startsWith('+') && !line.startsWith('+++')) {
            currentHunk.ops.push({ type: 'add', text: line.substring(1) });
          } else if (!line.startsWith('\\')) {
            currentHunk.ops.push({ type: 'ctx', text: line.startsWith(' ') ? line.substring(1) : line });
          }
        }
      }

      // Build aligned rows from hunks
      let leftIdx = 0;  // 0-based index into beforeLines
      let rightIdx = 0; // 0-based index into afterLines

      for (const hunk of hunks) {
        const hunkLeftStart = hunk.oldStart - 1; // 0-based
        const hunkRightStart = hunk.newStart - 1;

        // Add context lines before this hunk
        while (leftIdx < hunkLeftStart && rightIdx < hunkRightStart) {
          rows.push({
            type: 'ctx',
            leftNum: leftIdx + 1, rightNum: rightIdx + 1,
            leftText: beforeLines[leftIdx] || '', rightText: afterLines[rightIdx] || '',
          });
          leftIdx++;
          rightIdx++;
        }

        // Process hunk ops — group consecutive del+add as modifications
        let i = 0;
        while (i < hunk.ops.length) {
          const op = hunk.ops[i];
          if (op.type === 'ctx') {
            rows.push({
              type: 'ctx',
              leftNum: leftIdx + 1, rightNum: rightIdx + 1,
              leftText: beforeLines[leftIdx] || op.text,
              rightText: afterLines[rightIdx] || op.text,
            });
            leftIdx++;
            rightIdx++;
            i++;
          } else if (op.type === 'del') {
            // Collect consecutive del lines
            const dels = [];
            while (i < hunk.ops.length && hunk.ops[i].type === 'del') {
              dels.push(hunk.ops[i]);
              i++;
            }
            // Collect consecutive add lines right after
            const adds = [];
            while (i < hunk.ops.length && hunk.ops[i].type === 'add') {
              adds.push(hunk.ops[i]);
              i++;
            }
            // Pair up del/add as modifications
            const pairCount = Math.min(dels.length, adds.length);
            for (let p = 0; p < pairCount; p++) {
              rows.push({
                type: 'mod',
                leftNum: leftIdx + 1, rightNum: rightIdx + 1,
                leftText: beforeLines[leftIdx] || dels[p].text,
                rightText: afterLines[rightIdx] || adds[p].text,
              });
              leftIdx++;
              rightIdx++;
            }
            // Remaining dels (pure deletions)
            for (let p = pairCount; p < dels.length; p++) {
              rows.push({
                type: 'del',
                leftNum: leftIdx + 1, rightNum: null,
                leftText: beforeLines[leftIdx] || dels[p].text,
              });
              leftIdx++;
            }
            // Remaining adds (pure additions)
            for (let p = pairCount; p < adds.length; p++) {
              rows.push({
                type: 'add',
                leftNum: null, rightNum: rightIdx + 1,
                rightText: afterLines[rightIdx] || adds[p].text,
              });
              rightIdx++;
            }
          } else if (op.type === 'add') {
            rows.push({
              type: 'add',
              leftNum: null, rightNum: rightIdx + 1,
              rightText: afterLines[rightIdx] || op.text,
            });
            rightIdx++;
            i++;
          }
        }
      }

      // Add trailing context after last hunk
      while (leftIdx < beforeLines.length && rightIdx < afterLines.length) {
        rows.push({
          type: 'ctx',
          leftNum: leftIdx + 1, rightNum: rightIdx + 1,
          leftText: beforeLines[leftIdx] || '', rightText: afterLines[rightIdx] || '',
        });
        leftIdx++;
        rightIdx++;
      }
      // Handle any remaining lines
      while (leftIdx < beforeLines.length) {
        rows.push({ type: 'del', leftNum: leftIdx + 1, leftText: beforeLines[leftIdx] || '' });
        leftIdx++;
      }
      while (rightIdx < afterLines.length) {
        rows.push({ type: 'add', rightNum: rightIdx + 1, rightText: afterLines[rightIdx] || '' });
        rightIdx++;
      }

      return rows;
    }

    /**
     * Highlight word-level differences within a line.
     * side: 'del' = show removed tokens highlighted, 'add' = show added tokens highlighted
     */
    _highlightWordDiff(oldLine, newLine, side, lang) {
      if (!oldLine && !newLine) return '&nbsp;';
      const text = side === 'del' ? oldLine : newLine;
      if (!oldLine || !newLine) return escHtml(text) || '&nbsp;';

      // Split into tokens (words + whitespace)
      const tokenize = (s) => s.match(/\S+|\s+/g) || [];
      const oldTokens = tokenize(oldLine);
      const newTokens = tokenize(newLine);

      // Simple LCS-based token diff
      const oldSet = new Set();
      const newSet = new Set();

      // Find common prefix
      let commonPrefix = 0;
      while (commonPrefix < oldTokens.length && commonPrefix < newTokens.length &&
        oldTokens[commonPrefix] === newTokens[commonPrefix]) {
        commonPrefix++;
      }
      // Find common suffix
      let commonSuffix = 0;
      while (commonSuffix < (oldTokens.length - commonPrefix) &&
        commonSuffix < (newTokens.length - commonPrefix) &&
        oldTokens[oldTokens.length - 1 - commonSuffix] === newTokens[newTokens.length - 1 - commonSuffix]) {
        commonSuffix++;
      }

      // Mark changed token indices
      for (let i = commonPrefix; i < oldTokens.length - commonSuffix; i++) oldSet.add(i);
      for (let i = commonPrefix; i < newTokens.length - commonSuffix; i++) newSet.add(i);

      // Build highlighted output
      const tokens = side === 'del' ? oldTokens : newTokens;
      const changedSet = side === 'del' ? oldSet : newSet;
      let result = '';
      tokens.forEach((tok, i) => {
        const escaped = escHtml(tok);
        if (changedSet.has(i)) {
          const cls = side === 'del' ? 'diff-word-del' : 'diff-word-add';
          result += `<span class="${cls}">${escaped}</span>`;
        } else {
          result += escaped;
        }
      });
      return result || '&nbsp;';
    }

    _highlightLine(line, lang) {
      if (!line) return '&nbsp;';
      try {
        if (window.hljs && lang !== 'plaintext') {
          return hljs.highlight(line, { language: lang, ignoreIllegals: true }).value;
        }
      } catch (e) { }
      return escHtml(line) || '&nbsp;';
    }

    _parseDiffHunks(diff) {
      const removed = new Set();
      const added = new Set();
      if (!diff) return { removed, added };
      let oldLine = 0, newLine = 0;
      const lines = diff.split('\n');
      for (const line of lines) {
        if (line.startsWith('@@')) {
          // Parse hunk header: @@ -old,count +new,count @@
          const m = line.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
          if (m) { oldLine = parseInt(m[1]); newLine = parseInt(m[2]); }
        } else if (line.startsWith('-') && !line.startsWith('---')) {
          removed.add(oldLine);
          oldLine++;
        } else if (line.startsWith('+') && !line.startsWith('+++')) {
          added.add(newLine);
          newLine++;
        } else if (!line.startsWith('\\')) {
          oldLine++;
          newLine++;
        }
      }
      return { removed, added };
    }


    _relativeDate(dateStr) {
      try {
        const d = new Date(dateStr);
        const now = new Date();
        const diff = Math.floor((now - d) / 1000);
        if (diff < 60) return 'just now';
        if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
        if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
        if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
        if (diff < 2592000) return Math.floor(diff / 604800) + 'w ago';
        return d.toLocaleDateString();
      } catch (e) { return dateStr.substring(0, 10); }
    }


    // ---- Project Management ----
    async loadProjects() {
      try {
        const r = await fetch('/workspace/tree');
        const d = await r.json();
        const select = $('#project-select');
        if (!select) return;
        select.innerHTML = '<option value=".">workspace /</option>';
        // Add top-level directories as projects (extract from flat file list)
        const dirs = new Set();
        (d.files || []).forEach(f => {
          const firstDir = f.path.split('/')[0];
          if (f.path.includes('/') && firstDir) dirs.add(firstDir);
        });
        [...dirs].sort().forEach(dirName => {
          const opt = document.createElement('option');
          opt.value = dirName;
          opt.textContent = ' ' + dirName;
          select.appendChild(opt);
        });
        // Restore last project
        const last = localStorage.getItem('clawzd_project');
        if (last && select.querySelector(`option[value="${last}"]`)) {
          select.value = last;
        }
        // Add history projects that aren't in current tree
        this._addHistoryOptions(select);
      } catch (e) { }
    }

    _addHistoryOptions(select) {
      const history = JSON.parse(localStorage.getItem('clawzd_project_history') || '[]');
      history.forEach(p => {
        if (!select.querySelector(`option[value="${p}"]`) && p !== '.') {
          const opt = document.createElement('option');
          opt.value = p;
          opt.textContent = ' ' + p + ' (history)';
          opt.style.color = '#888';
          select.appendChild(opt);
        }
      });
    }

    switchProject(projectName) {
      localStorage.setItem('clawzd_project', projectName);
      // Add to history
      const history = JSON.parse(localStorage.getItem('clawzd_project_history') || '[]');
      if (!history.includes(projectName)) {
        history.unshift(projectName);
        if (history.length > 10) history.pop();
        localStorage.setItem('clawzd_project_history', JSON.stringify(history));
      }
      // Close all tabs
      this.openTabs = [];
      this.activeTab = null;
      this.renderTabs();
      this.showWelcome();
      // Reload tree for the project
      this.loadTree();
      this.addActivity(icon('folder'), 'Switched project', projectName === '.' ? 'workspace root' : projectName);
      toast('Project: ' + (projectName === '.' ? 'workspace' : projectName));
    }

    closeProject() {
      const current = $('#project-select').value;
      if (current === '.') { toast('Cannot close workspace root'); return; }
      // Remove from history
      let history = JSON.parse(localStorage.getItem('clawzd_project_history') || '[]');
      history = history.filter(p => p !== current);
      localStorage.setItem('clawzd_project_history', JSON.stringify(history));
      // Switch to root
      $('#project-select').value = '.';
      localStorage.setItem('clawzd_project', '.');
      this.openTabs = [];
      this.activeTab = null;
      this.renderTabs();
      this.showWelcome();
      this.loadTree();
      this.loadProjects();
      this.addActivity(icon('x'), 'Closed project', current);
    }

    showProjectHistory() {
      const history = JSON.parse(localStorage.getItem('clawzd_project_history') || '[]');
      if (!history.length) { toast('No project history'); return; }
      const choice = prompt('Recent projects:\n' + history.map((p, i) => (i + 1) + '. ' + p).join('\n') + '\n\nEnter number to open:');
      if (choice && history[parseInt(choice) - 1]) {
        this.switchProject(history[parseInt(choice) - 1]);
        $('#project-select').value = history[parseInt(choice) - 1];
      }
    }
  }

  // ---- Media Studio ----
  class MediaStudio {
    constructor() {
      this.active = false;
      this.items = [];        // gallery items from API
      this.filtered = [];     // after filter applied
      this.selected = new Set();
      this.filter = 'all';
      this.type = 'image';    // 'image', 'video', or 'audio'
      this.backend = 'local'; // 'local' or 'api'
      this.generating = false;
      this.lightboxIdx = -1;
      this.referenceImage = null; // for image-to-image
      this.audioSubMode = 'tts'; // 'tts', 'voice_clone', 'music', 'song'
      this.referenceAudio = null; // for voice cloning
      this.templateSubMode = 'business_card'; // 'business_card' or 'cv'
      this._linkedInData = null; // fetched LinkedIn profile data
      this._bind();
    }

    _bind() {
      // Init SVG icons
      $$('.media-icon').forEach(n => {
        if (window.icon && n.dataset.icon) {
          n.innerHTML = window.icon(n.dataset.icon, 16);
          n.style.marginRight = '6px';
          n.style.display = 'inline-flex';
          n.style.alignItems = 'center';
        }
      });

      // Type toggle
      $$('#media-type-toggle .media-type-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          $$('#media-type-toggle .media-type-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          this.type = btn.dataset.type;
          this._updateFormVisibility();
        });
      });

      // Clear reference image
      const refClear = $('#media-ref-clear');
      if (refClear) refClear.addEventListener('click', () => this.clearReferenceImage());

      // Duration range (video)
      const durationSlider = $('#media-duration');
      if (durationSlider) {
        durationSlider.addEventListener('input', () => {
          $('#media-duration-value').textContent = durationSlider.value + 's';
        });
      }

      // Num images range
      const numImgSlider = $('#media-num-images');
      if (numImgSlider) {
        numImgSlider.addEventListener('input', () => {
          $('#media-num-images-value').textContent = numImgSlider.value;
        });
      }

      // Backend toggle
      $$('#media-backend-toggle .media-type-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          $$('#media-backend-toggle .media-type-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          this.backend = btn.dataset.backend;
        });
      });

      // Audio sub-mode toggle
      $$('#media-audio-submode-toggle .media-type-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          $$('#media-audio-submode-toggle .media-type-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          this.audioSubMode = btn.dataset.submode;
          this._updateFormVisibility();
        });
      });



      // Audio tempo slider
      const tempoSlider = $('#media-tempo');
      if (tempoSlider) {
        tempoSlider.addEventListener('input', () => {
          $('#media-tempo-value').textContent = tempoSlider.value;
        });
      }

      // Audio duration slider
      const audioDurSlider = $('#media-audio-duration');
      if (audioDurSlider) {
        audioDurSlider.addEventListener('input', () => {
          $('#media-audio-duration-value').textContent = audioDurSlider.value + 's';
        });
      }

      // Reference audio upload (voice cloning)
      const audioRefBtn = $('#media-audio-ref-btn');
      const audioRefInput = $('#media-audio-ref-input');
      if (audioRefBtn && audioRefInput) {
        audioRefBtn.addEventListener('click', () => audioRefInput.click());
        audioRefInput.addEventListener('change', async (e) => {
          if (!e.target.files || !e.target.files[0]) return;
          const file = e.target.files[0];
          const formData = new FormData();
          formData.append('file', file);
          try {
            audioRefBtn.classList.add('loading');
            const resp = await fetch('/audio/upload-reference', { method: 'POST', body: formData });
            if (!resp.ok) throw new Error('Upload failed');
            const data = await resp.json();
            this.referenceAudio = data.filename;
            const preview = $('#media-audio-ref-preview');
            const player = $('#media-audio-ref-player');
            if (preview && player) {
              player.src = data.url;
              preview.style.display = 'block';
            }
            toast(ICONS.check(14) + ' Échantillon vocal chargé');
          } catch (err) {
            toast(ICONS.x(14) + ' Upload failed: ' + err.message);
          } finally {
            audioRefBtn.classList.remove('loading');
            audioRefInput.value = '';
          }
        });
      }
      const audioRefClear = $('#media-audio-ref-clear');
      if (audioRefClear) audioRefClear.addEventListener('click', () => {
        this.referenceAudio = null;
        const preview = $('#media-audio-ref-preview');
        if (preview) preview.style.display = 'none';
      });

      // Generate
      const genBtn = $('#media-generate-btn');
      if (genBtn) genBtn.addEventListener('click', () => this.generate());

      // Prompt — Ctrl+Enter shortcut
      const prompt = $('#media-prompt');
      if (prompt) prompt.addEventListener('keydown', e => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); this.generate(); }
      });

      // Upload Image
      const uploadBtn = $('#media-upload-btn');
      const uploadInput = $('#media-upload-input');
      if (uploadBtn && uploadInput) {
        uploadBtn.addEventListener('click', () => uploadInput.click());
        uploadInput.addEventListener('change', async (e) => {
          if (!e.target.files || !e.target.files[0]) return;
          const file = e.target.files[0];
          const formData = new FormData();
          formData.append('file', file);
          try {
            uploadBtn.classList.add('loading');
            const resp = await fetch('/image/upload', {
              method: 'POST',
              body: formData
            });
            if (!resp.ok) throw new Error('Upload failed');
            const data = await resp.json();
            const format = data.filename.split('.').pop().toLowerCase();
            if (['mp4', 'webm', 'gif'].includes(format)) {
              toast((window.icon ? window.icon('check', 14) : '✅') + ' Media imported successfully');
            } else {
              this.setReferenceImage({ filename: data.filename, url: data.url, format });
            }
            this.loadGallery(); // Reload gallery to show the newly uploaded image
          } catch (err) {
            toast(' Upload failed: ' + err.message);
          } finally {
            uploadBtn.classList.remove('loading');
            uploadInput.value = '';
          }
        });
      }

      // Unified Media Tools select
      const toolsSelect = $('#media-tools-select');
      if (toolsSelect) {
        toolsSelect.addEventListener('change', () => {
          const action = toolsSelect.value;
          toolsSelect.value = ''; // Reset to placeholder
          switch (action) {
            case 'convert_gif': this.convertVideo('gif'); break;
            case 'convert_mp4': this.convertVideo('mp4'); break;
            case 'convert_webm': this.convertVideo('webm'); break;
            case 'remove_bg': this.removeBgSelected(); break;
            case 'make_coloring': this.makeColoringSelected(); break;
            case 'download_zip': this.downloadZip(); break;
          }
        });
      }

      // Toolbar
      const selAll = $('#media-select-all');
      if (selAll) selAll.addEventListener('click', () => this.toggleSelectAll());

      const delSel = $('#media-delete-selected');
      if (delSel) delSel.addEventListener('click', () => this.deleteSelected());

      const refresh = $('#media-refresh');
      if (refresh) refresh.addEventListener('click', () => this.loadGallery());

      // Filter tabs
      $$('#media-filters .media-filter-tab').forEach(btn => {
        btn.addEventListener('click', () => {
          $$('#media-filters .media-filter-tab').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          this.filter = btn.dataset.filter;
          this._applyFilter();
          this.renderGallery();
        });
      });

      // Lightbox
      const lbClose = $('#media-lb-close');
      if (lbClose) lbClose.addEventListener('click', () => this.closeLightbox());
      const lbPrev = $('#media-lb-prev');
      if (lbPrev) lbPrev.addEventListener('click', () => this.lightboxNav(-1));
      const lbNext = $('#media-lb-next');
      if (lbNext) lbNext.addEventListener('click', () => this.lightboxNav(1));
      const lbDl = $('#media-lb-download');
      if (lbDl) lbDl.addEventListener('click', () => this.lightboxDownload());
      const lbDel = $('#media-lb-delete');
      if (lbDel) lbDel.addEventListener('click', () => this.lightboxDelete());
      const lbVar = $('#media-lb-variant');
      if (lbVar) lbVar.addEventListener('click', () => {
        if (this.lightboxIdx >= 0 && this.lightboxIdx < this.filtered.length) {
          this.setReferenceImage(this.filtered[this.lightboxIdx]);
        }
      });

      // Lightbox keyboard nav
      document.addEventListener('keydown', e => {
        const lb = $('#media-lightbox');
        if (lb && lb.classList.contains('open')) {
          if (e.key === 'Escape') this.closeLightbox();
          if (e.key === 'ArrowLeft') this.lightboxNav(-1);
          if (e.key === 'ArrowRight') this.lightboxNav(1);
          if (e.key === 'Delete' || e.key === 'Backspace') {
            if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
              this.lightboxDelete();
            }
          }
          return;
        }

        // Gallery keyboard nav
        if (this.active && (e.key === 'Delete' || e.key === 'Backspace')) {
          if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
            if (this.selected.size > 0) {
              this.deleteSelected();
            }
          }
        }
      });

      // Lightbox backdrop click
      const lb = $('#media-lightbox');
      if (lb) lb.addEventListener('click', e => {
        if (e.target === lb) this.closeLightbox();
      });

      // Lightbox Image-to-Video button
      const lbI2V = $('#media-lb-i2v');
      if (lbI2V) lbI2V.addEventListener('click', () => {
        if (this.lightboxIdx >= 0 && this.lightboxIdx < this.filtered.length) {
          const item = this.filtered[this.lightboxIdx];
          if (!item.isAudio && !item.isVideo && !item.isSvg) {
            this.closeLightbox();
            this.useImageAsVideoSource(item);
          } else {
            toast(ICONS.circle(14) + ' Sélectionnez une image statique (PNG/JPG) pour Image→Vidéo');
          }
        }
      });

      // Remove BG Modal Events
      this._rembgDebounce = null;
      const rmbgModal = $('#media-rembg-modal');
      const rmbgClose = $('#media-rembg-close');
      const rmbgCancel = $('#media-rembg-cancel-btn');
      const rmbgApply = $('#media-rembg-apply-btn');
      const rmbgAlphaCb = $('#rembg-alpha-matting');
      const rmbgAlphaCtrls = $('#rembg-alpha-controls');

      const updatePreview = () => {
        if (this._rembgDebounce) clearTimeout(this._rembgDebounce);
        this._rembgDebounce = setTimeout(() => this._refreshRembgPreview(), 600);
      };

      if (rmbgClose) rmbgClose.addEventListener('click', () => this.closeRembgModal());
      if (rmbgCancel) rmbgCancel.addEventListener('click', () => this.closeRembgModal());
      if (rmbgAlphaCb) rmbgAlphaCb.addEventListener('change', (e) => {
        if (rmbgAlphaCtrls) rmbgAlphaCtrls.style.display = e.target.checked ? 'flex' : 'none';
        updatePreview();
      });

      // Listen for changes on all rembg controls to trigger preview
      ['rembg-model', 'rembg-post-process', 'rembg-fg-thresh', 'rembg-bg-thresh', 'rembg-erode-size'].forEach(id => {
        const el = $(`#${id}`);
        if (el) el.addEventListener('change', updatePreview);
      });

      if (rmbgApply) rmbgApply.addEventListener('click', () => this._applyRembg());
    }

    _updateFormVisibility() {
      const isVideo = this.type === 'video';
      const isAudio = this.type === 'audio';
      const isImage = this.type === 'image';
      const isTemplate = this.type === 'templates';
      const isCard = isTemplate && this.templateSubMode === 'business_card';
      const isCV = isTemplate && this.templateSubMode === 'cv';

      // Image-specific groups
      const imgFmt = $('#media-format-image-group');
      const styleGrp = $('#media-style-group');
      const sizeGrp = $('#media-size-group');
      const countGrp = $('#media-count-group');
      if (imgFmt) imgFmt.style.display = isImage ? '' : 'none';
      if (styleGrp) styleGrp.style.display = isImage ? '' : 'none';
      if (sizeGrp) sizeGrp.style.display = isImage ? '' : 'none';
      if (countGrp) countGrp.style.display = isImage ? '' : 'none';

      // Video-specific groups
      const vidFmt = $('#media-format-video-group');
      const vidMod = $('#media-model-video-group');
      const durationGrp = $('#media-duration-group');
      const vidSizeGrp = $('#media-size-video-group');

      if (vidFmt) vidFmt.style.display = isVideo ? '' : 'none';
      if (vidMod) vidMod.style.display = isVideo ? '' : 'none';
      if (vidSizeGrp) vidSizeGrp.style.display = isVideo ? '' : 'none';
      if (durationGrp) durationGrp.style.display = isVideo ? '' : 'none';

      // Filter video models based on Image-to-Video mode
      const videoModelSel = $('#media-model-video');
      if (videoModelSel && isVideo) {
        const hasRefImage = !!this.referenceImage;
        const i2vModels = ['cogvideox', 'wan22']; // Models that support I2V
        let firstAvailable = null;

        Array.from(videoModelSel.options).forEach(opt => {
          if (hasRefImage) {
            // Hide models that don't support I2V
            if (!i2vModels.includes(opt.value)) {
              opt.style.display = 'none';
              opt.disabled = true;
            } else {
              opt.style.display = '';
              opt.disabled = false;
              if (!firstAvailable) firstAvailable = opt.value;
            }
          } else {
            // Show all models
            opt.style.display = '';
            opt.disabled = false;
          }
        });

        // If current selected is disabled, select the first available
        if (videoModelSel.selectedOptions.length === 0 || videoModelSel.selectedOptions[0].disabled) {
          if (firstAvailable) videoModelSel.value = firstAvailable;
        }
      }

      // Shared prompt & neg prompt — show for image/video only
      const promptGrp = $('#media-prompt')?.closest('.media-form-group');
      const negGrp = $('#media-neg-prompt')?.closest('.media-form-group');
      if (promptGrp) promptGrp.style.display = (isAudio || isTemplate) ? 'none' : '';
      if (negGrp) negGrp.style.display = (isAudio || isTemplate) ? 'none' : '';

      // Upload / reference image — show for image/video only
      const uploadGrp = $('#media-upload-group');
      if (uploadGrp) uploadGrp.style.display = (isAudio || isTemplate) ? 'none' : 'flex';

      // Update upload button label
      const uploadLabel = uploadGrp?.querySelector('#media-upload-btn');
      if (uploadLabel) {
        const iconHtml = uploadLabel.querySelector('.media-icon')?.outerHTML || '';
        uploadLabel.innerHTML = iconHtml + (isVideo ? ' Import Media (Image/Video)' : ' Import Media');
      }

      // Reference image block
      const refGrp = $('#media-ref-group');
      if (refGrp) {
        if (this.referenceImage && !isAudio) {
          refGrp.style.display = '';
          const refLabel = refGrp.querySelector('.media-form-label');
          if (refLabel) refLabel.textContent = isVideo ? 'Source Image (Image→Video)' : 'Reference Image (Variation)';
          const strengthRow = $('#media-ref-strength-row');
          const strengthHint = $('#media-ref-strength-hint');
          if (strengthRow) strengthRow.style.display = isVideo ? 'none' : '';
          if (strengthHint) strengthHint.style.display = isVideo ? 'none' : '';
        } else {
          refGrp.style.display = 'none';
        }
      }

      // Enhance checkbox — hide for audio/templates
      const enhanceGrp = $('#media-enhance')?.closest('.media-form-group');
      if (enhanceGrp) enhanceGrp.style.display = (isAudio || isTemplate) ? 'none' : '';

      // Backend toggle — hide for audio/templates (always local)
      const backendGrp = $('#media-backend-toggle')?.closest('.media-form-group');
      if (backendGrp) backendGrp.style.display = (isAudio || isTemplate) ? 'none' : '';



      // ---- Audio-specific groups ----
      const sub = this.audioSubMode;
      const isTTS = sub === 'tts';
      const isClone = sub === 'voice_clone';
      const isMusic = sub === 'music';
      const isSong = sub === 'song';

      const audioSubGrp = $('#media-audio-submode-group');
      const audioTextGrp = $('#media-audio-text-group');
      const voiceGrp = $('#media-voice-style-group');
      const ttsEngGrp = $('#media-tts-engine-group');
      const audioRefGrp = $('#media-audio-ref-group');
      const genreGrp = $('#media-genre-group');
      const tempoGrp = $('#media-tempo-group');
      const langGrp = $('#media-language-group');
      const audioDurGrp = $('#media-audio-duration-group');
      const audioFmtGrp = $('#media-format-audio-group');

      if (audioSubGrp) audioSubGrp.style.display = isAudio ? '' : 'none';
      if (audioTextGrp) audioTextGrp.style.display = isAudio && (isTTS || isClone || isSong) ? '' : 'none';
      if (voiceGrp) voiceGrp.style.display = isAudio && (isTTS || isSong) ? '' : 'none';
      if (ttsEngGrp) ttsEngGrp.style.display = isAudio && isTTS ? '' : 'none';
      if (audioRefGrp) audioRefGrp.style.display = isAudio && isClone ? '' : 'none';
      if (genreGrp) genreGrp.style.display = isAudio && (isMusic || isSong) ? '' : 'none';
      if (tempoGrp) tempoGrp.style.display = isAudio && (isMusic || isSong) ? '' : 'none';
      if (langGrp) langGrp.style.display = isAudio && (isTTS || isClone || isSong) ? '' : 'none';
      if (audioDurGrp) audioDurGrp.style.display = isAudio ? '' : 'none';
      if (audioFmtGrp) audioFmtGrp.style.display = isAudio ? '' : 'none';

      // Update audio duration slider max based on sub-mode
      const audioDurSlider = $('#media-audio-duration');
      if (audioDurSlider && isAudio) {
        audioDurSlider.max = (isMusic || isSong) ? '120' : '300';
        if (parseInt(audioDurSlider.value) > parseInt(audioDurSlider.max)) {
          audioDurSlider.value = audioDurSlider.max;
          $('#media-audio-duration-value').textContent = audioDurSlider.value + 's';
        }
      }

      // Update text placeholder based on sub-mode
      const audioText = $('#media-audio-text');
      if (audioText && isAudio) {
        if (isTTS) audioText.placeholder = 'Entrez le texte à convertir en parole...';
        else if (isClone) audioText.placeholder = 'Texte à dire avec la voix clonée...';
        else if (isSong) audioText.placeholder = 'Paroles ou thème de la chanson...';
      }
    }

    setReferenceImage(item) {
      if (item.format === 'mp4' || item.format === 'gif' || item.format === 'svg') {
        toast(ICONS.circle(14) + ' ️ Please select a raster image (PNG/JPG) for variation');
        return;
      }
      this.referenceImage = item.filename;
      const refGrp = $('#media-ref-group');
      const preview = $('#media-ref-preview');
      if (refGrp && preview) {
        preview.src = item.url;
        refGrp.style.display = '';
        toast(ICONS.circle(14) + ' Reference image loaded');
      }
      this._updateFormVisibility();
      this.closeLightbox();
    }

    clearReferenceImage() {
      this.referenceImage = null;
      const refGrp = $('#media-ref-group');
      if (refGrp) refGrp.style.display = 'none';
      this._updateFormVisibility();
    }


    toggle(on) {
      this.active = on;
      const mediaLayout = $('#media-layout');
      if (on) {
        mediaLayout.classList.add('active');
        this.loadGallery();
      } else {
        mediaLayout.classList.remove('active');
      }
    }

    async loadGallery() {
      try {
        const r = await fetch('/image/gallery', { cache: 'no-store' });
        const d = await r.json();
        this.items = (d.images || []).map(img => ({
          filename: img.filename,
          format: img.format,
          prompt: img.prompt || '',
          url: `/data/images/${img.filename}`,
          isVideo: ['gif', 'mp4'].includes(img.format),
          isSvg: img.format === 'svg',
          isAudio: false,
        }));

        // Also fetch audio files
        try {
          const ar = await fetch('/audio/gallery', { cache: 'no-store' });
          const ad = await ar.json();
          const audioItems = (ad.audio_files || []).map(af => ({
            filename: af.filename,
            format: af.format,
            prompt: af.prompt || '',
            url: `/data/audio/${af.filename}`,
            isVideo: false,
            isSvg: false,
            isAudio: true,
            mode: af.mode || 'unknown',
            duration: af.duration || 0,
          }));
          this.items = [...this.items, ...audioItems];
        } catch (e) { /* audio gallery optional */ }

        this._applyFilter();
        this.renderGallery();
      } catch (e) {
        console.error('Gallery load failed:', e);
        toast(ICONS.x(14) + ' Failed to load gallery');
      }
    }

    _applyFilter() {
      if (this.filter === 'all') {
        this.filtered = [...this.items];
      } else if (this.filter === 'image') {
        this.filtered = this.items.filter(i => !i.isVideo && !i.isSvg && !i.isAudio);
      } else if (this.filter === 'video') {
        this.filtered = this.items.filter(i => i.isVideo);
      } else if (this.filter === 'svg') {
        this.filtered = this.items.filter(i => i.isSvg);
      } else if (this.filter === 'audio') {
        this.filtered = this.items.filter(i => i.isAudio);
      } else if (this.filter === 'templates') {
        this.filtered = this.items.filter(i => i.filename.startsWith('card_') || i.filename.startsWith('cv_'));
      }
    }

    renderGallery() {
      const container = $('#media-gallery');
      if (!container) return;
      container.innerHTML = '';
      container.classList.remove('empty-state');

      // Update count
      const countEl = $('#media-count');
      if (countEl) countEl.textContent = `${this.filtered.length} item${this.filtered.length !== 1 ? 's' : ''}`;

      if (!this.filtered.length) {
        container.classList.add('empty-state');
        container.innerHTML = `
          <div class="media-empty">
            <div class="media-empty-icon">${window.icon ? window.icon('palette', 32) : ''}</div>
            <h3>No media yet</h3>
            <p>Use the sidebar to generate images and videos. They will appear here in your gallery.</p>
          </div>`;
        return;
      }

      const inner = el('div', { class: 'media-gallery-inner' });

      this.filtered.forEach((item, idx) => {
        const card = el('div', {
          class: 'media-card' + (this.selected.has(item.filename) ? ' selected' : ''),
          'data-filename': item.filename,
        });

        // Extract style from prompt if present
        let displayPrompt = item.prompt || '';
        let styleBadgeHTML = '';
        const styleMatch = displayPrompt.match(/^\[(.*?)\]\s+(.*)/s);
        if (styleMatch) {
          const styleName = styleMatch[1];
          displayPrompt = styleMatch[2];
          styleBadgeHTML = `<span class="badge" style="background:var(--accent);color:white;font-size:10px;margin-right:6px;padding:2px 6px;border-radius:4px;white-space:nowrap;display:inline-block;">${styleName}</span>`;
        }

        // Content (image, video, or audio)
        if (item.isAudio) {
          card.classList.add('media-card-audio');

          // Determine mode label for badge
          let modeLabel = 'Audio';
          let modeBadgeClass = 'audio-mode-default';
          if (item.mode === 'tts') { modeLabel = 'TTS'; modeBadgeClass = 'audio-mode-tts'; }
          else if (item.mode === 'voice_clone') { modeLabel = 'Clone'; modeBadgeClass = 'audio-mode-clone'; }
          else if (item.mode === 'song') { modeLabel = 'Song'; modeBadgeClass = 'audio-mode-song'; }
          else if (item.mode === 'music') { modeLabel = 'Music'; modeBadgeClass = 'audio-mode-music'; }

          let promptHtml = '';
          if (displayPrompt) {
            promptHtml = `<div class="media-audio-prompt">${styleBadgeHTML}${escHtml(displayPrompt)}</div>`;
          }

          card.innerHTML += `
            <div class="media-audio-header">
              <div class="media-audio-badge-row">
                <span class="media-audio-format-badge ${item.format}">${item.format.toUpperCase()}</span>
                <span class="media-audio-mode-badge ${modeBadgeClass}">${modeLabel}</span>
              </div>
              ${item.duration ? `<span class="media-audio-duration-badge">${Math.round(item.duration)}s</span>` : `<span class="media-audio-duration-badge dyn-duration">--s</span>`}
            </div>
            <div class="media-audio-card-inner">
              <div class="media-audio-visual">
                <div class="media-audio-icon-wrap">${window.icon ? window.icon('music', 28) : '🎵'}</div>
                <button class="media-audio-play-btn" title="Play/Pause">${window.icon ? window.icon('play', 20) : '▶'}</button>
              </div>
              <div class="media-audio-info">
                <div class="media-audio-name" title="${escHtml(item.filename)}">${escHtml(item.filename)}</div>
                ${promptHtml}
              </div>
            </div>
            <audio class="media-audio-el" src="${item.url}" preload="metadata"></audio>`;
          const playBtn = card.querySelector('.media-audio-play-btn');
          const audioEl = card.querySelector('.media-audio-el');
          const dynDur = card.querySelector('.dyn-duration');
          if (audioEl) {
            if (dynDur) {
              audioEl.addEventListener('loadedmetadata', () => {
                if (audioEl.duration && audioEl.duration !== Infinity) {
                  dynDur.textContent = Math.round(audioEl.duration) + 's';
                  dynDur.classList.remove('dyn-duration');
                }
              });
            }
          }
          if (playBtn && audioEl) {
            playBtn.addEventListener('click', (e) => {
              e.stopPropagation();
              if (audioEl.paused) {
                // Stop all other playing audio
                $$('.media-audio-el').forEach(a => { if (a !== audioEl) { a.pause(); a.currentTime = 0; } });
                $$('.media-audio-play-btn').forEach(b => {
                  b.innerHTML = window.icon ? window.icon('play', 20) : '▶';
                  b.classList.remove('playing');
                });
                audioEl.play();
                playBtn.innerHTML = ICONS.pause ? ICONS.pause(20) : '⏸';
                playBtn.classList.add('playing');
              } else {
                audioEl.pause();
                playBtn.innerHTML = window.icon ? window.icon('play', 20) : '▶';
                playBtn.classList.remove('playing');
              }
            });
            audioEl.addEventListener('ended', () => {
              playBtn.innerHTML = window.icon ? window.icon('play', 20) : '▶';
              playBtn.classList.remove('playing');
            });
          }
        } else if (item.isVideo && item.format === 'mp4') {
          const vid = el('video', { src: item.url, muted: 'true', loop: 'true', preload: 'metadata' });
          vid.addEventListener('mouseenter', () => vid.play());
          vid.addEventListener('mouseleave', () => { vid.pause(); vid.currentTime = 0; });
          card.appendChild(vid);
          // Play icon
          card.insertAdjacentHTML('beforeend', `<div class="media-card-play"><div class="media-card-play-icon">${window.icon ? window.icon('play', 24) : '►'}</div></div>`);
        } else if (item.isVideo && item.format === 'gif') {
          card.appendChild(el('img', { class: 'media-card-img', src: item.url, alt: item.filename, loading: 'lazy' }));
        } else {
          const img = el('img', { class: 'media-card-img', src: item.url, alt: item.filename, loading: 'lazy' });
          if (item.isSvg || item.format === 'transparent_png') {
            img.classList.add('is-transparent');
          }
          card.appendChild(img);
        }

        // Badge for special formats (Images/Video only — audio has its own badges)
        if (!item.isAudio && ['gif', 'mp4', 'svg'].includes(item.format)) {
          card.insertAdjacentHTML('beforeend', `<div class="media-card-badge ${item.format}">${item.format.toUpperCase()}</div>`);
        }

        // Select checkbox
        const selectDiv = el('div', {
          class: 'media-card-select',
          html: this.selected.has(item.filename) ? ICONS.check(14) : '',
          onclick: (e) => { e.stopPropagation(); this.toggleSelect(item.filename); },
        });
        card.appendChild(selectDiv);

        // Hover overlay (ONLY for images/video)
        if (!item.isAudio) {
          const overlay = el('div', { class: 'media-card-overlay' });
          overlay.innerHTML = `
            <div class="media-card-name" title="${escHtml(item.prompt)}">${escHtml(item.filename)}</div>
            <div class="media-card-meta">${item.format.toUpperCase()}</div>
            <div class="media-card-prompt" style="font-size: 0.7em; margin-top: 5px; opacity: 0.8; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis;" title="${escHtml(item.prompt)}">${styleBadgeHTML}${escHtml(displayPrompt)}</div>`;
          card.appendChild(overlay);
        }

        // Action buttons — determine if image is static (can be converted to video)
        const isStaticImage = !item.isAudio && !item.isVideo && !item.isSvg;
        const actions = el('div', { class: 'media-card-actions' });
        actions.innerHTML = `
          ${isStaticImage ? `<button class="media-card-action-btn" title="Create Variation (Image-to-Image)" data-action="variant">${window.icon ? window.icon('wand', 16) : ''}</button>` : ''}
          ${isStaticImage ? `<button class="media-card-action-btn i2v" title="Générer une vidéo depuis cette image" data-action="i2v">${window.icon ? window.icon('video', 16) : '🎬'}</button>` : ''}
          <button class="media-card-action-btn" title="Download" data-action="download">${window.icon ? window.icon('download', 16) : ''}</button>
          <button class="media-card-action-btn delete" title="Delete" data-action="delete">${window.icon ? window.icon('trash', 16) : ''}</button>`;
        actions.addEventListener('click', e => {
          e.stopPropagation();
          const btn = e.target.closest('[data-action]');
          if (!btn) return;
          if (btn.dataset.action === 'variant') this.setReferenceImage(item);
          if (btn.dataset.action === 'i2v') this.useImageAsVideoSource(item);
          if (btn.dataset.action === 'download') this.downloadFile(item.filename, item.url);
          if (btn.dataset.action === 'delete') {
            if (this.selected.has(item.filename) && this.selected.size > 1) {
              this.deleteSelected();
            } else {
              this.deleteFile(item.filename);
            }
          }
        });
        card.appendChild(actions);

        // Click → lightbox
        card.addEventListener('click', () => this.openLightbox(idx));

        inner.appendChild(card);
      });
      container.appendChild(inner);

      this._updateToolbar();
    }

    toggleSelect(filename) {
      if (this.selected.has(filename)) this.selected.delete(filename);
      else this.selected.add(filename);
      // Update card UI
      const cards = $$('.media-card');
      cards.forEach(c => {
        const fn = c.dataset.filename;
        c.classList.toggle('selected', this.selected.has(fn));
        const sel = c.querySelector('.media-card-select');
        if (sel) sel.innerHTML = this.selected.has(fn) ? ICONS.check(14) : '';
      });
      this._updateToolbar();
    }

    toggleSelectAll() {
      if (this.selected.size === this.filtered.length) {
        // Deselect all
        this.selected.clear();
      } else {
        // Select all
        this.filtered.forEach(i => this.selected.add(i.filename));
      }
      this.renderGallery();
    }

    _updateToolbar() {
      const cnt = this.selected.size;
      const delBtn = $('#media-delete-selected');
      const cntBadge = $('#media-selected-count');
      const selAllBtn = $('#media-select-all');
      if (delBtn) delBtn.style.display = cnt > 0 ? '' : 'none';
      if (cntBadge) cntBadge.textContent = cnt;
      if (selAllBtn) selAllBtn.innerHTML = cnt === this.filtered.length && cnt > 0 ? ICONS.square(14) + ' Deselect' : ICONS.checkSquare(14) + ' Select All';
    }

    async generate() {
      if (this.generating) return;
      // Delegate to template generator
      if (this.type === 'templates') { return this.generateTemplate(); }
      const prompt = $('#media-prompt');
      if (this.type === 'audio') {
        const audioText = ($('#media-audio-text') || {}).value || '';
        if (this.audioSubMode !== 'music' && !audioText.trim()) { toast(ICONS.circle(14) + ' Veuillez entrer du texte'); return; }
      } else if (!prompt || !prompt.value.trim()) { toast(ICONS.circle(14) + ' ️ Please enter a prompt'); return; }

      this.generating = true;
      const genBtn = $('#media-generate-btn');
      const cancelBtn = $('#media-cancel-btn');
      const progress = $('#media-progress');
      const progressBar = $('#media-progress-bar');
      if (genBtn) genBtn.classList.add('loading');
      if (genBtn) genBtn.disabled = true;

      this._abortController = new AbortController();
      if (cancelBtn) {
        cancelBtn.style.display = 'flex';
        cancelBtn.onclick = () => {
          if (this._abortController) {
            this._abortController.abort();
            this._abortController = null;
          }
        };
      }

      const negPrompt = ($('#media-neg-prompt') || {}).value || '';
      const enhance = $('#media-enhance') ? $('#media-enhance').checked : true;
      const numImages = this.type === 'image'
        ? Math.max(1, Math.min(50, parseInt(($('#media-num-images') || {}).value) || 1))
        : 1;

      // Show progress
      if (progress) {
        progress.classList.add('active');
        if (numImages <= 1) {
          progress.classList.add('indeterminate');
        } else {
          progress.classList.remove('indeterminate');
          if (progressBar) progressBar.style.width = '0%';
        }
      }

      let successCount = 0;
      let lastError = '';

      try {
        // --- Model Download Check ---
        const dlMsg = $('#media-download-msg');
        if (this.backend !== 'api') {
          try {
            const style = ($('#media-style') || {}).value || 'none';
            const videoModel = ($('#media-model-video') || {}).value || 'cogvideox';
            const checkResp = await fetch(`/image/check-model?type=${this.type}&style=${style}&video_model=${videoModel}`);
            if (checkResp.ok) {
              const checkData = await checkResp.json();
              if (!checkData.downloaded) {
                if (dlMsg) {
                  dlMsg.style.display = 'block';
                  dlMsg.innerHTML = ICONS.hourglass(14) + ' Initializing model download...';
                }
                toast('⏳ First time using this AI. Downloading model weights (~5-10GB), this may take a few minutes...', 8000);

                this._hfDlPoll = setInterval(async () => {
                  try {
                    const statusResp = await fetch('/image/download-status');
                    if (statusResp.ok) {
                      const sd = await statusResp.json();
                      if (sd.active && dlMsg) {
                        dlMsg.innerHTML = ICONS.hourglass(14) + ` Downloading ${sd.repo}... (${Math.round(sd.progress)}%)`;
                      }
                    }
                  } catch (e) { }
                }, 2000);
              }
            }
          } catch (e) { /* ignore check error */ }
        }

        let stylesToRun = ['none'];
        const baseStyle = ($('#media-style') || {}).value || 'none';
        let isAllModels = false;

        if (this.type === 'image') {
          if (baseStyle === 'all_models') {
            isAllModels = true;
            const selectEl = document.getElementById('media-style');
            if (selectEl) {
              stylesToRun = Array.from(selectEl.options)
                .map(o => o.value)
                .filter(v => v !== 'all_models' && v !== 'none');
            }
          } else {
            stylesToRun = [baseStyle];
          }
        }

        let totalRuns = (this.type === 'image' && isAllModels) ? stylesToRun.length : numImages;

        for (let i = 0; i < totalRuns; i++) {
          // Update progress for multi-image
          if (totalRuns > 1) {
            const pct = Math.round(((i) / totalRuns) * 100);
            if (progressBar) progressBar.style.width = pct + '%';
            toast(`${ICONS.palette(14)} Generating ${i + 1}/${totalRuns}...`);
          }

          let resp;
          let result = {};
          if (this.type === 'image') {
            const format = ($('#media-format-image') || {}).value || 'auto';
            const currentStyle = isAllModels ? stylesToRun[i] : baseStyle;
            const sizeVal = ($('#media-size') || {}).value || '1024x1024';
            const [width, height] = sizeVal.split('x').map(Number);

            resp = await fetch('/image/generate', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              signal: this._abortController ? this._abortController.signal : undefined,
              body: JSON.stringify({
                prompt: prompt.value.trim(),
                negative_prompt: negPrompt,
                format, style: currentStyle, enhance_prompt: enhance,
                backend: this.backend,
                reference_image: this.referenceImage,
                strength: parseFloat(($('#media-ref-strength') || {}).value) || 0.5,
                width: width || 1024,
                height: height || 1024,
                stream: true // Enable SSE stream preview
              }),
            });

            if (resp.headers.get('content-type')?.includes('text/event-stream')) {
              const reader = resp.body.getReader();
              const decoder = new TextDecoder();
              let buffer = '';
              while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                let lines = buffer.split('\n');
                buffer = lines.pop(); // keep incomplete line
                for (let line of lines) {
                  if (line.startsWith('data: ')) {
                    try {
                      const d = JSON.parse(line.substring(6));
                      if (d.status === 'generating') {
                        const prevCont = document.getElementById('media-stream-preview-container');
                        const prevImg = document.getElementById('media-stream-preview');
                        if (prevCont && prevImg) {
                          prevCont.style.display = 'block';
                          prevImg.src = 'data:image/jpeg;base64,' + d.base64;
                        }
                        if (d.progress !== undefined && genBtn) {
                          const lbl = genBtn.querySelector('.gen-label');
                          const pct = d.progress <= 1 ? Math.round(d.progress * 100) : Math.round(d.progress);
                          if (lbl) lbl.innerHTML = `<span class="media-icon" data-icon="sparkles"></span> Génération... ${pct}%`;
                        }
                      } else if (d.status === 'done') {
                        result = d.result;
                      } else if (d.status === 'error') {
                        result = { error: d.message };
                      }
                    } catch (e) { }
                  }
                }
              }
            } else {
              result = await resp.json();
            }
          } else if (this.type === 'video') {
            const format = ($('#media-format-video') || {}).value || 'gif';
            const videoModel = ($('#media-model-video') || {}).value || 'cogvideox';
            const duration = parseFloat(($('#media-duration') || {}).value) || 2.0;
            const videoSize = ($('#media-size-video') || {}).value || '704x480';
            const [vidW, vidH] = videoSize.split('x').map(Number);

            // Warn if reference image is set but model doesn't support I2V
            const i2vModels = ['cogvideox', 'wan22'];
            if (this.referenceImage && !i2vModels.includes(videoModel)) {
              toast(`⚠️ Le modèle ${videoModel} ne supporte pas Image→Vidéo. L'image sera ignorée. Utilisez CogVideoX 5B ou Wan 14B.`, 6000);
            }

            resp = await fetch('/image/animate', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              signal: this._abortController ? this._abortController.signal : undefined,
              body: JSON.stringify({
                prompt: prompt.value.trim(),
                negative_prompt: negPrompt,
                format, duration,
                width: vidW,
                height: vidH,
                video_model: videoModel,
                enhance_prompt: enhance,
                backend: this.backend,
                reference_image: this.referenceImage,
              }),
            });
            result = await resp.json();
          } else if (this.type === 'audio') {
            const audioText = ($('#media-audio-text') || {}).value || '';
            const audioFmt = ($('#media-format-audio') || {}).value || 'wav';
            const voiceStyle = ($('#media-voice-style') || {}).value || 'female_soft';
            const ttsEngine = ($('#media-tts-engine') || {}).value || 'speecht5';
            const genre = ($('#media-genre') || {}).value || '';
            const tempoBpm = parseInt(($('#media-tempo') || {}).value) || 120;
            const audioDur = parseFloat(($('#media-audio-duration') || {}).value) || 30;
            const language = ($('#media-language') || {}).value || 'auto';
            resp = await fetch('/audio/generate', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              signal: this._abortController ? this._abortController.signal : undefined,
              body: JSON.stringify({
                mode: this.audioSubMode,
                text: audioText,
                prompt: audioText,
                voice_style: voiceStyle,
                tts_engine: ttsEngine,
                reference_audio: this.referenceAudio,
                genre, tempo_bpm: tempoBpm,
                duration: audioDur,
                format: audioFmt,
                language,
                enhance_prompt: enhance,
              }),
            });
            result = await resp.json();
          }

          if (result && (result.error || result.detail)) {
            lastError = result.error || result.detail;
          } else if (result && result.status === 'ok') {
            successCount++;
            if (result.prompt) {
              if (this.type === 'audio') {
                const a = document.getElementById("media-audio-text");
                if (a && a.value !== result.prompt) a.value = result.prompt;
              } else if (prompt && prompt.value !== result.prompt) {
                prompt.value = result.prompt;
              }
            }
          }
        }

        // Final progress
        if (progressBar) progressBar.style.width = '100%';

        // Always reload gallery after generation (even on partial success)
        await this.loadGallery();

        // Scroll gallery to top to show the new image
        const galleryEl = $('#media-gallery');
        if (galleryEl) galleryEl.scrollTop = 0;
        const mediaMain = document.querySelector('.media-main');
        if (mediaMain) mediaMain.scrollTop = 0;

        if (successCount > 0) {
          toast(`${ICONS.check(14)} Generated ${successCount}/${totalRuns} image${successCount !== 1 ? 's' : ''}`);
        }
        if (lastError && successCount < totalRuns) {
          toast(' ' + lastError);
        }
      } catch (e) {
        if (e.name === 'AbortError') {
          toast((window.icon ? window.icon('x', 14) : '❌') + ' Génération annulée');
        } else {
          toast(' Generation failed: ' + e.message);
        }
      } finally {
        if (this._hfDlPoll) {
          clearInterval(this._hfDlPoll);
          this._hfDlPoll = null;
        }
        this.generating = false;
        this._abortController = null;
        const cancelBtn = $('#media-cancel-btn');
        if (cancelBtn) cancelBtn.style.display = 'none';
        if (genBtn) {
          genBtn.classList.remove('loading');
          genBtn.disabled = false;
          const lbl = genBtn.querySelector('.gen-label');
          if (lbl) lbl.innerHTML = `<span class="media-icon" data-icon="sparkles"></span> Generate`;
        }
        if (progress) progress.classList.remove('active', 'indeterminate');
        if (progressBar) progressBar.style.width = '0%';
        const dlMsg = $('#media-download-msg');
        if (dlMsg) {
          dlMsg.style.display = 'none';
          dlMsg.innerHTML = ICONS.hourglass(14) + ' Downloading model weights (~5-10GB). Please wait, this may take a few minutes...';
        }
        const prevCont = document.getElementById('media-stream-preview-container');
        if (prevCont) {
          prevCont.style.display = 'none';
        }
      }
    }

    async deleteFile(filename) {
      try {
        toast(' Deleting ' + filename + '...');
        const isAudioFile = filename.match(/\.(wav|mp3|ogg)$/i);
        const r = await fetch(isAudioFile ? '/audio/delete' : '/image/delete', {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename }),
        });
        if (!r.ok) throw new Error('Server returned ' + r.status);
        this.selected.delete(filename);
        toast(' Deleted ' + filename);
        await this.loadGallery();
      } catch (e) { toast(' Delete failed: ' + e.message); }
    }

    async deleteSelected() {
      const files = [...this.selected];
      if (!files.length) return;
      try {
        toast(`${ICONS.circle(14)} Deleting ${files.length} file(s)...`);
        // Separate audio and image files
        const audioFiles = files.filter(f => f.match(/\.(wav|mp3|ogg)$/i));
        const imageFiles = files.filter(f => !f.match(/\.(wav|mp3|ogg)$/i));
        let deletedCount = 0;
        // Delete image/video files via batch endpoint
        if (imageFiles.length) {
          const r = await fetch('/image/delete-batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filenames: imageFiles }),
          });
          if (r.ok) {
            const d = await r.json();
            deletedCount += (d.deleted || []).length;
          }
        }
        // Delete audio files individually
        for (const af of audioFiles) {
          try {
            const r = await fetch('/audio/delete', {
              method: 'DELETE',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ filename: af }),
            });
            if (r.ok) deletedCount++;
          } catch (e) { /* continue */ }
        }
        this.selected.clear();
        toast(`${ICONS.circle(14)} Deleted ${deletedCount} file(s)`);
        await this.loadGallery();
      } catch (e) { toast(' Batch delete failed: ' + e.message); }
    }

    async removeBgSelected() {
      const files = [...this.selected].filter(f => {
        const l = f.toLowerCase();
        return !l.endsWith('.gif') && !l.endsWith('.mp4') && !l.endsWith('.webm') && !l.endsWith('.svg') && !l.endsWith('.mp3') && !l.endsWith('.wav');
      });
      if (!files.length) {
        toast(`${ICONS.x(14)} No valid images selected for Remove BG`);
        return;
      }

      if (files.length === 1) {
        this._openRembgModal(files[0]);
      } else {
        try {
          toast(`${ICONS.sparkles(14)} Removing background for ${files.length} file(s)...`);
          const r = await fetch('/image/remove-bg', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filenames: files, settings: {} }),
          });
          if (!r.ok) {
            const err = await r.json();
            throw new Error(err.detail || 'Server returned ' + r.status);
          }
          const d = await r.json();
          this.selected.clear();
          toast(`${ICONS.check(14)} Background removed for ${(d.processed || []).length} file(s)`);
          await this.loadGallery();
        } catch (e) { toast(' Background removal failed: ' + e.message); }
      }
    }

    async makeColoringSelected() {
      const files = [...this.selected].filter(f => {
        const l = f.toLowerCase();
        return !l.endsWith('.gif') && !l.endsWith('.mp4') && !l.endsWith('.webm') && !l.endsWith('.svg') && !l.endsWith('.mp3') && !l.endsWith('.wav');
      });
      if (!files.length) {
        toast(`${ICONS.x(14)} No valid images selected for Crayons`);
        return;
      }
      try {
        toast(`${ICONS.sparkles(14)} Creating coloring pages for ${files.length} file(s)...`);
        for (const file of files) {
          const r = await fetch('/image/make-coloring', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename: file }),
          });
          if (!r.ok) {
            const err = await r.json();
            throw new Error(err.detail || 'Server returned ' + r.status);
          }
        }
        this.selected.clear();
        toast(`${ICONS.check(14)} Coloring pages created!`);
        await this.loadGallery();
      } catch (e) { toast(' Crayons conversion failed: ' + e.message); }
    }

    _openRembgModal(filename) {
      this._currentRembgFile = filename;
      const modal = $('#media-rembg-modal');
      const img = $('#media-rembg-preview-img');

      // Reset preview to original image
      img.src = `/data/images/${filename}`;

      // Reset controls
      const alphaCb = $('#rembg-alpha-matting');
      if (alphaCb) alphaCb.checked = false;
      const alphaCtrls = $('#rembg-alpha-controls');
      if (alphaCtrls) alphaCtrls.style.display = 'none';

      if (modal) modal.classList.add('open');

      // trigger initial preview
      this._refreshRembgPreview();
    }

    closeRembgModal() {
      const modal = $('#media-rembg-modal');
      if (modal) modal.classList.remove('open');
      this._currentRembgFile = null;
      if (this._rembgDebounce) clearTimeout(this._rembgDebounce);
    }

    _getRembgSettings() {
      return {
        model_name: $('#rembg-model')?.value || 'isnet-general-use',
        post_process_mask: $('#rembg-post-process')?.checked || false,
        alpha_matting: $('#rembg-alpha-matting')?.checked || false,
        alpha_matting_foreground_threshold: parseInt($('#rembg-fg-thresh')?.value || 240, 10),
        alpha_matting_background_threshold: parseInt($('#rembg-bg-thresh')?.value || 10, 10),
        alpha_matting_erode_size: parseInt($('#rembg-erode-size')?.value || 10, 10)
      };
    }

    async _refreshRembgPreview() {
      if (!this._currentRembgFile) return;
      const loading = $('#media-rembg-loading');
      if (loading) loading.style.display = 'block';

      try {
        const settings = this._getRembgSettings();
        const r = await fetch('/image/remove-bg-preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename: this._currentRembgFile, settings })
        });

        if (!r.ok) throw new Error('Preview generation failed');
        const data = await r.json();

        const img = $('#media-rembg-preview-img');
        if (img) {
          // Ensure it's a valid base64 src
          img.src = 'data:image/png;base64,' + data.image_base64;
        }
      } catch (e) {
        console.error(e);
        toast(ICONS.x(14) + ' Preview generation failed');
      } finally {
        if (loading) loading.style.display = 'none';
      }
    }

    async _applyRembg() {
      if (!this._currentRembgFile) return;
      const btn = $('#media-rembg-apply-btn');
      const oldText = btn.textContent;
      btn.textContent = 'Saving...';
      btn.disabled = true;

      try {
        const settings = this._getRembgSettings();
        const r = await fetch('/image/remove-bg', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filenames: [this._currentRembgFile], settings }),
        });
        if (!r.ok) {
          const err = await r.json();
          throw new Error(err.detail || 'Server returned ' + r.status);
        }
        const d = await r.json();
        this.selected.clear();
        toast(`${ICONS.check(14)} Background removed!`);
        this.closeRembgModal();
        await this.loadGallery();
      } catch (e) {
        toast(' Background removal failed: ' + e.message);
      } finally {
        btn.textContent = oldText;
        btn.disabled = false;
      }
    }

    async convertVideo(targetFormat) {
      const files = [...this.selected];
      if (files.length === 0) {
        toast((window.icon ? window.icon('circle', 14) : '⚪') + ' Sélectionnez une vidéo ou un GIF à convertir');
        return;
      }
      if (files.length > 1) {
        toast((window.icon ? window.icon('circle', 14) : '⚪') + ' Veuillez sélectionner un seul fichier à convertir');
        return;
      }
      const filename = files[0];
      const isGif = filename.toLowerCase().endsWith('.gif');
      const isMp4 = filename.toLowerCase().endsWith('.mp4');
      const isWebm = filename.toLowerCase().endsWith('.webm');

      if (!isGif && !isMp4 && !isWebm) {
        toast((window.icon ? window.icon('x', 14) : '❌') + " Le fichier sélectionné n'est ni un GIF ni une vidéo");
        return;
      }
      if (filename.toLowerCase().endsWith(`.${targetFormat}`)) {
        toast((window.icon ? window.icon('circle', 14) : '⚪') + ` Le fichier est déjà au format ${targetFormat.toUpperCase()}`);
        return;
      }

      toast((window.icon ? window.icon('hourglass', 14) : '⏳') + ` Conversion de ${filename} en ${targetFormat.toUpperCase()}...`);
      try {
        const r = await fetch('/image/convert-video', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename, target_format: targetFormat })
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || 'Erreur du serveur');

        toast((window.icon ? window.icon('check', 14) : '✅') + ' Conversion réussie !');
        this.selected.clear();
        await this.loadGallery();
      } catch (e) {
        toast((window.icon ? window.icon('x', 14) : '❌') + ' Échec de la conversion : ' + e.message);
      }
    }

    downloadFile(filename, url) {
      const a = document.createElement('a');
      a.href = url; a.download = filename; a.click();
    }

    async downloadZip() {
      const files = this.selected.size > 0
        ? [...this.selected].join(',')
        : '';  // empty = all
      const url = '/image/download-zip' + (files ? '?files=' + encodeURIComponent(files) : '');
      toast(ICONS.box(14) + ' Preparing ZIP...');
      try {
        const r = await fetch(url);
        if (!r.ok) { toast(ICONS.x(14) + ' ZIP download failed'); return; }
        const blob = await r.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = r.headers.get('Content-Disposition')?.split('filename="')[1]?.replace('"', '') || 'gallery.zip';
        a.click(); URL.revokeObjectURL(a.href);
        toast(ICONS.check(14) + ' ZIP downloaded!');
      } catch (e) { toast(' ZIP failed: ' + e.message); }
    }

    // ---- Lightbox ----
    openLightbox(idx) {
      this.lightboxIdx = idx;
      const item = this.filtered[idx];
      if (!item) return;

      const lb = $('#media-lightbox');
      const content = $('#media-lb-content');
      const info = $('#media-lb-info');
      if (!lb || !content) return;

      content.innerHTML = '';
      // Show/hide I2V button depending on item type (static images only)
      const lbI2VBtn = $('#media-lb-i2v');
      if (lbI2VBtn) {
        const canI2V = !item.isAudio && !item.isVideo && !item.isSvg;
        lbI2VBtn.style.display = canI2V ? '' : 'none';
      }
      if (item.isAudio) {
        content.innerHTML = `
          <div class="media-lightbox-audio">
            <div class="media-lb-audio-icon">${window.icon ? window.icon('music', 64) : '🎵'}</div>
            <div class="media-lb-audio-name">${escHtml(item.filename)}</div>
            <audio controls autoplay src="${item.url}" style="width:100%;max-width:500px;margin-top:16px;"></audio>
          </div>`;
      } else if (item.isVideo && item.format === 'mp4') {
        const vid = el('video', { src: item.url, controls: 'true', autoplay: 'true', loop: 'true' });
        content.appendChild(vid);
      } else {
        const img = el('img', { src: item.url, alt: item.filename });
        if (item.isSvg || item.format === 'transparent_png' || item.format === 'svg') {
          img.classList.add('is-transparent');
        }
        content.appendChild(img);
      }

      if (info) {
        let displayPrompt = item.prompt;
        let styleBadgeHTML = '';
        const styleMatch = displayPrompt.match(/^\[(.*?)\]\s+(.*)/s);
        if (styleMatch) {
          const styleName = styleMatch[1];
          displayPrompt = styleMatch[2];
          styleBadgeHTML = `<span class="badge" style="background:var(--accent);color:white;font-size:0.85em;margin-right:8px;padding:3px 8px;border-radius:4px">${styleName}</span>`;
        }
        info.innerHTML = `<strong>${item.filename}</strong> — ${item.format.toUpperCase()} — ${idx + 1}/${this.filtered.length}<br><div style="font-size: 0.9em; opacity: 0.8; word-wrap: break-word; cursor: pointer; margin-top: 8px;" title="Click to reuse prompt and style" onclick="window.mediaStudio && window.mediaStudio.reusePrompt(${idx})">${styleBadgeHTML}${escHtml(displayPrompt)}</div>`;
      }

      lb.classList.add('open');
    }

    closeLightbox() {
      const lb = $('#media-lightbox');
      if (lb) lb.classList.remove('open');
      // Stop any playing video
      const vid = lb?.querySelector('video');
      if (vid) vid.pause();
      this.lightboxIdx = -1;
    }

    reusePrompt(idx) {
      const item = this.filtered[idx];
      if (!item) return;

      this.closeLightbox();

      let style = 'none';
      let text = item.prompt;

      const match = text.match(/^\[(.*?)\]\s+(.*)/s);
      if (match) {
        style = match[1];
        text = match[2];
      }

      const promptEl = $('#media-prompt');
      if (promptEl) promptEl.value = text;

      if (item.isVideo) {
        const typeBtn = document.querySelector('.media-type-btn[data-type="video"]');
        if (typeBtn) typeBtn.click();

        const styleEl = $('#media-model-video');
        if (styleEl && Array.from(styleEl.options).some(o => o.value === style)) {
          styleEl.value = style;
        }
      } else {
        const typeBtn = document.querySelector('.media-type-btn[data-type="image"]');
        if (typeBtn) typeBtn.click();

        const styleEl = $('#media-style');
        if (styleEl && Array.from(styleEl.options).some(o => o.value === style)) {
          styleEl.value = style;
        }
      }

      toast(ICONS.sparkles(14) + ' Prompt and style copied');
    }

    lightboxNav(dir) {
      if (this.lightboxIdx < 0) return;
      let newIdx = this.lightboxIdx + dir;
      if (newIdx < 0) newIdx = this.filtered.length - 1;
      if (newIdx >= this.filtered.length) newIdx = 0;
      this.openLightbox(newIdx);
    }

    lightboxDownload() {
      const item = this.filtered[this.lightboxIdx];
      if (item) this.downloadFile(item.filename, item.url);
    }

    async lightboxDelete() {
      const item = this.filtered[this.lightboxIdx];
      if (!item) return;
      this.closeLightbox();
      await this.deleteFile(item.filename);
    }
    // ---- Image-to-Video (one click: import image as video source) ----

    useImageAsVideoSource(item) {
      // Guard: only static raster images
      if (item.isAudio || item.isVideo || item.isSvg) {
        toast(ICONS.circle(14) + ' Sélectionnez une image statique (PNG/JPG) pour Img→Vidéo');
        return;
      }

      // 1. Set as reference image
      this.referenceImage = item.filename;
      const refPreview = $('#media-ref-preview');
      if (refPreview) refPreview.src = item.url;

      // 2. Switch type to video
      this.type = 'video';
      $$('#media-type-toggle .media-type-btn').forEach(b => b.classList.remove('active'));
      const vidBtn = document.querySelector('#media-type-toggle .media-type-btn[data-type="video"]');
      if (vidBtn) vidBtn.classList.add('active');
      this._updateFormVisibility();

      // 3. Auto-select an I2V-compatible model
      const i2vModels = ['cogvideox', 'wan22'];
      const videoModelSel = $('#media-model-video');
      if (videoModelSel && !i2vModels.includes(videoModelSel.value)) {
        videoModelSel.value = 'cogvideox'; // CogVideoX 5B is the most accessible I2V model
      }

      // 4. Pre-fill video prompt from image prompt
      const promptEl = $('#media-prompt');
      if (promptEl && item.prompt) {
        let txt = item.prompt;
        const m = txt.match(/^\[.*?\]\s+(.*)/s);
        if (m) txt = m[1];
        if (!promptEl.value || promptEl.value === txt) promptEl.value = txt;
      }

      // 5. Scroll sidebar into view
      const sidebar = document.querySelector('.media-sidebar');
      if (sidebar) sidebar.scrollTop = 0;

      toast(`${ICONS.sparkles(14)} Image importée comme source vidéo (${videoModelSel?.options[videoModelSel?.selectedIndex]?.text || 'CogVideoX'}) — cliquez Générer`);
    }
  }

  // ==========================================
  // Presentation Studio Mode
  // ==========================================
  class PresentationStudio {
    constructor() {
      this.pages = [{ elements: [] }];
      this.currentPage = 0;
      this.selectedElement = null;
      this.dragItem = null;
      this.resizeItem = null;
      this.dragStartX = 0;
      this.dragStartY = 0;

      this.canvasW = 960;
      this.canvasH = 540;
      this.presId = localStorage.getItem('pt-last-id') || null;

      this.ctxMenuEl = null;

      // Internal clipboard for copy/paste of elements
      this._clipboard = null;
      this._pasteOffset = 0;

      // Snap-to-grid
      this.snapGrid = 20;
      this.showGrid = true;

      // Undo/Redo history
      this.history = [];
      this.historyIndex = -1;
      this.isUndoRedo = false;

      this.initEvents();
      this.loadRecent();
      this.loadTemplates();
    }

    async loadRecent() {
      if (!this.presId) {
        this.renderPages();
        this.renderCanvas();
        return;
      }
      try {
        const res = await fetch(`/presentation/load/${this.presId}`);
        if (res.ok) {
          const data = await res.json();
          this.pages = data.pages || [{ elements: [] }];
          this.canvasW = data.canvas_width || 960;
          this.canvasH = data.canvas_height || 540;
          this.title = data.title || '';
          if ($('#pt-pres-title')) $('#pt-pres-title').value = this.title || "My Presentation";

          // Try to sync format selector based on dims
          const sel = $('#pt-format-select');
          if (sel) {
            if (this.canvasW === 960 && this.canvasH === 540) sel.value = '16:9';
            else if (this.canvasW === 960 && this.canvasH === 720) sel.value = '4:3';
            else if (this.canvasW === 540 && this.canvasH === 960) sel.value = 'portrait';
            else if (this.canvasW === 794 && this.canvasH === 1123) sel.value = 'A4';
            else if (this.canvasW === 1080 && this.canvasH === 1080) sel.value = 'IG';
            else if (this.canvasW === 1280 && this.canvasH === 720) sel.value = 'YT';
            else if (this.canvasW === 638 && this.canvasH === 368) sel.value = 'card';
          }
        }
      } catch (e) {
        console.warn("Could not load recent presentation", e);
      }
      this.currentPage = 0;
      this.renderPages();
      this.renderCanvas();
      this.updateCanvasZoom();

      // Initial state save
      this.saveState();
    }

    toggle(show) {
      const panel = $('#presentation-layout');
      if (!panel) return;
      if (show) {
        panel.style.display = 'flex';
        this.renderCanvas();
        this.updateCanvasZoom();
      } else {
        panel.style.display = 'none';
      }
    }

    initEvents() {
      $('#pt-shapes-toggle')?.addEventListener('click', () => {
        const grid = $('#pt-shapes-grid');
        const chevron = $('#pt-shapes-chevron');
        if (grid && chevron) {
          grid.classList.toggle('collapsed');
          chevron.style.transform = grid.classList.contains('collapsed') ? 'rotate(0deg)' : 'rotate(180deg)';
        }
      });
      $('#pt-add-text')?.addEventListener('click', () => this.addElement('text', 'Double click to edit'));
      $('#pt-add-table')?.addEventListener('click', () => this.addElement('table', '| Header 1 | Header 2 |\n|---|---|\n| Data 1 | Data 2 |'));
      $('#pt-add-image')?.addEventListener('click', () => {
        $('#presentation-gallery-browser').style.display = 'flex';
        const lb = $('#presentation-library-browser');
        if (lb) lb.style.display = 'none';
        this.openGallery();
      });
      $('#pt-templates-toggle')?.addEventListener('click', () => {
        const grid = $('#pt-templates-grid');
        const chevron = $('#pt-templates-toggle .ic');
        if (grid && chevron) {
          grid.classList.toggle('collapsed');
          chevron.style.transform = grid.classList.contains('collapsed') ? 'rotate(0deg)' : 'rotate(180deg)';
        }
      });
      $('#pt-docgen-toggle')?.addEventListener('click', () => {
        const panel = $('#pt-docgen-panel');
        const chevron = $('#pt-docgen-toggle .ic');
        if (panel && chevron) {
          const isHidden = panel.style.display === 'none';
          panel.style.display = isHidden ? 'flex' : 'none';
          chevron.style.transform = isHidden ? 'rotate(0deg)' : 'rotate(180deg)';
        }
      });

      // Template sub-mode toggle
      $$('#pt-tpl-submode-toggle .media-type-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          $$('#pt-tpl-submode-toggle .media-type-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          this.templateSubMode = btn.dataset.tplmode;
          this._updateDocgenVisibility();
        });
      });
      this.templateSubMode = 'business_card';

      const liFetchBtn = $('#pt-tpl-linkedin-fetch');
      if (liFetchBtn) liFetchBtn.addEventListener('click', () => this.fetchLinkedInProfile());

      const docgenBtn = $('#pt-tpl-generate-btn');
      if (docgenBtn) docgenBtn.addEventListener('click', () => this.generateTemplate());
      $('#pt-show-library')?.addEventListener('click', () => {
        $('#presentation-library-browser').style.display = 'flex';
        const gb = $('#presentation-gallery-browser');
        if (gb) gb.style.display = 'none';
        this.loadLibrary();
      });
      $('#pt-library-close')?.addEventListener('click', () => {
        $('#presentation-library-browser').style.display = 'none';
      });
      $('#pt-library-search')?.addEventListener('input', (e) => {
        this.filterLibrary(e.target.value);
      });
      $('#pt-add-rect')?.addEventListener('click', () => this.addElement('shape', 'rect'));
      $('#pt-add-rounded-rect')?.addEventListener('click', () => this.addElement('shape', 'rounded-rect'));
      $('#pt-add-circle')?.addEventListener('click', () => this.addElement('shape', 'circle'));
      $('#pt-add-triangle')?.addEventListener('click', () => this.addElement('shape', 'triangle'));
      $('#pt-add-diamond')?.addEventListener('click', () => this.addElement('shape', 'diamond'));
      $('#pt-add-pentagon')?.addEventListener('click', () => this.addElement('shape', 'pentagon'));
      $('#pt-add-hexagon')?.addEventListener('click', () => this.addElement('shape', 'hexagon'));
      $('#pt-add-star')?.addEventListener('click', () => this.addElement('shape', 'star'));
      $('#pt-add-heart')?.addEventListener('click', () => this.addElement('shape', 'heart'));
      $('#pt-add-cross')?.addEventListener('click', () => this.addElement('shape', 'cross'));
      $('#pt-add-arrow')?.addEventListener('click', () => this.addElement('shape', 'arrow'));
      $('#pt-add-chevron')?.addEventListener('click', () => this.addElement('shape', 'chevron'));
      $('#pt-add-cloud')?.addEventListener('click', () => this.addElement('shape', 'cloud'));
      $('#pt-add-speech-bubble')?.addEventListener('click', () => this.addElement('shape', 'speech-bubble'));
      $('#pt-add-parallelogram')?.addEventListener('click', () => this.addElement('shape', 'parallelogram'));
      $('#pt-add-trapezoid')?.addEventListener('click', () => this.addElement('shape', 'trapezoid'));
      $('#pt-add-ring')?.addEventListener('click', () => this.addElement('shape', 'ring'));

      // SVG Illustrations browser
      $('#pt-show-illustrations')?.addEventListener('click', () => {
        const browser = $('#presentation-illustrations-browser');
        if (browser) {
          browser.style.display = 'flex';
          this.loadIllustrations();
        }
      });
      $('#pt-illustrations-close')?.addEventListener('click', () => {
        const browser = $('#presentation-illustrations-browser');
        if (browser) browser.style.display = 'none';
      });
      $('#pt-illustrations-search')?.addEventListener('input', (e) => {
        this.filterIllustrations(e.target.value);
      });

      // Stock Photo browser (local open-source library)
      $('#pt-show-stock-photos')?.addEventListener('click', () => {
        const browser = $('#presentation-stock-browser');
        if (browser) {
          browser.style.display = 'flex';
          this.loadStockPhotos();
        }
      });
      $('#pt-stock-close')?.addEventListener('click', () => {
        const browser = $('#presentation-stock-browser');
        if (browser) browser.style.display = 'none';
      });
      $('#pt-stock-search-btn')?.addEventListener('click', () => this.loadStockPhotos());
      $('#pt-stock-search-input')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') this.loadStockPhotos();
      });

      // Grid toggle
      $('#pt-grid-toggle')?.addEventListener('click', () => {
        this.showGrid = !this.showGrid;
        const btn = $('#pt-grid-toggle');
        if (btn) btn.classList.toggle('active', this.showGrid);
        this.renderCanvas();
      });
      // Set initial grid state
      const gridBtn = $('#pt-grid-toggle');
      if (gridBtn) gridBtn.classList.add('active');

      // AI Generation
      $('#pt-ai-generate')?.addEventListener('click', () => this.generatePresentation());
      $('#pt-ai-enrich')?.addEventListener('click', () => this.enrichPresentation());
      $('#pt-prop-ai-enhance')?.addEventListener('click', () => this.enhanceSelectedText());
      $('#pt-ai-prompt')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') this.generatePresentation();
      });

      const addPage = $('#pt-add-page');
      if (addPage) addPage.addEventListener('click', () => this.addPage());

      const formatSel = $('#pt-format-select');
      if (formatSel) formatSel.addEventListener('change', (e) => this.changeFormat(e.target.value));

      const zoomSel = $('#pt-zoom-select');
      if (zoomSel) zoomSel.addEventListener('change', () => this.updateCanvasZoom());
      window.addEventListener('resize', () => {
        if ($('#presentation-layout')?.style.display !== 'none') {
          this.updateCanvasZoom();
        }
      });

      const canvas = $('#presentation-canvas');
      if (canvas) {
        canvas.addEventListener('mousedown', (e) => {
          if (e.target === canvas) this.selectElement(null);
        });
        // Right-click on empty canvas -> show paste option
        canvas.addEventListener('contextmenu', (e) => {
          if (e.target !== canvas && !e.target.classList.contains('canvas-grid-overlay')) return;
          e.preventDefault();
          // Only show if there's something to paste
          if (!this._clipboard) return;
          this.ctxMenuEl = null;
          const menu = $('#pt-context-menu');
          if (menu) {
            menu.style.display = 'flex';
            let x = e.clientX;
            let y = e.clientY;
            if (x + 200 > window.innerWidth) x = window.innerWidth - 200;
            if (y + 60 > window.innerHeight) y = window.innerHeight - 60;
            menu.style.left = x + 'px';
            menu.style.top = y + 'px';
            // Hide everything except paste
            ['pt-ctx-copy', 'pt-ctx-cut', 'pt-ctx-duplicate', 'pt-ctx-forward', 'pt-ctx-backward', 'pt-ctx-front', 'pt-ctx-back', 'pt-ctx-bg', 'pt-ctx-delete'].forEach(id => {
              const el = document.getElementById(id);
              if (el) el.style.display = 'none';
            });
            const pasteBtn = $('#pt-ctx-paste');
            if (pasteBtn) pasteBtn.style.display = 'flex';
            // Hide all separators for a clean single-item menu
            menu.querySelectorAll('div[style*="height:1px"]').forEach(d => d.style.display = 'none');
          }
        });
      }

      // Export Dialog
      const exportModal = $('#pt-export-modal');
      $('#pt-btn-export-dialog')?.addEventListener('click', () => {
        if (exportModal) exportModal.style.display = 'flex';
      });
      $('#pt-export-close')?.addEventListener('click', () => {
        if (exportModal) exportModal.style.display = 'none';
      });

      const radios = document.querySelectorAll('input[name="pt-export-pages"]');
      radios.forEach(r => {
        r.addEventListener('change', (e) => {
          const cust = $('#pt-export-custom-pages');
          if (cust) cust.disabled = e.target.value !== 'custom';
        });
      });

      $('#pt-export-confirm')?.addEventListener('click', () => {
        if (exportModal) exportModal.style.display = 'none';
        const format = $('#pt-export-format')?.value || 'pptx';
        const pagesMode = document.querySelector('input[name="pt-export-pages"]:checked')?.value || 'all';
        const customPages = $('#pt-export-custom-pages')?.value || '';
        this.export(format, pagesMode, customPages);
      });

      $('#pt-btn-new')?.addEventListener('click', () => this.newPresentation());
      $('#pt-btn-save')?.addEventListener('click', () => this.save());

      // Toolbar Menu Toggle
      const menuToggle = $('#pt-menu-toggle');
      const menuDropdown = $('#pt-menu-dropdown');
      if (menuToggle && menuDropdown) {
        menuToggle.addEventListener('click', (e) => {
          e.stopPropagation();
          menuDropdown.style.display = menuDropdown.style.display === 'none' ? 'flex' : 'none';
        });
        document.addEventListener('click', (e) => {
          if (!menuToggle.contains(e.target) && !menuDropdown.contains(e.target)) {
            menuDropdown.style.display = 'none';
          }
        });
      }

      // Undo / Redo
      $('#pt-btn-undo')?.addEventListener('click', () => {
        if (this.historyIndex > 0) {
          this.isUndoRedo = true;
          this.historyIndex--;
          const state = this.history[this.historyIndex];
          this.pages = JSON.parse(JSON.stringify(state.pages));
          this.canvasW = state.canvasW;
          this.canvasH = state.canvasH;
          this.selectElement(null);
          this.renderPages();
          this.renderCanvas();
          this.updateUndoRedoButtons();
          setTimeout(() => this.isUndoRedo = false, 50);
        }
      });
      $('#pt-btn-redo')?.addEventListener('click', () => {
        if (this.historyIndex < this.history.length - 1) {
          this.isUndoRedo = true;
          this.historyIndex++;
          const state = this.history[this.historyIndex];
          this.pages = JSON.parse(JSON.stringify(state.pages));
          this.canvasW = state.canvasW;
          this.canvasH = state.canvasH;
          this.selectElement(null);
          this.renderPages();
          this.renderCanvas();
          this.updateUndoRedoButtons();
          setTimeout(() => this.isUndoRedo = false, 50);
        }
      });

      $('#pt-prop-content')?.addEventListener('input', (e) => {
        if (this.selectedElement && (this.selectedElement.type === 'text' || this.selectedElement.type === 'table')) {
          this.selectedElement.content = e.target.value;
          this.renderCanvas();
        }
      });

      const toggleFormat = (id, field) => {
        const btn = $(id);
        if (!btn) return;
        btn.addEventListener('click', () => {
          if (this.selectedElement && this.selectedElement.type === 'text') {
            this.selectedElement[field] = !this.selectedElement[field];
            btn.style.background = this.selectedElement[field] ? 'var(--accent)' : 'transparent';
            this.renderCanvas();
          }
        });
      };
      toggleFormat('#pt-prop-bold', 'isBold');
      toggleFormat('#pt-prop-italic', 'isItalic');
      toggleFormat('#pt-prop-underline', 'isUnderline');
      toggleFormat('#pt-prop-strikethrough', 'isStrikethrough');
      toggleFormat('#pt-prop-list', 'isList');

      const bindProp = (id, field, parser = String) => {
        $(id)?.addEventListener('input', (e) => {
          if (this.selectedElement) {
            this.selectedElement[field] = parser(e.target.value);
            this.renderCanvas();
            // Sync hex<->color if it's a color
            if (id.endsWith('-hex') && $(id.replace('-hex', ''))) {
              $(id.replace('-hex', '')).value = this.selectedElement[field];
            }
            if (!id.endsWith('-hex') && $(id + '-hex')) {
              $(id + '-hex').value = this.selectedElement[field];
            }
          }
        });
      };

      bindProp('#pt-prop-fontsize', 'fontSize', parseInt);
      bindProp('#pt-prop-fontfamily', 'fontFamily');
      bindProp('#pt-prop-color', 'color');
      bindProp('#pt-prop-color-hex', 'color');
      bindProp('#pt-prop-fill', 'backgroundColor');
      bindProp('#pt-prop-fill-hex', 'backgroundColor');
      bindProp('#pt-prop-header-bg', 'headerBgColor');
      bindProp('#pt-prop-header-bg-hex', 'headerBgColor');
      bindProp('#pt-prop-border', 'borderColor');
      bindProp('#pt-prop-border-hex', 'borderColor');
      bindProp('#pt-prop-borderwidth', 'borderWidth', parseInt);
      bindProp('#pt-prop-borderradius', 'borderRadius', parseInt);

      $('#pt-prop-header-bg-clear')?.addEventListener('click', () => {
        if (this.selectedElement) {
          this.selectedElement.headerBgColor = 'transparent';
          $('#pt-prop-header-bg-hex').value = 'transparent';
          this.renderCanvas();
        }
      });

      $('#pt-prop-color-clear')?.addEventListener('click', () => {
        if (this.selectedElement) {
          this.selectedElement.color = 'transparent';
          $('#pt-prop-color-hex').value = 'transparent';
          this.renderCanvas();
        }
      });

      $('#pt-prop-fill-clear')?.addEventListener('click', () => {
        if (this.selectedElement) {
          this.selectedElement.backgroundColor = 'transparent';
          $('#pt-prop-fill-hex').value = 'transparent';
          this.renderCanvas();
        }
      });
      $('#pt-prop-border-clear')?.addEventListener('click', () => {
        if (this.selectedElement) {
          this.selectedElement.borderColor = 'transparent';
          $('#pt-prop-border-hex').value = 'transparent';
          this.renderCanvas();
        }
      });

      $('#pt-prop-opacity')?.addEventListener('input', (e) => {
        if (this.selectedElement) {
          this.selectedElement.opacity = parseInt(e.target.value);
          $('#pt-prop-opacity-val').innerText = this.selectedElement.opacity;
          this.renderCanvas();
        }
      });
      $('#pt-prop-shadow')?.addEventListener('input', (e) => {
        if (this.selectedElement) {
          this.selectedElement.shadowLevel = parseInt(e.target.value);
          $('#pt-prop-shadow-val').innerText = this.selectedElement.shadowLevel;
          this.renderCanvas();
        }
      });
      $('#pt-prop-thickness')?.addEventListener('input', (e) => {
        if (this.selectedElement) {
          this.selectedElement.shapeThickness = parseInt(e.target.value);
          const valEl = $('#pt-prop-thickness-val');
          if (valEl) valEl.innerText = this.selectedElement.shapeThickness;
          this.renderCanvas();
        }
      });

      $('#pt-prop-align')?.addEventListener('change', (e) => {
        if (this.selectedElement) {
          this.selectedElement.textAlign = e.target.value;
          this.renderCanvas();
        }
      });
      $('#pt-prop-delete')?.addEventListener('click', () => {
        if (this.selectedElement) {
          const page = this.pages[this.currentPage];
          page.elements = page.elements.filter(e => e !== this.selectedElement);
          this.selectElement(null);
          this.renderCanvas();
        }
      });
      $('#pt-prop-bg')?.addEventListener('click', () => {
        if (this.selectedElement && this.selectedElement.type === 'image') {
          const page = this.pages[this.currentPage];

          // Make it full size
          this.selectedElement.x = 0;
          this.selectedElement.y = 0;
          this.selectedElement.width = this.canvasW;
          this.selectedElement.height = this.canvasH;

          // Move to back
          page.elements = page.elements.filter(e => e !== this.selectedElement);
          page.elements.unshift(this.selectedElement);

          this.renderCanvas();
        }
      });

      // Z-index layer controls
      $('#pt-prop-layer-up')?.addEventListener('click', () => {
        if (this.selectedElement) {
          const els = this.pages[this.currentPage].elements;
          const idx = els.indexOf(this.selectedElement);
          if (idx < els.length - 1) {
            [els[idx], els[idx + 1]] = [els[idx + 1], els[idx]];
            this.renderCanvas();
          }
        }
      });
      $('#pt-prop-layer-down')?.addEventListener('click', () => {
        if (this.selectedElement) {
          const els = this.pages[this.currentPage].elements;
          const idx = els.indexOf(this.selectedElement);
          if (idx > 0) {
            [els[idx], els[idx - 1]] = [els[idx - 1], els[idx]];
            this.renderCanvas();
          }
        }
      });


      // Context Menu logic
      const ctxMenu = $('#pt-context-menu');
      document.addEventListener('click', () => {
        if (ctxMenu) ctxMenu.style.display = 'none';
      });

      const doAction = (action) => {
        if (!this.ctxMenuEl) return;
        const page = this.pages[this.currentPage];
        const els = page.elements;
        const idx = els.indexOf(this.ctxMenuEl);
        if (idx === -1) return;

        if (action === 'forward' && idx < els.length - 1) {
          [els[idx], els[idx + 1]] = [els[idx + 1], els[idx]];
        } else if (action === 'backward' && idx > 0) {
          [els[idx], els[idx - 1]] = [els[idx - 1], els[idx]];
        } else if (action === 'front' && idx < els.length - 1) {
          const [el] = els.splice(idx, 1);
          els.push(el);
        } else if (action === 'back' && idx > 0) {
          const [el] = els.splice(idx, 1);
          els.unshift(el);
        } else if (action === 'bg' && this.ctxMenuEl.type === 'image') {
          this.ctxMenuEl.x = 0;
          this.ctxMenuEl.y = 0;
          this.ctxMenuEl.width = this.canvasW;
          this.ctxMenuEl.height = this.canvasH;
          const [el] = els.splice(idx, 1);
          els.unshift(el);
        } else if (action === 'copy') {
          this.copyElement(this.ctxMenuEl);
        } else if (action === 'cut') {
          this.cutElement(this.ctxMenuEl);
        } else if (action === 'paste') {
          this.pasteElement();
        } else if (action === 'duplicate') {
          this.duplicateElement(this.ctxMenuEl);
        } else if (action === 'delete') {
          els.splice(idx, 1);
          if (this.selectedElement === this.ctxMenuEl) this.selectElement(null);
        }

        this.ctxMenuEl = null;
        this.renderCanvas();
      };

      $('#pt-ctx-copy')?.addEventListener('click', () => doAction('copy'));
      $('#pt-ctx-cut')?.addEventListener('click', () => doAction('cut'));
      $('#pt-ctx-paste')?.addEventListener('click', () => doAction('paste'));
      $('#pt-ctx-duplicate')?.addEventListener('click', () => doAction('duplicate'));
      $('#pt-ctx-forward')?.addEventListener('click', () => doAction('forward'));
      $('#pt-ctx-backward')?.addEventListener('click', () => doAction('backward'));
      $('#pt-ctx-front')?.addEventListener('click', () => doAction('front'));
      $('#pt-ctx-back')?.addEventListener('click', () => doAction('back'));
      $('#pt-ctx-bg')?.addEventListener('click', () => doAction('bg'));
      $('#pt-ctx-delete')?.addEventListener('click', () => doAction('delete'));

      // Gallery interactions
      $('#pt-gallery-close')?.addEventListener('click', () => {
        $('#presentation-gallery-browser').style.display = 'none';
      });
      $('#pt-gallery-upload')?.addEventListener('click', () => {
        $('#pt-upload-input')?.click();
      });
      $('#pt-upload-input')?.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (file) {
          const formData = new FormData();
          formData.append('file', file);
          try {
            const res = await fetch('/image/upload', { method: 'POST', body: formData });
            const data = await res.json();
            if (res.ok) {
              this.addElement('image', data.url);
              $('#presentation-gallery-browser').style.display = 'none';
              toast(ICONS.check(14) + ' Image uploaded to gallery');
            } else throw new Error(data.detail);
          } catch (err) {
            toast(` Upload failed: ${err.message}`, 4000);
          }
        }
      });

      document.addEventListener('mousemove', (e) => this.onMouseMove(e));
      document.addEventListener('mouseup', (e) => this.onMouseUp(e));
      document.addEventListener('keydown', (e) => {
        const layout = $('#presentation-layout');
        if (!layout || layout.style.display === 'none') return;

        // Skip shortcuts when typing in input fields
        const isEditing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName);

        if (e.key === 'Delete' || e.key === 'Backspace') {
          if (isEditing) return;
          if (this.selectedElement) {
            const page = this.pages[this.currentPage];
            page.elements = page.elements.filter(el => el !== this.selectedElement);
            this.selectElement(null);
            this.renderCanvas();
          }
        } else if ((e.ctrlKey || e.metaKey) && e.key === 'c') {
          // Ctrl+C — Copy element
          if (isEditing) return;
          if (this.selectedElement) {
            e.preventDefault();
            this.copyElement(this.selectedElement);
          }
        } else if ((e.ctrlKey || e.metaKey) && e.key === 'x') {
          // Ctrl+X — Cut element
          if (isEditing) return;
          if (this.selectedElement) {
            e.preventDefault();
            this.cutElement(this.selectedElement);
          }
        } else if ((e.ctrlKey || e.metaKey) && e.key === 'v') {
          // Ctrl+V — Paste (internal clipboard or external content)
          if (isEditing) return;
          e.preventDefault();
          this.handlePaste();
        } else if ((e.ctrlKey || e.metaKey) && e.key === 'd') {
          // Ctrl+D — Duplicate element in place
          if (isEditing) return;
          if (this.selectedElement) {
            e.preventDefault();
            this.duplicateElement(this.selectedElement);
          }
        } else if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
          if (isEditing) return;
          if (this.selectedElement) {
            e.preventDefault();
            const step = e.shiftKey ? 10 : 1;
            if (e.key === 'ArrowUp') this.selectedElement.y -= step;
            if (e.key === 'ArrowDown') this.selectedElement.y += step;
            if (e.key === 'ArrowLeft') this.selectedElement.x -= step;
            if (e.key === 'ArrowRight') this.selectedElement.x += step;
            this.renderCanvas();
          }
        }
      });

      // Handle external paste events (images, SVG, text from OS clipboard)
      document.addEventListener('paste', (e) => {
        const layout = $('#presentation-layout');
        if (!layout || layout.style.display === 'none') return;
        if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;

        // Handled by keydown handler, but we need the ClipboardEvent for file/image data
        this._handleExternalPaste(e);
      });
    }

    changeFormat(fmt) {
      if (fmt === '16:9') { this.canvasW = 960; this.canvasH = 540; }
      else if (fmt === '4:3') { this.canvasW = 960; this.canvasH = 720; }
      else if (fmt === 'portrait') { this.canvasW = 540; this.canvasH = 960; }
      else if (fmt === 'A4') { this.canvasW = 794; this.canvasH = 1123; }
      else if (fmt === 'IG') { this.canvasW = 1080; this.canvasH = 1080; }
      else if (fmt === 'YT') { this.canvasW = 1280; this.canvasH = 720; }
      else if (fmt === 'card') { this.canvasW = 638; this.canvasH = 368; }

      const c = $('#presentation-canvas');
      if (c) {
        c.style.width = this.canvasW + 'px';
        c.style.height = this.canvasH + 'px';
      }
      this.renderCanvas();
      this.updateCanvasZoom();
    }

    updateCanvasZoom() {
      const zoomSel = $('#pt-zoom-select');
      const c = $('#presentation-canvas');
      const container = $('#presentation-canvas-container');
      const wrap = $('#presentation-canvas-wrapper');
      if (!c || !container || !wrap || !zoomSel) return;

      let scale = 1;
      const val = zoomSel.value;
      if (val === 'fit') {
        const cw = container.clientWidth - 80;
        const ch = container.clientHeight - 80;
        const scaleX = cw / this.canvasW;
        const scaleY = ch / this.canvasH;
        scale = Math.min(1, scaleX, scaleY);
      } else {
        scale = parseInt(val) / 100;
      }

      this.currentScale = scale || 1;
      c.style.transform = `scale(${this.currentScale})`;
      wrap.style.width = (this.canvasW * this.currentScale) + 'px';
      wrap.style.height = (this.canvasH * this.currentScale) + 'px';
    }

    addPage() {
      this.pages.push({ elements: [] });
      this.currentPage = this.pages.length - 1;
      this.selectElement(null);
      this.renderPages();
      this.renderCanvas();
    }

    switchPage(idx) {
      this.currentPage = idx;
      this.selectElement(null);
      this.renderPages();
      this.renderCanvas();
    }

    duplicatePage(idx) {
      const pageToCopy = this.pages[idx];
      const newPage = JSON.parse(JSON.stringify(pageToCopy));
      newPage.elements.forEach(el => el.id = 'el_' + Math.random().toString(36).substr(2, 9));

      this.pages.splice(idx + 1, 0, newPage);
      this.currentPage = idx + 1;
      this.selectElement(null);
      this.renderPages();
      this.renderCanvas();
    }

    reorderPage(fromIdx, toIdx) {
      if (fromIdx === toIdx) return;
      const [movedPage] = this.pages.splice(fromIdx, 1);
      this.pages.splice(toIdx, 0, movedPage);

      if (this.currentPage === fromIdx) {
        this.currentPage = toIdx;
      } else if (this.currentPage > fromIdx && this.currentPage <= toIdx) {
        this.currentPage--;
      } else if (this.currentPage < fromIdx && this.currentPage >= toIdx) {
        this.currentPage++;
      }

      this.renderPages();
    }

    deletePage(idx) {
      if (this.pages.length <= 1) return;
      this.pages.splice(idx, 1);
      if (this.currentPage >= this.pages.length) {
        this.currentPage = this.pages.length - 1;
      }
      this.selectElement(null);
      this.renderPages();
      this.renderCanvas();
    }

    addElement(type, content) {
      const el = {
        id: 'el_' + Date.now(),
        type: type,
        x: 50,
        y: 50,
        width: type === 'image' ? 200 : 300,
        height: type === 'image' ? 200 : 50,
      };

      if (type === 'text') {
        el.content = content || 'New Text';
        el.fontSize = 24;
        el.color = '#ffffff';
        el.backgroundColor = 'transparent';
        el.borderColor = 'transparent';
        el.borderWidth = 0;
        el.opacity = 100;
        el.textAlign = 'left';
      } else if (type === 'table') {
        el.content = content || '| Col 1 |\n|---|';
        el.fontSize = 16;
        el.color = '#000000';
        el.backgroundColor = 'transparent';
        el.borderColor = '#000000';
        el.borderWidth = 3;
        el.opacity = 100;
        el.textAlign = 'left';
      } else if (type === 'image') {
        el.src = content;
        el.width = 200;
        el.height = 200;
        el.opacity = 100;
      } else if (type === 'icon') {
        el.svgContent = content.svg;
        el.iconName = content.name;
        el.width = 100;
        el.height = 100;
        el.borderColor = '#000000';
        el.borderWidth = 2;
        el.backgroundColor = 'transparent';
        el.opacity = 100;
      } else if (type === 'shape') {
        el.shapeType = content || 'rect';
        el.backgroundColor = '#888888';
        el.borderColor = '#000000';
        el.borderWidth = 0;
        el.opacity = 100;
        el.width = 150;
        el.height = 150;
      }

      this.pages[this.currentPage].elements.push(el);
      this.selectElement(el);
      this.renderCanvas();
      return el;
    }

    // ---- Clipboard: Copy / Cut / Paste / Duplicate ----

    copyElement(el) {
      if (!el) return;
      this._clipboard = JSON.parse(JSON.stringify(el));
      this._pasteOffset = 0;
      toast(ICONS.clipboard(14) + ' Element copied');
    }

    cutElement(el) {
      if (!el) return;
      this._clipboard = JSON.parse(JSON.stringify(el));
      this._pasteOffset = 0;
      const page = this.pages[this.currentPage];
      page.elements = page.elements.filter(e => e !== el);
      if (this.selectedElement === el) this.selectElement(null);
      this.renderCanvas();
      toast(ICONS.circle(14) + ' ️ Element cut');
    }

    pasteElement() {
      if (!this._clipboard) {
        toast(ICONS.clipboard(14) + ' Nothing to paste');
        return;
      }
      this._pasteOffset += 20;
      const clone = JSON.parse(JSON.stringify(this._clipboard));
      clone.id = 'el_' + Date.now();
      clone.x = Math.min(clone.x + this._pasteOffset, this.canvasW - 40);
      clone.y = Math.min(clone.y + this._pasteOffset, this.canvasH - 40);
      this.pages[this.currentPage].elements.push(clone);
      this.selectElement(clone);
      this.renderCanvas();
      toast(ICONS.clipboard(14) + ' Element pasted');
    }

    duplicateElement(el) {
      if (!el) return;
      const clone = JSON.parse(JSON.stringify(el));
      clone.id = 'el_' + Date.now();
      clone.x += 20;
      clone.y += 20;
      this.pages[this.currentPage].elements.push(clone);
      this.selectElement(clone);
      this.renderCanvas();
      toast(ICONS.circle(14) + ' Element duplicated');
    }

    /** Try internal clipboard first, then system clipboard */
    async handlePaste() {
      if (this._clipboard) {
        this.pasteElement();
        return;
      }
      // If no internal clipboard, try reading from system clipboard
      try {
        if (navigator.clipboard && window.isSecureContext) {
          // Try to read images
          const items = await navigator.clipboard.read().catch(() => null);
          if (items) {
            for (const item of items) {
              // Try image types
              const imgType = item.types.find(t => t.startsWith('image/'));
              if (imgType) {
                const blob = await item.getType(imgType);
                await this._pasteImageBlob(blob);
                return;
              }
              // Try HTML (may contain SVG or rich content)
              if (item.types.includes('text/html')) {
                const htmlBlob = await item.getType('text/html');
                const html = await htmlBlob.text();
                if (html.includes('<svg')) {
                  this._pasteSvgContent(html);
                  return;
                }
              }
            }
          }
          // Fallback to plain text
          const text = await navigator.clipboard.readText().catch(() => null);
          if (text && text.trim()) {
            // Check if it's SVG markup
            if (text.trim().startsWith('<svg')) {
              this._pasteSvgContent(text);
            } else {
              this._pasteTextContent(text.trim());
            }
            return;
          }
        }
        toast(ICONS.clipboard(14) + ' Clipboard is empty');
      } catch (e) {
        toast(ICONS.clipboard(14) + ' Could not read clipboard');
      }
    }

    /** Handle paste event from the DOM (for file/image data) */
    _handleExternalPaste(e) {
      // If we have an internal clipboard, let handlePaste (from keydown) deal with it
      if (this._clipboard) return;

      const dt = e.clipboardData;
      if (!dt) return;

      // Check for files (images)
      if (dt.files && dt.files.length > 0) {
        e.preventDefault();
        for (const file of dt.files) {
          if (file.type.startsWith('image/')) {
            this._pasteImageBlob(file);
            return;
          }
        }
      }

      // Check for items (images in clipboard)
      if (dt.items) {
        for (const item of dt.items) {
          if (item.type.startsWith('image/')) {
            e.preventDefault();
            const blob = item.getAsFile();
            if (blob) this._pasteImageBlob(blob);
            return;
          }
        }
      }

      // Check for HTML containing SVG
      const html = dt.getData('text/html');
      if (html && html.includes('<svg')) {
        e.preventDefault();
        this._pasteSvgContent(html);
        return;
      }

      // Check for plain text or SVG text
      const text = dt.getData('text/plain');
      if (text && text.trim()) {
        e.preventDefault();
        if (text.trim().startsWith('<svg')) {
          this._pasteSvgContent(text);
        } else {
          this._pasteTextContent(text.trim());
        }
      }
    }

    /** Paste an image blob: upload to gallery then add to canvas */
    async _pasteImageBlob(blob) {
      toast(ICONS.clipboard(14) + ' Pasting image...');
      try {
        const formData = new FormData();
        const ext = blob.type.split('/')[1] || 'png';
        const fileName = `pasted_${Date.now()}.${ext}`;
        formData.append('file', blob, fileName);
        const res = await fetch('/image/upload', { method: 'POST', body: formData });
        const data = await res.json();
        if (res.ok && data.url) {
          this.addElement('image', data.url);
          toast(ICONS.check(14) + ' Image pasted!');
        } else {
          throw new Error(data.detail || 'Upload failed');
        }
      } catch (e) {
        toast(' Paste image failed: ' + e.message);
      }
    }

    /** Paste SVG content as an image data URI */
    _pasteSvgContent(rawHtml) {
      // Extract the <svg> tag from possibly larger HTML
      const match = rawHtml.match(/<svg[\s\S]*?<\/svg>/i);
      if (!match) {
        toast(ICONS.circle(14) + ' ️ No valid SVG found in clipboard');
        return;
      }
      const svgText = match[0];
      const blob = new Blob([svgText], { type: 'image/svg+xml' });
      const url = URL.createObjectURL(blob);

      // Determine size from SVG attributes or default
      const parser = new DOMParser();
      const doc = parser.parseFromString(svgText, 'image/svg+xml');
      const svgEl = doc.querySelector('svg');
      let w = 200, h = 200;
      if (svgEl) {
        const vb = svgEl.getAttribute('viewBox');
        if (vb) {
          const parts = vb.split(/[\s,]+/).map(Number);
          if (parts.length === 4) { w = parts[2]; h = parts[3]; }
        }
        const sw = parseInt(svgEl.getAttribute('width'));
        const sh = parseInt(svgEl.getAttribute('height'));
        if (sw && sh) { w = sw; h = sh; }
      }
      // Clamp to reasonable size
      const maxDim = Math.min(this.canvasW * 0.6, this.canvasH * 0.6);
      if (w > maxDim || h > maxDim) {
        const scale = maxDim / Math.max(w, h);
        w = Math.round(w * scale);
        h = Math.round(h * scale);
      }

      const el = this.addElement('image', url);
      el.width = w;
      el.height = h;
      this.renderCanvas();
      toast(ICONS.check(14) + ' SVG pasted!');
    }

    /** Paste plain text as a new text element */
    _pasteTextContent(text) {
      // Estimate a reasonable box height
      const lines = text.split('\n').length;
      const el = this.addElement('text', text);
      el.width = Math.min(Math.max(200, text.length * 8), this.canvasW - 100);
      el.height = Math.max(50, lines * 30);
      el.x = 50;
      el.y = 50;
      this.renderCanvas();
      toast(ICONS.check(14) + ' Text pasted!');
    }

    selectElement(el) {
      this.selectedElement = el;
      if (el) {
        if ($('#pt-no-selection')) $('#pt-no-selection').style.display = 'none';
        if ($('#presentation-sidebar-right')) $('#presentation-sidebar-right').style.display = 'flex';
        $('#pt-properties-panel').style.display = 'flex';

        $('#pt-prop-content').value = el.content || '';
        $('#pt-prop-fontsize').value = el.fontSize || 24;
        const c = el.color && el.color !== 'transparent' ? el.color : '#000000';
        $('#pt-prop-color').value = c;
        $('#pt-prop-color-hex').value = el.color || 'transparent';
        $('#pt-prop-align').value = el.textAlign || 'left';

        const bg = el.backgroundColor && el.backgroundColor !== 'transparent' ? el.backgroundColor : '#ffffff';
        $('#pt-prop-fill').value = bg;
        $('#pt-prop-fill-hex').value = el.backgroundColor || 'transparent';
        const bc = el.borderColor && el.borderColor !== 'transparent' ? el.borderColor : '#000000';
        $('#pt-prop-border').value = bc;
        $('#pt-prop-border-hex').value = el.borderColor || 'transparent';
        $('#pt-prop-borderwidth').value = el.borderWidth || 0;
        $('#pt-prop-borderradius').value = el.borderRadius || 0;
        $('#pt-prop-opacity').value = el.opacity !== undefined ? el.opacity : 100;
        const opVal = document.getElementById('pt-prop-opacity-val');
        if (opVal) opVal.innerText = el.opacity !== undefined ? el.opacity : 100;

        if ($('#pt-prop-shadow')) $('#pt-prop-shadow').value = el.shadowLevel || 0;
        const shVal = document.getElementById('pt-prop-shadow-val');
        if (shVal) shVal.innerText = el.shadowLevel || 0;

        if ($('#pt-prop-thickness')) $('#pt-prop-thickness').value = el.shapeThickness !== undefined ? el.shapeThickness : 50;
        const thickVal = document.getElementById('pt-prop-thickness-val');
        if (thickVal) thickVal.innerText = el.shapeThickness !== undefined ? el.shapeThickness : 50;

        const isTextOrTable = el.type === 'text' || el.type === 'table';
        if ($('#pt-prop-content-group')) $('#pt-prop-content-group').style.display = isTextOrTable ? 'block' : 'none';
        if ($('#pt-prop-borderradius-wrapper')) $('#pt-prop-borderradius-wrapper').style.display = el.type === 'icon' ? 'none' : 'block';
        $('#pt-prop-text-group').style.display = isTextOrTable ? 'flex' : 'none';
        $('#pt-prop-color-group').style.display = isTextOrTable ? 'flex' : 'none';
        $('#pt-prop-align-group').style.display = el.type === 'text' ? 'flex' : 'none';
        if ($('#pt-prop-header-bg-group')) $('#pt-prop-header-bg-group').style.display = el.type === 'table' ? 'flex' : 'none';
        $('#pt-prop-image-group').style.display = el.type === 'image' ? 'flex' : 'none';
        $('#pt-prop-text-format-group').style.display = el.type === 'text' ? 'flex' : 'none';

        const showThickness = el.type === 'shape' && (el.shapeType === 'cross' || el.shapeType === 'arrow');
        if ($('#pt-prop-thickness-group')) $('#pt-prop-thickness-group').style.display = showThickness ? 'flex' : 'none';

        const hbg = el.headerBgColor && el.headerBgColor !== 'transparent' ? el.headerBgColor : '#000000';
        if ($('#pt-prop-header-bg')) $('#pt-prop-header-bg').value = hbg;
        if ($('#pt-prop-header-bg-hex')) $('#pt-prop-header-bg-hex').value = el.headerBgColor || 'transparent';

        if ($('#pt-prop-fontfamily')) {
          $('#pt-prop-fontfamily').value = el.fontFamily || 'Inter, sans-serif';
        }
        if ($('#pt-prop-fontfamily-group')) {
          $('#pt-prop-fontfamily-group').style.display = isTextOrTable ? 'flex' : 'none';
        }

        const updateBtnState = (id, field) => {
          if ($(id)) $(id).style.background = el[field] ? 'var(--accent)' : 'transparent';
        };
        if (el.type === 'text') {
          updateBtnState('#pt-prop-bold', 'isBold');
          updateBtnState('#pt-prop-italic', 'isItalic');
          updateBtnState('#pt-prop-underline', 'isUnderline');
          updateBtnState('#pt-prop-strikethrough', 'isStrikethrough');
          updateBtnState('#pt-prop-list', 'isList');
        }
      } else {
        if ($('#pt-no-selection')) $('#pt-no-selection').style.display = 'block';
        if ($('#presentation-sidebar-right')) $('#presentation-sidebar-right').style.display = 'none';
        $('#pt-properties-panel').style.display = 'none';
      }
      this.renderCanvas(); // updates outlines
    }

    // Drag and Drop
    onMouseDown(e, el, action, handle = null) {
      e.stopPropagation();
      this.selectElement(el);
      if (action === 'drag') {
        this.dragItem = el;
      } else if (action === 'resize') {
        this.resizeItem = { el, handle, origX: el.x, origY: el.y, origW: el.width, origH: el.height };
      }
      this.dragStartX = e.clientX;
      this.dragStartY = e.clientY;
    }

    onMouseMove(e) {
      const c = $('#presentation-canvas');
      if (!c) return;
      const scale = c.getBoundingClientRect().width / this.canvasW;

      if (this.dragItem) {
        const dx = (e.clientX - this.dragStartX) / scale;
        const dy = (e.clientY - this.dragStartY) / scale;
        this.dragItem.x = this.dragItem.x + dx;
        this.dragItem.y = this.dragItem.y + dy;
        this.dragStartX = e.clientX;
        this.dragStartY = e.clientY;
        this.renderCanvas();
      } else if (this.resizeItem) {
        const dx = (e.clientX - this.dragStartX) / scale;
        const dy = (e.clientY - this.dragStartY) / scale;
        const { el, handle, origX, origY, origW, origH } = this.resizeItem;

        if (handle === 'br') {
          el.width = Math.max(20, origW + dx);
          el.height = Math.max(20, origH + dy);
        } else if (handle === 'bl') {
          el.width = Math.max(20, origW - dx);
          el.height = Math.max(20, origH + dy);
          el.x = origX + (origW - el.width);
        } else if (handle === 'tr') {
          el.width = Math.max(20, origW + dx);
          el.height = Math.max(20, origH - dy);
          el.y = origY + (origH - el.height);
        } else if (handle === 'tl') {
          el.width = Math.max(20, origW - dx);
          el.height = Math.max(20, origH - dy);
          el.x = origX + (origW - el.width);
          el.y = origY + (origH - el.height);
        }
        this.renderCanvas();
      }
    }

    onMouseUp(e) {
      const snap = (v) => this.showGrid ? Math.round(v / this.snapGrid) * this.snapGrid : v;
      let needsRender = false;

      if (this.resizeItem) {
        const el = this.resizeItem.el;
        el.x = snap(el.x);
        el.y = snap(el.y);
        el.width = Math.max(20, snap(el.width));
        el.height = Math.max(20, snap(el.height));
        this.resizeItem = null;
        needsRender = true;
      }

      if (this.dragItem) {
        this.dragItem.x = snap(this.dragItem.x);
        this.dragItem.y = snap(this.dragItem.y);
        this.dragItem = null;
        needsRender = true;
      }

      if (needsRender) {
        this.renderCanvas();
      }
    }

    saveStateDebounced() {
      if (this._saveStateTimer) clearTimeout(this._saveStateTimer);
      this._saveStateTimer = setTimeout(() => {
        this.saveState();
        this.autoSave();
      }, 300);
    }

    autoSave() {
      if (this._autoSaveTimer) clearTimeout(this._autoSaveTimer);
      this._autoSaveTimer = setTimeout(() => {
        this.save(true);
      }, 2000);
    }

    saveState() {
      if (this.isUndoRedo) return;
      const state = {
        pages: JSON.parse(JSON.stringify(this.pages)),
        canvasW: this.canvasW,
        canvasH: this.canvasH,
      };

      if (this.historyIndex >= 0) {
        const lastState = this.history[this.historyIndex];
        if (JSON.stringify(lastState.pages) === JSON.stringify(state.pages) &&
          lastState.canvasW === state.canvasW && lastState.canvasH === state.canvasH) {
          return;
        }
      }

      if (this.historyIndex < this.history.length - 1) {
        this.history = this.history.slice(0, this.historyIndex + 1);
      }
      this.history.push(state);
      if (this.history.length > 50) {
        this.history.shift();
      } else {
        this.historyIndex++;
      }
      this.updateUndoRedoButtons();
    }

    updateUndoRedoButtons() {
      const btnUndo = $('#pt-btn-undo');
      const btnRedo = $('#pt-btn-redo');
      if (btnUndo) {
        btnUndo.style.opacity = this.historyIndex > 0 ? '1' : '0.5';
        btnUndo.style.cursor = this.historyIndex > 0 ? 'pointer' : 'not-allowed';
      }
      if (btnRedo) {
        btnRedo.style.opacity = this.historyIndex < this.history.length - 1 ? '1' : '0.5';
        btnRedo.style.cursor = this.historyIndex < this.history.length - 1 ? 'pointer' : 'not-allowed';
      }
    }

    renderCanvas() {
      const c = $('#presentation-canvas');
      if (!c) return;

      c.style.width = this.canvasW + 'px';
      c.style.height = this.canvasH + 'px';

      if (!this.isUndoRedo) {
        this.saveStateDebounced();
      }
      c.innerHTML = '';

      // Grid overlay
      if (this.showGrid) {
        const gridSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        gridSvg.classList.add('canvas-grid-overlay');
        gridSvg.setAttribute('width', '100%');
        gridSvg.setAttribute('height', '100%');
        gridSvg.setAttribute('viewBox', `0 0 ${this.canvasW} ${this.canvasH}`);
        for (let x = this.snapGrid; x < this.canvasW; x += this.snapGrid) {
          for (let y = this.snapGrid; y < this.canvasH; y += this.snapGrid) {
            const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            dot.setAttribute('cx', x);
            dot.setAttribute('cy', y);
            dot.setAttribute('r', '0.8');
            dot.setAttribute('fill', 'rgba(255,255,255,0.12)');
            gridSvg.appendChild(dot);
          }
        }
        c.appendChild(gridSvg);
      }

      const page = this.pages[this.currentPage];
      if (!page) return;

      page.elements.forEach((el, index) => {
        const node = document.createElement('div');
        node.className = 'canvas-element' + (this.selectedElement === el ? ' selected' : '');
        node.style.left = el.x + 'px';
        node.style.top = el.y + 'px';
        node.style.width = el.width + 'px';
        node.style.height = el.height + 'px';
        node.style.zIndex = index + 1;

        node.style.opacity = (el.opacity !== undefined ? el.opacity : 100) / 100;
        if (el.shadowLevel > 0) {
          node.style.filter = `drop-shadow(0px ${Math.round(el.shadowLevel / 2)}px ${el.shadowLevel}px rgba(0,0,0,0.5))`;
        } else {
          node.style.filter = 'none';
        }
        if (el.type !== 'shape') {
          node.style.backgroundColor = el.backgroundColor || 'transparent';
          if (el.borderWidth && el.type !== 'table') {
            node.style.border = `${el.borderWidth}px solid ${el.borderColor || 'transparent'}`;
          } else {
            node.style.border = 'none';
          }
          if (el.borderRadius) {
            node.style.borderRadius = `${el.borderRadius}px`;
          } else {
            node.style.borderRadius = '0';
          }
        }

        if (el.type === 'text') {
          const inner = document.createElement('div');
          inner.className = 'canvas-text-content';
          inner.style.fontSize = (el.fontSize || 24) + 'px';
          inner.style.fontFamily = el.fontFamily || 'Inter, sans-serif';
          inner.style.color = el.color || '#000000';
          inner.style.textAlign = el.textAlign || 'left';

          if (el.isBold) inner.style.fontWeight = 'bold';
          if (el.isItalic) inner.style.fontStyle = 'italic';

          let decoration = '';
          if (el.isUnderline) decoration += ' underline';
          if (el.isStrikethrough) decoration += ' line-through';
          if (decoration) inner.style.textDecoration = decoration.trim();

          if (el.isList) {
            const ul = document.createElement('ul');
            ul.style.margin = '0';
            ul.style.paddingLeft = '1.2em';
            const lines = (el.content || '').split('\n');
            lines.forEach(line => {
              const li = document.createElement('li');
              li.innerText = line;
              ul.appendChild(li);
            });
            inner.appendChild(ul);
          } else {
            inner.innerText = el.content || '';
          }
          node.appendChild(inner);
        } else if (el.type === 'table') {
          const inner = document.createElement('div');
          inner.className = 'canvas-table-wrapper';
          inner.style.width = '100%';
          inner.style.height = '100%';
          inner.style.color = el.color || '#000000';
          inner.style.fontSize = (el.fontSize || 16) + 'px';
          inner.style.fontFamily = el.fontFamily || 'Inter, sans-serif';

          const tableMd = el.content || '| Header |\n|---|';
          const rows = tableMd.trim().split('\n').filter(r => r.trim());
          let thtml = '<table style="width:100%;height:100%;border-collapse:collapse;">';
          const cellBorderWidth = el.borderWidth !== undefined ? el.borderWidth : 1;
          const cellBorderColor = el.borderColor && el.borderColor !== 'transparent' ? el.borderColor : 'currentColor';
          const cellBorder = cellBorderWidth > 0 ? `${cellBorderWidth}px solid ${cellBorderColor}` : 'none';

          rows.forEach((row, i) => {
            if (row.match(/^\|[\s-:|]+\|$/)) return;
            const cells = row.split('|').filter(c => c.trim() !== '');
            const isHeader = i === 0;
            const tag = isHeader ? 'th' : 'td';
            const bgStyle = isHeader && el.headerBgColor && el.headerBgColor !== 'transparent' ? `background-color: ${el.headerBgColor};` : '';
            thtml += '<tr>' + cells.map(c => `<${tag} style="border: ${cellBorder}; padding: 8px; ${bgStyle}">${c.trim()}</${tag}>`).join('') + '</tr>';
          });
          thtml += '</table>';
          inner.innerHTML = thtml;
          node.appendChild(inner);
        } else if (el.type === 'image') {
          const inner = document.createElement('img');
          inner.className = 'canvas-image-content';
          inner.src = el.src;
          node.appendChild(inner);
        } else if (el.type === 'icon') {
          node.style.backgroundColor = 'transparent';
          node.style.border = 'none';
          node.style.borderRadius = '0';

          node.innerHTML = el.svgContent || '';
          const svg = node.querySelector('svg');
          if (svg) {
            svg.setAttribute('width', '100%');
            svg.setAttribute('height', '100%');
            svg.style.display = 'block';
            svg.style.overflow = 'visible';
            svg.setAttribute('stroke', el.borderColor || '#000000');
            svg.setAttribute('stroke-width', el.borderWidth !== undefined ? el.borderWidth : 2);
            svg.setAttribute('fill', el.backgroundColor === 'transparent' ? 'none' : el.backgroundColor);

            svg.querySelectorAll('*').forEach(child => {
              if (child.hasAttribute('stroke') && child.getAttribute('stroke') !== 'none') child.setAttribute('stroke', 'currentColor');
              if (child.hasAttribute('fill') && child.getAttribute('fill') !== 'none') child.setAttribute('fill', 'currentColor');
            });
            svg.style.color = el.borderColor || '#000000';
          }
        } else if (el.type === 'mermaid') {
          node.style.backgroundColor = el.backgroundColor || 'transparent';
          node.style.border = 'none';
          node.style.borderRadius = '0';

          const inner = document.createElement('div');
          inner.style.width = '100%';
          inner.style.height = '100%';
          inner.style.display = 'flex';
          inner.style.alignItems = 'center';
          inner.style.justifyContent = 'center';
          inner.style.color = el.color || '#000000';
          inner.style.padding = '10px';
          inner.style.boxSizing = 'border-box';

          if (window.mermaid) {
            const id = 'mmr-pres-' + Math.random().toString(36).substr(2, 9);
            inner.id = id;
            try {
              mermaid.render(id + '-svg', el.content || 'graph TD;\nA-->B;').then(r => {
                inner.innerHTML = r.svg;
                const svg = inner.querySelector('svg');
                if (svg) {
                  svg.style.maxWidth = '100%';
                  svg.style.maxHeight = '100%';
                  svg.style.width = 'auto';
                  svg.style.height = 'auto';
                }
              }).catch(e => {
                inner.innerHTML = `<div style="color:red; font-size:12px; font-family:monospace">Mermaid syntax error</div>`;
              });
            } catch (e) {
              inner.innerHTML = `<div style="color:red; font-size:12px; font-family:monospace">Mermaid rendering error</div>`;
            }
          } else {
            inner.innerText = el.content || '';
          }
          node.appendChild(inner);
        } else if (el.type === 'shape') {
          node.style.backgroundColor = 'transparent';
          node.style.border = 'none';
          node.style.borderRadius = '0';

          const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
          svg.setAttribute('width', '100%');
          svg.setAttribute('height', '100%');
          svg.style.overflow = 'visible';
          svg.style.display = 'block';

          let fill = el.backgroundColor || 'transparent';
          let stroke = el.borderWidth ? (el.borderColor || '#000000') : 'none';
          let strokeW = el.borderWidth || 0;
          let rx = el.borderRadius || 0;

          let effectiveStroke = stroke;
          let effectiveStrokeW = strokeW;
          const polygonShapes = ['triangle', 'hexagon', 'arrow', 'diamond', 'pentagon', 'star', 'heart', 'cross', 'chevron', 'parallelogram', 'trapezoid'];
          let isPolygon = polygonShapes.includes(el.shapeType);

          if (isPolygon && rx > 0) {
            if (stroke === 'none' || strokeW === 0) {
              effectiveStroke = fill !== 'transparent' ? fill : 'none';
            }
            effectiveStrokeW = strokeW + (rx * 2);
          }

          let inset = effectiveStrokeW / 2;
          const w = el.width;
          const h = el.height;

          let shapeNode;
          if (el.shapeType === 'circle') {
            shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'ellipse');
            shapeNode.setAttribute('cx', w / 2);
            shapeNode.setAttribute('cy', h / 2);
            shapeNode.setAttribute('rx', Math.max(0, (w / 2) - inset));
            shapeNode.setAttribute('ry', Math.max(0, (h / 2) - inset));
          } else if (el.shapeType === 'ring') {
            // Ring: two concentric circles
            const outer = document.createElementNS('http://www.w3.org/2000/svg', 'ellipse');
            outer.setAttribute('cx', w / 2);
            outer.setAttribute('cy', h / 2);
            outer.setAttribute('rx', Math.max(0, (w / 2) - inset));
            outer.setAttribute('ry', Math.max(0, (h / 2) - inset));
            outer.setAttribute('fill', fill);
            outer.setAttribute('stroke', effectiveStroke);
            outer.setAttribute('stroke-width', effectiveStrokeW);
            svg.appendChild(outer);
            const inner = document.createElementNS('http://www.w3.org/2000/svg', 'ellipse');
            inner.setAttribute('cx', w / 2);
            inner.setAttribute('cy', h / 2);
            inner.setAttribute('rx', Math.max(0, (w / 4)));
            inner.setAttribute('ry', Math.max(0, (h / 4)));
            inner.setAttribute('fill', '#ffffff');
            inner.setAttribute('stroke', effectiveStroke);
            inner.setAttribute('stroke-width', effectiveStrokeW);
            svg.appendChild(inner);
            node.appendChild(svg);
            // Skip the normal append below
            shapeNode = null;
          } else if (el.shapeType === 'triangle') {
            shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
            shapeNode.setAttribute('points', `${w / 2},${inset} ${inset},${h - inset} ${w - inset},${h - inset}`);
          } else if (el.shapeType === 'diamond') {
            shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
            shapeNode.setAttribute('points', `${w / 2},${inset} ${w - inset},${h / 2} ${w / 2},${h - inset} ${inset},${h / 2}`);
          } else if (el.shapeType === 'pentagon') {
            const cx = w / 2, cy = h / 2, r = Math.min(w, h) / 2 - inset;
            const pts = [];
            for (let i = 0; i < 5; i++) {
              const a = (Math.PI * 2 * i / 5) - Math.PI / 2;
              pts.push(`${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`);
            }
            shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
            shapeNode.setAttribute('points', pts.join(' '));
          } else if (el.shapeType === 'hexagon') {
            shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
            shapeNode.setAttribute('points', `${w / 4},${inset} ${w * 3 / 4},${inset} ${w - inset},${h / 2} ${w * 3 / 4},${h - inset} ${w / 4},${h - inset} ${inset},${h / 2}`);
          } else if (el.shapeType === 'star') {
            const cx = w / 2, cy = h / 2;
            const outerR = Math.min(w, h) / 2 - inset;
            const innerR = outerR * 0.4;
            const pts = [];
            for (let i = 0; i < 10; i++) {
              const a = (Math.PI * 2 * i / 10) - Math.PI / 2;
              const r = i % 2 === 0 ? outerR : innerR;
              pts.push(`${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`);
            }
            shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
            shapeNode.setAttribute('points', pts.join(' '));
          } else if (el.shapeType === 'heart') {
            shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            const s = Math.min(w, h);
            const sx = w / 2, sy = h * 0.3;
            shapeNode.setAttribute('d', `M${sx},${h - inset} C${inset},${h * 0.55} ${inset},${inset} ${sx},${sy} C${w - inset},${inset} ${w - inset},${h * 0.55} ${sx},${h - inset}Z`);
          } else if (el.shapeType === 'cross') {
            const thicknessPct = (el.shapeThickness !== undefined ? el.shapeThickness : 50) / 100;
            const t = Math.min(w, h) * (0.05 + 0.4 * thicknessPct);
            const cx = w / 2, cy = h / 2;
            shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
            shapeNode.setAttribute('points', `${cx - t},${inset} ${cx + t},${inset} ${cx + t},${cy - t} ${w - inset},${cy - t} ${w - inset},${cy + t} ${cx + t},${cy + t} ${cx + t},${h - inset} ${cx - t},${h - inset} ${cx - t},${cy + t} ${inset},${cy + t} ${inset},${cy - t} ${cx - t},${cy - t}`);
          } else if (el.shapeType === 'chevron') {
            const notch = w * 0.3;
            shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
            shapeNode.setAttribute('points', `${inset},${inset} ${w - notch},${inset} ${w - inset},${h / 2} ${w - notch},${h - inset} ${inset},${h - inset} ${notch},${h / 2}`);
          } else if (el.shapeType === 'cloud') {
            shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            shapeNode.setAttribute('d', `M${w * 0.25},${h * 0.7} a${w * 0.15},${h * 0.15} 0 0,1 0,-${h * 0.3} a${w * 0.2},${h * 0.2} 0 0,1 ${w * 0.3},-${h * 0.15} a${w * 0.15},${h * 0.15} 0 0,1 ${w * 0.25},0 a${w * 0.15},${h * 0.15} 0 0,1 ${w * 0.1},${h * 0.25} a${w * 0.1},${h * 0.1} 0 0,1 -${w * 0.1},${h * 0.2} Z`);
          } else if (el.shapeType === 'speech-bubble') {
            shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            const r2 = Math.min(w, h) * 0.1;
            shapeNode.setAttribute('d', `M${inset + r2},${inset} h${w - 2 * inset - 2 * r2} a${r2},${r2} 0 0,1 ${r2},${r2} v${h * 0.6 - 2 * r2} a${r2},${r2} 0 0,1 -${r2},${r2} h-${w * 0.5} l-${w * 0.1},${h * 0.25} v-${h * 0.25} h-${w * 0.15 - r2} a${r2},${r2} 0 0,1 -${r2},-${r2} v-${h * 0.6 - 2 * r2} a${r2},${r2} 0 0,1 ${r2},-${r2}Z`);
          } else if (el.shapeType === 'parallelogram') {
            const skew = w * 0.2;
            shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
            shapeNode.setAttribute('points', `${skew + inset},${inset} ${w - inset},${inset} ${w - skew - inset},${h - inset} ${inset},${h - inset}`);
          } else if (el.shapeType === 'trapezoid') {
            const indent = w * 0.15;
            shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
            shapeNode.setAttribute('points', `${indent + inset},${inset} ${w - indent - inset},${inset} ${w - inset},${h - inset} ${inset},${h - inset}`);
          } else if (el.shapeType === 'rounded-rect') {
            shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
            shapeNode.setAttribute('x', inset);
            shapeNode.setAttribute('y', inset);
            shapeNode.setAttribute('width', Math.max(0, w - effectiveStrokeW));
            shapeNode.setAttribute('height', Math.max(0, h - effectiveStrokeW));
            const autoRx = Math.min(w, h) * 0.05;
            shapeNode.setAttribute('rx', autoRx);
            shapeNode.setAttribute('ry', autoRx);
          } else if (el.shapeType === 'arrow') {
            shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
            const thicknessPct = (el.shapeThickness !== undefined ? el.shapeThickness : 50) / 100;
            let headStart = w * 0.6;
            let bodyH = h * (0.1 + 0.8 * thicknessPct);
            let bodyY1 = (h - bodyH) / 2;
            let bodyY2 = bodyY1 + bodyH;
            shapeNode.setAttribute('points', `${inset},${bodyY1 + inset / 2} ${headStart},${bodyY1 + inset / 2} ${headStart},${inset} ${w - inset},${h / 2} ${headStart},${h - inset} ${headStart},${bodyY2 - inset / 2} ${inset},${bodyY2 - inset / 2}`);
          } else {
            // Default rect
            shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
            shapeNode.setAttribute('x', inset);
            shapeNode.setAttribute('y', inset);
            shapeNode.setAttribute('width', Math.max(0, w - effectiveStrokeW));
            shapeNode.setAttribute('height', Math.max(0, h - effectiveStrokeW));
            if (rx) {
              shapeNode.setAttribute('rx', rx);
              shapeNode.setAttribute('ry', rx);
            }
          }

          if (shapeNode) {
            if (isPolygon) shapeNode.setAttribute('stroke-linejoin', 'round');
            shapeNode.setAttribute('fill', fill);
            shapeNode.setAttribute('stroke', effectiveStroke);
            shapeNode.setAttribute('stroke-width', effectiveStrokeW);
            svg.appendChild(shapeNode);
            node.appendChild(svg);
          }
        }

        // Drag handler
        node.addEventListener('mousedown', (e) => this.onMouseDown(e, el, 'drag'));

        // Double click to inline edit content
        node.addEventListener('dblclick', (e) => {
          e.stopPropagation();
          if (el.type === 'text' || el.type === 'table') {
            if (node.querySelector('.inline-editor')) return; // Already editing

            const innerContent = node.querySelector('.canvas-text-content, .canvas-table-wrapper');
            if (innerContent) innerContent.style.visibility = 'hidden';

            const textarea = document.createElement('textarea');
            textarea.className = 'inline-editor';
            textarea.value = el.content || '';
            textarea.style.position = 'absolute';
            textarea.style.left = '0';
            textarea.style.top = '0';
            textarea.style.width = '100%';
            textarea.style.height = '100%';

            if (el.type === 'text') {
              textarea.style.background = 'transparent';
              textarea.style.color = el.color || '#000000';
              textarea.style.border = '1px dashed var(--accent)';
              textarea.style.textAlign = el.textAlign || 'left';
            } else {
              textarea.style.background = 'var(--bg-elevated)';
              textarea.style.color = 'var(--text-primary)';
              textarea.style.border = '2px solid var(--accent)';
            }

            textarea.style.padding = '8px';
            textarea.style.fontSize = (el.fontSize || 16) + 'px';
            textarea.style.fontFamily = el.fontFamily || 'inherit';
            textarea.style.resize = 'none';
            textarea.style.zIndex = '100';
            textarea.style.outline = 'none';

            node.appendChild(textarea);
            textarea.focus();

            const save = () => {
              el.content = textarea.value;
              textarea.remove();
              if (innerContent) innerContent.style.visibility = 'visible';
              this.renderCanvas();
              this.updatePropertiesPanel();
            };

            textarea.addEventListener('blur', save);
            textarea.addEventListener('mousedown', e => e.stopPropagation());
            // Optionally save on Shift+Enter or Escape
            textarea.addEventListener('keydown', e => {
              if (e.key === 'Escape') save();
              if (e.key === 'Enter' && e.shiftKey) save();
            });
          }
        });

        // Context Menu handler
        node.addEventListener('contextmenu', (e) => {
          e.preventDefault();
          e.stopPropagation();
          this.ctxMenuEl = el;
          this.selectElement(el);
          const menu = $('#pt-context-menu');
          if (menu) {
            menu.style.display = 'flex';
            // Simple bound checking to keep menu in window
            let x = e.clientX;
            let y = e.clientY;
            if (x + 200 > window.innerWidth) x = window.innerWidth - 200;
            if (y + 280 > window.innerHeight) y = window.innerHeight - 280;
            menu.style.left = x + 'px';
            menu.style.top = y + 'px';

            // Reset all items visibility (canvas paste-only menu may have hidden them)
            ['pt-ctx-copy', 'pt-ctx-cut', 'pt-ctx-duplicate', 'pt-ctx-forward', 'pt-ctx-backward', 'pt-ctx-front', 'pt-ctx-back', 'pt-ctx-delete'].forEach(id => {
              const btn = document.getElementById(id);
              if (btn) btn.style.display = id.includes('copy') || id.includes('cut') || id.includes('duplicate') ? 'flex' : 'block';
            });
            menu.querySelectorAll('div[style*="height:1px"]').forEach(d => d.style.display = 'block');

            // Show/hide image specific options
            const bgBtn = $('#pt-ctx-bg');
            if (bgBtn) bgBtn.style.display = el.type === 'image' ? 'block' : 'none';
            // Show/hide paste option based on clipboard
            const pasteBtn = $('#pt-ctx-paste');
            if (pasteBtn) pasteBtn.style.display = this._clipboard ? 'flex' : 'none';
          }
        });

        // Resize handles
        if (this.selectedElement === el) {
          ['tl', 'tr', 'bl', 'br'].forEach(handleType => {
            const h = document.createElement('div');
            h.className = `canvas-element-resize-handle handle-${handleType}`;
            h.addEventListener('mousedown', (e) => this.onMouseDown(e, el, 'resize', handleType));
            node.appendChild(h);
          });
        }

        c.appendChild(node);
      });
    }

    renderPages() {
      const list = $('#pt-pages-list');
      if (!list) return;

      if (!this.isUndoRedo) {
        this.saveStateDebounced();
      }
      list.innerHTML = '';

      this.pages.forEach((page, idx) => {
        const thumb = document.createElement('div');
        thumb.className = 'pt-page-thumbnail' + (this.currentPage === idx ? ' active' : '');
        thumb.style.background = '#ffffff'; // Default slide bg

        // Scale down the 800x450 canvas
        const scale = 100 / this.canvasW;

        const previewContainer = document.createElement('div');
        previewContainer.style.width = this.canvasW + 'px';
        previewContainer.style.height = this.canvasH + 'px';
        previewContainer.style.transform = `scale(${scale})`;
        previewContainer.style.transformOrigin = 'top left';
        previewContainer.style.position = 'absolute';
        previewContainer.style.top = '0';
        previewContainer.style.left = '0';
        previewContainer.style.pointerEvents = 'none';
        previewContainer.style.overflow = 'hidden';
        previewContainer.style.borderRadius = (4 / scale) + 'px';

        (page.elements || []).forEach(el => {
          const node = document.createElement('div');
          node.style.position = 'absolute';
          node.style.left = el.x + 'px';
          node.style.top = el.y + 'px';
          node.style.width = el.width + 'px';
          node.style.height = el.height + 'px';
          node.style.backgroundColor = el.backgroundColor || 'transparent';
          if (el.type === 'text') {
            node.innerText = el.content || '';
            node.style.fontSize = (el.fontSize || 24) + 'px';
            node.style.fontFamily = el.fontFamily || 'sans-serif';
            node.style.color = el.color || '#000000';
            node.style.overflow = 'hidden';
            if (el.isBold) node.style.fontWeight = 'bold';
            if (el.isItalic) node.style.fontStyle = 'italic';
            let decoration = '';
            if (el.isUnderline) decoration += ' underline';
            if (el.isStrikethrough) decoration += ' line-through';
            if (decoration) node.style.textDecoration = decoration.trim();
          } else if (el.type === 'image') {
            node.style.backgroundImage = `url(${el.content})`;
            node.style.backgroundSize = '100% 100%';
          }
          if (el.borderRadius) {
            node.style.borderRadius = `${el.borderRadius}px`;
          }
          if (el.type !== 'shape' && el.borderWidth) {
            node.style.border = `${el.borderWidth}px solid ${el.borderColor || 'transparent'}`;
          }
          previewContainer.appendChild(node);
        });

        thumb.appendChild(previewContainer);

        // Number badge
        const badge = document.createElement('div');
        badge.innerText = idx + 1;
        badge.style.position = 'absolute';
        badge.style.bottom = '2px';
        badge.style.right = '4px';
        badge.style.fontSize = '9px';
        badge.style.background = 'rgba(0,0,0,0.5)';
        badge.style.color = '#fff';
        badge.style.padding = '1px 4px';
        badge.style.borderRadius = '4px';
        badge.style.zIndex = '10';
        thumb.appendChild(badge);

        thumb.onclick = () => this.switchPage(idx);

        // Drag and drop for reordering
        thumb.draggable = true;
        thumb.ondragstart = (e) => {
          e.dataTransfer.setData('text/plain', idx);
          thumb.style.opacity = '0.5';
        };
        thumb.ondragover = (e) => {
          e.preventDefault(); // necessary to allow dropping
          thumb.style.border = '2px dashed var(--accent)';
        };
        thumb.ondragleave = (e) => {
          thumb.style.border = '';
        };
        thumb.ondrop = (e) => {
          e.preventDefault();
          thumb.style.border = '';
          const fromIdx = parseInt(e.dataTransfer.getData('text/plain'));
          if (!isNaN(fromIdx)) {
            this.reorderPage(fromIdx, idx);
          }
        };
        thumb.ondragend = () => {
          thumb.style.opacity = '';
        };

        const dupBtn = document.createElement('button');
        dupBtn.className = 'pt-page-duplicate';
        dupBtn.innerHTML = window.icon ? window.icon('copy', 14) : '⧉';
        dupBtn.title = 'Duplicate Slide';
        dupBtn.style.zIndex = '20';
        dupBtn.onclick = (e) => { e.stopPropagation(); this.duplicatePage(idx); };

        const delBtn = document.createElement('button');
        delBtn.className = 'pt-page-delete';
        delBtn.innerHTML = window.icon ? window.icon('x', 14) : '×';
        delBtn.title = 'Delete Slide';
        delBtn.style.zIndex = '20';
        delBtn.onclick = (e) => { e.stopPropagation(); this.deletePage(idx); };

        thumb.appendChild(dupBtn);
        thumb.appendChild(delBtn);
        list.appendChild(thumb);
      });
    }

    async openGallery() {
      const browser = $('#presentation-gallery-browser');
      const grid = $('#pt-gallery-grid');
      if (!browser || !grid) return;

      browser.style.display = 'block';
      grid.innerHTML = '<div style="padding:10px;color:var(--text-muted)">Loading...</div>';

      try {
        const res = await fetch('/image/gallery');
        if (!res.ok) throw new Error('Failed to load gallery');
        const data = await res.json();

        grid.innerHTML = '';
        let list = data.images || data.files || [];

        // Show all images (AI generated + uploaded), filter out videos only
        const images = list.filter(f => !f.isVideo);

        if (images.length === 0) {
          grid.innerHTML = '<div style="padding:10px;color:var(--text-muted)">No media images found. Generate some in Media mode!</div>';
          return;
        }

        images.forEach(img => {
          const div = document.createElement('div');
          div.className = 'pt-gallery-item';
          const imgUrl = img.url || `/data/images/${img.filename}`;
          div.innerHTML = `<img src="${imgUrl}" alt="${img.filename}">`;
          div.onclick = () => {
            this.addElement('image', imgUrl);
            browser.style.display = 'none';
          };
          grid.appendChild(div);
        });
      } catch (e) {
        grid.innerHTML = `<div style="padding:10px;color:var(--red)">${e.message}</div>`;
      }
    }

    async loadTemplates() {
      const list = $('#pt-templates-list');
      if (!list) return;
      list.innerHTML = '<div style="color:var(--text-muted)">Loading...</div>';
      try {
        const res = await fetch('/presentation/list');
        if (!res.ok) throw new Error('Failed to load templates');
        const data = await res.json();
        list.innerHTML = '';
        if (!data.presentations || data.presentations.length === 0) {
          list.innerHTML = '<div style="color:var(--text-muted)">No saved presentations found.</div>';
          return;
        }
        data.presentations.forEach(p => {
          const btn = document.createElement('div');
          btn.className = 'presentation-template-tile';

          const dateStr = new Date(p.updated_at * 1000).toLocaleDateString();
          const imgHtml = p.thumbnail ?
            `<img src="${p.thumbnail}?t=${p.updated_at}">` :
            `<div class="no-preview" style="display:flex; align-items:center; justify-content:center; font-size:10px; color:#666;">No Preview</div>`;
          btn.style.position = 'relative';
          btn.innerHTML = `
             ${imgHtml}
             <div class="template-info" style="display:flex; flex-direction:column; gap:2px; flex: 1;">
               <strong>${p.title || p.id}</strong>
               <small>${dateStr}</small>
             </div>
             <button class="pt-template-rename" title="Rename Template" style="position: absolute; top: 4px; right: 32px; background: rgba(0,0,0,0.6); border: none; color: white; border-radius: 4px; padding: 4px; cursor: pointer; display: flex; align-items: center; justify-content: center; width: 24px; height: 24px; z-index: 10;">
               ${window.icon ? window.icon('pen', 14) : '✎'}
             </button>
             <button class="pt-template-delete" title="Delete Template" style="position: absolute; top: 4px; right: 4px; background: rgba(0,0,0,0.6); border: none; color: white; border-radius: 4px; padding: 4px; cursor: pointer; display: flex; align-items: center; justify-content: center; width: 24px; height: 24px; z-index: 10;">
               ${window.icon ? window.icon('trash', 14) : '×'}
             </button>
           `;

          const renBtn = btn.querySelector('.pt-template-rename');
          renBtn.onclick = async (e) => {
            e.stopPropagation();
            const newTitle = prompt('Rename template to:', p.title || p.id);
            if (newTitle && newTitle.trim() !== '') {
              try {
                const rr = await fetch(`/presentation/rename/${p.id}`, {
                  method: 'PUT',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ title: newTitle.trim() })
                });
                if (rr.ok) {
                  toast(ICONS.check(14) + ' Template renamed');
                  this.loadTemplates();
                } else {
                  toast(' Failed to rename', 4000);
                }
              } catch (err) {
                toast(' Error renaming template', 4000);
              }
            }
          };

          const delBtn = btn.querySelector('.pt-template-delete');
          delBtn.onclick = async (e) => {
            e.stopPropagation();
            if (confirm('Delete this template?')) {
              try {
                const dr = await fetch(`/presentation/delete/${p.id}`, { method: 'DELETE' });
                if (dr.ok) {
                  btn.remove();
                  if (this.presId === p.id) {
                    this.presId = null;
                    localStorage.removeItem('pt-last-id');
                  }
                  toast(ICONS.check(14) + ' Template deleted');
                } else {
                  toast(' Failed to delete template', 4000);
                }
              } catch (err) {
                toast(' Failed to delete template', 4000);
              }
            }
          };

          btn.onclick = async () => {
            const isEmpty = this.pages.length === 0 || (this.pages.length === 1 && this.pages[0].elements.length === 0);

            let mode = 'replace';
            if (!isEmpty) {
              const action = confirm('Cliquez sur OK pour REMPLACER vos slides actuels par ce template.\nCliquez sur Annuler pour AJOUTER ces slides à votre présentation actuelle.');
              mode = action ? 'replace' : 'add';
            } else {
              if (!confirm('Charger ce template ?')) return;
            }

            try {
              const lr = await fetch(`/presentation/load/${p.id}`);
              if (lr.ok) {
                const ldata = await lr.json();
                const loadedPages = ldata.pages || [{ elements: [] }];

                if (mode === 'replace') {
                  this.pages = loadedPages;
                  this.canvasW = ldata.canvas_width || 960;
                  this.canvasH = ldata.canvas_height || 540;
                  this.currentPage = 0;
                } else {
                  const newPages = JSON.parse(JSON.stringify(loadedPages));
                  newPages.forEach(page => {
                    page.elements.forEach(el => el.id = 'el_' + Math.random().toString(36).substr(2, 9));
                    this.pages.push(page);
                  });
                  this.currentPage = this.pages.length - newPages.length; // Jump to the first newly added page
                }

                // Sauvegarde par défaut a un nouveau template
                this.presId = null;
                localStorage.removeItem('pt-last-id');
                this.title = (ldata.title ? ldata.title + ' (Copie)' : 'Nouveau Template');
                if ($('#pt-pres-title')) $('#pt-pres-title').value = this.title;

                this.selectElement(null);
                this.renderPages();
                this.renderCanvas();

                const tplBrowser = $('#presentation-templates-browser');
                if (tplBrowser) tplBrowser.style.display = 'none';

                toast(mode === 'replace' ? ' Template chargé!' : ' Slides ajoutés!');
              }
            } catch (e) {
              toast(' Échec du chargement du template', 4000);
            }
          };
          list.appendChild(btn);
        });
      } catch (e) {
        list.innerHTML = `<div style="color:var(--red)">${e.message}</div>`;
      }
    }

    loadLibrary() {
      if (!window.lucide || !window.lucide.icons) {
        toast('Lucide icons library not loaded yet.', 3000);
        return;
      }
      this.filterLibrary('');
    }

    filterLibrary(query) {
      if (!window.lucide || !window.lucide.icons) return;
      const grid = $('#pt-library-grid');
      if (!grid) return;

      const browser = $('#presentation-library-browser');
      const q = (query || '').toLowerCase().trim();
      const icons = window.lucide.icons;
      // limit to 100 for performance
      const keys = Object.keys(icons).filter(k => k.toLowerCase().includes(q)).slice(0, 100);

      grid.innerHTML = '';
      if (keys.length === 0) {
        grid.innerHTML = '<div style="color:var(--text-muted); grid-column: 1 / -1; text-align: center;">No icons found.</div>';
        return;
      }

      keys.forEach(k => {
        const btn = document.createElement('button');
        btn.className = 'presentation-shape-tile';
        btn.title = k;
        btn.style.width = '100%';
        btn.style.height = '40px';
        const node = window.lucide.createElement(icons[k]);
        btn.innerHTML = node.outerHTML;
        btn.onclick = () => {
          this.addElement('icon', { name: k, svg: node.outerHTML });
          if (browser) browser.style.display = 'none';
        };
        grid.appendChild(btn);
      });
    }

    // ---- SVG Illustrations Browser ----
    async loadIllustrations() {
      const grid = $('#pt-illustrations-grid');
      if (!grid) return;
      grid.innerHTML = '<div style="color:var(--text-muted); grid-column: 1 / -1; text-align:center">Loading...</div>';

      try {
        const res = await fetch('/presentation/svg-catalog');
        if (!res.ok) throw new Error('Failed to load catalog');
        const data = await res.json();
        this._illustrationsCatalog = data.illustrations || [];
        this._illustrationsCategories = data.categories || {};
        this.filterIllustrations('');
      } catch (e) {
        grid.innerHTML = `<div style="color:var(--red); grid-column: 1 / -1">${e.message}</div>`;
      }
    }

    filterIllustrations(query) {
      const grid = $('#pt-illustrations-grid');
      if (!grid || !this._illustrationsCatalog) return;
      const q = (query || '').toLowerCase().trim();

      const filtered = this._illustrationsCatalog.filter(i => i.name.toLowerCase().includes(q));
      grid.innerHTML = '';

      if (filtered.length === 0) {
        grid.innerHTML = '<div style="color:var(--text-muted); grid-column: 1 / -1; text-align:center">No illustrations found.</div>';
        return;
      }

      filtered.forEach(item => {
        const btn = document.createElement('button');
        btn.className = 'presentation-shape-tile';
        btn.title = item.name;
        btn.style.width = '100%';
        btn.style.height = '60px';
        btn.style.padding = '4px';
        btn.innerHTML = item.svg;
        const svg = btn.querySelector('svg');
        if (svg) {
          svg.style.width = '100%';
          svg.style.height = '100%';
        }
        btn.onclick = () => {
          // Convert SVG to data URI and add as image element
          const blob = new Blob([item.svg], { type: 'image/svg+xml' });
          const url = URL.createObjectURL(blob);
          const el = this.addElement('image', url);
          el.width = 200;
          el.height = 200;
          this.renderCanvas();
          const browser = $('#presentation-illustrations-browser');
          if (browser) browser.style.display = 'none';
          toast(ICONS.check(14) + ` Illustration "${item.name}" added`);
        };
        grid.appendChild(btn);
      });
    }

    // ---- Local Open-Source Stock Photo Library ----
    async loadStockPhotos(category = '') {
      const input = $('#pt-stock-search-input');
      const grid = $('#pt-stock-grid');
      if (!grid) return;
      const query = input ? input.value.trim() : '';

      grid.innerHTML = '<div style="color:var(--text-muted); column-span: all; text-align:center">Loading...</div>';

      try {
        const params = new URLSearchParams();
        if (query) params.set('q', query);
        if (category) params.set('category', category);
        const res = await fetch(`/presentation/stock-images?${params}`);
        if (!res.ok) throw new Error('Failed to load stock images');
        const data = await res.json();

        grid.innerHTML = '';

        // Category filter tabs
        if (data.categories && data.categories.length > 0) {
          const tabs = document.createElement('div');
          tabs.style.cssText = 'column-span: all; display:flex; flex-wrap:wrap; gap:4px; padding-bottom:8px; border-bottom:1px solid var(--border); margin-bottom:4px';

          const allBtn = document.createElement('button');
          allBtn.className = 'btn btn-sm ' + (!category ? 'btn-primary' : 'btn-secondary');
          allBtn.textContent = 'All';
          allBtn.style.cssText = 'padding:2px 8px; font-size:11px; border-radius:12px';
          allBtn.onclick = () => this.loadStockPhotos('');
          tabs.appendChild(allBtn);

          data.categories.forEach(cat => {
            const btn = document.createElement('button');
            btn.className = 'btn btn-sm ' + (category === cat ? 'btn-primary' : 'btn-secondary');
            btn.textContent = cat.charAt(0).toUpperCase() + cat.slice(1);
            btn.style.cssText = 'padding:2px 8px; font-size:11px; border-radius:12px; text-transform:capitalize';
            btn.onclick = () => this.loadStockPhotos(cat);
            tabs.appendChild(btn);
          });
          grid.appendChild(tabs);
        }

        if (!data.images || data.images.length === 0) {
          grid.innerHTML += `<div style="color:var(--text-muted); column-span: all; text-align:center; font-size:12px; padding:20px">${data.message || 'No images found. Run: python scripts/download_stock_images.py'}</div>`;
          return;
        }

        data.images.forEach(img => {
          const div = document.createElement('div');
          div.className = 'pt-stock-item';
          div.style.position = 'relative';
          div.style.marginBottom = '8px';
          div.style.breakInside = 'avoid';
          div.innerHTML = `<img src="${img.url}" alt="${escHtml(img.description || '')}" loading="lazy" style="width:100%; border-radius:4px; display:block;">`;

          if (img.author_name) {
            // Author attribution badge
            const badge = document.createElement('div');
            badge.style.cssText = 'position:absolute;bottom:0;left:0;right:0;font-size:9px;color:white;background:linear-gradient(transparent, rgba(0,0,0,0.8));padding:12px 6px 4px;border-bottom-left-radius:4px;border-bottom-right-radius:4px;opacity:0;transition:opacity 0.2s;';
            const authorLink = img.author_link ? `${img.author_link}?utm_source=clawzd&utm_medium=referral` : '#';
            badge.innerHTML = `By <a href="${authorLink}" target="_blank" style="color:var(--accent);text-decoration:none;" onclick="event.stopPropagation()">${escHtml(img.author_name)}</a>`;

            div.onmouseenter = () => badge.style.opacity = '1';
            div.onmouseleave = () => badge.style.opacity = '0';
            div.appendChild(badge);
          } else if (img.category) {
            const badge = document.createElement('div');
            badge.style.cssText = 'position:absolute;top:3px;left:3px;font-size:9px;color:white;background:rgba(0,0,0,0.6);padding:1px 6px;border-radius:8px';
            badge.textContent = img.category || '';
            div.appendChild(badge);
          }

          div.onclick = () => {
            const el = this.addElement('image', img.url);
            if (img.author_name) {
              el.attribution = `Photo by ${img.author_name} on Unsplash`;
            }
            const browser = $('#presentation-stock-browser');
            if (browser) browser.style.display = 'none';
            toast(ICONS.check(14) + ` Image added`);
          };
          grid.appendChild(div);
        });

        // Credit footer
        const credit = document.createElement('div');
        credit.style.cssText = 'column-span: all; text-align: center; font-size: 10px; color: var(--text-muted); padding: 4px';
        credit.textContent = `${data.total} open-source images • Free to use`;
        grid.appendChild(credit);
      } catch (e) {
        grid.innerHTML = `<div style="color:var(--red); column-span: all;">${e.message}</div>`;
      }
    }

    newPresentation() {
      this.pages = [{ elements: [] }];
      this.currentPage = 0;
      this.selectedElement = null;
      this.presId = null;
      localStorage.removeItem('pt-last-id');

      const titleInput = $('#pt-pres-title');
      if (titleInput) titleInput.value = 'My Presentation';

      this.renderPages();
      this.renderCanvas();
      this.updatePropertiesPanel();
      toast(ICONS.fileText(14) + ' New blank presentation created');
    }

    async save(silent = false) {
      const titleInput = $('#pt-pres-title');
      const name = titleInput ? titleInput.value.trim() : "My Presentation";
      this.title = name || "My Presentation";

      if (!silent) toast(ICONS.hourglass(14) + ' Saving presentation... (This might take a moment to generate the preview)');
      try {
        const res = await fetch('/presentation/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            id: this.presId,
            title: this.title,
            pages: this.pages,
            canvas_width: this.canvasW,
            canvas_height: this.canvasH
          })
        });
        if (!res.ok) throw new Error('Failed to save');
        const data = await res.json();
        this.presId = data.id;
        localStorage.setItem('pt-last-id', data.id);
        if (!silent) toast(ICONS.check(14) + ' Presentation saved persistently!');
      } catch (e) {
        if (!silent) toast(` Save error: ${e.message}`, 4000);
      }
    }

    async enhanceSelectedText() {
      if (!this.selectedElement || this.selectedElement.type !== 'text') {
        toast('Please select a text element first.');
        return;
      }

      const btn = $('#pt-prop-ai-enhance');
      const originalText = btn.innerText;
      btn.innerText = ' Enhancing...';
      btn.disabled = true;

      try {
        const res = await fetch('/presentation/ai-enrich', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt: this.selectedElement.content,
            mode: 'enhance'
          })
        });

        if (!res.ok) throw new Error('API error');
        const data = await res.json();

        if (data.result) {
          this.selectedElement.content = data.result;
          $('#pt-prop-content').value = data.result;
          this.renderCanvas();
          toast(ICONS.check(14) + ' Text enhanced!');
        }
      } catch (e) {
        toast(' Enhancement failed: ' + e.message);
      } finally {
        btn.innerText = originalText;
        btn.disabled = false;
      }
    }

    async enrichPresentation() {
      const btn = $('#pt-ai-enrich');
      if (!btn) return;

      btn.classList.add('loading');
      btn.disabled = true;
      toast(ICONS.sparkles(14) + ' AI is enriching the current page...');

      try {
        const page = this.pages[this.currentPage];
        const textContents = page.elements
          .filter(e => e.type === 'text' && e.content)
          .map(e => e.content)
          .join(' | ');

        const userInput = $('#pt-ai-prompt') ? $('#pt-ai-prompt').value.trim() : '';
        let finalPrompt = '';
        let mode = 'bullets';

        if (userInput) {
          finalPrompt = textContents ? `Current slide text: ${textContents}\n\nUser request: ${userInput}` : userInput;
          mode = 'enhance';
        } else {
          if (!textContents) {
            toast('No text found on page to enrich. Please provide a prompt or select a slide with text.');
            btn.classList.remove('loading');
            btn.disabled = false;
            return;
          }
          finalPrompt = textContents;
          mode = 'bullets';
        }

        const res = await fetch('/presentation/ai-enrich', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt: finalPrompt,
            mode: mode
          })
        });

        if (!res.ok) throw new Error('API error');
        const data = await res.json();

        if (data.result) {
          this.addElement('text', data.result);
          const newEl = this.pages[this.currentPage].elements[this.pages[this.currentPage].elements.length - 1];
          newEl.x = this.canvasW / 2 - 150;
          newEl.y = this.canvasH / 2 - 50;
          newEl.width = Math.min(this.canvasW - 40, Math.max(300, newEl.content.length * 5));
          if (mode === 'bullets' || data.result.includes('\\n- ')) newEl.isList = true;
          this.selectElement(newEl);
          this.renderCanvas();
          toast(ICONS.check(14) + ' AI enriched text added to canvas!');
        }
      } catch (e) {
        toast(' Enrichment failed: ' + e.message);
      } finally {
        btn.classList.remove('loading');
        btn.disabled = false;
      }
    }

    async generatePresentation() {
      const input = $('#pt-ai-prompt');
      const btn = $('#pt-ai-generate');
      if (!input || !btn) return;

      const prompt = input.value.trim();
      if (!prompt) { toast('Please enter a description for your presentation.'); return; }

      btn.classList.add('loading');
      btn.disabled = true;
      toast(ICONS.sparkles(14) + ' AI is generating your presentation...');

      try {
        const res = await fetch('/presentation/ai-generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt,
            canvas_width: this.canvasW,
            canvas_height: this.canvasH
          })
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: 'Server error' }));
          throw new Error(err.detail || 'Generation failed');
        }

        const data = await res.json();

        if (data.pages && data.pages.length > 0) {
          this.pages = data.pages;
          this.currentPage = 0;
          this.selectElement(null);
          if (data.title) {
            this.title = data.title;
            if ($('#pt-pres-title')) $('#pt-pres-title').value = data.title;
          }
          this.renderPages();
          this.renderCanvas();
          toast(` Generated ${data.pages.length} slide(s)!`, 4000);
          input.value = '';
        } else {
          throw new Error('AI returned empty presentation');
        }
      } catch (e) {
        toast(` AI generation failed: ${e.message}`, 5000);
      } finally {
        btn.classList.remove('loading');
        btn.disabled = false;
      }
    }
    async export(format, pagesMode = 'all', customPages = '') {
      toast(`${ICONS.hourglass(14)} Generating ${format.toUpperCase()}...`);

      let pagesToExport = [];
      if (pagesMode === 'current') {
        pagesToExport = [JSON.parse(JSON.stringify(this.pages[this.currentPage]))];
      } else if (pagesMode === 'custom' && customPages) {
        const selected = [];
        const parts = customPages.split(',');
        for (let p of parts) {
          p = p.trim();
          if (p.includes('-')) {
            const [start, end] = p.split('-').map(Number);
            if (!isNaN(start) && !isNaN(end)) {
              for (let i = start; i <= end; i++) {
                if (i >= 1 && i <= this.pages.length) selected.push(this.pages[i - 1]);
              }
            }
          } else {
            const i = parseInt(p);
            if (!isNaN(i) && i >= 1 && i <= this.pages.length) {
              selected.push(this.pages[i - 1]);
            }
          }
        }
        if (selected.length > 0) pagesToExport = JSON.parse(JSON.stringify(selected));
        else pagesToExport = JSON.parse(JSON.stringify(this.pages));
      } else {
        pagesToExport = JSON.parse(JSON.stringify(this.pages));
      }

      // Convert mermaid elements to base64 PNGs for export
      if (window.mermaid) {
        for (const page of pagesToExport) {
          for (const el of page.elements) {
            if (el.type === 'mermaid') {
              try {
                const id = 'mmr-export-' + Math.random().toString(36).substr(2, 9);
                // Temporarily create a div to hold the SVG if mermaid requires it
                const r = await mermaid.render(id, el.content || 'graph TD; A-->B;');
                const svgStr = r.svg;

                // Convert SVG to PNG
                const pngDataUrl = await new Promise((resolve) => {
                  const img = new Image();
                  img.onload = () => {
                    const canvas = document.createElement('canvas');
                    canvas.width = el.width || 800;
                    canvas.height = el.height || 600;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                    resolve(canvas.toDataURL('image/png'));
                  };
                  img.onerror = () => resolve(null);
                  img.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgStr)));
                });

                if (pngDataUrl) {
                  el.type = 'image';
                  el.src = pngDataUrl;
                }
              } catch (e) {
                console.warn('Failed to render mermaid for export', e);
              }
            }
          }
        }
      }

      try {
        const res = await fetch('/presentation/export', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            format: format,
            pages: pagesToExport,
            canvas_width: this.canvasW,
            canvas_height: this.canvasH
          })
        });

        if (!res.ok) {
          const err = await res.text();
          throw new Error(err);
        }

        const data = await res.json();
        toast(` Successfully created ${data.filename}! Downloading...`, 4000);

        const a = document.createElement('a');
        a.href = data.url;
        a.download = data.filename;
        a.click();
      } catch (e) {
        toast(` Failed to export ${format.toUpperCase()}: ${e.message}`, 5000);
      }
    }

    _updateDocgenVisibility() {
      const isCard = this.templateSubMode === 'business_card';
      const show = id => { const el = document.getElementById(id); if (el) el.style.display = ''; };
      const hide = id => { const el = document.getElementById(id); if (el) el.style.display = 'none'; };

      const tplIds = [
        'pt-tpl-style-group', 'pt-tpl-cv-style-group',
        'pt-tpl-linkedin-group', 'pt-tpl-target-role-group',
        'pt-tpl-company-group', 'pt-tpl-summary-group',
        'pt-tpl-skills-group', 'pt-tpl-location-group',
        'pt-tpl-linkedin-preview'
      ];
      tplIds.forEach(id => hide(id));

      if (isCard) {
        show('pt-tpl-style-group');
        show('pt-tpl-company-group');
      } else {
        show('pt-tpl-cv-style-group');
        show('pt-tpl-linkedin-group');
        show('pt-tpl-target-role-group');
        show('pt-tpl-summary-group');
        show('pt-tpl-skills-group');
        show('pt-tpl-location-group');
        if (this._linkedInData) show('pt-tpl-linkedin-preview');
      }
    }

    async fetchLinkedInProfile() {
      const urlInput = $('#pt-tpl-linkedin-url');
      const statusEl = $('#pt-tpl-linkedin-status');
      const url = (urlInput?.value || '').trim();
      if (!url || !url.includes('linkedin.com')) {
        toast(ICONS.circle(14) + ' Veuillez entrer une URL LinkedIn valide');
        return;
      }
      if (statusEl) { statusEl.style.display = ''; statusEl.innerHTML = '⏳ Récupération du profil LinkedIn...'; }
      const fetchBtn = $('#pt-tpl-linkedin-fetch');
      if (fetchBtn) { fetchBtn.disabled = true; fetchBtn.textContent = '⏳...'; }
      try {
        const targetRole = ($('#pt-tpl-target-role') || {}).value || '';
        const resp = await fetch('/docgen/scrape-linkedin', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url, target_role: targetRole })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Fetch failed');
        const p = data.profile;
        this._linkedInData = p;
        if (p.name) { const el = $('#pt-tpl-name'); if (el && !el.value) el.value = p.name; }
        if (p.headline) { const el = $('#pt-tpl-title'); if (el && !el.value) el.value = p.headline; }
        if (p.summary || p.enriched_summary) { const el = $('#pt-tpl-summary'); if (el && !el.value) el.value = p.enriched_summary || p.summary; }
        if (p.location) { const el = $('#pt-tpl-location'); if (el && !el.value) el.value = p.location; }
        if (p.skills?.length) { const el = $('#pt-tpl-skills'); if (el && !el.value) el.value = p.skills.join(', '); }
        const previewEl = $('#pt-tpl-linkedin-data');
        const previewGrp = $('#pt-tpl-linkedin-preview');
        if (previewEl && previewGrp) {
          let html = `<strong>${p.name || '—'}</strong>`;
          if (p.headline) html += `<br>📌 ${p.headline}`;
          if (p.photo_url) html += `<br><img src="${p.photo_url}" style="width:60px;height:60px;border-radius:50%;margin-top:6px;object-fit:cover;">`;
          if (p.seo_keywords?.length) html += `<br>🏷️ <em>${p.seo_keywords.slice(0, 8).join(', ')}</em>`;
          previewEl.innerHTML = html;
          previewGrp.style.display = '';
        }
        if (statusEl) { statusEl.innerHTML = '✅ Profil LinkedIn importé avec succès'; }
        toast('✅ Profil LinkedIn importé !');
      } catch (e) {
        if (statusEl) { statusEl.innerHTML = `❌ Erreur: ${e.message}`; }
        toast('❌ ' + e.message);
      } finally {
        if (fetchBtn) { fetchBtn.disabled = false; fetchBtn.textContent = '🔍 Fetch'; }
      }
    }

    async generateTemplate() {
      if (this.generating) return;
      const name = ($('#pt-tpl-name') || {}).value?.trim();
      if (!name) { toast(ICONS.circle(14) + ' Le nom est requis'); return; }
      this.generating = true;
      const genBtn = $('#pt-tpl-generate-btn');
      if (genBtn) { genBtn.classList.add('loading'); genBtn.disabled = true; }
      try {
        let resp, endpoint;
        if (this.templateSubMode === 'business_card') {
          endpoint = '/docgen/generate-business-card';
          resp = await fetch(endpoint, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              name,
              title: ($('#pt-tpl-title') || {}).value || '',
              company: ($('#pt-tpl-company') || {}).value || '',
              email: ($('#pt-tpl-email') || {}).value || '',
              phone: ($('#pt-tpl-phone') || {}).value || '',
              website: ($('#pt-tpl-website') || {}).value || '',
              style: ($('#pt-tpl-style') || {}).value || 'modern',
            })
          });
        } else {
          endpoint = '/docgen/generate-cv';
          const skillsStr = ($('#pt-tpl-skills') || {}).value || '';
          const skills = skillsStr ? skillsStr.split(',').map(s => s.trim()).filter(Boolean) : [];
          resp = await fetch(endpoint, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              name,
              title: ($('#pt-tpl-title') || {}).value || '',
              email: ($('#pt-tpl-email') || {}).value || '',
              phone: ($('#pt-tpl-phone') || {}).value || '',
              website: ($('#pt-tpl-website') || {}).value || '',
              summary: ($('#pt-tpl-summary') || {}).value || '',
              location: ($('#pt-tpl-location') || {}).value || '',
              skills,
              seo_keywords: this._linkedInData?.seo_keywords || [],
              experience: this._linkedInData?.experience || [],
              education: this._linkedInData?.education || [],
              photo_url: this._linkedInData?.photo_url || '',
              linkedin_url: ($('#pt-tpl-linkedin-url') || {}).value || '',
              target_role: ($('#pt-tpl-target-role') || {}).value || '',
              style: ($('#pt-tpl-cv-style') || {}).value || 'professional',
            })
          });
        }
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Generation failed');
        toast(`✅ ${this.templateSubMode === 'business_card' ? 'Carte de visite' : 'CV'} généré !`);
        if (data.seo_keywords?.length) {
          toast(`🏷️ Mots-clés SEO: ${data.seo_keywords.slice(0, 5).join(', ')}`, 5000);
        }
        if (data.presentation) {
          this.pages = data.presentation.pages;
          this.canvasW = data.presentation.canvas_width;
          this.canvasH = data.presentation.canvas_height;
          this.currentPage = 0;

          const c = $('#presentation-canvas');
          if (c) {
            c.style.width = this.canvasW + 'px';
            c.style.height = this.canvasH + 'px';
          }

          this.renderPages();
          this.renderCanvas();
          this.updateCanvasZoom();
          this.saveState();

          const sel = $('#pt-format-select');
          if (sel) {
            if (this.canvasW === 638 && this.canvasH === 368) sel.value = 'card';
            else if (this.canvasW === 794 && this.canvasH === 1123) sel.value = 'A4';
          }
        }
      } catch (e) {
        toast('❌ ' + e.message);
      } finally {
        this.generating = false;
        if (genBtn) { genBtn.classList.remove('loading'); genBtn.disabled = false; }
      }
    }
  }

  // ---- Automation Studio ----
  class AutomationStudio {
    constructor() {
      this.layout = $('#automation-layout');
      this.canvas = $('#auto-canvas');
      this.nodesLayer = $('#auto-nodes-layer');
      this.connsLayer = $('#auto-connections-layer');
      this.wfList = $('#auto-wf-list');
      this.propsBody = $('#auto-props-body');
      this.propsPanel = $('#auto-props-panel');
      this.propsEmpty = $('#auto-props-empty');
      this.nameInput = $('#auto-wf-name');
      this.descInput = $('#auto-wf-desc');
      this.activeToggle = $('#auto-wf-active');
      this.nodes = []; this.connections = [];
      this._allWorkflows = [];
      this.currentWf = null; this.selectedNode = null;
      this.nodeTypes = {}; this.dragNode = null;
      this.pan = { x: 0, y: 0 }; this.isPanning = false;
      this.connecting = null; this.tempLine = null;
      this.selectedConnection = null;
      this._nextId = 1;
      this._init();
    }
    async _init() {
      // Load node types
      try { const r = await fetch('/automation/node-types'); const d = await r.json(); this.nodeTypes = d.types || {}; this.modelsByProvider = d.models_by_provider || {}; } catch (e) { }
      // Buttons
      $('#auto-btn-new')?.addEventListener('click', () => this.createWorkflow());
      $('#auto-btn-globals')?.addEventListener('click', () => this.openGlobalsModal());
      $('#auto-btn-save')?.addEventListener('click', () => this.saveWorkflow());
      $('#auto-btn-execute')?.addEventListener('click', () => this.executeWorkflow(false));
      $('#auto-btn-test')?.addEventListener('click', () => this.executeWorkflow(true));
      $('#auto-props-delete')?.addEventListener('click', () => this.deleteSelectedNode());
      $('#auto-exec-log-close')?.addEventListener('click', () => { $('#auto-exec-log').style.display = 'none'; });
      $('#auto-btn-ai-generate')?.addEventListener('click', () => this.generateWorkflowAI());
      $('#auto-ai-prompt')?.addEventListener('keypress', (e) => { if (e.key === 'Enter') this.generateWorkflowAI(); });

      // Globals UI
      $('#auto-btn-globals-cancel')?.addEventListener('click', () => { $('#auto-globals-modal').style.display = 'none'; });
      $('#auto-btn-globals-save')?.addEventListener('click', () => this.saveGlobals());
      $('#auto-btn-add-global')?.addEventListener('click', () => this.addGlobalRow());

      // Palette drag and icons
      $$('.auto-palette-node').forEach(n => {
        n.addEventListener('dragstart', e => { e.dataTransfer.setData('text/plain', n.dataset.type); });
      });
      $$('.auto-icon').forEach(n => {
        if (window.icon && n.dataset.icon) {
          n.innerHTML = window.icon(n.dataset.icon, 14);
          n.style.marginRight = '8px';
          n.style.display = 'inline-flex';
          n.style.alignItems = 'center';
        }
      });
      // Search: Workflows
      $('#auto-wf-search')?.addEventListener('input', e => this._filterWorkflows(e.target.value));
      $('#auto-wf-search-clear')?.addEventListener('click', () => { const s = $('#auto-wf-search'); if (s) { s.value = ''; this._filterWorkflows(''); } });
      // Search: Palette
      $('#auto-palette-search')?.addEventListener('input', e => this._filterPalette(e.target.value));
      $('#auto-palette-search-clear')?.addEventListener('click', () => { const s = $('#auto-palette-search'); if (s) { s.value = ''; this._filterPalette(''); } });
      // Canvas drop
      const wrap = $('#auto-canvas-wrap');
      wrap?.addEventListener('dragover', e => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
      wrap?.addEventListener('drop', e => {
        e.preventDefault();
        const type = e.dataTransfer.getData('text/plain');
        if (!type || !this.nodeTypes[type]) return;
        const rect = this.canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left - this.pan.x);
        const y = (e.clientY - rect.top - this.pan.y);
        this.addNode(type, x, y);
      });
      // Canvas pan
      this.canvas?.addEventListener('mousedown', e => {
        if (e.target === this.canvas || e.target.tagName === 'rect' && !e.target.classList.contains('auto-node-body')) {
          this.isPanning = true; this._panStart = { x: e.clientX - this.pan.x, y: e.clientY - this.pan.y };
          this.selectedConnection = null;
          this.deselectNode();
        }
      });
      window.addEventListener('mousemove', e => {
        if (this.isPanning) {
          this.pan.x = e.clientX - this._panStart.x;
          this.pan.y = e.clientY - this._panStart.y;
          this.nodesLayer.setAttribute('transform', `translate(${this.pan.x},${this.pan.y})`);
          this.connsLayer.setAttribute('transform', `translate(${this.pan.x},${this.pan.y})`);
        }
        if (this.connecting && this.tempLine) {
          const rect = this.canvas.getBoundingClientRect();
          const mx = e.clientX - rect.left - this.pan.x;
          const my = e.clientY - rect.top - this.pan.y;
          const sx = this.connecting.portX, sy = this.connecting.portY;
          this.tempLine.setAttribute('d', `M${sx},${sy} C${sx + 80},${sy} ${mx - 80},${my} ${mx},${my}`);
        }
        if (this.dragNode) {
          const rect = this.canvas.getBoundingClientRect();
          this.dragNode.node.x = e.clientX - rect.left - this.pan.x - this.dragNode.ox;
          this.dragNode.node.y = e.clientY - rect.top - this.pan.y - this.dragNode.oy;
          this.renderNodes(); this.renderConnections();
        }
      });
      window.addEventListener('mouseup', () => {
        this.isPanning = false; this.dragNode = null;
        if (this.connecting) { this._cancelConnect(); }
      });
      // Keyboard: Delete / Backspace to remove selected node or connection
      window.addEventListener('keydown', e => {
        if (e.key !== 'Delete' && e.key !== 'Backspace') return;
        // Don't intercept when typing in inputs
        const tag = document.activeElement?.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        // Only when automation mode is visible
        if (!this.layout || this.layout.style.display === 'none') return;
        e.preventDefault();
        if (this.selectedNode) {
          this.deleteSelectedNode();
        } else if (this.selectedConnection !== null && this.selectedConnection !== undefined) {
          this.connections.splice(this.selectedConnection, 1);
          this.selectedConnection = null;
          this.renderConnections();
        }
      });
      // Load workflows
      this.loadWorkflows();
    }
    toggle(show) {
      if (this.layout) this.layout.style.display = show ? 'flex' : 'none';
      if (show) this.loadWorkflows();
    }
    // ── Globals Management ──
    async openGlobalsModal() {
      const modal = $('#auto-globals-modal');
      if (!modal) return;
      modal.style.display = 'flex';
      $('#auto-globals-list').innerHTML = '<div style="color:var(--text-muted)">Loading...</div>';
      try {
        const r = await fetch('/automation/globals');
        const d = await r.json();
        this.globalsData = d.globals || {};
        this.renderGlobalsList();
      } catch (e) {
        toast(ICONS.x(14) + ' Failed to load globals');
      }
    }
    renderGlobalsList() {
      const list = $('#auto-globals-list');
      if (!list) return;
      list.innerHTML = '';
      const keys = Object.keys(this.globalsData);
      if (keys.length === 0) {
        list.innerHTML = '<div style="color:var(--text-muted); font-size:12px; margin-bottom:10px;">No global variables yet.</div>';
      }
      keys.forEach(k => {
        this.addGlobalRow(k, this.globalsData[k]);
      });
    }
    addGlobalRow(key = '', val = '') {
      const list = $('#auto-globals-list');
      if (!list) return;
      const row = document.createElement('div');
      row.style.display = 'flex';
      row.style.gap = '8px';

      const keyInp = document.createElement('input');
      keyInp.className = 'auto-prop-input global-key';
      keyInp.placeholder = 'Key (e.g. API_KEY)';
      keyInp.value = key;
      keyInp.style.flex = '1';

      const valInp = document.createElement('input');
      valInp.className = 'auto-prop-input global-val';
      valInp.placeholder = 'Value';
      valInp.value = val;
      valInp.style.flex = '2';

      const delBtn = document.createElement('button');
      delBtn.className = 'icon-btn';
      delBtn.style.color = '#ff5555';
      delBtn.innerHTML = window.icon ? window.icon('trash', 14) : '';
      delBtn.onclick = () => row.remove();

      row.appendChild(keyInp);
      row.appendChild(valInp);
      row.appendChild(delBtn);
      list.appendChild(row);
    }
    async saveGlobals() {
      const modal = $('#auto-globals-modal');
      const list = $('#auto-globals-list');
      if (!modal || !list) return;

      const newGlobals = {};
      Array.from(list.children).forEach(row => {
        const k = row.querySelector('.global-key')?.value.trim();
        const v = row.querySelector('.global-val')?.value.trim();
        if (k) newGlobals[k] = v || '';
      });

      try {
        const r = await fetch('/automation/globals', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ globals: newGlobals })
        });
        if (r.ok) {
          toast(ICONS.check(14) + ' Global variables saved');
          modal.style.display = 'none';
        } else {
          toast(ICONS.x(14) + ' Failed to save globals');
        }
      } catch (e) {
        toast(ICONS.x(14) + ' Error saving globals');
      }
    }
    // ── Node Management ──
    addNode(type, x, y) {
      const nt = this.nodeTypes[type];
      if (!nt) return;
      const id = 'n' + (this._nextId++);
      const node = { id, type, label: nt.label, x: Math.round(x), y: Math.round(y), params: {} };
      // Set default params
      (nt.params || []).forEach(p => { node.params[p.key] = p.default ?? ''; });
      this.nodes.push(node);
      this.renderNodes(); this.renderConnections();
      this.selectNode(id);
      return node;
    }
    selectNode(id) {
      this.selectedNode = id;
      this.selectedConnection = null;
      this.renderNodes();
      this.renderConnections();
      this.renderProps();
    }
    deselectNode() {
      this.selectedNode = null;
      this.renderNodes();
      if (this.propsPanel) this.propsPanel.style.display = 'none';
      if (this.propsEmpty) this.propsEmpty.style.display = '';
    }
    deleteSelectedNode() {
      if (!this.selectedNode) return;
      this.nodes = this.nodes.filter(n => n.id !== this.selectedNode);
      this.connections = this.connections.filter(c => c.source !== this.selectedNode && c.target !== this.selectedNode);
      this.deselectNode(); this.renderNodes(); this.renderConnections();
    }
    // ── SVG Rendering ──
    renderNodes() {
      if (!this.nodesLayer) return;
      this.nodesLayer.innerHTML = '';
      const NW = 180, NH = 60, HH = 28;
      this.nodes.forEach(node => {
        const nt = this.nodeTypes[node.type] || {};
        const color = nt.color || '#666';
        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        g.setAttribute('class', 'auto-node-group' + (this.selectedNode === node.id ? ' selected' : ''));
        g.setAttribute('transform', `translate(${node.x},${node.y})`);
        // Body
        const body = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        body.setAttribute('class', 'auto-node-body');
        body.setAttribute('width', NW); body.setAttribute('height', NH);
        body.setAttribute('rx', 8); body.setAttribute('ry', 8);
        g.appendChild(body);
        // Header
        const hdr = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        hdr.setAttribute('width', NW); hdr.setAttribute('height', HH);
        hdr.setAttribute('rx', 8); hdr.setAttribute('ry', 8);
        hdr.setAttribute('fill', color); hdr.setAttribute('fill-opacity', '0.9');
        g.appendChild(hdr);
        // Header bottom (square corners)
        const hdr2 = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        hdr2.setAttribute('x', 0); hdr2.setAttribute('y', HH - 8);
        hdr2.setAttribute('width', NW); hdr2.setAttribute('height', 8);
        hdr2.setAttribute('fill', color); hdr2.setAttribute('fill-opacity', '0.9');
        g.appendChild(hdr2);
        // Icon
        const iconName = nt.icon || 'bolt';
        const iconWrapper = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        iconWrapper.setAttribute('transform', `translate(8, ${HH / 2 - 9})`);
        iconWrapper.style.color = '#ffffff';
        if (window.icon) {
          iconWrapper.innerHTML = window.icon(iconName, 18);
        }
        g.appendChild(iconWrapper);

        // Title
        const ttl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        ttl.setAttribute('class', 'auto-node-title');
        ttl.setAttribute('x', 32); ttl.setAttribute('y', HH / 2 + 4);
        ttl.textContent = (node.label || nt.label || node.type).substring(0, 18);
        g.appendChild(ttl);
        // Subtitle (type)
        const sub = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        sub.setAttribute('class', 'auto-node-subtitle');
        sub.setAttribute('x', 10); sub.setAttribute('y', NH - 8);
        sub.textContent = node.type;
        g.appendChild(sub);
        // Input ports
        const inputs = nt.inputs || [];
        inputs.forEach((inp, i) => {
          const py = HH + (NH - HH) / (inputs.length + 1) * (i + 1);
          const port = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
          port.setAttribute('class', 'auto-node-port');
          port.setAttribute('cx', 0); port.setAttribute('cy', py);
          port.setAttribute('r', 6);
          port.setAttribute('data-node', node.id); port.setAttribute('data-port', inp);
          port.setAttribute('data-dir', 'input');
          port.addEventListener('mouseup', e => { e.stopPropagation(); this._finishConnect(node.id, inp); });
          g.appendChild(port);
        });
        // Output ports
        const outputs = nt.outputs || [];
        outputs.forEach((out, i) => {
          const py = HH + (NH - HH) / (outputs.length + 1) * (i + 1);
          const port = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
          port.setAttribute('class', 'auto-node-port');
          port.setAttribute('cx', NW); port.setAttribute('cy', py);
          port.setAttribute('r', 6);
          port.setAttribute('data-node', node.id); port.setAttribute('data-port', out);
          port.setAttribute('data-dir', 'output');
          port.addEventListener('mousedown', e => {
            e.stopPropagation();
            this._startConnect(node.id, out, node.x + NW, node.y + py);
          });
          g.appendChild(port);
          if (outputs.length > 1) {
            const lbl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            lbl.setAttribute('class', 'auto-node-port-label');
            lbl.setAttribute('x', NW + 10); lbl.setAttribute('y', py + 3);
            lbl.textContent = out;
            g.appendChild(lbl);
          }
        });
        // Drag
        g.addEventListener('mousedown', e => {
          if (e.target.classList.contains('auto-node-port')) return;
          e.stopPropagation();
          this.selectNode(node.id);
          const rect = this.canvas.getBoundingClientRect();
          this.dragNode = { node, ox: e.clientX - rect.left - this.pan.x - node.x, oy: e.clientY - rect.top - this.pan.y - node.y };
        });
        this.nodesLayer.appendChild(g);
      });
    }
    renderConnections() {
      if (!this.connsLayer) return;
      this.connsLayer.innerHTML = '';
      const NW = 180, NH = 60, HH = 28;
      this.connections.forEach((conn, idx) => {
        const src = this.nodes.find(n => n.id === conn.source);
        const tgt = this.nodes.find(n => n.id === conn.target);
        if (!src || !tgt) return;
        const srcNt = this.nodeTypes[src.type] || {};
        const tgtNt = this.nodeTypes[tgt.type] || {};
        const srcOutputs = srcNt.outputs || ['main'];
        const srcIdx = Math.max(0, srcOutputs.indexOf(conn.sourceOutput || 'main'));
        const sx = src.x + NW;
        const sy = src.y + HH + (NH - HH) / (srcOutputs.length + 1) * (srcIdx + 1);
        const tgtInputs = tgtNt.inputs || ['main'];
        const tgtIdx = Math.max(0, tgtInputs.indexOf(conn.targetInput || 'main'));
        const tx = tgt.x;
        const ty = tgt.y + HH + (NH - HH) / (tgtInputs.length + 1) * (tgtIdx + 1);
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const dx = Math.abs(tx - sx) * 0.5;
        path.setAttribute('d', `M${sx},${sy} C${sx + dx},${sy} ${tx - dx},${ty} ${tx},${ty}`);
        path.setAttribute('class', 'auto-connection' + (this.selectedConnection === idx ? ' selected' : ''));
        if (this.selectedConnection === idx) {
          path.setAttribute('stroke', 'var(--accent)'); path.setAttribute('stroke-width', '3');
        }
        path.addEventListener('click', (e) => {
          e.stopPropagation();
          this.deselectNode();
          this.selectedConnection = idx;
          this.renderConnections();
        });
        path.addEventListener('dblclick', () => {
          this.connections = this.connections.filter(c => c !== conn);
          this.selectedConnection = null;
          this.renderConnections();
        });
        this.connsLayer.appendChild(path);
      });
    }
    // ── Connection drawing ──
    _startConnect(nodeId, output, px, py) {
      this.connecting = { nodeId, output, portX: px, portY: py };
      this.tempLine = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      this.tempLine.setAttribute('class', 'auto-connection-temp');
      this.tempLine.setAttribute('d', `M${px},${py} C${px},${py} ${px},${py} ${px},${py}`);
      this.connsLayer.appendChild(this.tempLine);
    }
    _finishConnect(targetId, targetInput) {
      if (!this.connecting || this.connecting.nodeId === targetId) { this._cancelConnect(); return; }
      // Check for duplicate
      const exists = this.connections.some(c => c.source === this.connecting.nodeId && c.sourceOutput === this.connecting.output && c.target === targetId && c.targetInput === targetInput);
      if (!exists) {
        this.connections.push({ source: this.connecting.nodeId, sourceOutput: this.connecting.output, target: targetId, targetInput: targetInput });
      }
      this._cancelConnect();
      this.renderConnections();
    }
    _cancelConnect() {
      this.connecting = null;
      if (this.tempLine) { this.tempLine.remove(); this.tempLine = null; }
    }
    // ── Properties Panel ──
    renderProps() {
      const node = this.nodes.find(n => n.id === this.selectedNode);
      if (!node) { this.deselectNode(); return; }
      const nt = this.nodeTypes[node.type] || {};
      if (this.propsEmpty) this.propsEmpty.style.display = 'none';
      if (this.propsPanel) this.propsPanel.style.display = '';
      const title = $('#auto-props-title');
      if (title) title.textContent = `${nt.icon || ''} ${nt.label || node.type}`;
      if (!this.propsBody) return;
      this.propsBody.innerHTML = '';
      // Label edit
      const labelGrp = document.createElement('div'); labelGrp.className = 'auto-prop-group';
      labelGrp.innerHTML = `<label class="auto-prop-label">Label</label>`;
      const labelInp = document.createElement('input'); labelInp.className = 'auto-prop-input';
      labelInp.value = node.label || nt.label || ''; labelInp.addEventListener('input', () => { node.label = labelInp.value; this.renderNodes(); });
      labelGrp.appendChild(labelInp); this.propsBody.appendChild(labelGrp);
      // Params
      const inputsByKey = {};
      (nt.params || []).forEach(p => {
        const grp = document.createElement('div'); grp.className = 'auto-prop-group';
        grp.innerHTML = `<label class="auto-prop-label">${p.label}</label>`;
        let inp;
        if (p.type === 'textarea') {
          inp = document.createElement('textarea'); inp.className = 'auto-prop-textarea';
          inp.value = node.params[p.key] ?? p.default ?? '';
          inp.rows = 4;
        } else if (p.type === 'select') {
          inp = document.createElement('select'); inp.className = 'auto-prop-select';
          (p.options || []).forEach(o => { const opt = document.createElement('option'); opt.value = o; opt.textContent = o; inp.appendChild(opt); });
          inp.value = node.params[p.key] ?? p.default ?? '';
        } else if (p.type === 'number') {
          inp = document.createElement('input'); inp.className = 'auto-prop-input';
          inp.type = 'number'; inp.value = node.params[p.key] ?? p.default ?? 0;
        } else {
          inp = document.createElement('input'); inp.className = 'auto-prop-input';
          inp.type = 'text'; inp.value = node.params[p.key] ?? p.default ?? '';
        }
        inp.addEventListener('input', () => { node.params[p.key] = inp.value; });
        inp.addEventListener('change', () => { node.params[p.key] = inp.value; });
        inputsByKey[p.key] = inp;
        grp.appendChild(inp); this.propsBody.appendChild(grp);
      });

      // Provider -> Model linking
      if (inputsByKey['provider'] && inputsByKey['model']) {
        const provInp = inputsByKey['provider'];
        const modInp = inputsByKey['model'];

        let selectMod = modInp;
        if (modInp.tagName !== 'SELECT') {
          selectMod = document.createElement('select');
          selectMod.className = 'auto-prop-select';
          modInp.parentNode.replaceChild(selectMod, modInp);
          inputsByKey['model'] = selectMod;
          selectMod.addEventListener('change', () => { node.params['model'] = selectMod.value; });
        }

        const updateModels = () => {
          const prov = provInp.value;
          const models = this.modelsByProvider[prov] || [];
          const currentMod = node.params['model'];

          selectMod.innerHTML = '';
          models.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m;
            opt.textContent = m;
            selectMod.appendChild(opt);
          });

          if (models.includes(currentMod)) {
            selectMod.value = currentMod;
          } else if (models.length > 0) {
            selectMod.value = models[0];
            node.params['model'] = models[0];
          } else {
            node.params['model'] = '';
          }
        };

        provInp.addEventListener('change', updateModels);
        updateModels(); // Initialize options for the currently selected provider
      }
    }
    // ── Workflow CRUD ──
    async loadWorkflows() {
      try {
        const r = await fetch('/automation/workflows'); const d = await r.json();
        this._allWorkflows = d.workflows || [];
        this._renderWorkflowList();
      } catch (e) { console.error('Failed to load workflows', e); }
    }
    _renderWorkflowList(filter = '') {
      const wfs = this._allWorkflows;
      if (!this.wfList) return;
      const q = filter.toLowerCase().trim();
      const filtered = q ? wfs.filter(wf => {
        const name = (wf.name || '').toLowerCase();
        const desc = (wf.description || '').toLowerCase();
        const nodeTypes = (wf.nodes || []).map(n => (n.type || '') + ' ' + (n.label || '')).join(' ').toLowerCase();
        return name.includes(q) || desc.includes(q) || nodeTypes.includes(q);
      }) : wfs;
      if (!filtered.length) {
        this.wfList.innerHTML = q
          ? '<div class="auto-wf-empty">No matching workflows.</div>'
          : '<div class="auto-wf-empty">No workflows yet.<br>Click + to create one.</div>';
        return;
      }
      this.wfList.innerHTML = '';
      filtered.forEach(wf => {
        const item = document.createElement('div');
        item.className = 'auto-wf-item' + (this.currentWf?.id === wf.id ? ' active' : '');
        const descHint = wf.description ? `<span class="auto-wf-item-desc">${wf.description.substring(0, 40)}</span>` : '';
        item.innerHTML = `<div class="auto-wf-item-info"><span class="auto-wf-item-name">${wf.name}</span>${descHint}</div>` +
          `<span class="auto-wf-item-badge ${wf.active ? 'active' : 'inactive'}">${wf.active ? 'ON' : 'OFF'}</span>` +
          `<span class="auto-wf-item-delete" title="Delete"></span>`;
        item.querySelector('.auto-wf-item-info').addEventListener('click', () => this.loadWorkflow(wf.id));
        item.querySelector('.auto-wf-item-delete').addEventListener('click', async e => {
          e.stopPropagation();
          await fetch(`/automation/workflows/${wf.id}`, { method: 'DELETE' });
          if (this.currentWf?.id === wf.id) { this.currentWf = null; this.nodes = []; this.connections = []; this.renderNodes(); this.renderConnections(); this.deselectNode(); }
          this.loadWorkflows(); toast(ICONS.circle(14) + ' ️ Workflow deleted');
        });
        this.wfList.appendChild(item);
      });
    }
    _filterWorkflows(q) { this._renderWorkflowList(q); }
    _filterPalette(q) {
      const palette = $('#auto-palette');
      if (!palette) return;
      const term = q.toLowerCase().trim();
      palette.querySelectorAll('.auto-palette-group').forEach(group => {
        let anyVisible = false;
        group.querySelectorAll('.auto-palette-node').forEach(node => {
          const text = node.textContent.toLowerCase();
          const type = (node.dataset.type || '').toLowerCase();
          const match = !term || text.includes(term) || type.includes(term);
          node.style.display = match ? '' : 'none';
          if (match) anyVisible = true;
        });
        group.style.display = anyVisible ? '' : 'none';
      });
    }
    async loadWorkflow(id) {
      try {
        const r = await fetch(`/automation/workflows/${id}`); const d = await r.json();
        const wf = d.workflow;
        this.currentWf = wf; this.nodes = wf.nodes || []; this.connections = wf.connections || [];
        if (this.nameInput) this.nameInput.value = wf.name || '';
        if (this.descInput) this.descInput.value = wf.description || '';
        if (this.activeToggle) this.activeToggle.checked = wf.active || false;
        // Recalculate next id
        this._nextId = 1;
        this.nodes.forEach(n => { const num = parseInt(n.id.replace('n', '')); if (num >= this._nextId) this._nextId = num + 1; });
        this.deselectNode(); this.renderNodes(); this.renderConnections(); this.loadWorkflows();
        toast(`${ICONS.folderOpen(14)} Loaded: ${wf.name}`);
      } catch (e) { toast(ICONS.x(14) + ' Failed to load workflow'); }
    }
    async createWorkflow() {
      const name = prompt('Workflow name:', 'New Workflow');
      if (!name?.trim()) return;
      try {
        const r = await fetch('/automation/workflows', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name.trim() }) });
        const d = await r.json();
        this.currentWf = d.workflow; this.nodes = []; this.connections = [];
        if (this.nameInput) this.nameInput.value = name.trim();
        if (this.descInput) this.descInput.value = '';
        if (this.activeToggle) this.activeToggle.checked = false;
        this.deselectNode(); this.renderNodes(); this.renderConnections(); this.loadWorkflows();
        toast(`${ICONS.check(14)} Workflow created: ${name.trim()}`);
      } catch (e) { toast(ICONS.x(14) + ' Failed to create workflow'); }
    }
    async saveWorkflow() {
      if (!this.currentWf) { toast(ICONS.circle(14) + ' ️ Create a workflow first'); return; }
      const name = this.nameInput?.value || this.currentWf.name;
      const description = this.descInput?.value || '';
      const active = this.activeToggle?.checked || false;
      try {
        await fetch(`/automation/workflows/${this.currentWf.id}`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, description, nodes: this.nodes, connections: this.connections, active })
        });
        this.currentWf.name = name; this.currentWf.description = description; this.currentWf.active = active;
        this.loadWorkflows(); toast(ICONS.download(14) + ' Workflow saved!');
      } catch (e) { toast(ICONS.x(14) + ' Failed to save workflow'); }
    }
    async executeWorkflow(testingMode = false) {
      if (!this.currentWf) { toast(ICONS.circle(14) + ' ️ No workflow loaded'); return; }
      // Save first
      await this.saveWorkflow();
      toast(testingMode ? ' Testing workflow (no real sends)...' : ICONS.play(14) + ' Executing workflow...');
      const logEl = $('#auto-exec-log'); const logBody = $('#auto-exec-log-body');
      if (logEl) logEl.style.display = '';
      if (logBody) logBody.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted)">⏳ Running...</div>';
      try {
        const r = await fetch(`/automation/workflows/${this.currentWf.id}/execute`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ testing_mode: testingMode })
        });
        const result = await r.json();
        if (logBody) {
          logBody.innerHTML = '';
          // Testing mode header
          if (testingMode) {
            const banner = document.createElement('div');
            banner.className = 'auto-test-banner';
            banner.innerHTML = ' <strong>TESTING MODE</strong> — Communication nodes were simulated, no real messages sent.';
            logBody.appendChild(banner);
          }
          (result.log || []).forEach(entry => {
            const div = document.createElement('div'); div.className = 'auto-log-entry';
            div.style.cursor = 'pointer';
            div.style.flexDirection = 'column';
            div.style.alignItems = 'stretch';

            const header = document.createElement('div');
            header.style.display = 'flex';
            header.style.alignItems = 'center';
            header.style.gap = '10px';
            const simBadge = entry.simulated ? '<span class="auto-test-badge"> SIM</span>' : '';
            header.innerHTML = `<div class="auto-log-status ${entry.status}"></div>` +
              `<span class="auto-log-node" style="min-width:120px;"><strong>${entry.node_label || entry.node_type}</strong></span>` +
              simBadge +
              `<span class="auto-log-duration" style="font-size:12px;opacity:0.7;">${Math.round(entry.duration_ms)}ms</span>` +
              `<span class="auto-log-preview" style="flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${(entry.output_preview || '').substring(0, 80)}</span>`;

            const details = document.createElement('div');
            details.style.display = 'none';
            details.style.marginTop = '8px';
            details.style.padding = '8px';
            details.style.background = 'var(--bg-elevated)';
            details.style.borderRadius = '4px';
            details.style.fontSize = '12px';
            details.style.whiteSpace = 'pre-wrap';
            details.style.wordBreak = 'break-word';
            details.style.borderLeft = entry.status === 'error' ? '3px solid var(--red)' : entry.simulated ? '3px solid #f59e0b' : '3px solid var(--accent)';
            const fullRes = result.results ? result.results[entry.node_id] : entry.output_preview;
            details.textContent = fullRes || 'No details';

            div.appendChild(header);
            div.appendChild(details);

            div.onclick = () => {
              details.style.display = details.style.display === 'none' ? 'block' : 'none';
            };

            logBody.appendChild(div);
          });
        }
        const isTest = result.testing_mode;
        if (isTest) {
          toast(result.status.includes('error') ? ' Test completed with errors' : ' Test completed successfully!');
        } else {
          toast(result.status === 'success' ? ' Workflow completed!' : '️ Workflow completed with errors');
        }
      } catch (e) { toast(' Execution failed: ' + e.message); }
    }

    async generateWorkflowAI() {
      const input = $('#auto-ai-prompt');
      const prompt = input?.value.trim();
      if (!prompt) { toast('Please enter a description for the workflow.'); return; }
      const btn = $('#auto-btn-ai-generate');
      if (btn) { btn.disabled = true; btn.classList.add('loading'); }
      toast(ICONS.sparkles(14) + ' AI is generating/updating your workflow...');

      try {
        const res = await fetch('/automation/workflows/ai-generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt: prompt,
            current_workflow: this.currentWf ? { nodes: this.nodes, connections: this.connections, name: this.nameInput?.value } : null
          })
        });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        if (data.nodes) {
          this.nodes = data.nodes;
          this.connections = data.connections || [];
          if (data.name && this.nameInput) this.nameInput.value = data.name;
          if (!this.currentWf) {
            // Create a new local unsaved workflow context if not loaded
            this.currentWf = { id: 'temp_' + Date.now(), name: data.name || 'AI Workflow', active: false };
            if (this.nameInput) this.nameInput.value = this.currentWf.name;
          }
          // Recalculate nextId
          this._nextId = 1;
          this.nodes.forEach(n => { const num = parseInt(n.id.replace('n', '')); if (num >= this._nextId) this._nextId = num + 1; });

          this.renderNodes();
          this.renderConnections();
          this.deselectNode();
          toast(ICONS.check(14) + ' Workflow updated by AI! Remember to Save.');
        } else {
          throw new Error('Invalid AI response');
        }
      } catch (e) {
        toast(' AI Generation failed: ' + e.message);
      } finally {
        if (btn) { btn.disabled = false; btn.classList.remove('loading'); }
      }
    }
  }

  // ---- Twitter Watch Manager ----
  class TwitterWatch {
    constructor() {
      this._watchlist = [];
      this._platform = 'twitter';
      this._init();
    }

    _init() {
      // Search
      const searchBtn = $('#tw-search-btn');
      const searchInput = $('#tw-search-input');
      if (searchBtn) searchBtn.addEventListener('click', () => this.doSearch());
      if (searchInput) searchInput.addEventListener('keydown', e => { if (e.key === 'Enter') this.doSearch(); });
      // Platform toggle
      $$('.tw-platform-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          $$('.tw-platform-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          this._platform = btn.dataset.platform;
          const liType = $('#tw-linkedin-type');
          if (liType) liType.style.display = this._platform === 'linkedin' ? '' : 'none';
          if (searchInput) searchInput.placeholder = this._platform === 'linkedin' ? 'Search LinkedIn profiles or articles...' : 'Search tweets, @user, or #hashtag...';
        });
      });
      $$('.tw-tab').forEach(tab => {
        tab.addEventListener('click', () => {
          $$('.tw-tab').forEach(t => t.classList.remove('active'));
          tab.classList.add('active');
          const view = tab.dataset.twView;
          $('#tw-results')?.classList.toggle('active', view === 'results');
          $('#tw-trending')?.classList.toggle('active', view === 'trending');
          $('#tw-watchlist')?.classList.toggle('active', view === 'watchlist');
        });
      });
      const loadTrending = $('#tw-load-trending');
      if (loadTrending) loadTrending.addEventListener('click', () => this.loadTrending());
      const addWatch = $('#tw-watchlist-add');
      if (addWatch) addWatch.addEventListener('click', () => this.addWatch());
      const refreshWatch = $('#tw-watchlist-refresh');
      if (refreshWatch) refreshWatch.addEventListener('click', () => this.refreshWatchlist());
    }
    _switchToResults() {
      $$('.tw-tab').forEach(t => t.classList.remove('active'));
      $('#tw-tab-results')?.classList.add('active');
      $('#tw-results')?.classList.add('active');
      $('#tw-trending')?.classList.remove('active');
      $('#tw-watchlist')?.classList.remove('active');
    }

    async doSearch() {
      const input = $('#tw-search-input'), q = input?.value.trim();
      if (!q) return;
      this._switchToResults();
      const feed = $('#tw-feed'), empty = $('#tw-empty');
      if (empty) empty.style.display = 'none';
      const label = this._platform === 'linkedin' ? 'LinkedIn' : 'X';
      if (feed) feed.innerHTML = `<div class="tw-loading"><div class="spinner"></div>Searching ${label}...</div>`;
      try {
        if (this._platform === 'linkedin') {
          const liType = $('#tw-linkedin-type')?.value || 'profiles';
          const res = await fetch(`/twitter/linkedin/${liType}?q=${encodeURIComponent(q)}`);
          const data = await res.json();
          this.renderLinkedIn(data.results || [], feed, empty);
        } else {
          const isUser = q.startsWith('@');
          const url = isUser ? `/twitter/user/${encodeURIComponent(q.replace('@', ''))}` : `/twitter/search?q=${encodeURIComponent(q)}`;
          const res = await fetch(url);
          const data = await res.json();
          this.renderTweets(data.tweets || [], feed, empty);
        }
      } catch (e) {
        if (feed) feed.innerHTML = '';
        if (empty) { empty.style.display = ''; empty.innerHTML = '<p>Search failed.</p>'; }
      }
    }

    renderTweets(tweets, feed, empty) {
      if (!feed) return;
      feed.innerHTML = '';
      if (!tweets.length) {
        if (empty) { empty.style.display = ''; empty.innerHTML = '<p>No results found.</p>'; }
        return;
      }
      if (empty) empty.style.display = 'none';
      tweets.forEach(t => {
        const card = document.createElement('div');
        card.className = 'tw-card';
        const avatarHtml = t.author_avatar
          ? `<img src="${t.author_avatar}" alt="">`
          : `<svg class="ic" width="14" height="14"><use href="#icon-x-twitter"></use></svg>`;
        const timeStr = t.created_at ? this._relTime(t.created_at) : '';
        card.innerHTML = `
          <div class="tw-card-header">
            <div class="tw-card-avatar">${avatarHtml}</div>
            <div class="tw-card-author">
              <div class="tw-card-name">${this._esc(t.author_name || 'Unknown')}</div>
              <div class="tw-card-handle">${t.author_username ? '@' + this._esc(t.author_username) : ''}</div>
            </div>
            <span class="tw-card-time">${timeStr}</span>
          </div>
          <div class="tw-card-text">${this._linkify(this._esc(t.text || ''))}</div>
          <div class="tw-card-metrics">
            <span class="tw-metric likes">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>
              ${t.likes || 0}
            </span>
            <span class="tw-metric retweets">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>
              ${t.retweets || 0}
            </span>
            <span class="tw-metric replies">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
              ${t.replies || 0}
            </span>
            ${t.url ? `<a class="tw-card-link" href="${t.url}" target="_blank" rel="noopener">Open ↗</a>` : ''}
            ${t.source ? `<span class="tw-card-source">via ${t.source}</span>` : ''}
          </div>
        `;
        feed.appendChild(card);
      });
    }
    renderLinkedIn(items, feed, empty) {
      if (!feed) return;
      if (!items.length) { if (empty) { empty.style.display = ''; empty.innerHTML = '<p>No LinkedIn results.</p>'; } return; }
      if (empty) empty.style.display = 'none';
      items.forEach(item => {
        const card = document.createElement('div');
        card.className = 'li-card';
        if (item.type === 'profile') {
          const photoHtml = item.photo ? `<img src="${item.photo}" alt="">` : `<span class="li-initials">${(item.name || '?').split(' ').map(w => w[0]).join('').slice(0, 2)}</span>`;
          card.innerHTML = `<div class="li-card-header"><div class="li-card-photo">${photoHtml}</div><div class="li-card-info"><div class="li-card-name">${this._esc(item.name || 'Unknown')}</div><div class="li-card-headline">${this._esc(item.headline || '')}</div></div></div>${item.snippet ? `<div class="li-card-snippet">${this._esc(item.snippet)}</div>` : ''}<div class="li-card-footer"><span class="li-card-type profile">Profile</span>${item.url ? `<a class="li-card-link" href="${item.url}" target="_blank" rel="noopener">View on LinkedIn ↗</a>` : ''}</div>`;
        } else {
          card.innerHTML = `<div class="li-card-header"><div class="li-card-photo"><svg class="ic" width="18" height="18"><use href="#icon-file-text"></use></svg></div><div class="li-card-info"><div class="li-card-name">${this._esc(item.title || 'Article')}</div><div class="li-card-headline">${item.author ? 'by ' + this._esc(item.author) : ''}</div></div></div>${item.snippet ? `<div class="li-card-snippet">${this._esc(item.snippet)}</div>` : ''}<div class="li-card-footer"><span class="li-card-type article">Article</span>${item.url ? `<a class="li-card-link" href="${item.url}" target="_blank" rel="noopener">Read on LinkedIn ↗</a>` : ''}</div>`;
        }
        feed.appendChild(card);
      });
    }

    async loadTrending() {
      const list = $('#tw-trending-list');
      if (!list) return;
      list.innerHTML = '<div class="tw-loading"><div class="spinner"></div>Loading trends...</div>';
      try {
        const res = await fetch('/twitter/trending');
        const data = await res.json();
        const trends = data.trends || [];
        list.innerHTML = '';
        if (!trends.length) {
          list.innerHTML = '<div class="tw-empty"><p>No trending data available.</p></div>';
          return;
        }
        trends.forEach(t => {
          const item = document.createElement('div');
          item.className = 'tw-trending-item';
          item.innerHTML = `
            <span class="tw-trending-rank">${t.rank || ''}</span>
            <span class="tw-trending-name">${this._esc(t.name)}</span>
            ${t.tweet_count ? `<span class="tw-trending-count">${t.tweet_count} tweets</span>` : ''}
          `;
          item.addEventListener('click', () => {
            const input = $('#tw-search-input');
            if (input) { input.value = t.name; this.doSearch(); }
          });
          list.appendChild(item);
        });
      } catch (e) {
        list.innerHTML = '<div class="tw-empty"><p>Failed to load trends.</p></div>';
      }
    }

    async loadWatchlist() {
      try {
        const res = await fetch('/twitter/watchlist');
        const data = await res.json();
        this._watchlist = data.watchlist || [];
        this._renderWatchlist();
      } catch (e) { /* silent */ }
    }

    _renderWatchlist() {
      const list = $('#tw-watchlist-list');
      const badge = $('#tw-watchlist-badge');
      if (!list) return;
      if (badge) badge.textContent = this._watchlist.length || '';
      if (!this._watchlist.length) {
        list.innerHTML = '<div class="tw-empty"><p>No watches yet. Add keywords or usernames to monitor.</p></div>';
        return;
      }
      list.innerHTML = '';
      this._watchlist.forEach(item => {
        const el = document.createElement('div');
        el.className = 'tw-watchlist-item';
        const plat = item.platform || 'twitter';
        const platIcon = plat === 'linkedin' ? '#icon-linkedin' : '#icon-x-twitter';
        el.innerHTML = `
          <svg class="ic" width="12" height="12" style="flex-shrink:0;opacity:.6"><use href="${platIcon}"></use></svg>
          <span class="tw-watchlist-type ${item.type}">${item.type}</span>
          <span class="tw-watchlist-value">${this._esc(item.value)}</span>
          <button class="tw-watchlist-delete" title="Remove">
            <svg class="ic" width="10" height="10"><use href="#icon-x"></use></svg>
          </button>
        `;
        // Click value to search
        el.querySelector('.tw-watchlist-value').addEventListener('click', () => {
          // Switch platform
          if (plat === 'linkedin') { $$('.tw-platform-btn').forEach(b => b.classList.remove('active')); $('#tw-plat-linkedin')?.classList.add('active'); this._platform = 'linkedin'; const lt = $('#tw-linkedin-type'); if (lt) lt.style.display = ''; }
          else { $$('.tw-platform-btn').forEach(b => b.classList.remove('active')); $('#tw-plat-twitter')?.classList.add('active'); this._platform = 'twitter'; const lt = $('#tw-linkedin-type'); if (lt) lt.style.display = 'none'; }
          const input = $('#tw-search-input');
          if (input) { input.value = item.type === 'user' ? '@' + item.value : item.value; this.doSearch(); }
          this._switchToResults();
        });
        // Delete
        el.querySelector('.tw-watchlist-delete').addEventListener('click', async () => {
          try {
            await fetch(`/twitter/watchlist/${item.id}`, { method: 'DELETE' });
            this._watchlist = this._watchlist.filter(w => w.id !== item.id);
            this._renderWatchlist();
            toast(ICONS.check(14) + ' Watch removed');
          } catch (e) { toast(ICONS.x(14) + ' Failed to remove watch'); }
        });
        list.appendChild(el);
      });
    }

    async addWatch() {
      const hint = this._platform === 'linkedin' ? 'keyword or job title' : 'keyword or @username';
      const value = prompt(`Enter ${hint} to watch (${this._platform}):`);
      if (!value || !value.trim()) return;
      const v = value.trim();
      const type = this._platform === 'twitter' && v.startsWith('@') ? 'user' : (this._platform === 'linkedin' ? ($('#tw-linkedin-type')?.value || 'profiles') : 'keyword');
      const cleanVal = type === 'user' ? v.replace('@', '') : v;
      try {
        const res = await fetch('/twitter/watchlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type, value: cleanVal, platform: this._platform }) });
        const data = await res.json();
        if (data.entry) { this._watchlist.push(data.entry); this._renderWatchlist(); toast(ICONS.check(14) + ` Watching: ${cleanVal}`); }
      } catch (e) { toast(ICONS.x(14) + ' Failed to add watch'); }
    }

    async refreshWatchlist() {
      if (!this._watchlist.length) { toast('No watches to refresh'); return; }
      const feed = $('#tw-feed'), empty = $('#tw-empty');
      this._switchToResults();
      if (empty) empty.style.display = 'none';
      if (feed) feed.innerHTML = '<div class="tw-loading"><div class="spinner"></div>Refreshing watchlist...</div>';
      try {
        const res = await fetch('/twitter/watchlist/refresh', { method: 'POST' });
        const data = await res.json();
        if (!feed) return;
        feed.innerHTML = ''; let total = 0;
        Object.entries(data.results || {}).forEach(([id, items]) => {
          const entry = this._watchlist.find(w => w.id === id);
          if ((entry?.platform || 'twitter') === 'linkedin') this.renderLinkedIn(items, feed, null);
          else this.renderTweets(items, feed, null);
          total += items.length;
        });
        if (!total && empty) { empty.style.display = ''; empty.innerHTML = '<p>No results from watchlist.</p>'; }
        toast(ICONS.check(14) + ` Loaded ${total} results from watchlist`);
      } catch (e) { if (feed) feed.innerHTML = ''; if (empty) { empty.style.display = ''; empty.innerHTML = '<p>Refresh failed.</p>'; } }
    }

    _esc(str) {
      const div = document.createElement('div');
      div.textContent = str;
      return div.innerHTML;
    }

    _linkify(text) {
      return text
        .replace(/@(\w+)/g, '<a href="https://x.com/$1" target="_blank" rel="noopener" style="color:var(--accent)">@$1</a>')
        .replace(/#(\w+)/g, '<a href="https://x.com/hashtag/$1" target="_blank" rel="noopener" style="color:var(--accent)">#$1</a>');
    }

    _relTime(dateStr) {
      try {
        const d = new Date(dateStr);
        const now = new Date();
        const diff = Math.floor((now - d) / 1000);
        if (diff < 60) return diff + 's';
        if (diff < 3600) return Math.floor(diff / 60) + 'm';
        if (diff < 86400) return Math.floor(diff / 3600) + 'h';
        return Math.floor(diff / 86400) + 'd';
      } catch { return ''; }
    }
  }


  function applyToolVisibility(settings) {
    const tools = ['automation', 'research', 'media', 'presentation', 'project', 'editor'];
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

    // Research Studio
    window.researchStudio = new ResearchStudioV2();

    // Sync token usage from backend
    if (window.tokenTracker) window.tokenTracker.syncFromBackend();

    // Twitter Watch
    window.twitterWatch = new TwitterWatch();

    // Project Studio
    if (window.ProjectStudio) window.projectStudio = new ProjectStudio();

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
        window.automationStudio?.toggle(mode === 'automation');
        window.researchStudio?.toggle(mode === 'research');
        window.projectStudio?.toggle(mode === 'project');

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

    // Theme toggle
    const themeBtn = $('#btn-theme-toggle');
    const themeIconDark = $('#theme-icon-dark');
    const themeIconLight = $('#theme-icon-light');
    const hljsTheme = $('#hljs-theme');

    // Check local storage for theme
    const savedTheme = localStorage.getItem('omniclaw-theme') || 'dark';
    if (savedTheme === 'light') {
      document.documentElement.classList.add('theme-light');
      if (themeIconDark) themeIconDark.style.display = '';
      if (themeIconLight) themeIconLight.style.display = 'none';
      if (hljsTheme) hljsTheme.href = '/static/css/github.min.css';
    }

    if (themeBtn) {
      themeBtn.addEventListener('click', () => {
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
    $$('.editor-right-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        $$('.editor-right-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const panel = tab.dataset.panel;
        $('#editor-activity').classList.toggle('active', panel === 'activity');
        $('#editor-chat').classList.toggle('active', panel === 'chat');
        $('#editor-todo')?.classList.toggle('active', panel === 'todo');
        $('#editor-git').classList.toggle('active', panel === 'git');
        $('#editor-twitter')?.classList.toggle('active', panel === 'twitter');
        // Load git data when switching to git tab
        if (panel === 'git') {
          window.editor.loadGitStatus();
          window.editor.loadGitLog();
        }
        // Render todos when switching to todo tab
        if (panel === 'todo') {
          window.editor.renderTodos();
        }
        // Load watchlist when switching to twitter tab
        if (panel === 'twitter' && window.twitterWatch) {
          window.twitterWatch.loadWatchlist();
        }
      });
    });

    // Agent Mode Toggle buttons
    $$('.agent-mode-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        window.editor.setAgentMode(btn.dataset.agent);
      });
    });

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
            html += `<div class="media-import-item" data-filename="${img.filename}" style="cursor:pointer; border:2px solid transparent; border-radius:4px; overflow:hidden;">
              <img src="/data/images/${img.filename}" style="width:100%; height:100px; object-fit:cover;">
              <div style="font-size:10px; text-align:center; padding:2px; background:var(--bg-elevated); text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">${img.filename}</div>
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
      if (!window._auditPrompt) { toast(ICONS.circle(14) + ' {ICONS.circleSlash(14)} No prompt to copy'); return; }
      // Try modern clipboard API first, fallback to execCommand
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(window._auditPrompt)
          .then(() => toast(ICONS.circle(14) + ' {ICONS.clipboard(14)} Prompt copied to clipboard'))
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
        toast(ok ? '${ICONS.clipboard(14)} Prompt copied to clipboard' : '${ICONS.x(14)} Copy failed — select text manually');
      } catch (e) {
        toast(ICONS.circle(14) + ' {ICONS.x(14)} Copy failed — select text manually');
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
        toast(ICONS.circle(14) + ' {ICONS.send(14)} Prompt sent to chat');
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
                toast(`${ICONS.circle(14)} {ICONS.check(14)} Translation ready: ${outName}`);
              } catch (err) {
                status.innerHTML = `<span style="color:#f87171">${ICONS.x(14)} ${escHtml(err.message)}</span>`;
                btn.disabled = false;
                btn.innerHTML = `${icon('globe', 14)} Retry`;
              }
            });

          } else if (isImage) {
            // Add image to file tree as reference
            if (window.ft) window.ft.add(file.name, `[Image: ${file.name}] (${(file.size / 1024).toFixed(0)} KB)`);
            toast(ICONS.paperclip(14) + ' ' + file.name + ' attached');
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
          $('#chat-messages').innerHTML = '<div class="arena-container" id="arena-container" style="display:none"></div><div class="arena-eval-panel" id="arena-eval-panel" style="display:none"><button class="arena-eval-btn" id="arena-eval-btn">Ask AI to Judge</button></div>';
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

          const r = await fetch('/arena/evaluate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              prompt: window.arenaLastPrompt || '',
              responses: responses,
              provider: $('#provider-select').value,
              model: $('#model-select').value
            })
          });
          const d = await r.json();

          if (d.ratings) {
            Object.keys(d.ratings).forEach(s_id => {
              const info = d.ratings[s_id];
              const colBody = document.getElementById(`col-${s_id}`);
              if (colBody) {
                const scoreDiv = document.createElement('div');
                scoreDiv.className = 'arena-score';
                scoreDiv.innerHTML = `<strong>Score: ${info.score}/10</strong>${escHtml(info.rationale)}`;
                colBody.parentElement.appendChild(scoreDiv);
              }
            });
            btn.textContent = 'Evaluation Complete';
          }
        } catch (err) {
          toast('Evaluation failed');
          btn.textContent = 'Ask AI to Judge';
          btn.disabled = false;
        }
      }
    });

    // Settings
    $('#btn-settings').addEventListener('click', () => $('#settings-overlay').classList.add('open'));
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

      toast(ICONS.check(14) + ' Settings saved'); $('#settings-overlay').classList.remove('open');
    });

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
    loadSessions(); loadPreprompts(); loadProviders(); loadRagStats(); loadSettings(); loadEnvSettings();
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

  // ---- Skill Catalog ----
  class SkillCatalog {
    constructor() {
      this._overlay = $('#skills-catalog-overlay');
      this._grid = $('#skills-catalog-grid');
      this._subtitle = $('#skills-catalog-subtitle');
      this._searchInput = $('#skills-catalog-search-input');
      this._searchClear = $('#skills-search-clear');
      this._tabs = $('#skills-catalog-tabs');
      this._skills = [];
      this._activeFilter = 'all';
      this._searchQuery = '';

      // Search handler
      if (this._searchInput) {
        this._searchInput.addEventListener('input', () => {
          this._searchQuery = this._searchInput.value.toLowerCase().trim();
          if (this._searchClear) this._searchClear.classList.toggle('visible', this._searchQuery.length > 0);
          this._renderGrid();
        });
      }

      // Search clear button
      if (this._searchClear) {
        this._searchClear.addEventListener('click', () => {
          this._searchInput.value = '';
          this._searchQuery = '';
          this._searchClear.classList.remove('visible');
          this._renderGrid();
          this._searchInput.focus();
        });
      }

      // Tab handlers
      if (this._tabs) {
        this._tabs.addEventListener('click', (e) => {
          const tab = e.target.closest('.skills-cat-tab');
          if (!tab) return;
          this._tabs.querySelectorAll('.skills-cat-tab').forEach(t => t.classList.remove('active'));
          tab.classList.add('active');
          this._activeFilter = tab.dataset.cat;
          this._renderGrid();
        });
      }
    }

    async open() {
      this._overlay.classList.add('open');
      await this._loadSkills();
    }

    close() {
      this._overlay.classList.remove('open');
    }

    async _loadSkills() {
      try {
        const r = await fetch('/skills/catalog');
        const d = await r.json();
        this._skills = d.skills || [];
        this._subtitle.textContent = `${d.total} skills • ${d.active_count} active`;
        this._renderGrid();
      } catch (e) {
        this._subtitle.textContent = 'Error loading catalog';
        this._grid.innerHTML = '<div class="skills-catalog-empty">' + ICONS.x(14) + ' Failed to load skill catalog</div>';
      }
    }


    _renderGrid() {
      let filtered = this._skills;

      // Category filter
      if (this._activeFilter !== 'all') {
        filtered = filtered.filter(s => s.category === this._activeFilter);
      }

      // Search filter
      if (this._searchQuery) {
        filtered = filtered.filter(s =>
          s.name.toLowerCase().includes(this._searchQuery) ||
          (s.description || '').toLowerCase().includes(this._searchQuery) ||
          (s.category || '').toLowerCase().includes(this._searchQuery)
        );
      }

      if (!filtered.length) {
        this._grid.innerHTML = '<div class="skills-catalog-empty">No skills match your search.</div>';
        return;
      }

      // Sort: active first, then core, then alphabetical
      filtered.sort((a, b) => {
        if (a.active !== b.active) return a.active ? -1 : 1;
        if (a.source === 'core' && b.source !== 'core') return -1;
        if (b.source === 'core' && a.source !== 'core') return 1;
        return a.name.localeCompare(b.name);
      });

      this._grid.innerHTML = filtered.map(skill => this._renderCard(skill)).join('');

      // Bind toggle events
      this._grid.querySelectorAll('.skill-toggle input').forEach(inp => {
        inp.addEventListener('change', (e) => this._handleToggle(e.target));
      });
    }

    _renderCard(skill) {
      const isCore = skill.source === 'core';
      const cardClass = isCore ? 'skill-card skill-core' : (skill.active ? 'skill-card skill-active' : 'skill-card');
      const catClass = `cat-${skill.category || 'other'}`;
      const srcClass = `src-${skill.source || 'user'}`;

      const categoryIcons = {
        code: ICONS.monitor(14), web: ICONS.globe ? ICONS.globe(14) : ICONS.link(14), media: ICONS.palette(14), data: ICONS.barChart(14),
        automation: ICONS.settings(14), integration: ICONS.link(14), other: ICONS.penTool(14)
      };
      const icon = categoryIcons[skill.category] || ICONS.penTool(14);

      const toggleHtml = isCore
        ? '<span class="skill-core-badge">ALWAYS ON</span>'
        : `<label class="skill-toggle">
             <input type="checkbox" data-skill="${skill.name}" ${skill.active ? 'checked' : ''}>
             <span class="skill-toggle-slider"></span>
           </label>`;

      const versionTag = skill.version && skill.version !== '—'
        ? `<span class="skill-meta-tag">${skill.version}</span>` : '';

      const usageTag = skill.usage_count
        ? `<span class="skill-meta-tag">${skill.usage_count}× used</span>` : '';

      return `
        <div class="${cardClass}" data-skill-name="${skill.name}">
          <div class="skill-card-header">
            <span class="skill-card-name">${icon} ${skill.name}</span>
            ${toggleHtml}
          </div>
          <div class="skill-card-desc">${skill.description || 'No description'}</div>
          <div class="skill-card-meta">
            <span class="skill-meta-tag ${catClass}">${skill.category || 'other'}</span>
            <span class="skill-meta-tag ${srcClass}">${skill.source || 'user'}</span>
            ${versionTag}
            ${usageTag}
          </div>
        </div>`;
    }

    async _handleToggle(input) {
      const name = input.dataset.skill;
      const activate = input.checked;
      const url = activate ? `/skills/activate/${name}` : `/skills/deactivate/${name}`;

      try {
        const r = await fetch(url, { method: 'POST' });
        const d = await r.json();

        const card = input.closest('.skill-card');
        if (card) card.classList.toggle('skill-active', activate);

        this._subtitle.textContent = `${this._skills.length} skills • ${d.active_count} active`;

        const skill = this._skills.find(s => s.name === name);
        if (skill) skill.active = activate;

        this._updateBadge(d.active_count);

        toast(activate ? `${ICONS.bolt(14)} ${name} activated` : `${ICONS.link(14)} ${name} deactivated`);
      } catch (e) {
        input.checked = !activate;
        toast(ICONS.x(14) + ' Toggle failed');
      }
    }

    _updateBadge(count) {
      const badge = $('#skill-badge');
      const indicator = $('#input-skill-indicator');
      const countEl = $('#input-skill-count');

      if (badge) {
        badge.textContent = count;
        badge.style.display = count > 0 ? 'flex' : 'none';
      }
      if (indicator) {
        indicator.style.display = count > 0 ? 'inline-flex' : 'none';
      }
      if (countEl) {
        countEl.textContent = count;
      }
    }

    async refreshBadge() {
      try {
        const r = await fetch('/skills/active');
        const d = await r.json();
        this._updateBadge(d.count || 0);
      } catch (e) { /* non-critical */ }
    }
  }

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
                  <span style="font-weight:500;">${model}</span>
                  <span style="font-size:10px; color:var(--text-muted); background:var(--bg-elevated); padding:2px 6px; border-radius:10px;">${stats.provider}</span>
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
                  <span style="font-weight:500;">${tool}</span>
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
      applyToolVisibility(d);
    } catch (e) { /* ignore */ }
  }

  async function loadEnvSettings() {
    try {
      const r = await fetch('/api/env');
      const d = await r.json();

      const container = $('#env-modal-table-container');
      const perfProvidersContainer = $('#perf-providers-container');

      if (container) container.innerHTML = '';
      if (perfProvidersContainer) perfProvidersContainer.innerHTML = '';

      // Populate general env variables in the main settings drawer
      const keys = Object.keys(d).sort();
      const groups = {};
      const sensitiveKeywords = ['KEY', 'SECRET', 'TOKEN', 'PASSWORD'];

      for (const key of keys) {
        let groupName = 'System / Other';
        const prefixes = ['GOOGLE', 'GROQ', 'OPENAI', 'ANTHROPIC', 'HUGGINGFACE', 'MISTRAL', 'OPENROUTER', 'GROK', 'TAVILY', 'APP', 'OLLAMA'];
        for (const prefix of prefixes) {
          if (key.startsWith(prefix + '_')) {
            groupName = prefix;
            break;
          }
        }
        if (!groups[groupName]) groups[groupName] = [];
        groups[groupName].push(key);
      }

      let tableHtml = `<div style="display:flex; flex-direction:column; gap:24px;">`;

      for (const [groupName, groupKeys] of Object.entries(groups).sort()) {
        tableHtml += `
          <div>
            <h3 style="font-size:13px; color:var(--text-primary); margin-bottom:8px; border-bottom:1px solid var(--border); padding-bottom:4px;">${groupName}</h3>
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

          tableHtml += `
            <tr style="border-bottom:1px solid var(--border);">
              <td style="padding:8px 4px; color:var(--text-muted); font-family:var(--font-mono); font-size:11px; width:40%;">${key}</td>
              <td style="padding:8px 4px; display:flex; align-items:center;">
                <input type="${inputType}" class="settings-input" data-env-key="${key}" value="${d[key] || ''}" style="flex:1; font-family:var(--font-mono); font-size:11px; padding:4px 8px; border:1px solid transparent; background:var(--bg-elevated); outline:none;">
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

  const btnOpenUserMd = $('#btn-open-user-md');
  if (btnOpenUserMd) btnOpenUserMd.addEventListener('click', async () => {
    await openRagProfilEditor('USER.md');
  });

  const btnOpenMemoryMd = $('#btn-open-memory-md');
  if (btnOpenMemoryMd) btnOpenMemoryMd.addEventListener('click', async () => {
    await openRagProfilEditor('MEMORY.md');
  });

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

})();
