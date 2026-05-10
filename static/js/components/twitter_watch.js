/**
 * Clawzd — TwitterWatch
 * Extracted from app.js for modular architecture.
 * Uses window globals for shared utilities (el, $, $$, toast, escHtml, icon, ICONS).
 */
/* global $, $$, el, toast, escHtml, icon, ICONS, OC */

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
        ? `<img src="${this._esc(t.author_avatar)}" alt="">`
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
          ${t.url ? `<a class="tw-card-link" href="${this._esc(t.url)}" target="_blank" rel="noopener">Open ↗</a>` : ''}
          ${t.source ? `<span class="tw-card-source">via ${this._esc(t.source)}</span>` : ''}
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
        const photoHtml = item.photo ? `<img src="${this._esc(item.photo)}" alt="">` : `<span class="li-initials">${(item.name || '?').split(' ').map(w => w[0]).join('').slice(0, 2)}</span>`;
        card.innerHTML = `<div class="li-card-header"><div class="li-card-photo">${photoHtml}</div><div class="li-card-info"><div class="li-card-name">${this._esc(item.name || 'Unknown')}</div><div class="li-card-headline">${this._esc(item.headline || '')}</div></div></div>${item.snippet ? `<div class="li-card-snippet">${this._esc(item.snippet)}</div>` : ''}<div class="li-card-footer"><span class="li-card-type profile">Profile</span>${item.url ? `<a class="li-card-link" href="${this._esc(item.url)}" target="_blank" rel="noopener">View on LinkedIn ↗</a>` : ''}</div>`;
      } else {
        card.innerHTML = `<div class="li-card-header"><div class="li-card-photo"><svg class="ic" width="18" height="18"><use href="#icon-file-text"></use></svg></div><div class="li-card-info"><div class="li-card-name">${this._esc(item.title || 'Article')}</div><div class="li-card-headline">${item.author ? 'by ' + this._esc(item.author) : ''}</div></div></div>${item.snippet ? `<div class="li-card-snippet">${this._esc(item.snippet)}</div>` : ''}<div class="li-card-footer"><span class="li-card-type article">Article</span>${item.url ? `<a class="li-card-link" href="${this._esc(item.url)}" target="_blank" rel="noopener">Read on LinkedIn ↗</a>` : ''}</div>`;
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

// Backward compatibility
window.TwitterWatch = TwitterWatch;
