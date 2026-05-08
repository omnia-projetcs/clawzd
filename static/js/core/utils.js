/**
 * Clawzd — Shared DOM Utilities.
 *
 * Core helper functions used across all modules.
 * These are exported as ES modules AND placed on window
 * for backward compatibility with the app.js IIFE.
 */

/** Query a single element */
export function $(selector, context) {
  return (context || document).querySelector(selector);
}

/** Query all elements (returns array) */
export function $$(selector, context) {
  return Array.from((context || document).querySelectorAll(selector));
}

/** Create a DOM element with attributes and children */
export function el(tag, attrs, children) {
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
export function toast(msg) {
  const t = el('div', { class: 'toast', html: msg });
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 20300);
}

/** Escape HTML entities */
export function escHtml(s) {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Format ISO date to relative time */
export function timeAgo(iso) {
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
window._utils = { $, $$, el, toast, escHtml, timeAgo };
