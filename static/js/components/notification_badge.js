/**
 * Clawzd — Notification Badge Component.
 *
 * Periodically polls /notifications and shows a badge count in the
 * status bar. Clicking opens a dropdown with recent notifications.
 *
 * API:
 *   GET  /notifications  — List recent
 *   POST /notifications  — Push new (internal)
 */

const NotificationBadge = (() => {
  let _badgeEl = null;
  let _dropdownEl = null;
  let _isOpen = false;
  let _items = [];
  let _pollInterval = null;

  function init() {
    _createBadge();
    _createDropdown();
    _startPolling();
  }

  function _createBadge() {
    const headerRight = document.querySelector('.header-right');
    if (!headerRight) return;

    _badgeEl = document.createElement('button');
    _badgeEl.id = 'notification-badge';
    _badgeEl.className = 'icon-btn notif-badge';
    _badgeEl.title = 'Notifications';
    _badgeEl.innerHTML = '🔔 <span class="notif-count" id="notif-count" style="display:none">0</span>';
    _badgeEl.onclick = () => toggle();

    // Insert after theme toggle
    const themeBtn = document.getElementById('btn-theme-toggle');
    if (themeBtn && themeBtn.nextSibling) {
      headerRight.insertBefore(_badgeEl, themeBtn.nextSibling);
    } else {
      headerRight.insertBefore(_badgeEl, headerRight.firstChild);
    }
  }

  function _createDropdown() {
    _dropdownEl = document.createElement('div');
    _dropdownEl.id = 'notif-dropdown';
    _dropdownEl.className = 'notif-dropdown';
    _dropdownEl.innerHTML = '<div class="notif-empty">No notifications</div>';
    document.body.appendChild(_dropdownEl);

    // Close on outside click
    document.addEventListener('click', (e) => {
      if (_isOpen && !_dropdownEl.contains(e.target) && e.target !== _badgeEl && !_badgeEl.contains(e.target)) {
        toggle(false);
      }
    });
  }

  function _startPolling() {
    _poll(); // Initial
    _pollInterval = setInterval(_poll, 15000); // Every 15s
  }

  async function _poll() {
    try {
      const res = await fetch('/notifications?limit=10');
      _items = await res.json();
      _updateCount();
    } catch (e) {
      // Silent
    }
  }

  function _updateCount() {
    const countEl = document.getElementById('notif-count');
    if (!countEl) return;

    const unread = _items.filter(n => !n.read).length;
    if (unread > 0) {
      countEl.textContent = unread > 9 ? '9+' : unread;
      countEl.style.display = 'inline-flex';
    } else {
      countEl.style.display = 'none';
    }
  }

  function _renderDropdown() {
    if (!_dropdownEl) return;

    if (_items.length === 0) {
      _dropdownEl.innerHTML = '<div class="notif-empty">No notifications</div>';
      return;
    }

    _dropdownEl.innerHTML = `
      <div class="notif-header">
        <span>Notifications</span>
        <button class="notif-clear" onclick="NotificationBadge.clear()">Clear</button>
      </div>
      <div class="notif-list">
        ${_items.slice(0, 8).map(n => `
          <div class="notif-item ${n.read ? '' : 'notif-unread'}">
            <div class="notif-title">${n.title || ''}</div>
            <div class="notif-body">${n.body || ''}</div>
            <div class="notif-time">${_timeAgo(n.timestamp)}</div>
          </div>
        `).join('')}
      </div>
    `;
  }

  function toggle(force) {
    _isOpen = force !== undefined ? force : !_isOpen;
    if (_dropdownEl) {
      _dropdownEl.classList.toggle('notif-dropdown-open', _isOpen);
      if (_isOpen) {
        _renderDropdown();
        // Position near badge
        if (_badgeEl) {
          const rect = _badgeEl.getBoundingClientRect();
          _dropdownEl.style.top = (rect.bottom + 4) + 'px';
          _dropdownEl.style.right = (window.innerWidth - rect.right) + 'px';
        }
      }
    }
  }

  async function clear() {
    _items = [];
    _updateCount();
    _renderDropdown();
    toggle(false);
  }

  function _timeAgo(iso) {
    if (!iso) return '';
    const d = (Date.now() - new Date(iso).getTime()) / 1000;
    if (d < 60) return 'just now';
    if (d < 3600) return Math.floor(d / 60) + 'm ago';
    if (d < 86400) return Math.floor(d / 3600) + 'h ago';
    return Math.floor(d / 86400) + 'd ago';
  }

  return { init, toggle, clear };
})();

window.NotificationBadge = NotificationBadge;
