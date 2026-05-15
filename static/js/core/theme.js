/**
 * Clawzd — Dynamic Theme Engine.
 *
 * Inspired by OpenUI's ThemeProvider + createTheme().
 * Manages color themes with CSS custom properties, supports
 * user-created themes, and persists selection in localStorage.
 *
 * Usage:
 *   ThemeEngine.apply('midnight');
 *   ThemeEngine.register('custom', { primary: '#ff6b6b', ... });
 *   ThemeEngine.toggle(); // dark ↔ light
 */

const STORAGE_KEY = 'omniclaw-theme';
  const CUSTOM_STORAGE_KEY = 'clawzd-custom-themes';

  /* ---- Built-in themes ---- */

  const _builtinThemes = {
    dark: {
      label: '🌙 Dark',
      primary: '#6366f1',
      'primary-hover': '#818cf8',
      accent: '#818cf8',
      'bg-primary': '#0f0f14',
      'bg-secondary': '#1a1a24',
      'bg-tertiary': '#252532',
      border: '#2d2d3d',
      'text-primary': '#f0f0f5',
      'text-secondary': '#a0a0b5',
      'text-muted': '#6b6b80',
      success: '#10b981',
      warning: '#f59e0b',
      error: '#ef4444',
      info: '#3b82f6',
    },
    light: {
      label: '☀️ Light',
      primary: '#4f46e5',
      'primary-hover': '#4338ca',
      accent: '#6366f1',
      'bg-primary': '#ffffff',
      'bg-secondary': '#f8fafc',
      'bg-tertiary': '#f1f5f9',
      border: '#e2e8f0',
      'text-primary': '#1e293b',
      'text-secondary': '#64748b',
      'text-muted': '#94a3b8',
      success: '#059669',
      warning: '#d97706',
      error: '#dc2626',
      info: '#2563eb',
    },
    midnight: {
      label: '🌌 Midnight',
      primary: '#818cf8',
      'primary-hover': '#a5b4fc',
      accent: '#c4b5fd',
      'bg-primary': '#0a0a12',
      'bg-secondary': '#12121e',
      'bg-tertiary': '#1c1c2e',
      border: '#252540',
      'text-primary': '#e8e8f0',
      'text-secondary': '#9090b0',
      'text-muted': '#606080',
      success: '#34d399',
      warning: '#fbbf24',
      error: '#f87171',
      info: '#60a5fa',
    },
    forest: {
      label: '🌲 Forest',
      primary: '#10b981',
      'primary-hover': '#34d399',
      accent: '#6ee7b7',
      'bg-primary': '#0c1a12',
      'bg-secondary': '#142820',
      'bg-tertiary': '#1c3828',
      border: '#264030',
      'text-primary': '#e8f5e8',
      'text-secondary': '#a0c8a0',
      'text-muted': '#608060',
      success: '#22c55e',
      warning: '#eab308',
      error: '#f87171',
      info: '#38bdf8',
    },
    ocean: {
      label: '🌊 Ocean',
      primary: '#0ea5e9',
      'primary-hover': '#38bdf8',
      accent: '#7dd3fc',
      'bg-primary': '#0a1520',
      'bg-secondary': '#0f2030',
      'bg-tertiary': '#152a3e',
      border: '#1e3a52',
      'text-primary': '#e0f0ff',
      'text-secondary': '#90b8d8',
      'text-muted': '#607898',
      success: '#10b981',
      warning: '#f59e0b',
      error: '#ef4444',
      info: '#3b82f6',
    },
    sunset: {
      label: '🌅 Sunset',
      primary: '#f97316',
      'primary-hover': '#fb923c',
      accent: '#fdba74',
      'bg-primary': '#1a0f0a',
      'bg-secondary': '#281810',
      'bg-tertiary': '#38201a',
      border: '#4a2818',
      'text-primary': '#fff0e0',
      'text-secondary': '#d0a080',
      'text-muted': '#907060',
      success: '#22c55e',
      warning: '#eab308',
      error: '#ef4444',
      info: '#60a5fa',
    }
  };

  /** @type {Map<string, Object>} Custom user themes */
  const _customThemes = new Map();

  const ThemeEngine = {
    /**
     * Apply a theme by name.
     * @param {string} name - Theme name
     */
    apply(name) {
      const theme = _builtinThemes[name] || _customThemes.get(name);
      if (!theme) {
        console.warn(`[ThemeEngine] Unknown theme: "${name}"`);
        return;
      }

      const root = document.documentElement;
      Object.entries(theme).forEach(([key, value]) => {
        if (key === 'label') return;
        root.style.setProperty(`--${key}`, value);
      });

      // Update hljs theme link
      const hljsLink = document.getElementById('hljs-theme');
      if (hljsLink) {
        const isLight = name === 'light';
        hljsLink.href = `/static/css/${isLight ? 'github.min.css' : 'github-dark.min.css'}`;
      }

      // Reinitialize mermaid with theme
      if (window.mermaid) {
        const isLight = name === 'light';
        try {
          window.mermaid.initialize({
            startOnLoad: false,
            securityLevel: 'loose',
            theme: isLight ? 'default' : 'base',
            themeVariables: isLight ? {} : {
              fontFamily: 'inherit',
              primaryColor: theme['bg-tertiary'] || '#252532',
              primaryTextColor: theme['text-primary'] || '#f8fafc',
              primaryBorderColor: theme.border || '#3d3d4e',
              lineColor: theme.primary || '#6366f1',
              secondaryColor: theme['bg-secondary'] || '#2b2b36',
              tertiaryColor: theme['bg-primary'] || '#1a1a24',
              mainBkg: theme['bg-secondary'] || '#1e1e2d',
              nodeBorder: theme.primary || '#4f46e5',
              clusterBkg: 'transparent',
              clusterBorder: theme.primary || '#4f46e5',
              defaultLinkColor: theme.accent || '#818cf8',
              textColor: theme['text-secondary'] || '#e2e8f0',
              edgeLabelBackground: theme['bg-secondary'] || '#2b2b36',
            }
          });
        } catch (e) {
          // Mermaid re-init is non-critical
        }
      }

      // Persist selection
      localStorage.setItem(STORAGE_KEY, name);

      // Emit event
      if (window.EventBus) {
        window.EventBus.emit('theme:changed', { name, theme });
      }
    },

    /**
     * Toggle between dark and light themes.
     */
    toggle() {
      const current = this.current();
      this.apply(current === 'light' ? 'dark' : 'light');
    },

    /**
     * Get the current theme name.
     * @returns {string}
     */
    current() {
      return localStorage.getItem(STORAGE_KEY) || 'dark';
    },

    /**
     * Register a custom theme.
     * @param {string} name
     * @param {Object} tokens - CSS custom property values
     */
    register(name, tokens) {
      _customThemes.set(name, tokens);
      this._saveCustomThemes();
    },

    /**
     * Delete a custom theme.
     * @param {string} name
     */
    unregister(name) {
      _customThemes.delete(name);
      this._saveCustomThemes();
    },

    /**
     * Get all available theme names with labels.
     * @returns {Array<{name: string, label: string, custom: boolean}>}
     */
    list() {
      const themes = [];
      Object.entries(_builtinThemes).forEach(([name, t]) => {
        themes.push({ name, label: t.label || name, custom: false });
      });
      _customThemes.forEach((t, name) => {
        themes.push({ name, label: t.label || name, custom: true });
      });
      return themes;
    },

    /**
     * Initialize: apply saved theme on page load.
     */
    init() {
      this._loadCustomThemes();
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved && (saved in _builtinThemes || _customThemes.has(saved))) {
        this.apply(saved);
      }
    },

    _saveCustomThemes() {
      try {
        const obj = {};
        _customThemes.forEach((v, k) => { obj[k] = v; });
        localStorage.setItem(CUSTOM_STORAGE_KEY, JSON.stringify(obj));
      } catch (e) {
        // localStorage full or unavailable
      }
    },

    _loadCustomThemes() {
      try {
        const raw = localStorage.getItem(CUSTOM_STORAGE_KEY);
        if (raw) {
          const obj = JSON.parse(raw);
          Object.entries(obj).forEach(([k, v]) => _customThemes.set(k, v));
        }
      } catch (e) {
        // Corrupt data, ignore
      }
    }
  };

  window.ThemeEngine = ThemeEngine;
