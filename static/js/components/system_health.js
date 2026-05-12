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
    let el = document.getElementById('sys-health-widget');
    if (!el) {
      el = document.createElement('div');
      el.id = 'sys-health-widget';
      el.className = 'sys-health-widget';
      // Insert into status bar if it exists
      const statusBar = document.querySelector('.status-bar') ||
                         document.querySelector('.app-status-bar');
      if (statusBar) {
        statusBar.appendChild(el);
      } else {
        return; // No status bar to attach to
      }
    }

    if (!data) {
      el.innerHTML = '<span class="shw-offline" title="System health unavailable">⚠️</span>';
      return;
    }

    const parts = [];

    // GPU VRAM
    if (data.vram_used_mib != null && data.vram_total_mib) {
      const pct = Math.round(data.vram_used_mib / data.vram_total_mib * 100);
      const color = pct > 90 ? 'var(--red)' : pct > 70 ? 'var(--warning, #f59e0b)' : 'var(--green)';
      parts.push(
        `<span class="shw-item" title="GPU: ${data.gpu_name || 'GPU'}\nVRAM: ${data.vram_used_mib}/${data.vram_total_mib} MiB (${pct}%)" style="color:${color}">` +
        `🖥️ ${pct}%</span>`
      );
    }

    // RAM
    if (data.ram_used_mib != null && data.ram_total_mib) {
      const ramPct = Math.round(data.ram_used_mib / data.ram_total_mib * 100);
      const ramColor = ramPct > 90 ? 'var(--red)' : ramPct > 75 ? 'var(--warning, #f59e0b)' : 'var(--text-muted)';
      parts.push(
        `<span class="shw-item" title="RAM: ${data.ram_used_mib}/${data.ram_total_mib} MiB (${ramPct}%)" style="color:${ramColor}">` +
        `💾 ${ramPct}%</span>`
      );
    }

    // Ollama status
    if (data.ollama_status != null) {
      const ollamaOk = data.ollama_status === 'running';
      parts.push(
        `<span class="shw-item" title="Ollama: ${data.ollama_status}" style="color:${ollamaOk ? 'var(--green)' : 'var(--red)'}">` +
        `${ollamaOk ? '🟢' : '🔴'}</span>`
      );
    }

    el.innerHTML = parts.join('');
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
