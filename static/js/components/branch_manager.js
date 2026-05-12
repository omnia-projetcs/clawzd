/* Conversation Branching — inline branch navigation UI */
(function () {
  'use strict';

  const $ = s => document.querySelector(s);

  class BranchManager {
    constructor() {
      this._activeBranch = 'main';
      this._branches = [];
      this._sessionId = null;
    }

    /** Set the current session — loads branches from API */
    async setSession(sessionId) {
      this._sessionId = sessionId;
      this._activeBranch = 'main';
      await this._fetchBranches();
    }

    get activeBranch() { return this._activeBranch; }

    /** Fork conversation at a message */
    async forkAt(messageId) {
      if (!this._sessionId) return null;
      try {
        const res = await fetch('/api/branch/fork', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: this._sessionId,
            message_id: messageId,
          }),
        });
        const data = await res.json();
        if (data.branch_id) {
          await this._fetchBranches();
          await this.switchTo(data.branch_id);
          return data;
        }
      } catch (e) {
        console.error('Fork failed:', e);
      }
      return null;
    }

    /** Switch to a different branch */
    async switchTo(branchId) {
      if (!this._sessionId) return;
      this._activeBranch = branchId;
      try {
        const res = await fetch(`/api/branch/${this._sessionId}/${branchId}`);
        const data = await res.json();
        // Reload the chat messages with this branch's messages
        if (window.chat && data.messages) {
          window.chat.msgEl.innerHTML = '';
          data.messages.forEach(m => {
            window.chat.addMsg(m.role, m.content, m.metadata || {});
          });
          window.chat.extractFiles && data.messages
            .filter(m => m.role === 'assistant')
            .forEach(m => window.chat.extractFiles(m.content));
          if (typeof highlightAll === 'function') highlightAll();
        }
      } catch (e) {
        console.error('Branch switch failed:', e);
      }
      this._renderIndicator();
    }

    /** Delete a branch */
    async deleteBranch(branchId) {
      if (branchId === 'main' || !this._sessionId) return;
      try {
        await fetch(`/api/branch/${this._sessionId}/${branchId}`, { method: 'DELETE' });
        await this._fetchBranches();
        if (this._activeBranch === branchId) {
          await this.switchTo('main');
        }
        this._renderIndicator();
      } catch (e) {
        console.error('Branch delete failed:', e);
      }
    }

    /** Fetch branches from API */
    async _fetchBranches() {
      if (!this._sessionId) return;
      try {
        const res = await fetch(`/api/branch/${this._sessionId}`);
        const data = await res.json();
        this._branches = data.branches || [];
      } catch (e) {
        this._branches = [];
      }
      this._renderIndicator();
    }

    /** Render the branch indicator in the chat header */
    _renderIndicator() {
      let indicator = document.getElementById('branch-indicator');
      if (!indicator) {
        // Find chat header to attach
        const chatHeader = document.querySelector('.chat-header');
        if (!chatHeader) return;
        indicator = document.createElement('div');
        indicator.id = 'branch-indicator';
        indicator.className = 'branch-indicator';
        chatHeader.appendChild(indicator);
      }

      // Hide if only main branch
      if (this._branches.length <= 1) {
        indicator.style.display = 'none';
        return;
      }

      indicator.style.display = 'flex';
      const branchCount = this._branches.length;
      const activeName = this._activeBranch === 'main'
        ? 'main'
        : this._activeBranch.replace('branch-', '⑂ ');

      indicator.innerHTML = `
        <button class="branch-btn" id="branch-dropdown-btn" title="Switch branch">
          <svg class="ic" width="12" height="12"><use href="#icon-git-branch"></use></svg>
          <span class="branch-name">${activeName}</span>
          <span class="branch-count">${branchCount}</span>
        </button>
      `;

      // Dropdown on click
      const btn = indicator.querySelector('#branch-dropdown-btn');
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this._showDropdown(btn);
      });
    }

    /** Show branch dropdown menu */
    _showDropdown(anchor) {
      // Remove existing
      const existing = document.getElementById('branch-dropdown');
      if (existing) { existing.remove(); return; }

      const dropdown = document.createElement('div');
      dropdown.id = 'branch-dropdown';
      dropdown.className = 'branch-dropdown';

      dropdown.innerHTML = this._branches.map(b => {
        const isActive = b.branch_id === this._activeBranch;
        const name = b.branch_id === 'main' ? '🌿 main' : `⑂ ${b.branch_id.replace('branch-', '')}`;
        return `
          <div class="branch-dropdown-item ${isActive ? 'active' : ''}" data-branch="${b.branch_id}">
            <span class="branch-item-name">${name}</span>
            <span class="branch-item-count">${b.msg_count} msgs</span>
            ${b.branch_id !== 'main' ? `<button class="branch-item-delete" data-delete="${b.branch_id}" title="Delete branch">✕</button>` : ''}
          </div>
        `;
      }).join('');

      document.body.appendChild(dropdown);

      // Position near anchor
      const rect = anchor.getBoundingClientRect();
      dropdown.style.top = (rect.bottom + 4) + 'px';
      dropdown.style.left = rect.left + 'px';

      // Click handlers
      dropdown.querySelectorAll('.branch-dropdown-item').forEach(item => {
        item.addEventListener('click', (e) => {
          if (e.target.classList.contains('branch-item-delete')) return;
          const branchId = item.dataset.branch;
          dropdown.remove();
          this.switchTo(branchId);
        });
      });
      dropdown.querySelectorAll('.branch-item-delete').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const branchId = btn.dataset.delete;
          dropdown.remove();
          if (confirm(`Delete branch "${branchId}"?`)) {
            this.deleteBranch(branchId);
          }
        });
      });

      // Close on outside click
      const close = (e) => {
        if (!dropdown.contains(e.target) && e.target !== anchor) {
          dropdown.remove();
          document.removeEventListener('click', close);
        }
      };
      setTimeout(() => document.addEventListener('click', close), 0);
    }

    /** Inject fork button into a message element */
    addForkButton(actionsBar, messageId) {
      if (!messageId) return;
      const forkBtn = document.createElement('button');
      forkBtn.className = 'msg-action-btn';
      forkBtn.title = 'Fork conversation here';
      forkBtn.innerHTML = `<svg class="ic" width="13" height="13"><use href="#icon-git-branch"></use></svg> Fork`;
      forkBtn.addEventListener('click', async () => {
        forkBtn.disabled = true;
        forkBtn.innerHTML = '⏳ Forking…';
        const result = await this.forkAt(messageId);
        if (result) {
          if (typeof toast === 'function') toast('✅ Conversation forked — switched to new branch');
        } else {
          if (typeof toast === 'function') toast('❌ Fork failed');
        }
        forkBtn.disabled = false;
        forkBtn.innerHTML = `<svg class="ic" width="13" height="13"><use href="#icon-git-branch"></use></svg> Fork`;
      });
      actionsBar.appendChild(forkBtn);
    }
  }

  window.branchManager = new BranchManager();
})();
