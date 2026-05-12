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
      warn.textContent = '⚠️';
      container.appendChild(warn);
      return;
    }

    const items = [];

    // Ollama status
    if (data.ollama_status != null) {
      const ollamaOk = data.ollama_status === 'running';
      items.push({
        title: `Ollama: ${data.ollama_status}`,
        color: ollamaOk ? 'var(--green)' : 'var(--red)',
        text: ollamaOk ? '🟢' : '🔴',
      });
    }

    // RAM
    if (data.ram_used_mib != null && data.ram_total_mib) {
      const ramPct = Math.round(data.ram_used_mib / data.ram_total_mib * 100);
      const ramColor = ramPct > 90 ? 'var(--red)' : ramPct > 75 ? 'var(--warning, #f59e0b)' : 'var(--text-muted)';
      items.push({
        title: `RAM: ${data.ram_used_mib}/${data.ram_total_mib} MiB (${ramPct}%)`,
        color: ramColor,
        text: `💾 ${ramPct}%`,
      });
    }

    // GPU VRAM
    if (data.vram_used_mib != null && data.vram_total_mib) {
      const pct = Math.round(data.vram_used_mib / data.vram_total_mib * 100);
      const color = pct > 90 ? 'var(--red)' : pct > 70 ? 'var(--warning, #f59e0b)' : 'var(--green)';
      items.push({
        title: `GPU: ${data.gpu_name || 'GPU'}\nVRAM: ${data.vram_used_mib}/${data.vram_total_mib} MiB (${pct}%)`,
        color: color,
        text: `🖥️ ${pct}%`,
      });
    }

    items.forEach(item => {
      const span = document.createElement('span');
      span.className = 'shw-item';
      span.title = item.title;
      span.style.color = item.color;
      span.textContent = item.text;
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
