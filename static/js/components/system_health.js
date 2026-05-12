/**
 * System Health Monitor — lightweight status bar widget showing
 * GPU VRAM, RAM usage, and Ollama status. Updates every 30s.
 */
(function () {
  'use strict';

  const POLL_INTERVAL = 30_000; // 30s
  let _timer = null;

  async function fetchHealth() {
    try {
      const res = await fetch('/api/system/health');
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  function renderWidget(data) {
    const container = document.getElementById('sys-health-widget');
    if (!container) return;

    // Remove previous health items (keep existing children like #status-model)
    container.querySelectorAll('.shw-item, .shw-offline').forEach(el => el.remove());

    if (!data) {
      const warn = document.createElement('span');
      warn.className = 'shw-offline';
      warn.title = 'System health unavailable';
      warn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`;
      container.appendChild(warn);
      return;
    }

    const items = [];

    // Helper to format MiB to MB/GB
    const formatSize = (mib) => {
      if (mib >= 1024) return (mib / 1024).toFixed(1) + ' GB';
      return Math.round(mib) + ' MB';
    };

    // Ollama status
    if (data.ollama_status != null) {
      const ollamaOk = data.ollama_status === 'running';
      items.push({
        title: `Ollama: ${data.ollama_status}`,
        color: ollamaOk ? 'var(--green)' : 'var(--red)',
        html: `<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="currentColor" stroke="none" style="vertical-align:-1px"><circle cx="12" cy="12" r="10"></circle></svg>`,
      });
    }

    // RAM
    if (data.ram_used_mib != null && data.ram_total_mib) {
      const ramPct = Math.round(data.ram_used_mib / data.ram_total_mib * 100);
      const ramColor = ramPct > 90 ? 'var(--red)' : ramPct > 75 ? 'var(--warning, #f59e0b)' : 'var(--text-muted)';
      items.push({
        title: `RAM: ${formatSize(data.ram_used_mib)} / ${formatSize(data.ram_total_mib)} (${ramPct}%)`,
        color: ramColor,
        html: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px;vertical-align:-2px"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg>${ramPct}%`,
      });
    }

    // GPU VRAM
    if (data.vram_used_mib != null && data.vram_total_mib) {
      const pct = Math.round(data.vram_used_mib / data.vram_total_mib * 100);
      const color = pct > 90 ? 'var(--red)' : pct > 70 ? 'var(--warning, #f59e0b)' : 'var(--green)';
      items.push({
        title: `GPU: ${data.gpu_name || 'GPU'}\nVRAM: ${formatSize(data.vram_used_mib)} / ${formatSize(data.vram_total_mib)} (${pct}%)`,
        color: color,
        html: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px;vertical-align:-2px"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>${pct}%`,
      });
    }

    items.forEach(item => {
      const span = document.createElement('span');
      span.className = 'shw-item';
      span.title = item.title;
      span.style.color = item.color;
      span.style.display = 'inline-flex';
      span.style.alignItems = 'center';
      span.innerHTML = item.html;
      container.appendChild(span);
    });
  }

  async function poll() {
    const data = await fetchHealth();
    renderWidget(data);
  }

  function start() {
    poll();
    _timer = setInterval(poll, POLL_INTERVAL);
  }

  function stop() {
    if (_timer) { clearInterval(_timer); _timer = null; }
  }

  // Auto-start on load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }

  window.SystemHealth = { poll, start, stop };
})();
