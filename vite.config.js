/**
 * Clawzd — Vite Configuration.
 *
 * This config integrates Vite as a JS/CSS bundler alongside the
 * existing FastAPI/Jinja2 backend. In dev mode, Vite serves assets
 * with HMR. In production, it builds optimized bundles into static/dist/.
 *
 * The FastAPI server remains the primary server — Vite does NOT
 * replace it. The Jinja2 templates reference either:
 *   - /static/dist/... (production bundle)
 *   - http://localhost:5173/... (dev mode via Vite dev server)
 */
import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
  // Root directory for Vite (where the source files are)
  root: resolve(__dirname, 'static'),

  // Base path for assets (matches FastAPI's static mount)
  base: '/static/',

  build: {
    // Output to static/dist/ (gitignored, served by FastAPI)
    outDir: resolve(__dirname, 'static/dist'),
    emptyOutDir: true,

    // Multi-entry build: one entry per major module
    rollupOptions: {
      input: {
        // Main ES module entry — imports all core modules
        main: resolve(__dirname, 'static/js/main.js'),
        // Core app entry (IIFE — chat, init, OC API)
        app: resolve(__dirname, 'static/js/app.js'),
        // Core modules
        event_bus: resolve(__dirname, 'static/js/core/event_bus.js'),
        component_registry: resolve(__dirname, 'static/js/core/component_registry.js'),
        streaming_parser: resolve(__dirname, 'static/js/core/streaming_parser.js'),
        theme: resolve(__dirname, 'static/js/core/theme.js'),
        utils: resolve(__dirname, 'static/js/core/utils.js'),
        // Components
        token_tracker: resolve(__dirname, 'static/js/components/token_tracker.js'),
        chat_enhancements: resolve(__dirname, 'static/js/components/chat_enhancements.js'),
        voice_input: resolve(__dirname, 'static/js/components/voice_input.js'),
        model_manager: resolve(__dirname, 'static/js/components/model_manager.js'),
        twitter_watch: resolve(__dirname, 'static/js/components/twitter_watch.js'),
        skill_catalog: resolve(__dirname, 'static/js/components/skill_catalog.js'),
        // Studios
        editor: resolve(__dirname, 'static/js/studios/editor.js'),
        media: resolve(__dirname, 'static/js/studios/media.js'),
        presentation: resolve(__dirname, 'static/js/studios/presentation.js'),
        automation: resolve(__dirname, 'static/js/studios/automation.js'),
        project_studio: resolve(__dirname, 'static/js/project_studio.js'),
        spec_studio: resolve(__dirname, 'static/js/studios/spec.js'),
        research_studio: resolve(__dirname, 'static/js/studios/research.js'),
        studio_editor: resolve(__dirname, 'static/js/studios/studio_editor.js'),
      },
      output: {
        // Keep predictable filenames (no hash) for Jinja2 templates
        entryFileNames: 'js/[name].js',
        chunkFileNames: 'js/chunks/[name]-[hash].js',
        assetFileNames: (assetInfo) => {
          if (assetInfo.name && assetInfo.name.endsWith('.css')) {
            return 'css/[name][extname]';
          }
          return 'assets/[name]-[hash][extname]';
        },
      },
    },

    // Don't minify in development builds for easier debugging
    minify: 'esbuild',
    sourcemap: true,
  },

  server: {
    // Vite dev server settings
    port: 5173,
    strictPort: true,

    // Proxy API requests to FastAPI
    proxy: {
      '/api': 'http://localhost:8000',
      '/chat': 'http://localhost:8000',
      '/send': 'http://localhost:8000',
      '/stream': 'http://localhost:8000',
      '/rag': 'http://localhost:8000',
      '/web': 'http://localhost:8000',
      '/image': 'http://localhost:8000',
      '/workspace': 'http://localhost:8000',
      '/local': 'http://localhost:8000',
      '/quality': 'http://localhost:8000',
      '/browser': 'http://localhost:8000',
      '/screenshot': 'http://localhost:8000',
      '/automation': 'http://localhost:8000',
      '/research': 'http://localhost:8000',
      '/presentation': 'http://localhost:8000',
      '/project': 'http://localhost:8000',
      '/skills': 'http://localhost:8000',
      '/telegram': 'http://localhost:8000',
    },
  },
});
