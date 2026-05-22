/**
 * Clawzd — PresentationStudio
 * Extracted from app.js for modular architecture.
 * Uses window globals for shared utilities (el, $, $$, toast, escHtml, icon, ICONS).
 */
/* global $, $$, el, toast, escHtml, icon, ICONS, OC */

// ==========================================
// Presentation Studio Mode
// ==========================================
class PresentationStudio {
  constructor() {
    this.pages = [{ elements: [] }];
    this.currentPage = 0;
    this.selectedElement = null;
    this.dragItem = null;
    this.resizeItem = null;
    this.dragStartX = 0;
    this.dragStartY = 0;

    this.canvasW = 960;
    this.canvasH = 540;
    this.presId = localStorage.getItem('pt-last-id') || null;

    this.ctxMenuEl = null;

    // Internal clipboard for copy/paste of elements
    this._clipboard = null;
    this._pasteOffset = 0;

    // Snap-to-grid
    this.snapGrid = 20;
    this.showGrid = true;

    // Undo/Redo history
    this.history = [];
    this.historyIndex = -1;
    this.isUndoRedo = false;

    this.initEvents();
    this.loadRecent();
    this.loadTemplates();
    this.loadSavedPresentations();
  }

  async loadRecent() {
    if (!this.presId) {
      this.renderPages();
      this.renderCanvas();
      return;
    }
    try {
      const res = await fetch(`/presentation/load/${this.presId}`);
      if (res.ok) {
        const data = await res.json();
        this.pages = data.pages || [{ elements: [] }];
        this.canvasW = data.canvas_width || 960;
        this.canvasH = data.canvas_height || 540;
        this.title = data.title || '';
        if ($('#pt-pres-title')) $('#pt-pres-title').value = this.title || "My Presentation";

        // Try to sync format selector based on dims
        const sel = $('#pt-format-select');
        if (sel) {
          if (this.canvasW === 960 && this.canvasH === 540) sel.value = '16:9';
          else if (this.canvasW === 960 && this.canvasH === 720) sel.value = '4:3';
          else if (this.canvasW === 540 && this.canvasH === 960) sel.value = 'portrait';
          else if (this.canvasW === 794 && this.canvasH === 1123) sel.value = 'A4';
          else if (this.canvasW === 1080 && this.canvasH === 1080) sel.value = 'IG';
          else if (this.canvasW === 1280 && this.canvasH === 720) sel.value = 'YT';
          else if (this.canvasW === 638 && this.canvasH === 368) sel.value = 'card';
        }
      }
    } catch (e) {
      console.warn("Could not load recent presentation", e);
    }
    this.currentPage = 0;
    this.renderPages();
    this.renderCanvas();
    this.updateCanvasZoom();

    // Initial state save
    this.saveState();
  }

  toggle(show) {
    const panel = $('#presentation-layout');
    if (!panel) return;
    if (show) {
      panel.style.display = 'flex';
      this.renderCanvas();
      this.updateCanvasZoom();
    } else {
      panel.style.display = 'none';
    }
  }

  initEvents() {
    $('#pt-shapes-toggle')?.addEventListener('click', () => {
      const grid = $('#pt-shapes-grid');
      const chevron = $('#pt-shapes-chevron');
      if (grid && chevron) {
        grid.classList.toggle('collapsed');
        chevron.style.transform = grid.classList.contains('collapsed') ? 'rotate(0deg)' : 'rotate(180deg)';
      }
    });
    const closeAllBrowsers = () => {
      ['presentation-gallery-browser', 'presentation-library-browser',
        'presentation-illustrations-browser', 'presentation-stock-browser',
        'presentation-templates-browser', 'presentation-saved-browser',
        'presentation-docgen-browser'].forEach(id => {
          const el = $('#' + id);
          if (el) el.style.display = 'none';
        });
    };

    $('#pt-add-text')?.addEventListener('click', () => this.addElement('text', 'Double click to edit'));
    $('#pt-add-table')?.addEventListener('click', () => this.addElement('table', '| Header 1 | Header 2 |\n|---|---|\n| Data 1 | Data 2 |'));
    $('#pt-add-image')?.addEventListener('click', () => {
      closeAllBrowsers();
      $('#presentation-gallery-browser').style.display = 'flex';
      this.openGallery();
    });
    $('#pt-show-templates')?.addEventListener('click', () => {
      closeAllBrowsers();
      $('#presentation-templates-browser').style.display = 'flex';
    });
    $('#pt-templates-close')?.addEventListener('click', () => {
      $('#presentation-templates-browser').style.display = 'none';
    });

    $('#pt-show-saved')?.addEventListener('click', () => {
      closeAllBrowsers();
      $('#presentation-saved-browser').style.display = 'flex';
    });
    $('#pt-saved-close')?.addEventListener('click', () => {
      $('#presentation-saved-browser').style.display = 'none';
    });

    $('#pt-show-docgen')?.addEventListener('click', () => {
      closeAllBrowsers();
      $('#presentation-docgen-browser').style.display = 'flex';
    });
    $('#pt-docgen-close')?.addEventListener('click', () => {
      $('#presentation-docgen-browser').style.display = 'none';
    });

    // Template sub-mode toggle
    $$('#pt-tpl-submode-toggle .media-type-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        $$('#pt-tpl-submode-toggle .media-type-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.templateSubMode = btn.dataset.tplmode;
        this._updateDocgenVisibility();
      });
    });
    this.templateSubMode = 'business_card';

    const liFetchBtn = $('#pt-tpl-linkedin-fetch');
    if (liFetchBtn) liFetchBtn.addEventListener('click', () => this.fetchLinkedInProfile());

    const docgenBtn = $('#pt-tpl-generate-btn');
    if (docgenBtn) docgenBtn.addEventListener('click', () => this.generateTemplate());
    $('#pt-show-library')?.addEventListener('click', () => {
      closeAllBrowsers();
      $('#presentation-library-browser').style.display = 'flex';
      this.loadLibrary();
    });
    $('#pt-library-close')?.addEventListener('click', () => {
      $('#presentation-library-browser').style.display = 'none';
    });
    $('#pt-library-search')?.addEventListener('input', (e) => {
      this.filterLibrary(e.target.value);
    });
    $('#pt-add-rect')?.addEventListener('click', () => this.addElement('shape', 'rect'));
    $('#pt-add-rounded-rect')?.addEventListener('click', () => this.addElement('shape', 'rounded-rect'));
    $('#pt-add-circle')?.addEventListener('click', () => this.addElement('shape', 'circle'));
    $('#pt-add-triangle')?.addEventListener('click', () => this.addElement('shape', 'triangle'));
    $('#pt-add-diamond')?.addEventListener('click', () => this.addElement('shape', 'diamond'));
    $('#pt-add-pentagon')?.addEventListener('click', () => this.addElement('shape', 'pentagon'));
    $('#pt-add-hexagon')?.addEventListener('click', () => this.addElement('shape', 'hexagon'));
    $('#pt-add-star')?.addEventListener('click', () => this.addElement('shape', 'star'));
    $('#pt-add-heart')?.addEventListener('click', () => this.addElement('shape', 'heart'));
    $('#pt-add-cross')?.addEventListener('click', () => this.addElement('shape', 'cross'));
    $('#pt-add-arrow')?.addEventListener('click', () => this.addElement('shape', 'arrow'));
    $('#pt-add-chevron')?.addEventListener('click', () => this.addElement('shape', 'chevron'));
    $('#pt-add-cloud')?.addEventListener('click', () => this.addElement('shape', 'cloud'));
    $('#pt-add-speech-bubble')?.addEventListener('click', () => this.addElement('shape', 'speech-bubble'));
    $('#pt-add-parallelogram')?.addEventListener('click', () => this.addElement('shape', 'parallelogram'));
    $('#pt-add-trapezoid')?.addEventListener('click', () => this.addElement('shape', 'trapezoid'));
    $('#pt-add-ring')?.addEventListener('click', () => this.addElement('shape', 'ring'));

    // SVG Illustrations browser
    $('#pt-show-illustrations')?.addEventListener('click', () => {
      closeAllBrowsers();
      const browser = $('#presentation-illustrations-browser');
      if (browser) {
        browser.style.display = 'flex';
        this.loadIllustrations();
      }
    });
    $('#pt-illustrations-close')?.addEventListener('click', () => {
      const browser = $('#presentation-illustrations-browser');
      if (browser) browser.style.display = 'none';
    });
    $('#pt-illustrations-search')?.addEventListener('input', (e) => {
      this.filterIllustrations(e.target.value);
    });

    // Stock Photo browser (local open-source library)
    $('#pt-show-stock-photos')?.addEventListener('click', () => {
      closeAllBrowsers();
      const browser = $('#presentation-stock-browser');
      if (browser) {
        browser.style.display = 'flex';
        this.loadStockPhotos();
      }
    });
    $('#pt-stock-close')?.addEventListener('click', () => {
      const browser = $('#presentation-stock-browser');
      if (browser) browser.style.display = 'none';
    });
    $('#pt-stock-search-btn')?.addEventListener('click', () => this.loadStockPhotos());
    $('#pt-stock-search-input')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.loadStockPhotos();
    });

    // Grid toggle
    $('#pt-grid-toggle')?.addEventListener('click', () => {
      this.showGrid = !this.showGrid;
      const btn = $('#pt-grid-toggle');
      if (btn) btn.classList.toggle('active', this.showGrid);
      this.renderCanvas();
    });
    // Set initial grid state
    const gridBtn = $('#pt-grid-toggle');
    if (gridBtn) gridBtn.classList.add('active');

    // AI Generation
    $('#pt-ai-generate')?.addEventListener('click', () => this.generatePresentation());
    $('#pt-ai-enrich')?.addEventListener('click', () => this.enrichPresentation());
    $('#pt-prop-ai-enhance')?.addEventListener('click', () => this.enhanceSelectedText());
    $('#pt-ai-prompt')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.generatePresentation();
    });

    const addPage = $('#pt-add-page');
    if (addPage) addPage.addEventListener('click', () => this.addPage());

    const formatSel = $('#pt-format-select');
    if (formatSel) formatSel.addEventListener('change', (e) => this.changeFormat(e.target.value));

    const zoomSel = $('#pt-zoom-select');
    if (zoomSel) zoomSel.addEventListener('change', () => this.updateCanvasZoom());
    window.addEventListener('resize', () => {
      if ($('#presentation-layout')?.style.display !== 'none') {
        this.updateCanvasZoom();
      }
    });

    const canvas = $('#presentation-canvas');
    if (canvas) {
      canvas.addEventListener('mousedown', (e) => {
        if (e.target === canvas) this.selectElement(null);
      });
      // Right-click on empty canvas -> show paste option
      canvas.addEventListener('contextmenu', (e) => {
        if (e.target !== canvas && !e.target.classList.contains('canvas-grid-overlay')) return;
        e.preventDefault();
        // Only show if there's something to paste
        if (!this._clipboard) return;
        this.ctxMenuEl = null;
        const menu = $('#pt-context-menu');
        if (menu) {
          menu.style.display = 'flex';
          let x = e.clientX;
          let y = e.clientY;
          if (x + 200 > window.innerWidth) x = window.innerWidth - 200;
          if (y + 60 > window.innerHeight) y = window.innerHeight - 60;
          menu.style.left = x + 'px';
          menu.style.top = y + 'px';
          // Hide everything except paste
          ['pt-ctx-copy', 'pt-ctx-cut', 'pt-ctx-duplicate', 'pt-ctx-forward', 'pt-ctx-backward', 'pt-ctx-front', 'pt-ctx-back', 'pt-ctx-bg', 'pt-ctx-delete'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.display = 'none';
          });
          const pasteBtn = $('#pt-ctx-paste');
          if (pasteBtn) pasteBtn.style.display = 'flex';
          // Hide all separators for a clean single-item menu
          menu.querySelectorAll('div[style*="height:1px"]').forEach(d => d.style.display = 'none');
        }
      });
    }

    // Export Dialog
    const exportModal = $('#pt-export-modal');
    $('#pt-btn-export-dialog')?.addEventListener('click', () => {
      if (exportModal) exportModal.style.display = 'flex';
    });
    $('#pt-export-close')?.addEventListener('click', () => {
      if (exportModal) exportModal.style.display = 'none';
    });

    const radios = document.querySelectorAll('input[name="pt-export-pages"]');
    radios.forEach(r => {
      r.addEventListener('change', (e) => {
        const cust = $('#pt-export-custom-pages');
        if (cust) cust.disabled = e.target.value !== 'custom';
      });
    });

    $('#pt-export-format')?.addEventListener('change', (e) => {
      const opts = $('#pt-video-options');
      if (opts) opts.style.display = e.target.value === 'mp4' ? 'block' : 'none';
    });

    $('#pt-video-subtitles')?.addEventListener('change', (e) => {
      const langGrp = $('#pt-video-subtitles-lang-group');
      if (langGrp) langGrp.style.display = e.target.checked ? 'block' : 'none';
    });

    $('#pt-video-lang')?.addEventListener('change', (e) => {
      const lang = e.target.value;
      const voiceSelect = $('#pt-video-voice');
      if (voiceSelect) {
        voiceSelect.innerHTML = '';
        if (lang === 'fr') {
          const opt1 = document.createElement('option');
          opt1.value = 'fr-FR-EloiseNeural';
          opt1.textContent = 'Eloise (Voix Premium Féminine)';
          voiceSelect.appendChild(opt1);
          
          const opt2 = document.createElement('option');
          opt2.value = 'fr-FR-RemyMultilingualNeural';
          opt2.textContent = 'Remy (Voix Premium Masculine)';
          voiceSelect.appendChild(opt2);

          const opt3 = document.createElement('option');
          opt3.value = 'fr-FR-VivienneMultilingualNeural';
          opt3.textContent = 'Vivienne (Voix Claire Féminine)';
          voiceSelect.appendChild(opt3);

          const opt4 = document.createElement('option');
          opt4.value = 'fr-FR-DeniseNeural';
          opt4.textContent = 'Denise (Standard Féminine)';
          voiceSelect.appendChild(opt4);

          const opt5 = document.createElement('option');
          opt5.value = 'fr-FR-HenriNeural';
          opt5.textContent = 'Henri (Standard Masculine)';
          voiceSelect.appendChild(opt5);
        } else if (lang === 'en') {
          const opt1 = document.createElement('option');
          opt1.value = 'en-US-AvaMultilingualNeural';
          opt1.textContent = 'Ava (Premium Conversational Female)';
          voiceSelect.appendChild(opt1);
          
          const opt2 = document.createElement('option');
          opt2.value = 'en-US-AndrewMultilingualNeural';
          opt2.textContent = 'Andrew (Premium Warm Male)';
          voiceSelect.appendChild(opt2);

          const opt3 = document.createElement('option');
          opt3.value = 'en-US-AriaNeural';
          opt3.textContent = 'Aria (Professional Female)';
          voiceSelect.appendChild(opt3);

          const opt4 = document.createElement('option');
          opt4.value = 'en-US-BrianMultilingualNeural';
          opt4.textContent = 'Brian (Sincere Male)';
          voiceSelect.appendChild(opt4);

          const opt5 = document.createElement('option');
          opt5.value = 'en-US-GuyNeural';
          opt5.textContent = 'Guy (Standard Male)';
          voiceSelect.appendChild(opt5);
        }
      }
    });

    $('#pt-slide-narration')?.addEventListener('input', (e) => {
      if (this.pages[this.currentPage]) {
        this.pages[this.currentPage].narration = e.target.value;
      }
    });

    $('#pt-slide-narrate-ai')?.addEventListener('click', async () => {
      const page = this.pages[this.currentPage];
      if (!page) return;
      const btn = $('#pt-slide-narrate-ai');
      const originalText = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<span class="pt-ai-gen-spinner" style="display:inline-block"></span> Generating...';
      try {
        const voice = $('#pt-video-voice')?.value || 'fr-FR-DeniseNeural';
        const res = await fetch('/presentation/auto-narrate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            elements: page.elements || [],
            voice: voice
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Script generation failed');

        
        page.narration = data.script || '';
        const textEl = $('#pt-slide-narration');
        if (textEl) textEl.value = page.narration;
        toast('✨ Narration script written by AI!');
      } catch (e) {
        toast(`⚠️ AI Error: ${e.message}`, 4000);
      } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
      }
    });

    $('#pt-export-confirm')?.addEventListener('click', () => {
      if (exportModal) exportModal.style.display = 'none';
      const format = $('#pt-export-format')?.value || 'pptx';
      const pagesMode = document.querySelector('input[name="pt-export-pages"]:checked')?.value || 'all';
      const customPages = $('#pt-export-custom-pages')?.value || '';
      this.export(format, pagesMode, customPages);
    });

    // Player mode
    $('#pt-btn-player')?.addEventListener('click', () => this.startPlayer());

    // Import button
    $('#pt-btn-import')?.addEventListener('click', () => {
      $('#pt-import-input')?.click();
    });
    $('#pt-import-input')?.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const ext = file.name.split('.').pop().toLowerCase();
      if (!['pdf', 'pptx'].includes(ext)) {
        toast('⚠️ Only PDF and PPTX files are supported', 4000);
        e.target.value = '';
        return;
      }
      const formData = new FormData();
      formData.append('file', file);
      const importBtn = $('#pt-btn-import');
      if (importBtn) {
        importBtn.disabled = true;
        importBtn.innerHTML = '<span class="pt-ai-gen-spinner" style="display:inline-block"></span> Importing...';
      }
      try {
        const res = await fetch('/presentation/import', { method: 'POST', body: formData });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Import failed');
        if (data.pages && data.pages.length > 0) {
          this.pages = data.pages;
          this.canvasW = data.canvas_width || 960;
          this.canvasH = data.canvas_height || 540;
          this.currentPage = 0;
          this.presId = null;
          localStorage.removeItem('pt-last-id');
          const titleInput = $('#pt-pres-title');
          if (titleInput) titleInput.value = data.title || file.name.replace(/\.[^.]+$/, '');
          this.title = titleInput?.value || '';
          this.selectElement(null);
          this.renderPages();
          this.renderCanvas();
          this.updateCanvasZoom();
          this.saveState();
          toast(ICONS.check(14) + ` Imported ${data.pages.length} slide(s) from ${ext.toUpperCase()}`);
          // Close menu dropdown
          const dd = $('#pt-menu-dropdown');
          if (dd) dd.style.display = 'none';
        } else {
          toast('⚠️ No slides found in file', 4000);
        }
      } catch (err) {
        toast(`❌ Import failed: ${err.message}`, 5000);
        console.error('Import error:', err);
      } finally {
        if (importBtn) {
          importBtn.disabled = false;
          importBtn.innerHTML = '<svg class="ic" width="14" height="14"><use href="#icon-import-txt"></use></svg> Import';
        }
        e.target.value = '';
      }
    });

    // Handle fullscreen exit to also stop player
    document.addEventListener('fullscreenchange', () => {
      if (!document.fullscreenElement && this._playerActive) {
        this.stopPlayer();
      }
    });

    $('#pt-btn-new')?.addEventListener('click', () => this.newPresentation());
    $('#pt-sidebar-new')?.addEventListener('click', () => this.newPresentation());
    $('#pt-btn-save')?.addEventListener('click', () => this.save());

    // Toolbar Menu Toggle
    const menuToggle = $('#pt-menu-toggle');
    const menuDropdown = $('#pt-menu-dropdown');
    if (menuToggle && menuDropdown) {
      menuToggle.addEventListener('click', (e) => {
        e.stopPropagation();
        menuDropdown.style.display = menuDropdown.style.display === 'none' ? 'flex' : 'none';
      });
      document.addEventListener('click', (e) => {
        if (!menuToggle.contains(e.target) && !menuDropdown.contains(e.target)) {
          menuDropdown.style.display = 'none';
        }
      });
    }

    // Undo / Redo
    $('#pt-btn-undo')?.addEventListener('click', () => {
      if (this.historyIndex > 0) {
        this.isUndoRedo = true;
        this.historyIndex--;
        const state = this.history[this.historyIndex];
        this.pages = JSON.parse(JSON.stringify(state.pages));
        this.canvasW = state.canvasW;
        this.canvasH = state.canvasH;
        this.selectElement(null);
        this.renderPages();
        this.renderCanvas();
        this.updateUndoRedoButtons();
        setTimeout(() => this.isUndoRedo = false, 50);
      }
    });
    $('#pt-btn-redo')?.addEventListener('click', () => {
      if (this.historyIndex < this.history.length - 1) {
        this.isUndoRedo = true;
        this.historyIndex++;
        const state = this.history[this.historyIndex];
        this.pages = JSON.parse(JSON.stringify(state.pages));
        this.canvasW = state.canvasW;
        this.canvasH = state.canvasH;
        this.selectElement(null);
        this.renderPages();
        this.renderCanvas();
        this.updateUndoRedoButtons();
        setTimeout(() => this.isUndoRedo = false, 50);
      }
    });

    $('#pt-prop-content')?.addEventListener('input', (e) => {
      if (this.selectedElement && (this.selectedElement.type === 'text' || this.selectedElement.type === 'table')) {
        this.selectedElement.content = e.target.value;
        this.renderCanvas();
      }
    });

    const toggleFormat = (id, field) => {
      const btn = $(id);
      if (!btn) return;
      btn.addEventListener('click', () => {
        if (this.selectedElement && this.selectedElement.type === 'text') {
          this.selectedElement[field] = !this.selectedElement[field];
          btn.style.background = this.selectedElement[field] ? 'var(--accent)' : 'transparent';
          this.renderCanvas();
        }
      });
    };
    toggleFormat('#pt-prop-bold', 'isBold');
    toggleFormat('#pt-prop-italic', 'isItalic');
    toggleFormat('#pt-prop-underline', 'isUnderline');
    toggleFormat('#pt-prop-strikethrough', 'isStrikethrough');
    toggleFormat('#pt-prop-list', 'isList');

    const bindProp = (id, field, parser = String) => {
      $(id)?.addEventListener('input', (e) => {
        if (this.selectedElement) {
          this.selectedElement[field] = parser(e.target.value);
          this.renderCanvas();
          // Sync hex<->color if it's a color
          if (id.endsWith('-hex') && $(id.replace('-hex', ''))) {
            $(id.replace('-hex', '')).value = this.selectedElement[field];
          }
          if (!id.endsWith('-hex') && $(id + '-hex')) {
            $(id + '-hex').value = this.selectedElement[field];
          }
        }
      });
    };

    bindProp('#pt-prop-fontsize', 'fontSize', parseInt);
    bindProp('#pt-prop-fontfamily', 'fontFamily');
    bindProp('#pt-prop-color', 'color');
    bindProp('#pt-prop-color-hex', 'color');
    bindProp('#pt-prop-fill', 'backgroundColor');
    bindProp('#pt-prop-fill-hex', 'backgroundColor');
    bindProp('#pt-prop-header-bg', 'headerBgColor');
    bindProp('#pt-prop-header-bg-hex', 'headerBgColor');
    bindProp('#pt-prop-border', 'borderColor');
    bindProp('#pt-prop-border-hex', 'borderColor');
    bindProp('#pt-prop-borderwidth', 'borderWidth', parseInt);
    bindProp('#pt-prop-borderradius', 'borderRadius', parseInt);

    $('#pt-prop-header-bg-clear')?.addEventListener('click', () => {
      if (this.selectedElement) {
        this.selectedElement.headerBgColor = 'transparent';
        $('#pt-prop-header-bg-hex').value = 'transparent';
        this.renderCanvas();
      }
    });

    $('#pt-prop-color-clear')?.addEventListener('click', () => {
      if (this.selectedElement) {
        this.selectedElement.color = 'transparent';
        $('#pt-prop-color-hex').value = 'transparent';
        this.renderCanvas();
      }
    });

    $('#pt-prop-fill-clear')?.addEventListener('click', () => {
      if (this.selectedElement) {
        this.selectedElement.backgroundColor = 'transparent';
        $('#pt-prop-fill-hex').value = 'transparent';
        this.renderCanvas();
      }
    });
    $('#pt-prop-border-clear')?.addEventListener('click', () => {
      if (this.selectedElement) {
        this.selectedElement.borderColor = 'transparent';
        $('#pt-prop-border-hex').value = 'transparent';
        this.renderCanvas();
      }
    });

    $('#pt-prop-opacity')?.addEventListener('input', (e) => {
      if (this.selectedElement) {
        this.selectedElement.opacity = parseInt(e.target.value);
        $('#pt-prop-opacity-val').innerText = this.selectedElement.opacity;
        this.renderCanvas();
      }
    });
    $('#pt-prop-shadow')?.addEventListener('input', (e) => {
      if (this.selectedElement) {
        this.selectedElement.shadowLevel = parseInt(e.target.value);
        $('#pt-prop-shadow-val').innerText = this.selectedElement.shadowLevel;
        this.renderCanvas();
      }
    });
    $('#pt-prop-thickness')?.addEventListener('input', (e) => {
      if (this.selectedElement) {
        this.selectedElement.shapeThickness = parseInt(e.target.value);
        const valEl = $('#pt-prop-thickness-val');
        if (valEl) valEl.innerText = this.selectedElement.shapeThickness;
        this.renderCanvas();
      }
    });

    $('#pt-prop-align')?.addEventListener('change', (e) => {
      if (this.selectedElement) {
        this.selectedElement.textAlign = e.target.value;
        this.renderCanvas();
      }
    });
    $('#pt-prop-delete')?.addEventListener('click', () => {
      if (this.selectedElement) {
        const page = this.pages[this.currentPage];
        page.elements = page.elements.filter(e => e !== this.selectedElement);
        this.selectElement(null);
        this.renderCanvas();
      }
    });
    $('#pt-prop-crop')?.addEventListener('click', () => {
      if (this.selectedElement && this.selectedElement.type === 'image') {
        this.selectedElement.isCropMode = !this.selectedElement.isCropMode;
        this.updatePropertiesPanel();
      }
    });

    $('#pt-prop-reset-crop')?.addEventListener('click', () => {
      if (this.selectedElement && this.selectedElement.type === 'image') {
        const el = this.selectedElement;
        const cl = el.cropLeft || 0;
        const ct = el.cropTop || 0;
        const cr = el.cropRight || 0;
        const cb = el.cropBottom || 0;
        const origImgW = el.width / (1 - cl - cr);
        const origImgH = el.height / (1 - ct - cb);
        
        el.x = el.x - (cl * origImgW);
        el.y = el.y - (ct * origImgH);
        el.width = origImgW;
        el.height = origImgH;
        
        el.cropLeft = 0;
        el.cropTop = 0;
        el.cropRight = 0;
        el.cropBottom = 0;
        el.isCropMode = false;
        
        this.updatePropertiesPanel();
      }
    });

    $('#pt-prop-bg')?.addEventListener('click', () => {
      if (this.selectedElement && this.selectedElement.type === 'image') {
        const page = this.pages[this.currentPage];

        // Make it full size
        this.selectedElement.x = 0;
        this.selectedElement.y = 0;
        this.selectedElement.width = this.canvasW;
        this.selectedElement.height = this.canvasH;

        // Move to back
        page.elements = page.elements.filter(e => e !== this.selectedElement);
        page.elements.unshift(this.selectedElement);

        this.renderCanvas();
      }
    });

    // Z-index layer controls
    $('#pt-prop-layer-up')?.addEventListener('click', () => {
      if (this.selectedElement) {
        const els = this.pages[this.currentPage].elements;
        const idx = els.indexOf(this.selectedElement);
        if (idx < els.length - 1) {
          [els[idx], els[idx + 1]] = [els[idx + 1], els[idx]];
          this.renderCanvas();
        }
      }
    });
    $('#pt-prop-layer-down')?.addEventListener('click', () => {
      if (this.selectedElement) {
        const els = this.pages[this.currentPage].elements;
        const idx = els.indexOf(this.selectedElement);
        if (idx > 0) {
          [els[idx], els[idx - 1]] = [els[idx - 1], els[idx]];
          this.renderCanvas();
        }
      }
    });


    // Context Menu logic
    const ctxMenu = $('#pt-context-menu');
    document.addEventListener('click', () => {
      if (ctxMenu) ctxMenu.style.display = 'none';
    });

    const doAction = (action) => {
      if (!this.ctxMenuEl) return;
      const page = this.pages[this.currentPage];
      const els = page.elements;
      const idx = els.indexOf(this.ctxMenuEl);
      if (idx === -1) return;

      if (action === 'forward' && idx < els.length - 1) {
        [els[idx], els[idx + 1]] = [els[idx + 1], els[idx]];
      } else if (action === 'backward' && idx > 0) {
        [els[idx], els[idx - 1]] = [els[idx - 1], els[idx]];
      } else if (action === 'front' && idx < els.length - 1) {
        const [el] = els.splice(idx, 1);
        els.push(el);
      } else if (action === 'back' && idx > 0) {
        const [el] = els.splice(idx, 1);
        els.unshift(el);
      } else if (action === 'bg' && this.ctxMenuEl.type === 'image') {
        this.ctxMenuEl.x = 0;
        this.ctxMenuEl.y = 0;
        this.ctxMenuEl.width = this.canvasW;
        this.ctxMenuEl.height = this.canvasH;
        const [el] = els.splice(idx, 1);
        els.unshift(el);
      } else if (action === 'copy') {
        this.copyElement(this.ctxMenuEl);
      } else if (action === 'cut') {
        this.cutElement(this.ctxMenuEl);
      } else if (action === 'paste') {
        this.pasteElement();
      } else if (action === 'duplicate') {
        this.duplicateElement(this.ctxMenuEl);
      } else if (action === 'delete') {
        els.splice(idx, 1);
        if (this.selectedElement === this.ctxMenuEl) this.selectElement(null);
      }

      this.ctxMenuEl = null;
      this.renderCanvas();
    };

    $('#pt-ctx-copy')?.addEventListener('click', () => doAction('copy'));
    $('#pt-ctx-cut')?.addEventListener('click', () => doAction('cut'));
    $('#pt-ctx-paste')?.addEventListener('click', () => doAction('paste'));
    $('#pt-ctx-duplicate')?.addEventListener('click', () => doAction('duplicate'));
    $('#pt-ctx-forward')?.addEventListener('click', () => doAction('forward'));
    $('#pt-ctx-backward')?.addEventListener('click', () => doAction('backward'));
    $('#pt-ctx-front')?.addEventListener('click', () => doAction('front'));
    $('#pt-ctx-back')?.addEventListener('click', () => doAction('back'));
    $('#pt-ctx-bg')?.addEventListener('click', () => doAction('bg'));
    $('#pt-ctx-delete')?.addEventListener('click', () => doAction('delete'));

    // Gallery interactions
    $('#pt-gallery-close')?.addEventListener('click', () => {
      $('#presentation-gallery-browser').style.display = 'none';
    });
    $('#pt-gallery-upload')?.addEventListener('click', () => {
      $('#pt-upload-input')?.click();
    });
    $('#pt-upload-input')?.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (file) {
        const formData = new FormData();
        formData.append('file', file);
        try {
          const res = await fetch('/image/upload', { method: 'POST', body: formData });
          const data = await res.json();
          if (res.ok) {
            this.addElement('image', data.url);
            $('#presentation-gallery-browser').style.display = 'none';
            toast(ICONS.check(14) + ' Image uploaded to gallery');
          } else if (res.status === 409) {
            // Image already exists — reuse it
            const match = (data.detail || '').match(/'([^']+)'/);
            const existingName = match ? match[1] : null;
            if (existingName) {
              this.addElement('image', `/data/images/${existingName}`);
              $('#presentation-gallery-browser').style.display = 'none';
              toast(ICONS.check(14) + ' Image already in gallery — reused');
            } else {
              throw new Error(data.detail);
            }
          } else throw new Error(data.detail);
        } catch (err) {
          toast(` Upload failed: ${err.message}`, 4000);
        }
      }
    });

    document.addEventListener('mousemove', (e) => this.onMouseMove(e));
    document.addEventListener('mouseup', (e) => this.onMouseUp(e));
    document.addEventListener('keydown', (e) => {
      const layout = $('#presentation-layout');
      if (!layout || layout.style.display === 'none') return;

      // Skip shortcuts when typing in input fields
      const isEditing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName);

      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (isEditing) return;
        if (this.selectedElement) {
          const page = this.pages[this.currentPage];
          page.elements = page.elements.filter(el => el !== this.selectedElement);
          this.selectElement(null);
          this.renderCanvas();
        }
      } else if ((e.ctrlKey || e.metaKey) && e.key === 'c') {
        // Ctrl+C — Copy element
        if (isEditing) return;
        if (this.selectedElement) {
          e.preventDefault();
          this.copyElement(this.selectedElement);
        }
      } else if ((e.ctrlKey || e.metaKey) && e.key === 'x') {
        // Ctrl+X — Cut element
        if (isEditing) return;
        if (this.selectedElement) {
          e.preventDefault();
          this.cutElement(this.selectedElement);
        }
      } else if ((e.ctrlKey || e.metaKey) && e.key === 'v') {
        // Ctrl+V — Paste (internal clipboard or external content)
        if (isEditing) return;
        e.preventDefault();
        this.handlePaste();
      } else if ((e.ctrlKey || e.metaKey) && e.key === 'd') {
        // Ctrl+D — Duplicate element in place
        if (isEditing) return;
        if (this.selectedElement) {
          e.preventDefault();
          this.duplicateElement(this.selectedElement);
        }
      } else if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
        if (isEditing) return;
        if (this.selectedElement) {
          // Move selected element
          e.preventDefault();
          const step = e.shiftKey ? 10 : 1;
          if (e.key === 'ArrowUp') this.selectedElement.y -= step;
          if (e.key === 'ArrowDown') this.selectedElement.y += step;
          if (e.key === 'ArrowLeft') this.selectedElement.x -= step;
          if (e.key === 'ArrowRight') this.selectedElement.x += step;
          this.renderCanvas();
        } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
          // Navigate between slides when no element is selected
          e.preventDefault();
          if (e.key === 'ArrowLeft' && this.currentPage > 0) {
            this.switchPage(this.currentPage - 1);
          } else if (e.key === 'ArrowRight' && this.currentPage < this.pages.length - 1) {
            this.switchPage(this.currentPage + 1);
          }
        }
      }
    });

    // Handle external paste events (images, SVG, text from OS clipboard)
    document.addEventListener('paste', (e) => {
      const layout = $('#presentation-layout');
      if (!layout || layout.style.display === 'none') return;
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;

      // Handled by keydown handler, but we need the ClipboardEvent for file/image data
      this._handleExternalPaste(e);
    });
  }

  changeFormat(fmt) {
    if (fmt === '16:9') { this.canvasW = 960; this.canvasH = 540; }
    else if (fmt === '4:3') { this.canvasW = 960; this.canvasH = 720; }
    else if (fmt === 'portrait') { this.canvasW = 540; this.canvasH = 960; }
    else if (fmt === 'A4') { this.canvasW = 794; this.canvasH = 1123; }
    else if (fmt === 'IG') { this.canvasW = 1080; this.canvasH = 1080; }
    else if (fmt === 'YT') { this.canvasW = 1280; this.canvasH = 720; }
    else if (fmt === 'card') { this.canvasW = 638; this.canvasH = 368; }

    const c = $('#presentation-canvas');
    if (c) {
      c.style.width = this.canvasW + 'px';
      c.style.height = this.canvasH + 'px';
    }
    this.renderCanvas();
    this.updateCanvasZoom();
  }

  updateCanvasZoom() {
    const zoomSel = $('#pt-zoom-select');
    const c = $('#presentation-canvas');
    const container = $('#presentation-canvas-container');
    const wrap = $('#presentation-canvas-wrapper');
    if (!c || !container || !wrap || !zoomSel) return;

    let scale = 1;
    const val = zoomSel.value;
    if (val === 'fit') {
      const cw = container.clientWidth - 80;
      const ch = container.clientHeight - 80;
      const scaleX = cw / this.canvasW;
      const scaleY = ch / this.canvasH;
      scale = Math.min(1, scaleX, scaleY);
    } else {
      scale = parseInt(val) / 100;
    }

    this.currentScale = scale || 1;
    c.style.transform = `scale(${this.currentScale})`;
    wrap.style.width = (this.canvasW * this.currentScale) + 'px';
    wrap.style.height = (this.canvasH * this.currentScale) + 'px';
  }

  addPage() {
    this.pages.push({ elements: [] });
    this.currentPage = this.pages.length - 1;
    this.selectElement(null);
    this.renderPages();
    this.renderCanvas();
  }

  switchPage(idx) {
    this.currentPage = idx;
    this.selectElement(null);
    this.renderPages();
    this.renderCanvas();
  }

  duplicatePage(idx) {
    const pageToCopy = this.pages[idx];
    const newPage = JSON.parse(JSON.stringify(pageToCopy));
    newPage.elements.forEach(el => el.id = 'el_' + Math.random().toString(36).substr(2, 9));

    this.pages.splice(idx + 1, 0, newPage);
    this.currentPage = idx + 1;
    this.selectElement(null);
    this.renderPages();
    this.renderCanvas();
  }

  reorderPage(fromIdx, toIdx) {
    if (fromIdx === toIdx) return;
    const [movedPage] = this.pages.splice(fromIdx, 1);
    this.pages.splice(toIdx, 0, movedPage);

    if (this.currentPage === fromIdx) {
      this.currentPage = toIdx;
    } else if (this.currentPage > fromIdx && this.currentPage <= toIdx) {
      this.currentPage--;
    } else if (this.currentPage < fromIdx && this.currentPage >= toIdx) {
      this.currentPage++;
    }

    this.renderPages();
  }

  deletePage(idx) {
    if (this.pages.length <= 1) return;
    this.pages.splice(idx, 1);
    if (this.currentPage >= this.pages.length) {
      this.currentPage = this.pages.length - 1;
    }
    this.selectElement(null);
    this.renderPages();
    this.renderCanvas();
  }

  addElement(type, content) {
    const el = {
      id: 'el_' + Date.now(),
      type: type,
      x: 50,
      y: 50,
      width: type === 'image' ? 200 : 300,
      height: type === 'image' ? 200 : 50,
    };

    if (type === 'text') {
      el.content = content || 'New Text';
      el.fontSize = 24;
      el.color = '#ffffff';
      el.backgroundColor = 'transparent';
      el.borderColor = 'transparent';
      el.borderWidth = 0;
      el.opacity = 100;
      el.textAlign = 'left';
    } else if (type === 'table') {
      el.content = content || '| Col 1 |\n|---|';
      el.fontSize = 16;
      el.color = '#000000';
      el.backgroundColor = 'transparent';
      el.borderColor = '#000000';
      el.borderWidth = 3;
      el.opacity = 100;
      el.textAlign = 'left';
    } else if (type === 'image') {
      el.src = content;
      el.width = 200;
      el.height = 200;
      el.opacity = 100;
      el.isCropMode = false;
    } else if (type === 'icon') {
      el.svgContent = content.svg;
      el.iconName = content.name;
      el.width = 100;
      el.height = 100;
      el.borderColor = '#000000';
      el.borderWidth = 2;
      el.backgroundColor = 'transparent';
      el.opacity = 100;
    } else if (type === 'shape') {
      el.shapeType = content || 'rect';
      el.backgroundColor = '#888888';
      el.borderColor = '#000000';
      el.borderWidth = 0;
      el.opacity = 100;
      el.width = 150;
      el.height = 150;
    }

    this.pages[this.currentPage].elements.push(el);
    this.selectElement(el);
    this.renderCanvas();
    return el;
  }

  // ---- Clipboard: Copy / Cut / Paste / Duplicate ----

  copyElement(el) {
    if (!el) return;
    this._clipboard = JSON.parse(JSON.stringify(el));
    this._pasteOffset = 0;
    toast(ICONS.clipboard(14) + ' Element copied');
  }

  cutElement(el) {
    if (!el) return;
    this._clipboard = JSON.parse(JSON.stringify(el));
    this._pasteOffset = 0;
    const page = this.pages[this.currentPage];
    page.elements = page.elements.filter(e => e !== el);
    if (this.selectedElement === el) this.selectElement(null);
    this.renderCanvas();
    toast(ICONS.circle(14) + ' ️ Element cut');
  }

  pasteElement() {
    if (!this._clipboard) {
      toast(ICONS.clipboard(14) + ' Nothing to paste');
      return;
    }
    this._pasteOffset += 20;
    const clone = JSON.parse(JSON.stringify(this._clipboard));
    clone.id = 'el_' + Date.now();
    clone.x = Math.min(clone.x + this._pasteOffset, this.canvasW - 40);
    clone.y = Math.min(clone.y + this._pasteOffset, this.canvasH - 40);
    this.pages[this.currentPage].elements.push(clone);
    this.selectElement(clone);
    this.renderCanvas();
    toast(ICONS.clipboard(14) + ' Element pasted');
  }

  duplicateElement(el) {
    if (!el) return;
    const clone = JSON.parse(JSON.stringify(el));
    clone.id = 'el_' + Date.now();
    clone.x += 20;
    clone.y += 20;
    this.pages[this.currentPage].elements.push(clone);
    this.selectElement(clone);
    this.renderCanvas();
    toast(ICONS.circle(14) + ' Element duplicated');
  }

  /** Try internal clipboard first, then system clipboard */
  async handlePaste() {
    if (this._clipboard) {
      this.pasteElement();
      return;
    }
    // If no internal clipboard, try reading from system clipboard
    try {
      if (navigator.clipboard && window.isSecureContext) {
        // Try to read images
        const items = await navigator.clipboard.read().catch(() => null);
        if (items) {
          for (const item of items) {
            // Try image types
            const imgType = item.types.find(t => t.startsWith('image/'));
            if (imgType) {
              const blob = await item.getType(imgType);
              await this._pasteImageBlob(blob);
              return;
            }
            // Try HTML (may contain SVG or rich content)
            if (item.types.includes('text/html')) {
              const htmlBlob = await item.getType('text/html');
              const html = await htmlBlob.text();
              if (html.includes('<svg')) {
                this._pasteSvgContent(html);
                return;
              }
            }
          }
        }
        // Fallback to plain text
        const text = await navigator.clipboard.readText().catch(() => null);
        if (text && text.trim()) {
          // Check if it's SVG markup
          if (text.trim().startsWith('<svg')) {
            this._pasteSvgContent(text);
          } else {
            this._pasteTextContent(text.trim());
          }
          return;
        }
      }
      toast(ICONS.clipboard(14) + ' Clipboard is empty');
    } catch (e) {
      toast(ICONS.clipboard(14) + ' Could not read clipboard');
    }
  }

  /** Handle paste event from the DOM (for file/image data) */
  _handleExternalPaste(e) {
    // If we have an internal clipboard, let handlePaste (from keydown) deal with it
    if (this._clipboard) return;

    const dt = e.clipboardData;
    if (!dt) return;

    // Check for files (images)
    if (dt.files && dt.files.length > 0) {
      e.preventDefault();
      for (const file of dt.files) {
        if (file.type.startsWith('image/')) {
          this._pasteImageBlob(file);
          return;
        }
      }
    }

    // Check for items (images in clipboard)
    if (dt.items) {
      for (const item of dt.items) {
        if (item.type.startsWith('image/')) {
          e.preventDefault();
          const blob = item.getAsFile();
          if (blob) this._pasteImageBlob(blob);
          return;
        }
      }
    }

    // Check for HTML containing SVG
    const html = dt.getData('text/html');
    if (html && html.includes('<svg')) {
      e.preventDefault();
      this._pasteSvgContent(html);
      return;
    }

    // Check for plain text or SVG text
    const text = dt.getData('text/plain');
    if (text && text.trim()) {
      e.preventDefault();
      if (text.trim().startsWith('<svg')) {
        this._pasteSvgContent(text);
      } else {
        this._pasteTextContent(text.trim());
      }
    }
  }

  /** Paste an image blob: upload to gallery then add to canvas */
  async _pasteImageBlob(blob) {
    toast(ICONS.clipboard(14) + ' Pasting image...');
    try {
      const formData = new FormData();
      const ext = blob.type.split('/')[1] || 'png';
      const fileName = `pasted_${Date.now()}.${ext}`;
      formData.append('file', blob, fileName);
      const res = await fetch('/image/upload', { method: 'POST', body: formData });
      const data = await res.json();
      if (res.ok && data.url) {
        this.addElement('image', data.url);
        toast(ICONS.check(14) + ' Image pasted!');
      } else if (res.status === 409) {
        // Image already exists — reuse it
        const match = (data.detail || '').match(/'([^']+)'/);
        const existingName = match ? match[1] : null;
        if (existingName) {
          this.addElement('image', `/data/images/${existingName}`);
          toast(ICONS.check(14) + ' Image already in gallery — reused');
        } else {
          throw new Error(data.detail || 'Upload failed');
        }
      } else {
        throw new Error(data.detail || 'Upload failed');
      }
    } catch (e) {
      toast(' Paste image failed: ' + e.message);
    }
  }

  /** Paste SVG content as an image data URI */
  _pasteSvgContent(rawHtml) {
    // Extract the <svg> tag from possibly larger HTML
    const match = rawHtml.match(/<svg[\s\S]*?<\/svg>/i);
    if (!match) {
      toast(ICONS.circle(14) + ' ️ No valid SVG found in clipboard');
      return;
    }
    const svgText = match[0];
    const blob = new Blob([svgText], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(blob);

    // Determine size from SVG attributes or default
    const parser = new DOMParser();
    const doc = parser.parseFromString(svgText, 'image/svg+xml');
    const svgEl = doc.querySelector('svg');
    let w = 200, h = 200;
    if (svgEl) {
      const vb = svgEl.getAttribute('viewBox');
      if (vb) {
        const parts = vb.split(/[\s,]+/).map(Number);
        if (parts.length === 4) { w = parts[2]; h = parts[3]; }
      }
      const sw = parseInt(svgEl.getAttribute('width'));
      const sh = parseInt(svgEl.getAttribute('height'));
      if (sw && sh) { w = sw; h = sh; }
    }
    // Clamp to reasonable size
    const maxDim = Math.min(this.canvasW * 0.6, this.canvasH * 0.6);
    if (w > maxDim || h > maxDim) {
      const scale = maxDim / Math.max(w, h);
      w = Math.round(w * scale);
      h = Math.round(h * scale);
    }

    const el = this.addElement('image', url);
    el.width = w;
    el.height = h;
    this.renderCanvas();
    toast(ICONS.check(14) + ' SVG pasted!');
  }

  /** Paste plain text as a new text element */
  _pasteTextContent(text) {
    // Estimate a reasonable box height
    const lines = text.split('\n').length;
    const el = this.addElement('text', text);
    el.width = Math.min(Math.max(200, text.length * 8), this.canvasW - 100);
    el.height = Math.max(50, lines * 30);
    el.x = 50;
    el.y = 50;
    this.renderCanvas();
    toast(ICONS.check(14) + ' Text pasted!');
  }

  selectElement(el) {
    this.selectedElement = el;
    if (el) {
      if ($('#pt-no-selection')) $('#pt-no-selection').style.display = 'none';
      if ($('#presentation-sidebar-right')) $('#presentation-sidebar-right').style.display = 'flex';
      $('#pt-properties-panel').style.display = 'flex';

      $('#pt-prop-content').value = el.content || '';
      $('#pt-prop-fontsize').value = el.fontSize || 24;
      const c = el.color && el.color !== 'transparent' ? el.color : '#000000';
      $('#pt-prop-color').value = c;
      $('#pt-prop-color-hex').value = el.color || 'transparent';
      $('#pt-prop-align').value = el.textAlign || 'left';

      const bg = el.backgroundColor && el.backgroundColor !== 'transparent' ? el.backgroundColor : '#ffffff';
      $('#pt-prop-fill').value = bg;
      $('#pt-prop-fill-hex').value = el.backgroundColor || 'transparent';
      const bc = el.borderColor && el.borderColor !== 'transparent' ? el.borderColor : '#000000';
      $('#pt-prop-border').value = bc;
      $('#pt-prop-border-hex').value = el.borderColor || 'transparent';
      $('#pt-prop-borderwidth').value = el.borderWidth || 0;
      $('#pt-prop-borderradius').value = el.borderRadius || 0;
      $('#pt-prop-opacity').value = el.opacity !== undefined ? el.opacity : 100;
      const opVal = document.getElementById('pt-prop-opacity-val');
      if (opVal) opVal.innerText = el.opacity !== undefined ? el.opacity : 100;

      if ($('#pt-prop-shadow')) $('#pt-prop-shadow').value = el.shadowLevel || 0;
      const shVal = document.getElementById('pt-prop-shadow-val');
      if (shVal) shVal.innerText = el.shadowLevel || 0;

      if ($('#pt-prop-thickness')) $('#pt-prop-thickness').value = el.shapeThickness !== undefined ? el.shapeThickness : 50;
      const thickVal = document.getElementById('pt-prop-thickness-val');
      if (thickVal) thickVal.innerText = el.shapeThickness !== undefined ? el.shapeThickness : 50;

      const isTextOrTable = el.type === 'text' || el.type === 'table';
      if ($('#pt-prop-content-group')) $('#pt-prop-content-group').style.display = isTextOrTable ? 'block' : 'none';
      if ($('#pt-prop-borderradius-wrapper')) $('#pt-prop-borderradius-wrapper').style.display = el.type === 'icon' ? 'none' : 'block';
      $('#pt-prop-text-group').style.display = isTextOrTable ? 'flex' : 'none';
      $('#pt-prop-color-group').style.display = isTextOrTable ? 'flex' : 'none';
      $('#pt-prop-align-group').style.display = el.type === 'text' ? 'flex' : 'none';
      if ($('#pt-prop-header-bg-group')) $('#pt-prop-header-bg-group').style.display = el.type === 'table' ? 'flex' : 'none';
      $('#pt-prop-image-group').style.display = el.type === 'image' ? 'flex' : 'none';

      if (el.type === 'image') {
        const cropBtn = $('#pt-prop-crop');
        if (cropBtn) {
          cropBtn.innerText = el.isCropMode ? 'Exit Crop' : 'Crop Mode';
          cropBtn.style.background = el.isCropMode ? 'var(--accent)' : '';
          cropBtn.style.color = el.isCropMode ? '#fff' : '';
          cropBtn.style.borderColor = el.isCropMode ? 'var(--accent)' : '';
        }
      }

      $('#pt-prop-text-format-group').style.display = el.type === 'text' ? 'flex' : 'none';

      const showThickness = el.type === 'shape' && (el.shapeType === 'cross' || el.shapeType === 'arrow');
      if ($('#pt-prop-thickness-group')) $('#pt-prop-thickness-group').style.display = showThickness ? 'flex' : 'none';

      const hbg = el.headerBgColor && el.headerBgColor !== 'transparent' ? el.headerBgColor : '#000000';
      if ($('#pt-prop-header-bg')) $('#pt-prop-header-bg').value = hbg;
      if ($('#pt-prop-header-bg-hex')) $('#pt-prop-header-bg-hex').value = el.headerBgColor || 'transparent';

      if ($('#pt-prop-fontfamily')) {
        $('#pt-prop-fontfamily').value = el.fontFamily || 'Inter, sans-serif';
      }
      if ($('#pt-prop-fontfamily-group')) {
        $('#pt-prop-fontfamily-group').style.display = isTextOrTable ? 'flex' : 'none';
      }

      const updateBtnState = (id, field) => {
        if ($(id)) $(id).style.background = el[field] ? 'var(--accent)' : 'transparent';
      };
      if (el.type === 'text') {
        updateBtnState('#pt-prop-bold', 'isBold');
        updateBtnState('#pt-prop-italic', 'isItalic');
        updateBtnState('#pt-prop-underline', 'isUnderline');
        updateBtnState('#pt-prop-strikethrough', 'isStrikethrough');
        updateBtnState('#pt-prop-list', 'isList');
      }
    } else {
      if ($('#pt-no-selection')) {
        $('#pt-no-selection').style.display = 'block';
        const txtEl = $('#pt-slide-narration');
        if (txtEl) {
          txtEl.value = (this.pages[this.currentPage] && this.pages[this.currentPage].narration) || '';
        }
      }
      if ($('#presentation-sidebar-right')) $('#presentation-sidebar-right').style.display = 'flex';
      $('#pt-properties-panel').style.display = 'none';
    }
    this.renderCanvas(); // updates outlines
  }

  /** Re-sync the properties sidebar with the currently selected element. */
  updatePropertiesPanel() {
    this.selectElement(this.selectedElement);
  }

  // Drag and Drop
  onMouseDown(e, el, action, handle = null) {
    e.stopPropagation();
    this.selectElement(el);
    if (action === 'drag') {
      this.dragItem = el;
    } else if (action === 'resize') {
      this.resizeItem = { 
         el, handle, 
         origX: el.x, origY: el.y, 
         origW: el.width, origH: el.height,
         origCl: el.cropLeft || 0,
         origCt: el.cropTop || 0,
         origCr: el.cropRight || 0,
         origCb: el.cropBottom || 0
      };
    }
    this.dragStartX = e.clientX;
    this.dragStartY = e.clientY;
  }

  onMouseMove(e) {
    const c = $('#presentation-canvas');
    if (!c) return;
    const scale = c.getBoundingClientRect().width / this.canvasW;

    if (this.dragItem) {
      const dx = (e.clientX - this.dragStartX) / scale;
      const dy = (e.clientY - this.dragStartY) / scale;
      this.dragItem.x = this.dragItem.x + dx;
      this.dragItem.y = this.dragItem.y + dy;
      this.dragStartX = e.clientX;
      this.dragStartY = e.clientY;
      this.renderCanvas();
    } else if (this.resizeItem) {
      const dx = (e.clientX - this.dragStartX) / scale;
      const dy = (e.clientY - this.dragStartY) / scale;
      const { el, handle, origX, origY, origW, origH, origCl, origCt, origCr, origCb } = this.resizeItem;

      if (el.isCropMode && el.type === 'image') {
         const cl = origCl || 0;
         const ct = origCt || 0;
         const cr = origCr || 0;
         const cb = origCb || 0;
         const origImgW = origW / (1 - cl - cr);
         const origImgH = origH / (1 - ct - cb);

         let newW = origW;
         let newH = origH;
         let newX = origX;
         let newY = origY;

         if (handle === 'br') {
            newW = Math.max(20, origW + dx);
            newH = Math.max(20, origH + dy);
         } else if (handle === 'bl') {
            newW = Math.max(20, origW - dx);
            newH = Math.max(20, origH + dy);
            newX = origX + (origW - newW);
         } else if (handle === 'tr') {
            newW = Math.max(20, origW + dx);
            newH = Math.max(20, origH - dy);
            newY = origY + (origH - newH);
         } else if (handle === 'tl') {
            newW = Math.max(20, origW - dx);
            newH = Math.max(20, origH - dy);
            newX = origX + (origW - newW);
            newY = origY + (origH - newH);
         }

         let newCl = cl + (newX - origX) / origImgW;
         let newCt = ct + (newY - origY) / origImgH;
         let newCr = cr + (origX + origW - (newX + newW)) / origImgW;
         let newCb = cb + (origY + origH - (newY + newH)) / origImgH;

         if (newCl < 0) { const diff = -newCl * origImgW; newX += diff; newW -= diff; newCl = 0; }
         if (newCt < 0) { const diff = -newCt * origImgH; newY += diff; newH -= diff; newCt = 0; }
         if (newCr < 0) { const diff = -newCr * origImgW; newW -= diff; newCr = 0; }
         if (newCb < 0) { const diff = -newCb * origImgH; newH -= diff; newCb = 0; }

         if (newCl + newCr >= 0.95) { newW = origW; newX = origX; newCl = cl; newCr = cr; }
         if (newCt + newCb >= 0.95) { newH = origH; newY = origY; newCt = ct; newCb = cb; }

         el.x = newX;
         el.y = newY;
         el.width = newW;
         el.height = newH;
         el.cropLeft = newCl;
         el.cropTop = newCt;
         el.cropRight = newCr;
         el.cropBottom = newCb;

      } else {
        if (handle === 'br') {
          el.width = Math.max(20, origW + dx);
          el.height = Math.max(20, origH + dy);
        } else if (handle === 'bl') {
          el.width = Math.max(20, origW - dx);
          el.height = Math.max(20, origH + dy);
          el.x = origX + (origW - el.width);
        } else if (handle === 'tr') {
          el.width = Math.max(20, origW + dx);
          el.height = Math.max(20, origH - dy);
          el.y = origY + (origH - el.height);
        } else if (handle === 'tl') {
          el.width = Math.max(20, origW - dx);
          el.height = Math.max(20, origH - dy);
          el.x = origX + (origW - el.width);
          el.y = origY + (origH - el.height);
        }
      }
      this.renderCanvas();
    }
  }

  onMouseUp(e) {
    const snap = (v) => this.showGrid ? Math.round(v / this.snapGrid) * this.snapGrid : v;
    let needsRender = false;

    if (this.resizeItem) {
      const el = this.resizeItem.el;
      if (!(el.isCropMode && el.type === 'image')) {
        el.x = snap(el.x);
        el.y = snap(el.y);
        el.width = Math.max(20, snap(el.width));
        el.height = Math.max(20, snap(el.height));
      }
      this.resizeItem = null;
      needsRender = true;
    }

    if (this.dragItem) {
      this.dragItem.x = snap(this.dragItem.x);
      this.dragItem.y = snap(this.dragItem.y);
      this.dragItem = null;
      needsRender = true;
    }

    if (needsRender) {
      this.renderCanvas();
    }
  }

  saveStateDebounced() {
    if (this._saveStateTimer) clearTimeout(this._saveStateTimer);
    this._saveStateTimer = setTimeout(() => {
      this.saveState();
      this.autoSave();
    }, 300);
  }

  autoSave() {
    if (this._autoSaveTimer) clearTimeout(this._autoSaveTimer);
    this._autoSaveTimer = setTimeout(() => {
      this.save(true);
    }, 2000);
  }

  saveState() {
    if (this.isUndoRedo) return;
    const state = {
      pages: JSON.parse(JSON.stringify(this.pages)),
      canvasW: this.canvasW,
      canvasH: this.canvasH,
    };

    if (this.historyIndex >= 0) {
      const lastState = this.history[this.historyIndex];
      if (JSON.stringify(lastState.pages) === JSON.stringify(state.pages) &&
        lastState.canvasW === state.canvasW && lastState.canvasH === state.canvasH) {
        return;
      }
    }

    if (this.historyIndex < this.history.length - 1) {
      this.history = this.history.slice(0, this.historyIndex + 1);
    }
    this.history.push(state);
    if (this.history.length > 50) {
      this.history.shift();
    } else {
      this.historyIndex++;
    }
    this.updateUndoRedoButtons();
  }

  updateUndoRedoButtons() {
    const btnUndo = $('#pt-btn-undo');
    const btnRedo = $('#pt-btn-redo');
    if (btnUndo) {
      btnUndo.style.opacity = this.historyIndex > 0 ? '1' : '0.5';
      btnUndo.style.cursor = this.historyIndex > 0 ? 'pointer' : 'not-allowed';
    }
    if (btnRedo) {
      btnRedo.style.opacity = this.historyIndex < this.history.length - 1 ? '1' : '0.5';
      btnRedo.style.cursor = this.historyIndex < this.history.length - 1 ? 'pointer' : 'not-allowed';
    }
  }

  renderCanvas() {
    const c = $('#presentation-canvas');
    if (!c) return;

    c.style.width = this.canvasW + 'px';
    c.style.height = this.canvasH + 'px';

    if (!this.isUndoRedo) {
      this.saveStateDebounced();
    }
    c.innerHTML = '';

    // Grid overlay
    if (this.showGrid) {
      const gridSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      gridSvg.classList.add('canvas-grid-overlay');
      gridSvg.setAttribute('width', '100%');
      gridSvg.setAttribute('height', '100%');
      gridSvg.setAttribute('viewBox', `0 0 ${this.canvasW} ${this.canvasH}`);
      for (let x = this.snapGrid; x < this.canvasW; x += this.snapGrid) {
        for (let y = this.snapGrid; y < this.canvasH; y += this.snapGrid) {
          const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
          dot.setAttribute('cx', x);
          dot.setAttribute('cy', y);
          dot.setAttribute('r', '0.8');
          dot.setAttribute('fill', 'rgba(255,255,255,0.12)');
          gridSvg.appendChild(dot);
        }
      }
      c.appendChild(gridSvg);
    }

    const page = this.pages[this.currentPage];
    if (!page) return;

    page.elements.forEach((el, index) => {
      const node = document.createElement('div');
      node.className = 'canvas-element' + (this.selectedElement === el ? ' selected' : '');
      if (this.selectedElement === el && el.isCropMode) {
          node.style.outline = '3px dashed var(--accent)';
          node.style.boxShadow = '0 0 20px rgba(0,0,0,0.5)';
      }
      node.style.left = el.x + 'px';
      node.style.top = el.y + 'px';
      node.style.width = el.width + 'px';
      node.style.height = el.height + 'px';
      node.style.zIndex = index + 1;

      node.style.opacity = (el.opacity !== undefined ? el.opacity : 100) / 100;
      if (el.shadowLevel > 0) {
        node.style.filter = `drop-shadow(0px ${Math.round(el.shadowLevel / 2)}px ${el.shadowLevel}px rgba(0,0,0,0.5))`;
      } else {
        node.style.filter = 'none';
      }
      if (el.type !== 'shape') {
        node.style.backgroundColor = el.backgroundColor || 'transparent';
        if (el.borderWidth && el.type !== 'table') {
          node.style.border = `${el.borderWidth}px solid ${el.borderColor || 'transparent'}`;
        } else {
          node.style.border = 'none';
        }
        if (el.borderRadius) {
          node.style.borderRadius = `${el.borderRadius}px`;
        } else {
          node.style.borderRadius = '0';
        }
      }

      if (el.type === 'text') {
        const inner = document.createElement('div');
        inner.className = 'canvas-text-content';
        inner.style.fontSize = (el.fontSize || 24) + 'px';
        inner.style.fontFamily = el.fontFamily || 'Inter, sans-serif';
        inner.style.color = el.color || '#000000';
        inner.style.textAlign = el.textAlign || 'left';

        if (el.isBold) inner.style.fontWeight = 'bold';
        if (el.isItalic) inner.style.fontStyle = 'italic';

        let decoration = '';
        if (el.isUnderline) decoration += ' underline';
        if (el.isStrikethrough) decoration += ' line-through';
        if (decoration) inner.style.textDecoration = decoration.trim();

        if (el.isList) {
          const ul = document.createElement('ul');
          ul.style.margin = '0';
          ul.style.paddingLeft = '1.2em';
          const lines = (el.content || '').split('\n');
          lines.forEach(line => {
            const li = document.createElement('li');
            li.innerText = line;
            ul.appendChild(li);
          });
          inner.appendChild(ul);
        } else {
          inner.innerText = el.content || '';
        }
        node.appendChild(inner);
      } else if (el.type === 'table') {
        const inner = document.createElement('div');
        inner.className = 'canvas-table-wrapper';
        inner.style.width = '100%';
        inner.style.height = '100%';
        inner.style.color = el.color || '#000000';
        inner.style.fontSize = (el.fontSize || 16) + 'px';
        inner.style.fontFamily = el.fontFamily || 'Inter, sans-serif';

        const tableMd = el.content || '| Header |\n|---|';
        const rows = tableMd.trim().split('\n').filter(r => r.trim());
        let thtml = '<table style="width:100%;height:100%;border-collapse:collapse;">';
        const cellBorderWidth = el.borderWidth !== undefined ? el.borderWidth : 1;
        const cellBorderColor = el.borderColor && el.borderColor !== 'transparent' ? el.borderColor : 'currentColor';
        const cellBorder = cellBorderWidth > 0 ? `${cellBorderWidth}px solid ${cellBorderColor}` : 'none';

        rows.forEach((row, i) => {
          if (row.match(/^\|[\s-:|]+\|$/)) return;
          const cells = row.split('|').filter(c => c.trim() !== '');
          const isHeader = i === 0;
          const tag = isHeader ? 'th' : 'td';
          const bgStyle = isHeader && el.headerBgColor && el.headerBgColor !== 'transparent' ? `background-color: ${el.headerBgColor};` : '';
          thtml += '<tr>' + cells.map(c => `<${tag} style="border: ${cellBorder}; padding: 8px; ${bgStyle}">${c.trim()}</${tag}>`).join('') + '</tr>';
        });
        thtml += '</table>';
        inner.innerHTML = thtml;
        node.appendChild(inner);
      } else if (el.type === 'image') {
        node.style.overflow = 'hidden';
        const inner = document.createElement('img');
        inner.className = 'canvas-image-content';
        inner.src = el.src;
        
        const cl = el.cropLeft || 0;
        const ct = el.cropTop || 0;
        const cr = el.cropRight || 0;
        const cb = el.cropBottom || 0;
        const cw = 1 - cl - cr;
        const ch = 1 - ct - cb;
        
        inner.style.position = 'absolute';
        inner.style.width = (100 / cw) + '%';
        inner.style.height = (100 / ch) + '%';
        inner.style.left = -(cl / cw * 100) + '%';
        inner.style.top = -(ct / ch * 100) + '%';
        inner.style.objectFit = 'fill';
        inner.style.borderRadius = 'inherit';
        
        node.appendChild(inner);
      } else if (el.type === 'icon') {
        node.style.backgroundColor = 'transparent';
        node.style.border = 'none';
        node.style.borderRadius = '0';

        node.innerHTML = el.svgContent || '';
        const svg = node.querySelector('svg');
        if (svg) {
          svg.setAttribute('width', '100%');
          svg.setAttribute('height', '100%');
          svg.style.display = 'block';
          svg.style.overflow = 'visible';
          svg.setAttribute('stroke', el.borderColor || '#000000');
          svg.setAttribute('stroke-width', el.borderWidth !== undefined ? el.borderWidth : 2);
          svg.setAttribute('fill', el.backgroundColor === 'transparent' ? 'none' : el.backgroundColor);

          svg.querySelectorAll('*').forEach(child => {
            if (child.hasAttribute('stroke') && child.getAttribute('stroke') !== 'none') child.setAttribute('stroke', 'currentColor');
            if (child.hasAttribute('fill') && child.getAttribute('fill') !== 'none') child.setAttribute('fill', 'currentColor');
          });
          svg.style.color = el.borderColor || '#000000';
        }
      } else if (el.type === 'mermaid') {
        node.style.backgroundColor = el.backgroundColor || 'transparent';
        node.style.border = 'none';
        node.style.borderRadius = '0';

        const inner = document.createElement('div');
        inner.style.width = '100%';
        inner.style.height = '100%';
        inner.style.display = 'flex';
        inner.style.alignItems = 'center';
        inner.style.justifyContent = 'center';
        inner.style.color = el.color || '#000000';
        inner.style.padding = '10px';
        inner.style.boxSizing = 'border-box';

        if (window.mermaid) {
          const id = 'mmr-pres-' + Math.random().toString(36).substr(2, 9);
          inner.id = id;
          try {
            mermaid.render(id + '-svg', el.content || 'graph TD;\nA-->B;').then(r => {
              inner.innerHTML = r.svg;
              const svg = inner.querySelector('svg');
              if (svg) {
                svg.style.maxWidth = '100%';
                svg.style.maxHeight = '100%';
                svg.style.width = 'auto';
                svg.style.height = 'auto';
              }
            }).catch(e => {
              inner.innerHTML = `<div style="color:red; font-size:12px; font-family:monospace">Mermaid syntax error</div>`;
            });
          } catch (e) {
            inner.innerHTML = `<div style="color:red; font-size:12px; font-family:monospace">Mermaid rendering error</div>`;
          }
        } else {
          inner.innerText = el.content || '';
        }
        node.appendChild(inner);
      } else if (el.type === 'shape') {
        node.style.backgroundColor = 'transparent';
        node.style.border = 'none';
        node.style.borderRadius = '0';

        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('width', '100%');
        svg.setAttribute('height', '100%');
        svg.style.overflow = 'visible';
        svg.style.display = 'block';

        let fill = el.backgroundColor || 'transparent';
        let stroke = el.borderWidth ? (el.borderColor || '#000000') : 'none';
        let strokeW = el.borderWidth || 0;
        let rx = el.borderRadius || 0;

        let effectiveStroke = stroke;
        let effectiveStrokeW = strokeW;
        const polygonShapes = ['triangle', 'hexagon', 'arrow', 'diamond', 'pentagon', 'star', 'heart', 'cross', 'chevron', 'parallelogram', 'trapezoid'];
        let isPolygon = polygonShapes.includes(el.shapeType);

        if (isPolygon && rx > 0) {
          if (stroke === 'none' || strokeW === 0) {
            effectiveStroke = fill !== 'transparent' ? fill : 'none';
          }
          effectiveStrokeW = strokeW + (rx * 2);
        }

        let inset = effectiveStrokeW / 2;
        const w = el.width;
        const h = el.height;

        let shapeNode;
        if (el.shapeType === 'circle') {
          shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'ellipse');
          shapeNode.setAttribute('cx', w / 2);
          shapeNode.setAttribute('cy', h / 2);
          shapeNode.setAttribute('rx', Math.max(0, (w / 2) - inset));
          shapeNode.setAttribute('ry', Math.max(0, (h / 2) - inset));
        } else if (el.shapeType === 'ring') {
          // Ring: two concentric circles
          const outer = document.createElementNS('http://www.w3.org/2000/svg', 'ellipse');
          outer.setAttribute('cx', w / 2);
          outer.setAttribute('cy', h / 2);
          outer.setAttribute('rx', Math.max(0, (w / 2) - inset));
          outer.setAttribute('ry', Math.max(0, (h / 2) - inset));
          outer.setAttribute('fill', fill);
          outer.setAttribute('stroke', effectiveStroke);
          outer.setAttribute('stroke-width', effectiveStrokeW);
          svg.appendChild(outer);
          const inner = document.createElementNS('http://www.w3.org/2000/svg', 'ellipse');
          inner.setAttribute('cx', w / 2);
          inner.setAttribute('cy', h / 2);
          inner.setAttribute('rx', Math.max(0, (w / 4)));
          inner.setAttribute('ry', Math.max(0, (h / 4)));
          inner.setAttribute('fill', '#ffffff');
          inner.setAttribute('stroke', effectiveStroke);
          inner.setAttribute('stroke-width', effectiveStrokeW);
          svg.appendChild(inner);
          node.appendChild(svg);
          // Skip the normal append below
          shapeNode = null;
        } else if (el.shapeType === 'triangle') {
          shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
          shapeNode.setAttribute('points', `${w / 2},${inset} ${inset},${h - inset} ${w - inset},${h - inset}`);
        } else if (el.shapeType === 'diamond') {
          shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
          shapeNode.setAttribute('points', `${w / 2},${inset} ${w - inset},${h / 2} ${w / 2},${h - inset} ${inset},${h / 2}`);
        } else if (el.shapeType === 'pentagon') {
          const cx = w / 2, cy = h / 2, r = Math.min(w, h) / 2 - inset;
          const pts = [];
          for (let i = 0; i < 5; i++) {
            const a = (Math.PI * 2 * i / 5) - Math.PI / 2;
            pts.push(`${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`);
          }
          shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
          shapeNode.setAttribute('points', pts.join(' '));
        } else if (el.shapeType === 'hexagon') {
          shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
          shapeNode.setAttribute('points', `${w / 4},${inset} ${w * 3 / 4},${inset} ${w - inset},${h / 2} ${w * 3 / 4},${h - inset} ${w / 4},${h - inset} ${inset},${h / 2}`);
        } else if (el.shapeType === 'star') {
          const cx = w / 2, cy = h / 2;
          const outerR = Math.min(w, h) / 2 - inset;
          const innerR = outerR * 0.4;
          const pts = [];
          for (let i = 0; i < 10; i++) {
            const a = (Math.PI * 2 * i / 10) - Math.PI / 2;
            const r = i % 2 === 0 ? outerR : innerR;
            pts.push(`${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`);
          }
          shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
          shapeNode.setAttribute('points', pts.join(' '));
        } else if (el.shapeType === 'heart') {
          shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'path');
          const s = Math.min(w, h);
          const sx = w / 2, sy = h * 0.3;
          shapeNode.setAttribute('d', `M${sx},${h - inset} C${inset},${h * 0.55} ${inset},${inset} ${sx},${sy} C${w - inset},${inset} ${w - inset},${h * 0.55} ${sx},${h - inset}Z`);
        } else if (el.shapeType === 'cross') {
          const thicknessPct = (el.shapeThickness !== undefined ? el.shapeThickness : 50) / 100;
          const t = Math.min(w, h) * (0.05 + 0.4 * thicknessPct);
          const cx = w / 2, cy = h / 2;
          shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
          shapeNode.setAttribute('points', `${cx - t},${inset} ${cx + t},${inset} ${cx + t},${cy - t} ${w - inset},${cy - t} ${w - inset},${cy + t} ${cx + t},${cy + t} ${cx + t},${h - inset} ${cx - t},${h - inset} ${cx - t},${cy + t} ${inset},${cy + t} ${inset},${cy - t} ${cx - t},${cy - t}`);
        } else if (el.shapeType === 'chevron') {
          const notch = w * 0.3;
          shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
          shapeNode.setAttribute('points', `${inset},${inset} ${w - notch},${inset} ${w - inset},${h / 2} ${w - notch},${h - inset} ${inset},${h - inset} ${notch},${h / 2}`);
        } else if (el.shapeType === 'cloud') {
          shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'path');
          shapeNode.setAttribute('d', `M${w * 0.25},${h * 0.7} a${w * 0.15},${h * 0.15} 0 0,1 0,-${h * 0.3} a${w * 0.2},${h * 0.2} 0 0,1 ${w * 0.3},-${h * 0.15} a${w * 0.15},${h * 0.15} 0 0,1 ${w * 0.25},0 a${w * 0.15},${h * 0.15} 0 0,1 ${w * 0.1},${h * 0.25} a${w * 0.1},${h * 0.1} 0 0,1 -${w * 0.1},${h * 0.2} Z`);
        } else if (el.shapeType === 'speech-bubble') {
          shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'path');
          const r2 = Math.min(w, h) * 0.1;
          shapeNode.setAttribute('d', `M${inset + r2},${inset} h${w - 2 * inset - 2 * r2} a${r2},${r2} 0 0,1 ${r2},${r2} v${h * 0.6 - 2 * r2} a${r2},${r2} 0 0,1 -${r2},${r2} h-${w * 0.5} l-${w * 0.1},${h * 0.25} v-${h * 0.25} h-${w * 0.15 - r2} a${r2},${r2} 0 0,1 -${r2},-${r2} v-${h * 0.6 - 2 * r2} a${r2},${r2} 0 0,1 ${r2},-${r2}Z`);
        } else if (el.shapeType === 'parallelogram') {
          const skew = w * 0.2;
          shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
          shapeNode.setAttribute('points', `${skew + inset},${inset} ${w - inset},${inset} ${w - skew - inset},${h - inset} ${inset},${h - inset}`);
        } else if (el.shapeType === 'trapezoid') {
          const indent = w * 0.15;
          shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
          shapeNode.setAttribute('points', `${indent + inset},${inset} ${w - indent - inset},${inset} ${w - inset},${h - inset} ${inset},${h - inset}`);
        } else if (el.shapeType === 'rounded-rect') {
          shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
          shapeNode.setAttribute('x', inset);
          shapeNode.setAttribute('y', inset);
          shapeNode.setAttribute('width', Math.max(0, w - effectiveStrokeW));
          shapeNode.setAttribute('height', Math.max(0, h - effectiveStrokeW));
          const autoRx = Math.min(w, h) * 0.05;
          shapeNode.setAttribute('rx', autoRx);
          shapeNode.setAttribute('ry', autoRx);
        } else if (el.shapeType === 'arrow') {
          shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
          const thicknessPct = (el.shapeThickness !== undefined ? el.shapeThickness : 50) / 100;
          let headStart = w * 0.6;
          let bodyH = h * (0.1 + 0.8 * thicknessPct);
          let bodyY1 = (h - bodyH) / 2;
          let bodyY2 = bodyY1 + bodyH;
          shapeNode.setAttribute('points', `${inset},${bodyY1 + inset / 2} ${headStart},${bodyY1 + inset / 2} ${headStart},${inset} ${w - inset},${h / 2} ${headStart},${h - inset} ${headStart},${bodyY2 - inset / 2} ${inset},${bodyY2 - inset / 2}`);
        } else {
          // Default rect
          shapeNode = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
          shapeNode.setAttribute('x', inset);
          shapeNode.setAttribute('y', inset);
          shapeNode.setAttribute('width', Math.max(0, w - effectiveStrokeW));
          shapeNode.setAttribute('height', Math.max(0, h - effectiveStrokeW));
          if (rx) {
            shapeNode.setAttribute('rx', rx);
            shapeNode.setAttribute('ry', rx);
          }
        }

        if (shapeNode) {
          if (isPolygon) shapeNode.setAttribute('stroke-linejoin', 'round');
          shapeNode.setAttribute('fill', fill);
          shapeNode.setAttribute('stroke', effectiveStroke);
          shapeNode.setAttribute('stroke-width', effectiveStrokeW);
          svg.appendChild(shapeNode);
          node.appendChild(svg);
        }
      }

      // Drag handler
      node.addEventListener('mousedown', (e) => this.onMouseDown(e, el, 'drag'));

      // Double click to inline edit content
      node.addEventListener('dblclick', (e) => {
        e.stopPropagation();
        if (el.type === 'text' || el.type === 'table') {
          if (node.querySelector('.inline-editor')) return; // Already editing

          const innerContent = node.querySelector('.canvas-text-content, .canvas-table-wrapper');
          if (innerContent) innerContent.style.visibility = 'hidden';

          const textarea = document.createElement('textarea');
          textarea.className = 'inline-editor';
          textarea.value = el.content || '';
          textarea.style.position = 'absolute';
          textarea.style.left = '0';
          textarea.style.top = '0';
          textarea.style.width = '100%';
          textarea.style.height = '100%';

          if (el.type === 'text') {
            textarea.style.background = 'transparent';
            textarea.style.color = el.color || '#000000';
            textarea.style.border = '1px dashed var(--accent)';
            textarea.style.textAlign = el.textAlign || 'left';
          } else {
            textarea.style.background = 'var(--bg-elevated)';
            textarea.style.color = 'var(--text-primary)';
            textarea.style.border = '2px solid var(--accent)';
          }

          textarea.style.padding = '8px';
          textarea.style.fontSize = (el.fontSize || 16) + 'px';
          textarea.style.fontFamily = el.fontFamily || 'inherit';
          textarea.style.resize = 'none';
          textarea.style.zIndex = '100';
          textarea.style.outline = 'none';

          node.appendChild(textarea);
          textarea.focus();

          const save = () => {
            el.content = textarea.value;
            textarea.remove();
            if (innerContent) innerContent.style.visibility = 'visible';
            this.renderCanvas();
            this.updatePropertiesPanel();
          };

          textarea.addEventListener('blur', save);
          textarea.addEventListener('mousedown', e => e.stopPropagation());
          // Optionally save on Shift+Enter or Escape
          textarea.addEventListener('keydown', e => {
            if (e.key === 'Escape') save();
            if (e.key === 'Enter' && e.shiftKey) save();
          });
        }
      });

      // Context Menu handler
      node.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        e.stopPropagation();
        this.ctxMenuEl = el;
        this.selectElement(el);
        const menu = $('#pt-context-menu');
        if (menu) {
          menu.style.display = 'flex';
          // Simple bound checking to keep menu in window
          let x = e.clientX;
          let y = e.clientY;
          if (x + 200 > window.innerWidth) x = window.innerWidth - 200;
          if (y + 280 > window.innerHeight) y = window.innerHeight - 280;
          menu.style.left = x + 'px';
          menu.style.top = y + 'px';

          // Reset all items visibility (canvas paste-only menu may have hidden them)
          ['pt-ctx-copy', 'pt-ctx-cut', 'pt-ctx-duplicate', 'pt-ctx-forward', 'pt-ctx-backward', 'pt-ctx-front', 'pt-ctx-back', 'pt-ctx-delete'].forEach(id => {
            const btn = document.getElementById(id);
            if (btn) btn.style.display = id.includes('copy') || id.includes('cut') || id.includes('duplicate') ? 'flex' : 'block';
          });
          menu.querySelectorAll('div[style*="height:1px"]').forEach(d => d.style.display = 'block');

          // Show/hide image specific options
          const bgBtn = $('#pt-ctx-bg');
          if (bgBtn) bgBtn.style.display = el.type === 'image' ? 'block' : 'none';
          // Show/hide paste option based on clipboard
          const pasteBtn = $('#pt-ctx-paste');
          if (pasteBtn) pasteBtn.style.display = this._clipboard ? 'flex' : 'none';
        }
      });

      // Resize handles
      if (this.selectedElement === el) {
        ['tl', 'tr', 'bl', 'br'].forEach(handleType => {
          const h = document.createElement('div');
          h.className = `canvas-element-resize-handle handle-${handleType}`;
          h.addEventListener('mousedown', (e) => this.onMouseDown(e, el, 'resize', handleType));
          node.appendChild(h);
        });
      }

      c.appendChild(node);
    });
  }

  renderPages() {
    const list = $('#pt-pages-list');
    if (!list) return;

    if (!this.isUndoRedo) {
      this.saveStateDebounced();
    }
    list.innerHTML = '';

    this.pages.forEach((page, idx) => {
      const thumb = document.createElement('div');
      thumb.className = 'pt-page-thumbnail' + (this.currentPage === idx ? ' active' : '');
      thumb.style.background = '#ffffff'; // Default slide bg

      // Scale down the 800x450 canvas
      const scale = 100 / this.canvasW;

      const previewContainer = document.createElement('div');
      previewContainer.style.width = this.canvasW + 'px';
      previewContainer.style.height = this.canvasH + 'px';
      previewContainer.style.transform = `scale(${scale})`;
      previewContainer.style.transformOrigin = 'top left';
      previewContainer.style.position = 'absolute';
      previewContainer.style.top = '0';
      previewContainer.style.left = '0';
      previewContainer.style.pointerEvents = 'none';
      previewContainer.style.overflow = 'hidden';
      previewContainer.style.borderRadius = (4 / scale) + 'px';

      (page.elements || []).forEach(el => {
        const node = document.createElement('div');
        node.style.position = 'absolute';
        node.style.left = el.x + 'px';
        node.style.top = el.y + 'px';
        node.style.width = el.width + 'px';
        node.style.height = el.height + 'px';
        node.style.backgroundColor = el.backgroundColor || 'transparent';
        if (el.type === 'text') {
          node.innerText = el.content || '';
          node.style.fontSize = (el.fontSize || 24) + 'px';
          node.style.fontFamily = el.fontFamily || 'sans-serif';
          node.style.color = el.color || '#000000';
          node.style.overflow = 'hidden';
          if (el.isBold) node.style.fontWeight = 'bold';
          if (el.isItalic) node.style.fontStyle = 'italic';
          let decoration = '';
          if (el.isUnderline) decoration += ' underline';
          if (el.isStrikethrough) decoration += ' line-through';
          if (decoration) node.style.textDecoration = decoration.trim();
        } else if (el.type === 'image') {
          node.style.backgroundImage = `url(${el.content})`;
          node.style.backgroundSize = '100% 100%';
        }
        if (el.borderRadius) {
          node.style.borderRadius = `${el.borderRadius}px`;
        }
        if (el.type !== 'shape' && el.borderWidth) {
          node.style.border = `${el.borderWidth}px solid ${el.borderColor || 'transparent'}`;
        }
        previewContainer.appendChild(node);
      });

      thumb.appendChild(previewContainer);

      // Number badge
      const badge = document.createElement('div');
      badge.innerText = idx + 1;
      badge.style.position = 'absolute';
      badge.style.bottom = '2px';
      badge.style.right = '4px';
      badge.style.fontSize = '9px';
      badge.style.background = 'rgba(0,0,0,0.5)';
      badge.style.color = '#fff';
      badge.style.padding = '1px 4px';
      badge.style.borderRadius = '4px';
      badge.style.zIndex = '10';
      thumb.appendChild(badge);

      thumb.onclick = () => this.switchPage(idx);

      // Drag and drop for reordering
      thumb.draggable = true;
      thumb.ondragstart = (e) => {
        e.dataTransfer.setData('text/plain', idx);
        thumb.style.opacity = '0.5';
      };
      thumb.ondragover = (e) => {
        e.preventDefault(); // necessary to allow dropping
        thumb.style.border = '2px dashed var(--accent)';
      };
      thumb.ondragleave = (e) => {
        thumb.style.border = '';
      };
      thumb.ondrop = (e) => {
        e.preventDefault();
        thumb.style.border = '';
        const fromIdx = parseInt(e.dataTransfer.getData('text/plain'));
        if (!isNaN(fromIdx)) {
          this.reorderPage(fromIdx, idx);
        }
      };
      thumb.ondragend = () => {
        thumb.style.opacity = '';
      };

      const dupBtn = document.createElement('button');
      dupBtn.className = 'pt-page-duplicate';
      dupBtn.innerHTML = window.icon ? window.icon('copy', 14) : '⧉';
      dupBtn.title = 'Duplicate Slide';
      dupBtn.style.zIndex = '20';
      dupBtn.onclick = (e) => { e.stopPropagation(); this.duplicatePage(idx); };

      const delBtn = document.createElement('button');
      delBtn.className = 'pt-page-delete';
      delBtn.innerHTML = window.icon ? window.icon('x', 14) : '×';
      delBtn.title = 'Delete Slide';
      delBtn.style.zIndex = '20';
      delBtn.onclick = (e) => { e.stopPropagation(); this.deletePage(idx); };

      thumb.appendChild(dupBtn);
      thumb.appendChild(delBtn);
      list.appendChild(thumb);
    });
  }

  async openGallery() {
    const browser = $('#presentation-gallery-browser');
    const grid = $('#pt-gallery-grid');
    if (!browser || !grid) return;

    browser.style.display = 'flex';
    grid.innerHTML = '<div style="padding:10px;color:var(--text-muted)">Loading...</div>';

    try {
      const res = await fetch('/image/gallery');
      if (!res.ok) throw new Error('Failed to load gallery');
      const data = await res.json();

      grid.innerHTML = '';
      let list = data.images || data.files || [];

      // Show all images (AI generated + uploaded), filter out videos only
      const images = list.filter(f => !f.isVideo);

      if (images.length === 0) {
        grid.innerHTML = '<div style="padding:10px;color:var(--text-muted)">No media images found. Generate some in Media mode!</div>';
        return;
      }

      images.forEach(img => {
        const div = document.createElement('div');
        div.className = 'pt-gallery-item';
        const imgUrl = img.url || `/data/images/${img.filename}`;
        div.innerHTML = `<img src="${imgUrl}" alt="${img.filename}">`;
        div.onclick = () => {
          this.addElement('image', imgUrl);
          browser.style.display = 'none';
        };
        grid.appendChild(div);
      });
    } catch (e) {
      grid.innerHTML = `<div style="padding:10px;color:var(--red)">${e.message}</div>`;
    }
  }

  async loadTemplates() {
    const list = $('#pt-templates-list');
    if (!list) return;
    list.innerHTML = '<div style="color:var(--text-muted)">Loading templates...</div>';
    try {
      const res = await fetch('/presentation/templates');
      if (!res.ok) throw new Error('Failed to load templates');
      const data = await res.json();
      list.innerHTML = '';
      if (!data.templates || data.templates.length === 0) {
        list.innerHTML = '<div style="color:var(--text-muted)">No templates found.</div>';
        return;
      }
      data.templates.forEach(t => {
        const btn = document.createElement('div');
        btn.className = 'presentation-template-tile';
        btn.style.position = 'relative';
        btn.style.cursor = 'pointer';

        // Simple visual preview using the theme colors
        const colors = t.colors || {};
        const bg = colors.bg || '#000';
        const accent = colors.accent || '#fff';
        const surface = colors.surface || '#222';

        btn.innerHTML = `
           <div style="width:100%; height:80px; background:${bg}; border-radius:4px; margin-bottom:4px; position:relative; overflow:hidden; border:1px solid var(--border)">
             <div style="position:absolute; top:10%; left:10%; width:80%; height:20%; background:${accent}; opacity:0.8; border-radius:2px;"></div>
             <div style="position:absolute; top:40%; left:10%; width:40%; height:40%; background:${surface}; border-radius:2px;"></div>
             <div style="position:absolute; top:40%; right:10%; width:30%; height:40%; background:${surface}; border-radius:2px;"></div>
           </div>
           <div class="template-info" style="display:flex; flex-direction:column; gap:2px; text-align:center;">
             <strong style="font-size:11px;">${t.title}</strong>
           </div>
         `;

        btn.onclick = async () => {
          const isEmpty = this.pages.length === 0 || (this.pages.length === 1 && this.pages[0].elements.length === 0);
          let mode = 'replace';
          if (!isEmpty) {
            const action = confirm('Click OK to REPLACE your current slides with this template.\nClick Cancel to ADD these slides to your current presentation.');
            mode = action ? 'replace' : 'add';
          }

          try {
            const lr = await fetch(`/presentation/template/${t.id}`);
            if (lr.ok) {
              const ldata = await lr.json();
              const loadedPages = ldata.pages || [{ elements: [] }];

              if (mode === 'replace') {
                this.pages = loadedPages;
                this.canvasW = ldata.canvas_width || 960;
                this.canvasH = ldata.canvas_height || 540;
                this.currentPage = 0;
              } else {
                const newPages = JSON.parse(JSON.stringify(loadedPages));
                newPages.forEach(page => {
                  page.elements.forEach(el => el.id = 'el_' + Math.random().toString(36).substr(2, 9));
                  this.pages.push(page);
                });
                this.currentPage = this.pages.length - newPages.length;
              }

              this.presId = null;
              localStorage.removeItem('pt-last-id');
              this.title = ldata.title || 'Nouveau Template';
              if ($('#pt-pres-title')) $('#pt-pres-title').value = this.title;

              this.selectElement(null);
              this.renderPages();
              this.renderCanvas();

              toast(mode === 'replace' ? ' Template loaded!' : ' Slides added!');
            }
          } catch (e) {
            toast(' Template loading failed', 4000);
          }
        };
        list.appendChild(btn);
      });
    } catch (e) {
      list.innerHTML = `<div style="color:var(--red)">${e.message}</div>`;
    }
  }

  async loadSavedPresentations() {
    const list = $('#pt-saved-list');
    if (!list) return;
    list.innerHTML = '<div style="color:var(--text-muted)">Loading...</div>';
    try {
      const res = await fetch('/presentation/list');
      if (!res.ok) throw new Error('Failed to load saved presentations');
      const data = await res.json();
      list.innerHTML = '';
      if (!data.presentations || data.presentations.length === 0) {
        list.innerHTML = '<div style="color:var(--text-muted); grid-column: span 2;">No saved presentations found.</div>';
        return;
      }
      data.presentations.forEach(p => {
        const btn = document.createElement('div');
        btn.className = 'presentation-template-tile';

        const dateStr = new Date(p.updated_at * 1000).toLocaleDateString();
        const imgHtml = p.thumbnail ?
          `<img src="${p.thumbnail}?t=${p.updated_at}">` :
          `<div class="no-preview" style="display:flex; align-items:center; justify-content:center; font-size:10px; color:#666;">No Preview</div>`;
        btn.style.position = 'relative';
        btn.innerHTML = `
           ${imgHtml}
           <div class="template-info" style="display:flex; flex-direction:column; gap:2px; flex: 1;">
             <strong>${p.title || p.id}</strong>
             <small>${dateStr}</small>
           </div>
           <button class="pt-template-rename" title="Rename" style="position: absolute; top: 4px; right: 32px; background: rgba(0,0,0,0.6); border: none; color: white; border-radius: 4px; padding: 4px; cursor: pointer; display: flex; align-items: center; justify-content: center; width: 24px; height: 24px; z-index: 10;">
             ${window.icon ? window.icon('pen', 14) : '✎'}
           </button>
           <button class="pt-template-delete" title="Delete" style="position: absolute; top: 4px; right: 4px; background: rgba(0,0,0,0.6); border: none; color: white; border-radius: 4px; padding: 4px; cursor: pointer; display: flex; align-items: center; justify-content: center; width: 24px; height: 24px; z-index: 10;">
             ${window.icon ? window.icon('trash', 14) : '×'}
           </button>
         `;

        const renBtn = btn.querySelector('.pt-template-rename');
        renBtn.onclick = async (e) => {
          e.stopPropagation();
          const newTitle = prompt('Rename presentation to:', p.title || p.id);
          if (newTitle && newTitle.trim() !== '') {
            try {
              const rr = await fetch(`/presentation/rename/${p.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: newTitle.trim() })
              });
              if (rr.ok) {
                toast(ICONS.check(14) + ' Renamed');
                this.loadSavedPresentations();
              } else {
                toast(' Failed to rename', 4000);
              }
            } catch (err) {
              toast(' Error renaming', 4000);
            }
          }
        };

        const delBtn = btn.querySelector('.pt-template-delete');
        delBtn.onclick = async (e) => {
          e.stopPropagation();
          if (confirm('Delete this presentation?')) {
            try {
              const dr = await fetch(`/presentation/delete/${p.id}`, { method: 'DELETE' });
              if (dr.ok) {
                btn.remove();
                if (this.presId === p.id) {
                  this.presId = null;
                  localStorage.removeItem('pt-last-id');
                }
                toast(ICONS.check(14) + ' Deleted');
              } else {
                toast(' Failed to delete', 4000);
              }
            } catch (err) {
              toast(' Failed to delete', 4000);
            }
          }
        };

        btn.onclick = async () => {
          try {
            const lr = await fetch(`/presentation/load/${p.id}`);
            if (lr.ok) {
              const ldata = await lr.json();
              this.pages = ldata.pages || [{ elements: [] }];
              this.canvasW = ldata.canvas_width || 960;
              this.canvasH = ldata.canvas_height || 540;
              this.currentPage = 0;
              this.presId = p.id;
              localStorage.setItem('pt-last-id', p.id);
              this.title = ldata.title || 'Loaded Presentation';
              if ($('#pt-pres-title')) $('#pt-pres-title').value = this.title;
              this.selectElement(null);
              this.renderPages();
              this.renderCanvas();
              toast(' Presentation loaded!');
            }
          } catch (e) {
            toast(' Failed to load presentation', 4000);
          }
        };
        list.appendChild(btn);
      });
    } catch (e) {
      list.innerHTML = `<div style="color:var(--red)">${e.message}</div>`;
    }
  }

  loadLibrary() {
    if (!window.lucide || !window.lucide.icons) {
      toast('Lucide icons library not loaded yet.', 3000);
      return;
    }
    this.filterLibrary('');
  }

  filterLibrary(query) {
    if (!window.lucide || !window.lucide.icons) return;
    const grid = $('#pt-library-grid');
    if (!grid) return;

    const browser = $('#presentation-library-browser');
    const q = (query || '').toLowerCase().trim();
    const icons = window.lucide.icons;
    // limit to 100 for performance
    const keys = Object.keys(icons).filter(k => k.toLowerCase().includes(q)).slice(0, 100);

    grid.innerHTML = '';
    if (keys.length === 0) {
      grid.innerHTML = '<div style="color:var(--text-muted); grid-column: 1 / -1; text-align: center;">No icons found.</div>';
      return;
    }

    keys.forEach(k => {
      const btn = document.createElement('button');
      btn.className = 'presentation-shape-tile';
      btn.title = k;
      btn.style.width = '100%';
      btn.style.height = '40px';
      const node = window.lucide.createElement(icons[k]);
      btn.innerHTML = node.outerHTML;
      btn.onclick = () => {
        this.addElement('icon', { name: k, svg: node.outerHTML });
        if (browser) browser.style.display = 'none';
      };
      grid.appendChild(btn);
    });
  }

  // ---- SVG Illustrations Browser ----
  async loadIllustrations() {
    const grid = $('#pt-illustrations-grid');
    if (!grid) return;
    grid.innerHTML = '<div style="color:var(--text-muted); grid-column: 1 / -1; text-align:center">Loading...</div>';

    try {
      const res = await fetch('/presentation/svg-catalog');
      if (!res.ok) throw new Error('Failed to load catalog');
      const data = await res.json();
      this._illustrationsCatalog = data.illustrations || [];
      this._illustrationsCategories = data.categories || {};
      this.filterIllustrations('');
    } catch (e) {
      grid.innerHTML = `<div style="color:var(--red); grid-column: 1 / -1">${e.message}</div>`;
    }
  }

  filterIllustrations(query) {
    const grid = $('#pt-illustrations-grid');
    if (!grid || !this._illustrationsCatalog) return;
    const q = (query || '').toLowerCase().trim();

    const filtered = this._illustrationsCatalog.filter(i => i.name.toLowerCase().includes(q));
    grid.innerHTML = '';

    if (filtered.length === 0) {
      grid.innerHTML = '<div style="color:var(--text-muted); grid-column: 1 / -1; text-align:center">No illustrations found.</div>';
      return;
    }

    filtered.forEach(item => {
      const btn = document.createElement('button');
      btn.className = 'presentation-shape-tile';
      btn.title = item.name;
      btn.style.width = '100%';
      btn.style.height = '60px';
      btn.style.padding = '4px';
      btn.innerHTML = item.svg;
      const svg = btn.querySelector('svg');
      if (svg) {
        svg.style.width = '100%';
        svg.style.height = '100%';
      }
      btn.onclick = () => {
        // Convert SVG to data URI and add as image element
        const blob = new Blob([item.svg], { type: 'image/svg+xml' });
        const url = URL.createObjectURL(blob);
        const el = this.addElement('image', url);
        el.width = 200;
        el.height = 200;
        this.renderCanvas();
        const browser = $('#presentation-illustrations-browser');
        if (browser) browser.style.display = 'none';
        toast(ICONS.check(14) + ` Illustration "${item.name}" added`);
      };
      grid.appendChild(btn);
    });
  }

  // ---- Local Open-Source Stock Photo Library ----
  async loadStockPhotos(category = '') {
    const input = $('#pt-stock-search-input');
    const grid = $('#pt-stock-grid');
    if (!grid) return;
    const query = input ? input.value.trim() : '';

    grid.innerHTML = '<div style="color:var(--text-muted); column-span: all; text-align:center">Loading...</div>';

    try {
      const params = new URLSearchParams();
      if (query) params.set('q', query);
      if (category) params.set('category', category);
      const res = await fetch(`/presentation/stock-images?${params}`);
      if (!res.ok) throw new Error('Failed to load stock images');
      const data = await res.json();

      grid.innerHTML = '';

      // Category filter tabs
      if (data.categories && data.categories.length > 0) {
        const tabs = document.createElement('div');
        tabs.style.cssText = 'column-span: all; display:flex; flex-wrap:wrap; gap:4px; padding-bottom:8px; border-bottom:1px solid var(--border); margin-bottom:4px';

        const allBtn = document.createElement('button');
        allBtn.className = 'btn btn-sm ' + (!category ? 'btn-primary' : 'btn-secondary');
        allBtn.textContent = 'All';
        allBtn.style.cssText = 'padding:2px 8px; font-size:11px; border-radius:12px';
        allBtn.onclick = () => this.loadStockPhotos('');
        tabs.appendChild(allBtn);

        data.categories.forEach(cat => {
          const btn = document.createElement('button');
          btn.className = 'btn btn-sm ' + (category === cat ? 'btn-primary' : 'btn-secondary');
          btn.textContent = cat.charAt(0).toUpperCase() + cat.slice(1);
          btn.style.cssText = 'padding:2px 8px; font-size:11px; border-radius:12px; text-transform:capitalize';
          btn.onclick = () => this.loadStockPhotos(cat);
          tabs.appendChild(btn);
        });
        grid.appendChild(tabs);
      }

      if (!data.images || data.images.length === 0) {
        grid.innerHTML += `<div style="color:var(--text-muted); column-span: all; text-align:center; font-size:12px; padding:20px">${data.message || 'No images found. Run: python scripts/download_stock_images.py'}</div>`;
        return;
      }

      data.images.forEach(img => {
        const div = document.createElement('div');
        div.className = 'pt-stock-item';
        div.style.position = 'relative';
        div.style.marginBottom = '8px';
        div.style.breakInside = 'avoid';
        div.innerHTML = `<img src="${img.url}" alt="${escHtml(img.description || '')}" loading="lazy" style="width:100%; border-radius:4px; display:block;">`;

        if (img.author_name) {
          // Author attribution badge
          const badge = document.createElement('div');
          badge.style.cssText = 'position:absolute;bottom:0;left:0;right:0;font-size:9px;color:white;background:linear-gradient(transparent, rgba(0,0,0,0.8));padding:12px 6px 4px;border-bottom-left-radius:4px;border-bottom-right-radius:4px;opacity:0;transition:opacity 0.2s;';
          const authorLink = img.author_link ? `${img.author_link}?utm_source=clawzd&utm_medium=referral` : '#';
          badge.innerHTML = `By <a href="${authorLink}" target="_blank" style="color:var(--accent);text-decoration:none;" onclick="event.stopPropagation()">${escHtml(img.author_name)}</a>`;

          div.onmouseenter = () => badge.style.opacity = '1';
          div.onmouseleave = () => badge.style.opacity = '0';
          div.appendChild(badge);
        } else if (img.category) {
          const badge = document.createElement('div');
          badge.style.cssText = 'position:absolute;top:3px;left:3px;font-size:9px;color:white;background:rgba(0,0,0,0.6);padding:1px 6px;border-radius:8px';
          badge.textContent = img.category || '';
          div.appendChild(badge);
        }

        div.onclick = () => {
          const el = this.addElement('image', img.url);
          if (img.author_name) {
            el.attribution = `Photo by ${img.author_name} on Unsplash`;
          }
          const browser = $('#presentation-stock-browser');
          if (browser) browser.style.display = 'none';
          toast(ICONS.check(14) + ` Image added`);
        };
        grid.appendChild(div);
      });

      // Credit footer
      const credit = document.createElement('div');
      credit.style.cssText = 'column-span: all; text-align: center; font-size: 10px; color: var(--text-muted); padding: 4px';
      credit.textContent = `${data.total} open-source images • Free to use`;
      grid.appendChild(credit);
    } catch (e) {
      grid.innerHTML = `<div style="color:var(--red); column-span: all;">${e.message}</div>`;
    }
  }

  newPresentation() {
    this.pages = [{ elements: [] }];
    this.currentPage = 0;
    this.selectedElement = null;
    this.presId = null;
    localStorage.removeItem('pt-last-id');

    const titleInput = $('#pt-pres-title');
    if (titleInput) titleInput.value = 'My Presentation';

    this.renderPages();
    this.renderCanvas();
    this.updatePropertiesPanel();
    toast(ICONS.fileText(14) + ' New blank presentation created');
  }

  async save(silent = false) {
    const titleInput = $('#pt-pres-title');
    const name = titleInput ? titleInput.value.trim() : "My Presentation";
    this.title = name || "My Presentation";

    // Don't save empty presentations
    const totalElements = this.pages.reduce((sum, p) => sum + (p.elements ? p.elements.length : 0), 0);
    if (totalElements === 0) {
      if (!silent) toast('⚠️ Empty presentation — nothing to save.', 3000);
      return;
    }

    if (!silent) toast(ICONS.hourglass(14) + ' Saving presentation... (This might take a moment to generate the preview)');
    try {
      const res = await fetch('/presentation/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: this.presId,
          title: this.title,
          pages: this.pages,
          canvas_width: this.canvasW,
          canvas_height: this.canvasH
        })
      });
      if (!res.ok) throw new Error('Failed to save');
      const data = await res.json();
      this.presId = data.id;
      localStorage.setItem('pt-last-id', data.id);
      if (!silent) toast(ICONS.check(14) + ' Presentation saved persistently!');
    } catch (e) {
      if (!silent) toast(` Save error: ${e.message}`, 4000);
    }
  }

  async enhanceSelectedText() {
    if (!this.selectedElement || this.selectedElement.type !== 'text') {
      toast('Please select a text element first.');
      return;
    }

    const btn = $('#pt-prop-ai-enhance');
    const originalText = btn.innerText;
    btn.innerText = ' Enhancing...';
    btn.disabled = true;

    try {
      const res = await fetch('/presentation/ai-enrich', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: this.selectedElement.content,
          mode: 'enhance'
        })
      });

      if (!res.ok) throw new Error('API error');
      const data = await res.json();

      if (data.result) {
        this.selectedElement.content = data.result;
        $('#pt-prop-content').value = data.result;
        this.renderCanvas();
        toast(ICONS.check(14) + ' Text enhanced!');
      }
    } catch (e) {
      toast(' Enhancement failed: ' + e.message);
    } finally {
      btn.innerText = originalText;
      btn.disabled = false;
    }
  }

  async enrichPresentation() {
    const btn = $('#pt-ai-enrich');
    if (!btn) return;

    btn.classList.add('loading');
    btn.disabled = true;
    toast(ICONS.sparkles(14) + ' AI is enriching the current page...');

    try {
      const page = this.pages[this.currentPage];
      const textContents = page.elements
        .filter(e => e.type === 'text' && e.content)
        .map(e => e.content)
        .join(' | ');

      const userInput = $('#pt-ai-prompt') ? $('#pt-ai-prompt').value.trim() : '';
      let finalPrompt = '';
      let mode = 'bullets';

      if (userInput) {
        finalPrompt = textContents ? `Current slide text: ${textContents}\n\nUser request: ${userInput}` : userInput;
        mode = 'enhance';
      } else {
        if (!textContents) {
          toast('No text found on page to enrich. Please provide a prompt or select a slide with text.');
          btn.classList.remove('loading');
          btn.disabled = false;
          return;
        }
        finalPrompt = textContents;
        mode = 'bullets';
      }

      const res = await fetch('/presentation/ai-enrich', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: finalPrompt,
          mode: mode
        })
      });

      if (!res.ok) throw new Error('API error');
      const data = await res.json();

      if (data.result) {
        this.addElement('text', data.result);
        const newEl = this.pages[this.currentPage].elements[this.pages[this.currentPage].elements.length - 1];
        newEl.x = this.canvasW / 2 - 150;
        newEl.y = this.canvasH / 2 - 50;
        newEl.width = Math.min(this.canvasW - 40, Math.max(300, newEl.content.length * 5));
        if (mode === 'bullets' || data.result.includes('\\n- ')) newEl.isList = true;
        this.selectElement(newEl);
        this.renderCanvas();
        toast(ICONS.check(14) + ' AI enriched text added to canvas!');
      }
    } catch (e) {
      toast(' Enrichment failed: ' + e.message);
    } finally {
      btn.classList.remove('loading');
      btn.disabled = false;
    }
  }

  async generatePresentation() {
    const input = $('#pt-ai-prompt');
    const btn = $('#pt-ai-generate');
    if (!input || !btn) return;

    const prompt = input.value.trim();
    if (!prompt) { toast('Please enter a description for your presentation.'); return; }

    btn.classList.add('loading');
    btn.disabled = true;
    toast(ICONS.sparkles(14) + ' AI is generating your presentation...');

    try {
      const res = await fetch('/presentation/ai-generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt,
          canvas_width: this.canvasW,
          canvas_height: this.canvasH
        })
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Server error' }));
        throw new Error(err.detail || 'Generation failed');
      }

      const data = await res.json();

      if (data.pages && data.pages.length > 0) {
        this.pages = data.pages;
        this.currentPage = 0;
        this.selectElement(null);
        if (data.title) {
          this.title = data.title;
          if ($('#pt-pres-title')) $('#pt-pres-title').value = data.title;
        }
        this.renderPages();
        this.renderCanvas();
        toast(` Generated ${data.pages.length} slide(s)!`, 4000);
        input.value = '';
      } else {
        throw new Error('AI returned empty presentation');
      }
    } catch (e) {
      toast(` AI generation failed: ${e.message}`, 5000);
    } finally {
      btn.classList.remove('loading');
      btn.disabled = false;
    }
  }
  async export(format, pagesMode = 'all', customPages = '') {
    toast(`${ICONS.hourglass(14)} Generating ${format.toUpperCase()}...`);

    let pagesToExport = [];
    if (pagesMode === 'current') {
      pagesToExport = [JSON.parse(JSON.stringify(this.pages[this.currentPage]))];
    } else if (pagesMode === 'custom' && customPages) {
      const selected = [];
      const parts = customPages.split(',');
      for (let p of parts) {
        p = p.trim();
        if (p.includes('-')) {
          const [start, end] = p.split('-').map(Number);
          if (!isNaN(start) && !isNaN(end)) {
            for (let i = start; i <= end; i++) {
              if (i >= 1 && i <= this.pages.length) selected.push(this.pages[i - 1]);
            }
          }
        } else {
          const i = parseInt(p);
          if (!isNaN(i) && i >= 1 && i <= this.pages.length) {
            selected.push(this.pages[i - 1]);
          }
        }
      }
      if (selected.length > 0) pagesToExport = JSON.parse(JSON.stringify(selected));
      else pagesToExport = JSON.parse(JSON.stringify(this.pages));
    } else {
      pagesToExport = JSON.parse(JSON.stringify(this.pages));
    }

    // ── Convert all images (blob:, relative, etc.) to base64 data URIs ──
    for (const page of pagesToExport) {
      for (const el of page.elements) {
        // Convert image elements with blob: or relative URLs to base64
        if (el.type === 'image' && el.src) {
          if (el.src.startsWith('blob:') || (!el.src.startsWith('data:') && !el.src.startsWith('http') && !el.src.startsWith('/data/'))) {
            try {
              el.src = await this._imageToBase64(el.src, el.width || 400, el.height || 300);
            } catch (e) {
              console.warn('Failed to convert image to base64 for export:', e);
            }
          }
        }

        // Convert icon SVG elements to base64 PNG images for export
        if (el.type === 'icon' && el.svgContent) {
          try {
            const svgStr = el.svgContent;
            const b64 = await this._svgToBase64Png(svgStr, el.width || 100, el.height || 100,
              el.borderColor || '#000000', el.backgroundColor || 'transparent');
            if (b64) {
              el.type = 'image';
              el.src = b64;
            }
          } catch (e) {
            console.warn('Failed to convert icon to image for export:', e);
          }
        }

        // Convert mermaid elements to base64 PNGs for export
        if (el.type === 'mermaid' && window.mermaid) {
          try {
            const id = 'mmr-export-' + Math.random().toString(36).substr(2, 9);
            const r = await mermaid.render(id, el.content || 'graph TD; A-->B;');
            const pngDataUrl = await this._svgToBase64Png(r.svg, el.width || 800, el.height || 600);
            if (pngDataUrl) {
              el.type = 'image';
              el.src = pngDataUrl;
            }
          } catch (e) {
            console.warn('Failed to render mermaid for export', e);
          }
        }
      }
    }

    if (format === 'mp4') {
      const voice = $('#pt-video-voice')?.value || 'fr-FR-DeniseNeural';
      const avatar = $('#pt-video-avatar')?.value || 'sophie';
      const avatar_position = $('#pt-video-avatar-pos')?.value || 'bottom-right';
      const auto_narrate = $('#pt-video-auto-narrate')?.checked || false;
      const subtitles = $('#pt-video-subtitles')?.checked || false;
      const subtitles_lang = $('#pt-video-subtitles-lang')?.value || 'none';
      const quality = $('#pt-video-quality')?.value || '1080p';
      
      toast(ICONS.hourglass(14) + ' Generating video presentation... Synthesizing neural voices and compiling frames. This might take up to a minute.', 45000);
      try {
        const res = await fetch('/presentation/export-video', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            pages: pagesToExport,
            canvas_width: this.canvasW,
            canvas_height: this.canvasH,
            voice: voice,
            avatar: avatar,
            avatar_position: avatar_position,
            auto_narrate: auto_narrate,
            subtitles: subtitles,
            subtitles_language: subtitles_lang,
            quality: quality
          })
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || 'Video compilation crashed.');
        }

        const data = await res.json();
        toast(' Successfully compiled video! Downloading presentation...', 5000);

        const a = document.createElement('a');
        a.href = data.url;
        a.download = data.filename;
        a.click();
      } catch (e) {
        toast(`⚠️ Video compilation failed: ${e.message}`, 6000);
      }
      return;
    }

    try {
      const res = await fetch('/presentation/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          format: format,
          pages: pagesToExport,
          canvas_width: this.canvasW,
          canvas_height: this.canvasH
        })
      });

      if (!res.ok) {
        const err = await res.text();
        throw new Error(err);
      }

      const data = await res.json();
      toast(` Successfully created ${data.filename}! Downloading...`, 4000);

      const a = document.createElement('a');
      a.href = data.url;
      a.download = data.filename;
      a.click();
    } catch (e) {
      toast(` Failed to export ${format.toUpperCase()}: ${e.message}`, 5000);
    }
  }

  /** Convert an image URL (blob:, relative, etc.) to a base64 data URI */
  _imageToBase64(src, w, h) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = img.naturalWidth || w;
        canvas.height = img.naturalHeight || h;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL('image/png'));
      };
      img.onerror = () => reject(new Error('Image load failed: ' + src.substring(0, 50)));
      img.src = src;
    });
  }

  /** Convert an SVG string to a base64 PNG data URI */
  _svgToBase64Png(svgStr, w, h, stroke, fill) {
    return new Promise((resolve) => {
      // Ensure SVG has proper xmlns
      let svg = svgStr;
      if (!svg.includes('xmlns')) {
        svg = svg.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"');
      }
      // Apply colors if needed
      if (stroke && stroke !== 'transparent') {
        svg = svg.replace(/<svg([^>]*)>/, `<svg$1 stroke="${stroke}">`);
      }
      if (fill && fill !== 'transparent') {
        svg = svg.replace(/<svg([^>]*)>/, `<svg$1 fill="${fill}">`);
      }

      const img = new Image();
      img.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL('image/png'));
      };
      img.onerror = () => resolve(null);
      img.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svg)));
    });
  }

  _updateDocgenVisibility() {
    const isCard = this.templateSubMode === 'business_card';
    const show = id => { const el = document.getElementById(id); if (el) el.style.display = ''; };
    const hide = id => { const el = document.getElementById(id); if (el) el.style.display = 'none'; };

    const tplIds = [
      'pt-tpl-style-group', 'pt-tpl-cv-style-group',
      'pt-tpl-linkedin-group', 'pt-tpl-target-role-group',
      'pt-tpl-company-group', 'pt-tpl-summary-group',
      'pt-tpl-skills-group', 'pt-tpl-location-group',
      'pt-tpl-linkedin-preview'
    ];
    tplIds.forEach(id => hide(id));

    if (isCard) {
      show('pt-tpl-style-group');
      show('pt-tpl-company-group');
    } else {
      show('pt-tpl-cv-style-group');
      show('pt-tpl-linkedin-group');
      show('pt-tpl-target-role-group');
      show('pt-tpl-summary-group');
      show('pt-tpl-skills-group');
      show('pt-tpl-location-group');
      if (this._linkedInData) show('pt-tpl-linkedin-preview');
    }
  }

  async fetchLinkedInProfile() {
    const urlInput = $('#pt-tpl-linkedin-url');
    const statusEl = $('#pt-tpl-linkedin-status');
    const url = (urlInput?.value || '').trim();
    if (!url || !url.includes('linkedin.com')) {
      toast(ICONS.circle(14) + ' Please enter a valid LinkedIn URL');
      return;
    }
    if (statusEl) { statusEl.style.display = ''; statusEl.innerHTML = '⏳ Fetching LinkedIn profile...'; }
    const fetchBtn = $('#pt-tpl-linkedin-fetch');
    if (fetchBtn) { fetchBtn.disabled = true; fetchBtn.textContent = '⏳...'; }
    try {
      const targetRole = ($('#pt-tpl-target-role') || {}).value || '';
      const resp = await fetch('/docgen/scrape-linkedin', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, target_role: targetRole })
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || 'Fetch failed');
      const p = data.profile;
      this._linkedInData = p;
      if (p.name) { const el = $('#pt-tpl-name'); if (el && !el.value) el.value = p.name; }
      if (p.headline) { const el = $('#pt-tpl-title'); if (el && !el.value) el.value = p.headline; }
      if (p.summary || p.enriched_summary) { const el = $('#pt-tpl-summary'); if (el && !el.value) el.value = p.enriched_summary || p.summary; }
      if (p.location) { const el = $('#pt-tpl-location'); if (el && !el.value) el.value = p.location; }
      if (p.skills?.length) { const el = $('#pt-tpl-skills'); if (el && !el.value) el.value = p.skills.join(', '); }
      const previewEl = $('#pt-tpl-linkedin-data');
      const previewGrp = $('#pt-tpl-linkedin-preview');
      if (previewEl && previewGrp) {
        let html = `<strong>${p.name || '—'}</strong>`;
        if (p.headline) html += `<br>📌 ${p.headline}`;
        if (p.photo_url) html += `<br><img src="${p.photo_url}" style="width:60px;height:60px;border-radius:50%;margin-top:6px;object-fit:cover;">`;
        if (p.seo_keywords?.length) html += `<br>🏷️ <em>${p.seo_keywords.slice(0, 8).join(', ')}</em>`;
        previewEl.innerHTML = html;
        previewGrp.style.display = '';
      }
      if (statusEl) { statusEl.innerHTML = '✅ LinkedIn profile imported successfully'; }
      toast('✅ LinkedIn profile imported !');
    } catch (e) {
      if (statusEl) { statusEl.innerHTML = `❌ Error: ${e.message}`; }
      toast('❌ ' + e.message);
    } finally {
      if (fetchBtn) { fetchBtn.disabled = false; fetchBtn.textContent = '🔍 Fetch'; }
    }
  }

  async generateTemplate() {
    if (this.generating) return;
    const name = ($('#pt-tpl-name') || {}).value?.trim();
    if (!name) { toast(ICONS.circle(14) + ' Le nom est requis'); return; }
    this.generating = true;
    const genBtn = $('#pt-tpl-generate-btn');
    if (genBtn) { genBtn.classList.add('loading'); genBtn.disabled = true; }
    try {
      let resp, endpoint;
      if (this.templateSubMode === 'business_card') {
        endpoint = '/docgen/generate-business-card';
        resp = await fetch(endpoint, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name,
            title: ($('#pt-tpl-title') || {}).value || '',
            company: ($('#pt-tpl-company') || {}).value || '',
            email: ($('#pt-tpl-email') || {}).value || '',
            phone: ($('#pt-tpl-phone') || {}).value || '',
            website: ($('#pt-tpl-website') || {}).value || '',
            style: ($('#pt-tpl-style') || {}).value || 'modern',
          })
        });
      } else {
        endpoint = '/docgen/generate-cv';
        const skillsStr = ($('#pt-tpl-skills') || {}).value || '';
        const skills = skillsStr ? skillsStr.split(',').map(s => s.trim()).filter(Boolean) : [];
        resp = await fetch(endpoint, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name,
            title: ($('#pt-tpl-title') || {}).value || '',
            email: ($('#pt-tpl-email') || {}).value || '',
            phone: ($('#pt-tpl-phone') || {}).value || '',
            website: ($('#pt-tpl-website') || {}).value || '',
            summary: ($('#pt-tpl-summary') || {}).value || '',
            location: ($('#pt-tpl-location') || {}).value || '',
            skills,
            seo_keywords: this._linkedInData?.seo_keywords || [],
            experience: this._linkedInData?.experience || [],
            education: this._linkedInData?.education || [],
            photo_url: this._linkedInData?.photo_url || '',
            linkedin_url: ($('#pt-tpl-linkedin-url') || {}).value || '',
            target_role: ($('#pt-tpl-target-role') || {}).value || '',
            style: ($('#pt-tpl-cv-style') || {}).value || 'professional',
          })
        });
      }
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || 'Generation failed');
      toast(`✅ ${this.templateSubMode === 'business_card' ? 'Business Card' : 'CV'} generated !`);
      if (data.seo_keywords?.length) {
        toast(`🏷️ SEO keywords: ${data.seo_keywords.slice(0, 5).join(', ')}`, 5000);
      }
      if (data.presentation) {
        this.pages = data.presentation.pages;
        this.canvasW = data.presentation.canvas_width;
        this.canvasH = data.presentation.canvas_height;
        this.currentPage = 0;

        const c = $('#presentation-canvas');
        if (c) {
          c.style.width = this.canvasW + 'px';
          c.style.height = this.canvasH + 'px';
        }

        this.renderPages();
        this.renderCanvas();
        this.updateCanvasZoom();
        this.saveState();

        const sel = $('#pt-format-select');
        if (sel) {
          if (this.canvasW === 638 && this.canvasH === 368) sel.value = 'card';
          else if (this.canvasW === 794 && this.canvasH === 1123) sel.value = 'A4';
        }
      }
    } catch (e) {
      toast('❌ ' + e.message);
    } finally {
      this.generating = false;
      if (genBtn) { genBtn.classList.remove('loading'); genBtn.disabled = false; }
    }
  }

  // ═══════════════════════════════════════════════════
  // ──────────── FULLSCREEN PLAYER MODE ──────────────
  // ═══════════════════════════════════════════════════

  startPlayer() {
    if (this.pages.length === 0) {
      toast('No slides to present.');
      return;
    }

    this._playerSlide = 0;
    this._playerActive = true;

    // Create overlay
    let overlay = document.getElementById('pt-player-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'pt-player-overlay';
      overlay.className = 'pt-player-overlay';
      document.body.appendChild(overlay);
    }
    overlay.innerHTML = `
      <div class="pt-player-canvas-wrap" id="pt-player-canvas-wrap">
        <div class="pt-player-canvas" id="pt-player-canvas"></div>
      </div>
      <div class="pt-player-controls" id="pt-player-controls">
        <button class="pt-player-nav-btn" id="pt-player-prev" title="Previous (←)">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
        </button>
        <span class="pt-player-counter" id="pt-player-counter">1 / ${this.pages.length}</span>
        <button class="pt-player-nav-btn" id="pt-player-next" title="Next (→)">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
        </button>
        <button class="pt-player-nav-btn pt-player-exit-btn" id="pt-player-exit" title="Exit (Esc)">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
      <div class="pt-player-progress" id="pt-player-progress">
        <div class="pt-player-progress-bar" id="pt-player-progress-bar"></div>
      </div>
    `;
    overlay.style.display = 'flex';

    // Request fullscreen
    const docEl = document.documentElement;
    if (docEl.requestFullscreen) docEl.requestFullscreen().catch(() => { });
    else if (docEl.webkitRequestFullscreen) docEl.webkitRequestFullscreen();

    // Bind events
    this._playerKeyHandler = (e) => this._playerOnKey(e);
    this._playerClickHandler = (e) => this._playerOnClick(e);
    this._playerMoveHandler = () => this._playerShowControls();
    this._playerResizeHandler = () => {
      if (this._playerActive) this.renderPlayerSlide(this._playerSlide);
    };
    document.addEventListener('keydown', this._playerKeyHandler);
    overlay.addEventListener('click', this._playerClickHandler);
    overlay.addEventListener('mousemove', this._playerMoveHandler);
    window.addEventListener('resize', this._playerResizeHandler);

    // Button events
    document.getElementById('pt-player-prev')?.addEventListener('click', (e) => {
      e.stopPropagation();
      this.playerNavigate(-1);
    });
    document.getElementById('pt-player-next')?.addEventListener('click', (e) => {
      e.stopPropagation();
      this.playerNavigate(1);
    });
    document.getElementById('pt-player-exit')?.addEventListener('click', (e) => {
      e.stopPropagation();
      this.stopPlayer();
    });

    // Render first slide
    this.renderPlayerSlide(0);
    this._playerShowControls();
  }

  stopPlayer() {
    this._playerActive = false;
    const overlay = document.getElementById('pt-player-overlay');
    if (overlay) overlay.style.display = 'none';

    // Remove event listeners
    if (this._playerKeyHandler) document.removeEventListener('keydown', this._playerKeyHandler);
    if (this._playerResizeHandler) window.removeEventListener('resize', this._playerResizeHandler);
    if (this._playerClickHandler) {
      const ov = document.getElementById('pt-player-overlay');
      if (ov) ov.removeEventListener('click', this._playerClickHandler);
    }

    // Exit fullscreen
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => { });
    } else if (document.webkitFullscreenElement) {
      document.webkitExitFullscreen();
    }

    // Clear timer
    if (this._playerControlsTimer) clearTimeout(this._playerControlsTimer);
  }

  playerNavigate(direction) {
    if (!this._playerActive) return;
    const next = this._playerSlide + direction;
    if (next < 0 || next >= this.pages.length) return;
    this.renderPlayerSlide(next);
  }

  renderPlayerSlide(index) {
    this._playerSlide = index;
    const canvas = document.getElementById('pt-player-canvas');
    const counter = document.getElementById('pt-player-counter');
    const progressBar = document.getElementById('pt-player-progress-bar');
    if (!canvas) return;

    // Set canvas size
    canvas.style.width = this.canvasW + 'px';
    canvas.style.height = this.canvasH + 'px';

    // Scale to fit viewport
    const wrap = document.getElementById('pt-player-canvas-wrap');
    if (wrap) {
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const scaleX = vw / this.canvasW;
      const scaleY = vh / this.canvasH;
      const scale = Math.min(scaleX, scaleY);
      canvas.style.transform = `scale(${scale})`;
    }

    // Render elements
    canvas.innerHTML = '';
    const page = this.pages[index];
    if (!page) return;

    page.elements.forEach((el) => {
      const node = document.createElement('div');
      node.style.position = 'absolute';
      node.style.left = el.x + 'px';
      node.style.top = el.y + 'px';
      node.style.width = el.width + 'px';
      node.style.height = el.height + 'px';
      node.style.opacity = (el.opacity !== undefined ? el.opacity : 100) / 100;
      node.style.pointerEvents = 'none';
      node.style.boxSizing = 'border-box';

      if (el.shadowLevel > 0) {
        node.style.filter = `drop-shadow(0px ${Math.round(el.shadowLevel / 2)}px ${el.shadowLevel}px rgba(0,0,0,0.5))`;
      }

      if (el.type !== 'shape') {
        node.style.backgroundColor = el.backgroundColor || 'transparent';
        if (el.borderWidth && el.type !== 'table') {
          node.style.border = `${el.borderWidth}px solid ${el.borderColor || 'transparent'}`;
        }
        if (el.borderRadius) node.style.borderRadius = `${el.borderRadius}px`;
      }

      if (el.type === 'text') {
        const inner = document.createElement('div');
        inner.style.fontSize = (el.fontSize || 24) + 'px';
        inner.style.fontFamily = el.fontFamily || 'Inter, sans-serif';
        inner.style.color = el.color || '#000000';
        inner.style.textAlign = el.textAlign || 'left';
        inner.style.width = '100%';
        inner.style.height = '100%';
        inner.style.wordWrap = 'break-word';
        inner.style.overflow = 'hidden';
        inner.style.lineHeight = '1.2';
        if (el.isBold) inner.style.fontWeight = 'bold';
        if (el.isItalic) inner.style.fontStyle = 'italic';
        let decoration = '';
        if (el.isUnderline) decoration += ' underline';
        if (el.isStrikethrough) decoration += ' line-through';
        if (decoration) inner.style.textDecoration = decoration.trim();

        if (el.isList) {
          const ul = document.createElement('ul');
          ul.style.margin = '0';
          ul.style.paddingLeft = '1.2em';
          (el.content || '').split('\n').forEach(line => {
            const li = document.createElement('li');
            li.innerText = line;
            ul.appendChild(li);
          });
          inner.appendChild(ul);
        } else {
          inner.innerText = el.content || '';
        }
        node.appendChild(inner);
      } else if (el.type === 'image') {
        const img = document.createElement('img');
        img.src = el.src;
        img.style.width = '100%';
        img.style.height = '100%';
        img.style.objectFit = 'fill';
        img.style.pointerEvents = 'none';
        node.appendChild(img);
      } else if (el.type === 'icon') {
        node.style.backgroundColor = 'transparent';
        node.style.border = 'none';
        node.innerHTML = el.svgContent || '';
        const svg = node.querySelector('svg');
        if (svg) {
          svg.setAttribute('width', '100%');
          svg.setAttribute('height', '100%');
          svg.style.display = 'block';
          svg.setAttribute('stroke', el.borderColor || '#000000');
          svg.setAttribute('stroke-width', el.borderWidth !== undefined ? el.borderWidth : 2);
          svg.setAttribute('fill', el.backgroundColor === 'transparent' ? 'none' : el.backgroundColor);
        }
      } else if (el.type === 'table') {
        const inner = document.createElement('div');
        inner.style.width = '100%';
        inner.style.height = '100%';
        inner.style.color = el.color || '#000000';
        inner.style.fontSize = (el.fontSize || 16) + 'px';
        inner.style.fontFamily = el.fontFamily || 'Inter, sans-serif';
        const tableMd = el.content || '| Header |\n|---|';
        const rows = tableMd.trim().split('\n').filter(r => r.trim());
        let thtml = '<table style="width:100%;height:100%;border-collapse:collapse;">';
        rows.forEach((row, i) => {
          if (row.match(/^\|[\s-:|]+\|$/)) return;
          const cells = row.split('|').filter(c => c.trim() !== '');
          const tag = i === 0 ? 'th' : 'td';
          thtml += '<tr>' + cells.map(c => `<${tag} style="border:1px solid currentColor;padding:8px;">${c.trim()}</${tag}>`).join('') + '</tr>';
        });
        thtml += '</table>';
        inner.innerHTML = thtml;
        node.appendChild(inner);
      } else if (el.type === 'mermaid') {
        const inner = document.createElement('div');
        inner.className = 'mermaid';
        inner.textContent = el.content || '';
        node.appendChild(inner);
        if (window.mermaid) {
          try { window.mermaid.run({ nodes: [inner] }); } catch (e) { /* ignore */ }
        }
      } else if (el.type === 'shape') {
        node.style.backgroundColor = 'transparent';
        node.style.border = 'none';
        const svgNS = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(svgNS, 'svg');
        svg.setAttribute('width', '100%');
        svg.setAttribute('height', '100%');
        svg.setAttribute('viewBox', `0 0 ${el.width} ${el.height}`);
        const fillC = el.backgroundColor || 'transparent';
        const strokeC = el.borderColor || 'transparent';
        const sw = el.borderWidth || 0;

        let shape;
        const st = el.shapeType || 'rect';
        if (st === 'circle') {
          shape = document.createElementNS(svgNS, 'ellipse');
          shape.setAttribute('cx', el.width / 2);
          shape.setAttribute('cy', el.height / 2);
          shape.setAttribute('rx', el.width / 2 - sw);
          shape.setAttribute('ry', el.height / 2 - sw);
        } else if (st === 'triangle') {
          shape = document.createElementNS(svgNS, 'polygon');
          shape.setAttribute('points', `${el.width / 2},${sw} ${el.width - sw},${el.height - sw} ${sw},${el.height - sw}`);
        } else {
          shape = document.createElementNS(svgNS, 'rect');
          shape.setAttribute('x', sw / 2);
          shape.setAttribute('y', sw / 2);
          shape.setAttribute('width', el.width - sw);
          shape.setAttribute('height', el.height - sw);
          shape.setAttribute('rx', el.borderRadius || 0);
        }
        shape.setAttribute('fill', fillC);
        shape.setAttribute('stroke', strokeC);
        shape.setAttribute('stroke-width', sw);
        svg.appendChild(shape);
        node.appendChild(svg);
      }

      canvas.appendChild(node);
    });

    // Update counter and progress
    if (counter) counter.textContent = `${index + 1} / ${this.pages.length}`;
    if (progressBar) progressBar.style.width = `${((index + 1) / this.pages.length) * 100}%`;
  }

  _playerOnKey(e) {
    if (!this._playerActive) return;
    if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'Enter') {
      e.preventDefault();
      this.playerNavigate(1);
    } else if (e.key === 'ArrowLeft' || e.key === 'Backspace') {
      e.preventDefault();
      this.playerNavigate(-1);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      this.stopPlayer();
    } else if (e.key === 'Home') {
      e.preventDefault();
      this.renderPlayerSlide(0);
    } else if (e.key === 'End') {
      e.preventDefault();
      this.renderPlayerSlide(this.pages.length - 1);
    }
  }

  _playerOnClick(e) {
    if (!this._playerActive) return;
    // Don't navigate if clicking on controls
    const controls = document.getElementById('pt-player-controls');
    if (controls && controls.contains(e.target)) return;

    // Click left half = prev, right half = next
    const rect = e.currentTarget.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    if (clickX < rect.width * 0.3) {
      this.playerNavigate(-1);
    } else {
      this.playerNavigate(1);
    }
  }

  _playerShowControls() {
    const controls = document.getElementById('pt-player-controls');
    if (!controls) return;
    controls.classList.add('visible');

    if (this._playerControlsTimer) clearTimeout(this._playerControlsTimer);
    this._playerControlsTimer = setTimeout(() => {
      if (controls) controls.classList.remove('visible');
    }, 3000);
  }
}

// Backward compatibility
window.PresentationStudio = PresentationStudio;
