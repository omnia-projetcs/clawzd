/* Clawzd — Tool Approval Panel (HITL)
 * OpenSwarm-inspired floating approval widget that appears inline
 * when a tool execution requires user confirmation.
 *
 * Listens for __TOOL_APPROVAL__ markers in the SSE stream and renders
 * an approval card with Approve/Deny buttons + "Always allow" checkbox.
 */
(function () {
  'use strict';

  class ToolApproval {
    constructor() {
      this._activeApprovals = new Map();
    }

    /**
     * Extract and process tool approval requests from SSE tokens.
     * Returns the cleaned token (without approval markers), or null
     * if the entire token was an approval request.
     */
    processToken(token) {
      const regex = /__TOOL_APPROVAL__(.+?)__TOOL_APPROVAL__/g;
      let match;
      let cleaned = token;
      let hasApproval = false;

      while ((match = regex.exec(token)) !== null) {
        hasApproval = true;
        try {
          const data = JSON.parse(match[1]);
          this._showApproval(data);
        } catch (e) {
          console.warn('[ToolApproval] Failed to parse:', e);
        }
        cleaned = cleaned.replace(match[0], '');
      }

      return hasApproval ? (cleaned.trim() || null) : token;
    }

    _showApproval(data) {
      const { id, tool_name, params, session_id } = data;

      // Prevent duplicates
      if (this._activeApprovals.has(id)) return;
      this._activeApprovals.set(id, data);

      // Build params display
      let paramsHtml = '';
      if (params && Object.keys(params).length > 0) {
        const entries = Object.entries(params).slice(0, 8);
        paramsHtml = entries.map(([k, v]) => {
          const isCode = (k === 'code' || k === 'command' || k === 'script');
          const raw = typeof v === 'string' ? v : JSON.stringify(v, null, 2);

          if (isCode) {
            // Render as a proper code block
            const lang = k === 'command' ? 'bash' : 'python';
            const truncated = raw.length > 2000 ? raw.slice(0, 2000) + '\n# …truncated' : raw;
            const escaped = this._esc(truncated);
            let highlighted = escaped;
            if (typeof hljs !== 'undefined') {
              try {
                highlighted = hljs.highlight(truncated, { language: lang }).value;
              } catch (_) { /* fallback to escaped */ }
            }
            return `<div class="ta-param ta-param-code">`
              + `<div class="ta-param-key">${this._esc(k)}</div>`
              + `<pre class="ta-code-block"><code class="language-${lang}">${highlighted}</code></pre>`
              + `</div>`;
          }

          // Normal param — generous truncation
          const val = raw.length > 300 ? raw.slice(0, 300) + '…' : raw;
          return `<div class="ta-param"><span class="ta-param-key">${this._esc(k)}:</span> <span class="ta-param-val">${this._esc(val)}</span></div>`;
        }).join('');
      }

      // Build the approval card
      const card = document.createElement('div');
      card.className = 'tool-approval-card';
      card.id = `ta-${id}`;
      card.innerHTML = `
        <div class="ta-header">
          <div class="ta-icon">⚡</div>
          <div class="ta-info">
            <div class="ta-title">Tool requires approval</div>
            <div class="ta-tool-name">${this._esc(tool_name)}</div>
          </div>
          <div class="ta-timer" id="ta-timer-${id}">2:00</div>
        </div>
        ${paramsHtml ? `<div class="ta-params">${paramsHtml}</div>` : ''}
        <div class="ta-actions">
          <label class="ta-always-label">
            <input type="checkbox" class="ta-always-check" id="ta-always-${id}">
            <span>Always allow <code>${this._esc(tool_name)}</code></span>
          </label>
          <div class="ta-buttons">
            <button class="ta-btn ta-deny" onclick="window.toolApproval._respond('${id}', false)">
              ✕ Deny
            </button>
            <button class="ta-btn ta-approve" onclick="window.toolApproval._respond('${id}', true)">
              ✓ Approve
            </button>
          </div>
        </div>
      `;

      // Insert into the chat messages area (at the bottom, before input)
      const chatMessages = document.getElementById('chat-messages');
      if (chatMessages) {
        chatMessages.appendChild(card);
        chatMessages.scrollTop = chatMessages.scrollHeight;
      }

      // Start countdown timer
      this._startTimer(id, 120);
    }

    _startTimer(approvalId, seconds) {
      let remaining = seconds;
      const timerEl = document.getElementById(`ta-timer-${approvalId}`);

      const interval = setInterval(() => {
        remaining--;
        if (timerEl) {
          const mins = Math.floor(remaining / 60);
          const secs = remaining % 60;
          timerEl.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
          if (remaining <= 10) timerEl.classList.add('ta-urgent');
        }
        if (remaining <= 0) {
          clearInterval(interval);
          this._respond(approvalId, false);
        }
      }, 1000);

      // Store interval for cleanup
      const data = this._activeApprovals.get(approvalId);
      if (data) data._interval = interval;
    }

    async _respond(approvalId, approved) {
      const data = this._activeApprovals.get(approvalId);
      if (!data) return;

      // Clear timer
      if (data._interval) clearInterval(data._interval);

      const alwaysAllow = document.getElementById(`ta-always-${approvalId}`)?.checked || false;

      // Send response to backend
      try {
        await fetch('/api/tool-approval', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            approval_id: approvalId,
            approved,
            always_allow: alwaysAllow,
          }),
        });
      } catch (e) {
        console.error('[ToolApproval] Response failed:', e);
      }

      // Animate out
      const card = document.getElementById(`ta-${approvalId}`);
      if (card) {
        card.classList.add(approved ? 'ta-approved' : 'ta-denied');
        const statusEl = document.createElement('div');
        statusEl.className = `ta-status ${approved ? 'ta-status-approved' : 'ta-status-denied'}`;
        statusEl.textContent = approved ? '✓ Approved' : '✕ Denied';
        card.querySelector('.ta-actions')?.replaceWith(statusEl);
        setTimeout(() => card.remove(), 2000);
      }

      this._activeApprovals.delete(approvalId);

      // Show toast for always-allow
      if (alwaysAllow && approved && window.toast) {
        window.toast(`🔓 <code>${data.tool_name}</code> will now execute without asking`);
      }
    }

    _esc(s) {
      if (!s) return '';
      return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
  }

  window.toolApproval = new ToolApproval();
})();
