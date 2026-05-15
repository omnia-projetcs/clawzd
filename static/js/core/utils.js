/**
 * Clawzd — Shared DOM Utilities.
 *
 * Core helper functions used across all modules.
 * Placed on window for backward compatibility with the app.js IIFE.
 */

/** Query a single element */
function _u$(selector, context) {
  return (context || document).querySelector(selector);
}

/** Query all elements (returns array) */
function _u$$(selector, context) {
  return Array.from((context || document).querySelectorAll(selector));
}

/** Create a DOM element with attributes and children */
function _uEl(tag, attrs, children) {
  const e = document.createElement(tag);
  if (attrs) {
    Object.entries(attrs).forEach(([k, v]) => {
      if (k === 'class') e.className = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else if (k === 'html') e.innerHTML = v;
      else if (k === 'text') e.textContent = v;
      else e.setAttribute(k, v);
    });
  }
  if (children) {
    children.forEach(c => {
      if (c) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
  }
  return e;
}

/** Show a toast notification */
function _uToast(msg, duration = 5000) {
  // Delegate to the global toast if loaded (ensures notification history integration)
  if (window.toast && window.toast !== _uToast) {
    return window.toast(msg, duration);
  }
  const t = _uEl('div', { class: 'toast', html: msg });
  document.body.appendChild(t);
  
  const delay = Math.max(0, (duration / 1000) - 0.3);
  t.style.animation = `toastIn .3s ease forwards, toastOut .3s ease ${delay}s forwards`;
  
  setTimeout(() => t.remove(), duration);
}

/** Escape HTML entities */
function _uEscHtml(s) {
  if (s == null) return '';
  s = String(s);
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Format ISO date to relative time */
function _uTimeAgo(iso) {
  const d = new Date(iso);
  const now = new Date();
  const diff = (now - d) / 1000;
  if (diff < 60) return 'now';
  if (diff < 3600) return Math.floor(diff / 60) + 'm';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h';
  return Math.floor(diff / 86400) + 'd';
}

/* ---- Backward Compatibility ---- */
// Expose on window for scripts that haven't migrated to imports yet.
window._utils = { $: _u$, $$: _u$$, el: _uEl, toast: _uToast, escHtml: _uEscHtml, timeAgo: _uTimeAgo };

