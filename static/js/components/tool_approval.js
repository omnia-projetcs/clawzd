/* Clawzd — Tool Approval (HITL)
 * Compact inline approval widget: tool name + Approve/Deny buttons.
 * No code preview, no params — just a clean, visible action bar.
 */
(function () {
  'use strict';

  class ToolApproval {
    constructor() {
      this._active = new Map();
    }

    /* Extract approval markers from SSE tokens */
    processToken(token) {
      const re = /__TOOL_APPROVAL__(.+?)__TOOL_APPROVAL__/g;
      let m, cleaned = token, found = false;
      while ((m = re.exec(token)) !== null) {
        found = true;
        try { this._show(JSON.parse(m[1])); } catch (_) {}
        cleaned = cleaned.replace(m[0], '');
      }
      return found ? (cleaned.trim() || null) : token;
    }

    _show(data) {
      const { id, tool_name } = data;
      if (this._active.has(id)) return;
      this._active.set(id, data);

      const card = document.createElement('div');
      card.className = 'ta-card';
      card.id = `ta-${id}`;
      card.innerHTML =
        `<div class="ta-row">` +
          `<span class="ta-badge">⚡</span>` +
          `<span class="ta-label">Approve <code>${this._esc(tool_name)}</code> ?</span>` +
          `<span class="ta-countdown" id="ta-cd-${id}">2:00</span>` +
          `<label class="ta-remember"><input type="checkbox" id="ta-chk-${id}"> Always</label>` +
          `<button class="ta-btn ta-btn-deny"  onclick="window.toolApproval._reply('${id}',false)">✕ Deny</button>` +
          `<button class="ta-btn ta-btn-ok"    onclick="window.toolApproval._reply('${id}',true)">✓ Approve</button>` +
        `</div>`;

      const chat = document.getElementById('chat-messages');
      if (chat) { chat.appendChild(card); chat.scrollTop = chat.scrollHeight; }

      this._timer(id, 120);
    }

    _timer(id, sec) {
      let r = sec;
      const el = document.getElementById(`ta-cd-${id}`);
      const iv = setInterval(() => {
        r--;
        if (el) {
          el.textContent = `${Math.floor(r / 60)}:${(r % 60).toString().padStart(2, '0')}`;
          if (r <= 10) el.classList.add('ta-urgent');
        }
        if (r <= 0) { clearInterval(iv); this._reply(id, false); }
      }, 1000);
      const d = this._active.get(id);
      if (d) d._iv = iv;
    }

    async _reply(id, ok) {
      const d = this._active.get(id);
      if (!d) return;
      if (d._iv) clearInterval(d._iv);

      const always = document.getElementById(`ta-chk-${id}`)?.checked || false;

      try {
        await fetch('/api/tool-approval', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ approval_id: id, approved: ok, always_allow: always }),
        });
      } catch (_) {}

      const card = document.getElementById(`ta-${id}`);
      if (card) {
        card.style.transition = 'opacity 0.15s, transform 0.15s';
        card.style.opacity = '0';
        card.style.transform = 'translateY(-4px)';
        card.style.pointerEvents = 'none';
        setTimeout(() => card.remove(), 200);
      }

      this._active.delete(id);
      if (always && ok && window.toast) {
        window.toast(`🔓 <code>${d.tool_name}</code> will now auto-execute`);
      }
    }

    _esc(s) {
      return s ? String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;') : '';
    }
  }

  window.toolApproval = new ToolApproval();
})();
