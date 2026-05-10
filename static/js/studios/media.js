/**
 * Clawzd — MediaStudio
 * Extracted from app.js for modular architecture.
 * Uses window globals for shared utilities (el, $, $$, toast, escHtml, icon, ICONS).
 */
/* global $, $$, el, toast, escHtml, icon, ICONS, OC */

// ---- Media Studio ----
class MediaStudio {
  constructor() {
    this.active = false;
    this.items = [];        // gallery items from API
    this.filtered = [];     // after filter applied
    this.selected = new Set();
    this.filter = 'all';
    this.type = 'image';    // 'image', 'video', or 'audio'
    this.backend = 'local'; // 'local' or 'api'
    this.generating = false;
    this.lightboxIdx = -1;
    this.referenceImage = null; // for image-to-image
    this.audioSubMode = 'tts'; // 'tts', 'voice_clone', 'music', 'song'
    this.referenceAudio = null; // for voice cloning
    this.templateSubMode = 'business_card'; // 'business_card' or 'cv'
    this._linkedInData = null; // fetched LinkedIn profile data
    this._bind();
  }

  _bind() {
    // Init SVG icons
    $$('.media-icon').forEach(n => {
      if (window.icon && n.dataset.icon) {
        n.innerHTML = window.icon(n.dataset.icon, 16);
        n.style.marginRight = '6px';
        n.style.display = 'inline-flex';
        n.style.alignItems = 'center';
      }
    });

    // Type toggle
    $$('#media-type-toggle .media-type-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        $$('#media-type-toggle .media-type-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.type = btn.dataset.type;
        this._updateFormVisibility();
      });
    });

    // Clear reference image
    const refClear = $('#media-ref-clear');
    if (refClear) refClear.addEventListener('click', () => this.clearReferenceImage());

    // Duration range (video)
    const durationSlider = $('#media-duration');
    if (durationSlider) {
      durationSlider.addEventListener('input', () => {
        $('#media-duration-value').textContent = durationSlider.value + 's';
      });
    }

    // Num images range
    const numImgSlider = $('#media-num-images');
    if (numImgSlider) {
      numImgSlider.addEventListener('input', () => {
        $('#media-num-images-value').textContent = numImgSlider.value;
      });
    }

    // Number of passes (steps) range
    const stepsSlider = $('#media-steps');
    if (stepsSlider) {
      stepsSlider.addEventListener('input', () => {
        $('#media-steps-value').textContent = stepsSlider.value;
      });
    }

    // Backend toggle
    $$('#media-backend-toggle .media-type-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        $$('#media-backend-toggle .media-type-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.backend = btn.dataset.backend;
      });
    });

    // Audio sub-mode toggle
    $$('#media-audio-submode-toggle .media-type-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        $$('#media-audio-submode-toggle .media-type-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.audioSubMode = btn.dataset.submode;
        this._updateFormVisibility();
      });
    });



    // Audio tempo slider
    const tempoSlider = $('#media-tempo');
    if (tempoSlider) {
      tempoSlider.addEventListener('input', () => {
        $('#media-tempo-value').textContent = tempoSlider.value;
      });
    }

    // Audio duration slider
    const audioDurSlider = $('#media-audio-duration');
    if (audioDurSlider) {
      audioDurSlider.addEventListener('input', () => {
        $('#media-audio-duration-value').textContent = audioDurSlider.value + 's';
      });
    }

    // Reference audio upload (voice cloning)
    const audioRefBtn = $('#media-audio-ref-btn');
    const audioRefInput = $('#media-audio-ref-input');
    if (audioRefBtn && audioRefInput) {
      audioRefBtn.addEventListener('click', () => audioRefInput.click());
      audioRefInput.addEventListener('change', async (e) => {
        if (!e.target.files || !e.target.files[0]) return;
        const file = e.target.files[0];
        const formData = new FormData();
        formData.append('file', file);
        try {
          audioRefBtn.classList.add('loading');
          const resp = await fetch('/audio/upload-reference', { method: 'POST', body: formData });
          if (!resp.ok) throw new Error('Upload failed');
          const data = await resp.json();
          this.referenceAudio = data.filename;
          const preview = $('#media-audio-ref-preview');
          const player = $('#media-audio-ref-player');
          if (preview && player) {
            player.src = data.url;
            preview.style.display = 'block';
          }
          toast(ICONS.check(14) + ' Échantillon vocal chargé');
        } catch (err) {
          toast(ICONS.x(14) + ' Upload failed: ' + err.message);
        } finally {
          audioRefBtn.classList.remove('loading');
          audioRefInput.value = '';
        }
      });
    }
    const audioRefClear = $('#media-audio-ref-clear');
    if (audioRefClear) audioRefClear.addEventListener('click', () => {
      this.referenceAudio = null;
      const preview = $('#media-audio-ref-preview');
      if (preview) preview.style.display = 'none';
    });

    // Generate
    const genBtn = $('#media-generate-btn');
    if (genBtn) genBtn.addEventListener('click', () => this.generate());

    // Prompt — Ctrl+Enter shortcut
    const prompt = $('#media-prompt');
    if (prompt) prompt.addEventListener('keydown', e => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); this.generate(); }
    });

    // Upload Image
    const uploadBtn = $('#media-upload-btn');
    const uploadInput = $('#media-upload-input');
    if (uploadBtn && uploadInput) {
      uploadBtn.addEventListener('click', () => uploadInput.click());
      uploadInput.addEventListener('change', async (e) => {
        if (!e.target.files || !e.target.files[0]) return;
        const file = e.target.files[0];
        const formData = new FormData();
        formData.append('file', file);
        try {
          uploadBtn.classList.add('loading');
          const resp = await fetch('/image/upload', {
            method: 'POST',
            body: formData
          });
          if (!resp.ok) throw new Error('Upload failed');
          const data = await resp.json();
          const format = data.filename.split('.').pop().toLowerCase();
          if (['mp4', 'webm', 'gif'].includes(format)) {
            toast((window.icon ? window.icon('check', 14) : '✅') + ' Media imported successfully');
          } else {
            this.setReferenceImage({ filename: data.filename, url: data.url, format });
          }
          this.loadGallery(); // Reload gallery to show the newly uploaded image
        } catch (err) {
          toast(' Upload failed: ' + err.message);
        } finally {
          uploadBtn.classList.remove('loading');
          uploadInput.value = '';
        }
      });
    }

    // Unified Media Tools select
    const toolsSelect = $('#media-tools-select');
    if (toolsSelect) {
      toolsSelect.addEventListener('change', () => {
        const action = toolsSelect.value;
        toolsSelect.value = ''; // Reset to placeholder
        switch (action) {
          case 'convert_gif': this.convertVideo('gif'); break;
          case 'convert_mp4': this.convertVideo('mp4'); break;
          case 'convert_webm': this.convertVideo('webm'); break;
          case 'remove_bg': this.removeBgSelected(); break;
          case 'make_coloring': this.makeColoringSelected(); break;
          case 'download_zip': this.downloadZip(); break;
        }
      });
    }

    // Toolbar
    const selAll = $('#media-select-all');
    if (selAll) selAll.addEventListener('click', () => this.toggleSelectAll());

    const delSel = $('#media-delete-selected');
    if (delSel) delSel.addEventListener('click', () => this.deleteSelected());

    const refresh = $('#media-refresh');
    if (refresh) refresh.addEventListener('click', () => this.loadGallery());

    // Filter tabs
    $$('#media-filters .media-filter-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        $$('#media-filters .media-filter-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.filter = btn.dataset.filter;
        this._applyFilter();
        this.renderGallery();
      });
    });

    // Lightbox
    const lbClose = $('#media-lb-close');
    if (lbClose) lbClose.addEventListener('click', () => this.closeLightbox());
    const lbPrev = $('#media-lb-prev');
    if (lbPrev) lbPrev.addEventListener('click', () => this.lightboxNav(-1));
    const lbNext = $('#media-lb-next');
    if (lbNext) lbNext.addEventListener('click', () => this.lightboxNav(1));
    const lbDl = $('#media-lb-download');
    if (lbDl) lbDl.addEventListener('click', () => this.lightboxDownload());
    const lbDel = $('#media-lb-delete');
    if (lbDel) lbDel.addEventListener('click', () => this.lightboxDelete());
    const lbVar = $('#media-lb-variant');
    if (lbVar) lbVar.addEventListener('click', () => {
      if (this.lightboxIdx >= 0 && this.lightboxIdx < this.filtered.length) {
        this.setReferenceImage(this.filtered[this.lightboxIdx]);
      }
    });

    // Lightbox keyboard nav
    document.addEventListener('keydown', e => {
      const lb = $('#media-lightbox');
      if (lb && lb.classList.contains('open')) {
        if (e.key === 'Escape') this.closeLightbox();
        if (e.key === 'ArrowLeft') this.lightboxNav(-1);
        if (e.key === 'ArrowRight') this.lightboxNav(1);
        if (e.key === 'Delete' || e.key === 'Backspace') {
          if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
            this.lightboxDelete();
          }
        }
        return;
      }

      // Gallery keyboard nav
      if (this.active && (e.key === 'Delete' || e.key === 'Backspace')) {
        if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
          if (this.selected.size > 0) {
            this.deleteSelected();
          }
        }
      }
    });

    // Lightbox backdrop click
    const lb = $('#media-lightbox');
    if (lb) lb.addEventListener('click', e => {
      if (e.target === lb) this.closeLightbox();
    });

    // Lightbox Image-to-Video button
    const lbI2V = $('#media-lb-i2v');
    if (lbI2V) lbI2V.addEventListener('click', () => {
      if (this.lightboxIdx >= 0 && this.lightboxIdx < this.filtered.length) {
        const item = this.filtered[this.lightboxIdx];
        if (!item.isAudio && !item.isVideo && !item.isSvg) {
          this.closeLightbox();
          this.useImageAsVideoSource(item);
        } else {
          toast(ICONS.circle(14) + ' Sélectionnez une image statique (PNG/JPG) pour Image→Vidéo');
        }
      }
    });

    // Remove BG Modal Events
    this._rembgDebounce = null;
    const rmbgModal = $('#media-rembg-modal');
    const rmbgClose = $('#media-rembg-close');
    const rmbgCancel = $('#media-rembg-cancel-btn');
    const rmbgApply = $('#media-rembg-apply-btn');
    const rmbgAlphaCb = $('#rembg-alpha-matting');
    const rmbgAlphaCtrls = $('#rembg-alpha-controls');

    const updatePreview = () => {
      if (this._rembgDebounce) clearTimeout(this._rembgDebounce);
      this._rembgDebounce = setTimeout(() => this._refreshRembgPreview(), 600);
    };

    if (rmbgClose) rmbgClose.addEventListener('click', () => this.closeRembgModal());
    if (rmbgCancel) rmbgCancel.addEventListener('click', () => this.closeRembgModal());
    if (rmbgAlphaCb) rmbgAlphaCb.addEventListener('change', (e) => {
      if (rmbgAlphaCtrls) rmbgAlphaCtrls.style.display = e.target.checked ? 'flex' : 'none';
      updatePreview();
    });

    // Listen for changes on all rembg controls to trigger preview
    ['rembg-model', 'rembg-post-process', 'rembg-fg-thresh', 'rembg-bg-thresh', 'rembg-erode-size'].forEach(id => {
      const el = $(`#${id}`);
      if (el) {
        el.addEventListener('change', updatePreview);
        el.addEventListener('input', updatePreview);
      }
    });

    if (rmbgApply) rmbgApply.addEventListener('click', () => this._applyRembg());
  }

  _updateFormVisibility() {
    const isVideo = this.type === 'video';
    const isAudio = this.type === 'audio';
    const isImage = this.type === 'image';
    const isTemplate = this.type === 'templates';
    const isCard = isTemplate && this.templateSubMode === 'business_card';
    const isCV = isTemplate && this.templateSubMode === 'cv';

    // Image-specific groups
    const imgFmt = $('#media-format-image-group');
    const styleGrp = $('#media-style-group');
    const sizeGrp = $('#media-size-group');
    const countGrp = $('#media-count-group');
    if (imgFmt) imgFmt.style.display = isImage ? '' : 'none';
    if (styleGrp) styleGrp.style.display = isImage ? '' : 'none';
    if (sizeGrp) sizeGrp.style.display = isImage ? '' : 'none';
    if (countGrp) countGrp.style.display = isImage ? '' : 'none';

    // Video-specific groups
    const vidFmt = $('#media-format-video-group');
    const vidMod = $('#media-model-video-group');
    const durationGrp = $('#media-duration-group');
    const vidSizeGrp = $('#media-size-video-group');

    if (vidFmt) vidFmt.style.display = isVideo ? '' : 'none';
    if (vidMod) vidMod.style.display = isVideo ? '' : 'none';
    if (vidSizeGrp) vidSizeGrp.style.display = isVideo ? '' : 'none';
    if (durationGrp) durationGrp.style.display = isVideo ? '' : 'none';

    // Filter video models based on Image-to-Video mode
    const videoModelSel = $('#media-model-video');
    if (videoModelSel && isVideo) {
      const hasRefImage = !!this.referenceImage;
      const i2vModels = ['svd_xt', 'cogvideox', 'wan22']; // Models that support I2V
      let firstAvailable = null;

      Array.from(videoModelSel.options).forEach(opt => {
        if (hasRefImage) {
          // Hide models that don't support I2V
          if (!i2vModels.includes(opt.value)) {
            opt.style.display = 'none';
            opt.disabled = true;
          } else {
            opt.style.display = '';
            opt.disabled = false;
            if (!firstAvailable) firstAvailable = opt.value;
          }
        } else {
          // Show all models
          opt.style.display = '';
          opt.disabled = false;
        }
      });

      // If current selected is disabled, select the first available
      if (videoModelSel.selectedOptions.length === 0 || videoModelSel.selectedOptions[0].disabled) {
        if (firstAvailable) videoModelSel.value = firstAvailable;
      }
    }

    // Shared prompt & neg prompt — show for image/video only
    const promptGrp = $('#media-prompt')?.closest('.media-form-group');
    const negGrp = $('#media-neg-prompt')?.closest('.media-form-group');
    if (promptGrp) promptGrp.style.display = (isAudio || isTemplate) ? 'none' : '';
    if (negGrp) negGrp.style.display = (isAudio || isTemplate) ? 'none' : '';

    // Upload / reference image — show for image/video only
    const uploadGrp = $('#media-upload-group');
    if (uploadGrp) uploadGrp.style.display = (isAudio || isTemplate) ? 'none' : 'flex';

    // Update upload button label
    const uploadLabel = uploadGrp?.querySelector('#media-upload-btn');
    if (uploadLabel) {
      const iconHtml = uploadLabel.querySelector('.media-icon')?.outerHTML || '';
      uploadLabel.innerHTML = iconHtml + (isVideo ? ' Import Media (Image/Video)' : ' Import Media');
    }

    // Reference image block
    const refGrp = $('#media-ref-group');
    if (refGrp) {
      if (this.referenceImage && !isAudio) {
        refGrp.style.display = '';
        const refLabel = refGrp.querySelector('.media-form-label');
        if (refLabel) refLabel.textContent = isVideo ? 'Source Image (Image→Video)' : 'Reference Image (Variation)';
        const strengthRow = $('#media-ref-strength-row');
        const strengthHint = $('#media-ref-strength-hint');
        if (strengthRow) strengthRow.style.display = isVideo ? 'none' : '';
        if (strengthHint) strengthHint.style.display = isVideo ? 'none' : '';
      } else {
        refGrp.style.display = 'none';
      }
    }

    // Enhance checkbox — hide for audio/templates
    const enhanceGrp = $('#media-enhance')?.closest('.media-form-group');
    if (enhanceGrp) enhanceGrp.style.display = (isAudio || isTemplate) ? 'none' : '';

    // Backend toggle — hide for audio/templates (always local)
    const backendGrp = $('#media-backend-toggle')?.closest('.media-form-group');
    if (backendGrp) backendGrp.style.display = (isAudio || isTemplate) ? 'none' : '';



    // ---- Audio-specific groups ----
    const sub = this.audioSubMode;
    const isTTS = sub === 'tts';
    const isClone = sub === 'voice_clone';
    const isMusic = sub === 'music';
    const isSong = sub === 'song';

    const audioSubGrp = $('#media-audio-submode-group');
    const audioTextGrp = $('#media-audio-text-group');
    const voiceGrp = $('#media-voice-style-group');
    const ttsEngGrp = $('#media-tts-engine-group');
    const audioRefGrp = $('#media-audio-ref-group');
    const genreGrp = $('#media-genre-group');
    const tempoGrp = $('#media-tempo-group');
    const langGrp = $('#media-language-group');
    const audioDurGrp = $('#media-audio-duration-group');
    const audioFmtGrp = $('#media-format-audio-group');

    if (audioSubGrp) audioSubGrp.style.display = isAudio ? '' : 'none';
    if (audioTextGrp) audioTextGrp.style.display = isAudio && (isTTS || isClone || isSong) ? '' : 'none';
    if (voiceGrp) voiceGrp.style.display = isAudio && (isTTS || isSong) ? '' : 'none';
    if (ttsEngGrp) ttsEngGrp.style.display = isAudio && isTTS ? '' : 'none';
    if (audioRefGrp) audioRefGrp.style.display = isAudio && isClone ? '' : 'none';
    if (genreGrp) genreGrp.style.display = isAudio && (isMusic || isSong) ? '' : 'none';
    if (tempoGrp) tempoGrp.style.display = isAudio && (isMusic || isSong) ? '' : 'none';
    if (langGrp) langGrp.style.display = isAudio && (isTTS || isClone || isSong) ? '' : 'none';
    if (audioDurGrp) audioDurGrp.style.display = isAudio ? '' : 'none';
    if (audioFmtGrp) audioFmtGrp.style.display = isAudio ? '' : 'none';

    // Update audio duration slider max based on sub-mode
    const audioDurSlider = $('#media-audio-duration');
    if (audioDurSlider && isAudio) {
      audioDurSlider.max = (isMusic || isSong) ? '120' : '300';
      if (parseInt(audioDurSlider.value) > parseInt(audioDurSlider.max)) {
        audioDurSlider.value = audioDurSlider.max;
        $('#media-audio-duration-value').textContent = audioDurSlider.value + 's';
      }
    }

    // Update text placeholder based on sub-mode
    const audioText = $('#media-audio-text');
    if (audioText && isAudio) {
      if (isTTS) audioText.placeholder = 'Entrez le texte à convertir en parole...';
      else if (isClone) audioText.placeholder = 'Texte à dire avec la voix clonée...';
      else if (isSong) audioText.placeholder = 'Paroles ou thème de la chanson...';
    }
  }

  setReferenceImage(item) {
    if (item.format === 'mp4' || item.format === 'gif' || item.format === 'svg') {
      toast(ICONS.circle(14) + ' ️ Please select a raster image (PNG/JPG) for variation');
      return;
    }
    this.referenceImage = item.filename;
    const refGrp = $('#media-ref-group');
    const preview = $('#media-ref-preview');
    if (refGrp && preview) {
      preview.src = item.url;
      refGrp.style.display = '';
      toast(ICONS.circle(14) + ' Reference image loaded');
    }
    this._updateFormVisibility();
    this.closeLightbox();
  }

  clearReferenceImage() {
    this.referenceImage = null;
    const refGrp = $('#media-ref-group');
    if (refGrp) refGrp.style.display = 'none';
    this._updateFormVisibility();
  }


  toggle(on) {
    this.active = on;
    const mediaLayout = $('#media-layout');
    if (on) {
      mediaLayout.classList.add('active');
      this.loadGallery();
      // Check for running background tasks
      this._checkActiveTasks();
    } else {
      mediaLayout.classList.remove('active');
    }
  }

  async _checkActiveTasks() {
    if (this.generating) return; // Already tracking
    try {
      const resp = await fetch('/api/tasks/active');
      if (!resp.ok) return;
      const data = await resp.json();
      const mediaTasks = (data.tasks || []).filter(t =>
        t.type === 'image' || t.type === 'video' || t.type === 'audio'
      );
      if (mediaTasks.length > 0) {
        // Verify the task is actually still running before resuming
        const endpoint = mediaTasks[0].type === 'audio' ? '/audio/generation-progress' : '/image/generation-progress';
        try {
          const pr = await fetch(endpoint);
          if (pr.ok) {
            const pg = await pr.json();
            if (!pg.active) {
              // Task is registered but generation already finished — just reload gallery
              this.loadGallery();
              return;
            }
          }
        } catch (_) { /* proceed to resume */ }
        this._resumeFromTask(mediaTasks[0]);
      }
    } catch (e) { /* ignore */ }
  }

  _resumeFromTask(task) {
    if (this.generating) return;
    this.generating = true;
    this._resumeFinished = false; // reentry guard
    const genBtn = $('#media-generate-btn');
    const progress = $('#media-progress');
    const progressBar = $('#media-progress-bar');
    const cancelBtn = $('#media-cancel-btn');

    if (genBtn) {
      genBtn.classList.add('loading');
      genBtn.disabled = true;
      const lbl = genBtn.querySelector('.gen-label');
      if (lbl) lbl.textContent = `Resuming ${task.type}...`;
    }
    if (progress) progress.classList.add('active', 'indeterminate');
    if (cancelBtn) cancelBtn.style.display = 'inline-flex';

    // Poll generation progress
    this._genProgressPoll = setInterval(async () => {
      // Guard: don't fire if already finishing or not generating
      if (this._resumeFinished || !this.generating) return;
      try {
        // Check if the task is still active
        const tResp = await fetch(`/api/tasks/${task.id}`);
        if (tResp.ok) {
          const tData = await tResp.json();
          if (!tData.active) {
            // Task completed — stop tracking and reload gallery
            this._finishResumedTask();
            return;
          }
        }

        // Check generation progress
        const endpoint = task.type === 'audio' ? '/audio/generation-progress' : '/image/generation-progress';
        const pr = await fetch(endpoint);
        if (pr.ok) {
          const pg = await pr.json();
          if (pg.active && genBtn) {
            const lbl = genBtn.querySelector('.gen-label');
            const pct = Math.round(pg.progress);
            if (lbl) lbl.textContent = `Generating... ${pct}%`;
            if (progressBar) {
              progress.classList.remove('indeterminate');
              progressBar.style.width = pct + '%';
            }
          } else if (!pg.active) {
            this._finishResumedTask();
          }
        }
      } catch (_) { /* ignore poll errors */ }
    }, 1000);

    // Set up cancel button for the resumed task
    if (cancelBtn) {
      cancelBtn.onclick = async () => {
        try {
          await fetch(`/api/tasks/${task.id}/stop`, { method: 'POST' });
          if (window.toast) toast((window.icon ? window.icon('x', 14) : '❌') + ' Generation cancelled');
        } catch (_) {}
        this._finishResumedTask();
      };
    }
  }

  _finishResumedTask() {
    // Reentry guard — prevent multiple simultaneous calls
    if (this._resumeFinished) return;
    this._resumeFinished = true;

    if (this._genProgressPoll) {
      clearInterval(this._genProgressPoll);
      this._genProgressPoll = null;
    }
    this.generating = false;
    const genBtn = $('#media-generate-btn');
    const progress = $('#media-progress');
    const progressBar = $('#media-progress-bar');
    const cancelBtn = $('#media-cancel-btn');

    if (cancelBtn) cancelBtn.style.display = 'none';
    if (genBtn) {
      genBtn.classList.remove('loading');
      genBtn.disabled = false;
      const lbl = genBtn.querySelector('.gen-label');
      if (lbl) lbl.innerHTML = `<span class="media-icon" data-icon="sparkles"></span> Generate`;
    }
    if (progress) progress.classList.remove('active', 'indeterminate');
    if (progressBar) progressBar.style.width = '0%';
    // Reload gallery once to show the new result
    this.loadGallery();
    if (window.taskIndicator) window.taskIndicator.refresh();
  }

  async loadGallery() {
    try {
      const r = await fetch('/image/gallery', { cache: 'no-store' });
      const d = await r.json();
      this.items = (d.images || []).map(img => ({
        filename: img.filename,
        format: img.format,
        prompt: img.prompt || '',
        url: `/data/images/${img.filename}`,
        isVideo: ['gif', 'mp4'].includes(img.format),
        isSvg: img.format === 'svg',
        isAudio: false,
      }));

      // Also fetch audio files
      try {
        const ar = await fetch('/audio/gallery', { cache: 'no-store' });
        const ad = await ar.json();
        const audioItems = (ad.audio_files || []).map(af => ({
          filename: af.filename,
          format: af.format,
          prompt: af.prompt || '',
          url: `/data/audio/${af.filename}`,
          isVideo: false,
          isSvg: false,
          isAudio: true,
          mode: af.mode || 'unknown',
          duration: af.duration || 0,
        }));
        this.items = [...this.items, ...audioItems];
      } catch (e) { /* audio gallery optional */ }

      this._applyFilter();
      this.renderGallery();
    } catch (e) {
      console.error('Gallery load failed:', e);
      toast(ICONS.x(14) + ' Failed to load gallery');
    }
  }

  _applyFilter() {
    if (this.filter === 'all') {
      this.filtered = [...this.items];
    } else if (this.filter === 'image') {
      this.filtered = this.items.filter(i => !i.isVideo && !i.isSvg && !i.isAudio);
    } else if (this.filter === 'video') {
      this.filtered = this.items.filter(i => i.isVideo);
    } else if (this.filter === 'svg') {
      this.filtered = this.items.filter(i => i.isSvg);
    } else if (this.filter === 'audio') {
      this.filtered = this.items.filter(i => i.isAudio);
    } else if (this.filter === 'templates') {
      this.filtered = this.items.filter(i => i.filename.startsWith('card_') || i.filename.startsWith('cv_'));
    }
  }

  renderGallery() {
    const container = $('#media-gallery');
    if (!container) return;
    container.innerHTML = '';
    container.classList.remove('empty-state');

    // Update count
    const countEl = $('#media-count');
    if (countEl) countEl.textContent = `${this.filtered.length} item${this.filtered.length !== 1 ? 's' : ''}`;

    if (!this.filtered.length) {
      container.classList.add('empty-state');
      container.innerHTML = `
        <div class="media-empty">
          <div class="media-empty-icon">${window.icon ? window.icon('palette', 32) : ''}</div>
          <h3>No media yet</h3>
          <p>Use the sidebar to generate images and videos. They will appear here in your gallery.</p>
        </div>`;
      return;
    }

    const inner = el('div', { class: 'media-gallery-inner' });

    this.filtered.forEach((item, idx) => {
      const card = el('div', {
        class: 'media-card' + (this.selected.has(item.filename) ? ' selected' : ''),
        'data-filename': item.filename,
      });

      // Extract style from prompt if present
      let displayPrompt = item.prompt || '';
      let styleBadgeHTML = '';
      const styleMatch = displayPrompt.match(/^\[(.*?)\]\s+(.*)/s);
      if (styleMatch) {
        let styleName = styleMatch[1];
        if (styleName === 'none') styleName = 'Z-Image Turbo';
        displayPrompt = styleMatch[2];
        styleBadgeHTML = `<span class="badge" style="background:var(--accent);color:white;font-size:10px;margin-right:6px;padding:2px 6px;border-radius:4px;white-space:nowrap;display:inline-block;">${escHtml(styleName)}</span>`;
      }

      // Content (image, video, or audio)
      if (item.isAudio) {
        card.classList.add('media-card-audio');

        // Determine mode label for badge
        let modeLabel = 'Audio';
        let modeBadgeClass = 'audio-mode-default';
        if (item.mode === 'tts') { modeLabel = 'TTS'; modeBadgeClass = 'audio-mode-tts'; }
        else if (item.mode === 'voice_clone') { modeLabel = 'Clone'; modeBadgeClass = 'audio-mode-clone'; }
        else if (item.mode === 'song') { modeLabel = 'Song'; modeBadgeClass = 'audio-mode-song'; }
        else if (item.mode === 'music') { modeLabel = 'Music'; modeBadgeClass = 'audio-mode-music'; }

        let promptHtml = '';
        if (displayPrompt) {
          promptHtml = `<div class="media-audio-prompt">${styleBadgeHTML}${escHtml(displayPrompt)}</div>`;
        }

        card.innerHTML += `
          <div class="media-audio-header">
            <div class="media-audio-badge-row">
              <span class="media-audio-format-badge ${item.format}">${item.format.toUpperCase()}</span>
              <span class="media-audio-mode-badge ${modeBadgeClass}">${modeLabel}</span>
            </div>
            ${item.duration ? `<span class="media-audio-duration-badge">${Math.round(item.duration)}s</span>` : `<span class="media-audio-duration-badge dyn-duration">--s</span>`}
          </div>
          <div class="media-audio-card-inner">
            <div class="media-audio-visual">
              <div class="media-audio-icon-wrap">${window.icon ? window.icon('music', 28) : '🎵'}</div>
              <button class="media-audio-play-btn" title="Play/Pause">${window.icon ? window.icon('play', 20) : '▶'}</button>
            </div>
            <div class="media-audio-info">
              <div class="media-audio-name" title="${escHtml(item.filename)}">${escHtml(item.filename)}</div>
              ${promptHtml}
            </div>
          </div>
          <audio class="media-audio-el" src="${item.url}" preload="metadata"></audio>`;
        const playBtn = card.querySelector('.media-audio-play-btn');
        const audioEl = card.querySelector('.media-audio-el');
        const dynDur = card.querySelector('.dyn-duration');
        if (audioEl) {
          if (dynDur) {
            audioEl.addEventListener('loadedmetadata', () => {
              if (audioEl.duration && audioEl.duration !== Infinity) {
                dynDur.textContent = Math.round(audioEl.duration) + 's';
                dynDur.classList.remove('dyn-duration');
              }
            });
          }
        }
        if (playBtn && audioEl) {
          playBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (audioEl.paused) {
              // Stop all other playing audio
              $$('.media-audio-el').forEach(a => { if (a !== audioEl) { a.pause(); a.currentTime = 0; } });
              $$('.media-audio-play-btn').forEach(b => {
                b.innerHTML = window.icon ? window.icon('play', 20) : '▶';
                b.classList.remove('playing');
              });
              audioEl.play();
              playBtn.innerHTML = ICONS.pause ? ICONS.pause(20) : '⏸';
              playBtn.classList.add('playing');
            } else {
              audioEl.pause();
              playBtn.innerHTML = window.icon ? window.icon('play', 20) : '▶';
              playBtn.classList.remove('playing');
            }
          });
          audioEl.addEventListener('ended', () => {
            playBtn.innerHTML = window.icon ? window.icon('play', 20) : '▶';
            playBtn.classList.remove('playing');
          });
        }
      } else if (item.isVideo && item.format === 'mp4') {
        const vid = el('video', { src: item.url, muted: 'true', loop: 'true', preload: 'metadata' });
        vid.addEventListener('mouseenter', () => vid.play());
        vid.addEventListener('mouseleave', () => { vid.pause(); vid.currentTime = 0; });
        card.appendChild(vid);
        // Play icon
        card.insertAdjacentHTML('beforeend', `<div class="media-card-play"><div class="media-card-play-icon">${window.icon ? window.icon('play', 24) : '►'}</div></div>`);
      } else if (item.isVideo && item.format === 'gif') {
        card.appendChild(el('img', { class: 'media-card-img', src: item.url, alt: item.filename, loading: 'lazy' }));
      } else {
        const img = el('img', { class: 'media-card-img', src: item.url, alt: item.filename, loading: 'lazy' });
        if (item.isSvg || item.format === 'transparent_png') {
          img.classList.add('is-transparent');
        }
        card.appendChild(img);
      }

      // Badge for special formats (Images/Video only — audio has its own badges)
      if (!item.isAudio && ['gif', 'mp4', 'svg'].includes(item.format)) {
        card.insertAdjacentHTML('beforeend', `<div class="media-card-badge ${item.format}">${item.format.toUpperCase()}</div>`);
      }

      // Select checkbox
      const selectDiv = el('div', {
        class: 'media-card-select',
        html: this.selected.has(item.filename) ? ICONS.check(14) : '',
        onclick: (e) => { e.stopPropagation(); this.toggleSelect(item.filename); },
      });
      card.appendChild(selectDiv);

      // Hover overlay (ONLY for images/video)
      if (!item.isAudio) {
        const overlay = el('div', { class: 'media-card-overlay' });
        overlay.innerHTML = `
          <div class="media-card-name" title="${escHtml(item.prompt)}">${escHtml(item.filename)}</div>
          <div class="media-card-meta">${item.format.toUpperCase()}</div>
          <div class="media-card-prompt" style="font-size: 0.7em; margin-top: 5px; opacity: 0.8; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis;" title="${escHtml(item.prompt)}">${styleBadgeHTML}${escHtml(displayPrompt)}</div>`;
        card.appendChild(overlay);
      }

      // Action buttons — determine if image is static (can be converted to video)
      const isStaticImage = !item.isAudio && !item.isVideo && !item.isSvg;
      const actions = el('div', { class: 'media-card-actions' });
      actions.innerHTML = `
        ${isStaticImage ? `<button class="media-card-action-btn" title="Create Variation (Image-to-Image)" data-action="variant">${window.icon ? window.icon('wand', 16) : ''}</button>` : ''}
        ${isStaticImage ? `<button class="media-card-action-btn i2v" title="Générer une vidéo depuis cette image" data-action="i2v">${window.icon ? window.icon('video', 16) : '🎬'}</button>` : ''}
        <button class="media-card-action-btn" title="Download" data-action="download">${window.icon ? window.icon('download', 16) : ''}</button>
        <button class="media-card-action-btn delete" title="Delete" data-action="delete">${window.icon ? window.icon('trash', 16) : ''}</button>`;
      actions.addEventListener('click', e => {
        e.stopPropagation();
        const btn = e.target.closest('[data-action]');
        if (!btn) return;
        if (btn.dataset.action === 'variant') this.setReferenceImage(item);
        if (btn.dataset.action === 'i2v') this.useImageAsVideoSource(item);
        if (btn.dataset.action === 'download') this.downloadFile(item.filename, item.url);
        if (btn.dataset.action === 'delete') {
          if (this.selected.has(item.filename) && this.selected.size > 1) {
            this.deleteSelected();
          } else {
            this.deleteFile(item.filename);
          }
        }
      });
      card.appendChild(actions);

      // Click → lightbox
      card.addEventListener('click', () => this.openLightbox(idx));

      inner.appendChild(card);
    });
    container.appendChild(inner);

    this._updateToolbar();
  }

  toggleSelect(filename) {
    if (this.selected.has(filename)) this.selected.delete(filename);
    else this.selected.add(filename);
    // Update card UI
    const cards = $$('.media-card');
    cards.forEach(c => {
      const fn = c.dataset.filename;
      c.classList.toggle('selected', this.selected.has(fn));
      const sel = c.querySelector('.media-card-select');
      if (sel) sel.innerHTML = this.selected.has(fn) ? ICONS.check(14) : '';
    });
    this._updateToolbar();
  }

  toggleSelectAll() {
    if (this.selected.size === this.filtered.length) {
      // Deselect all
      this.selected.clear();
    } else {
      // Select all
      this.filtered.forEach(i => this.selected.add(i.filename));
    }
    this.renderGallery();
  }

  _updateToolbar() {
    const cnt = this.selected.size;
    const delBtn = $('#media-delete-selected');
    const cntBadge = $('#media-selected-count');
    const selAllBtn = $('#media-select-all');
    if (delBtn) delBtn.style.display = cnt > 0 ? '' : 'none';
    if (cntBadge) cntBadge.textContent = cnt;
    if (selAllBtn) selAllBtn.innerHTML = cnt === this.filtered.length && cnt > 0 ? ICONS.square(14) + ' Deselect' : ICONS.checkSquare(14) + ' Select All';
  }

  async generate() {
    if (this.generating) return;
    // Delegate to template generator
    if (this.type === 'templates') { return this.generateTemplate(); }
    const prompt = $('#media-prompt');
    if (this.type === 'audio') {
      const audioText = ($('#media-audio-text') || {}).value || '';
      if (this.audioSubMode !== 'music' && !audioText.trim()) { toast(ICONS.circle(14) + ' Veuillez entrer du texte'); return; }
    } else if (!prompt || !prompt.value.trim()) { toast(ICONS.circle(14) + ' ️ Please enter a prompt'); return; }

    this.generating = true;
    const genBtn = $('#media-generate-btn');
    const cancelBtn = $('#media-cancel-btn');
    const progress = $('#media-progress');
    const progressBar = $('#media-progress-bar');
    if (genBtn) genBtn.classList.add('loading');
    if (genBtn) genBtn.disabled = true;

    this._abortController = new AbortController();
    if (cancelBtn) {
      cancelBtn.style.display = 'flex';
      cancelBtn.onclick = () => {
        if (this._abortController) {
          this._abortController.abort();
          this._abortController = null;
        }
      };
    }

    const negPrompt = ($('#media-neg-prompt') || {}).value || '';
    const enhance = $('#media-enhance') ? $('#media-enhance').checked : true;
    const numImages = this.type === 'image'
      ? Math.max(1, Math.min(50, parseInt(($('#media-num-images') || {}).value) || 1))
      : 1;

    // Show progress
    if (progress) {
      progress.classList.add('active');
      if (numImages <= 1) {
        progress.classList.add('indeterminate');
      } else {
        progress.classList.remove('indeterminate');
        if (progressBar) progressBar.style.width = '0%';
      }
    }

    let successCount = 0;
    let lastError = '';

    try {
      // --- Model Download Check ---
      const dlMsg = $('#media-download-msg');
      if (this.backend !== 'api') {
        try {
          const style = ($('#media-style') || {}).value || 'none';
          const videoModel = ($('#media-model-video') || {}).value || 'cogvideox';
          const checkResp = await fetch(`/image/check-model?type=${this.type}&style=${style}&video_model=${videoModel}`);
          if (checkResp.ok) {
            const checkData = await checkResp.json();
            if (!checkData.downloaded) {
              if (dlMsg) {
                dlMsg.style.display = 'block';
                dlMsg.innerHTML = ICONS.hourglass(14) + ' Initializing model download...';
              }
              toast('⏳ First time using this AI. Downloading model weights (~5-10GB), this may take a few minutes...', 8000);
            }
          }
        } catch (e) { /* ignore check error */ }
        
        // Always start the download progress poll just in case a partial download needs to complete
        this._hfDlPoll = setInterval(async () => {
          try {
            const statusResp = await fetch('/image/download-status');
            if (statusResp.ok) {
              const sd = await statusResp.json();
              if (sd.active && dlMsg) {
                dlMsg.style.display = 'block';
                dlMsg.innerHTML = ICONS.hourglass(14) + ` Downloading ${sd.repo}... (${Math.round(sd.progress)}%)`;
              } else if (!sd.active && dlMsg && dlMsg.style.display === 'block' && dlMsg.innerHTML.includes('Downloading')) {
                // Hide it if download finished but generation hasn't started yet
                dlMsg.style.display = 'none';
              }
            }
          } catch (e) { }
        }, 2000);
      }

      let stylesToRun = ['none'];
      const baseStyle = ($('#media-style') || {}).value || 'none';
      let isAllModels = false;

      if (this.type === 'image') {
        if (baseStyle === 'all_models') {
          isAllModels = true;
          const selectEl = document.getElementById('media-style');
          if (selectEl) {
            stylesToRun = Array.from(selectEl.options)
              .map(o => o.value)
              .filter(v => v !== 'all_models' && v !== 'none');
          }
        } else {
          stylesToRun = [baseStyle];
        }
      }

      let totalRuns = (this.type === 'image' && isAllModels) ? stylesToRun.length : numImages;

      for (let i = 0; i < totalRuns; i++) {
        // Update progress for multi-image
        if (totalRuns > 1) {
          const pct = Math.round(((i) / totalRuns) * 100);
          if (progressBar) progressBar.style.width = pct + '%';
          toast(`${ICONS.palette(14)} Generating ${i + 1}/${totalRuns}...`);
        }

        let resp;
        let result = {};
        if (this.type === 'image') {
          const format = ($('#media-format-image') || {}).value || 'auto';
          const currentStyle = isAllModels ? stylesToRun[i] : baseStyle;
          const sizeVal = ($('#media-size') || {}).value || '1024x1024';
          const [width, height] = sizeVal.split('x').map(Number);
          const stepsVal = parseInt(($('#media-steps') || {}).value) || 4;

          resp = await fetch('/image/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: this._abortController ? this._abortController.signal : undefined,
            body: JSON.stringify({
              prompt: prompt.value.trim(),
              negative_prompt: negPrompt,
              format, style: currentStyle, enhance_prompt: enhance,
              backend: this.backend,
              reference_image: this.referenceImage,
              strength: parseFloat(($('#media-ref-strength') || {}).value) || 0.5,
              width: width || 1024,
              height: height || 1024,
              steps: stepsVal,
              stream: true // Enable SSE stream preview
            }),
          });

          if (resp.headers.get('content-type')?.includes('text/event-stream')) {
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            while (true) {
              const { done, value } = await reader.read();
              if (done) break;
              buffer += decoder.decode(value, { stream: true });
              let lines = buffer.split('\n');
              buffer = lines.pop(); // keep incomplete line
              for (let line of lines) {
                if (line.startsWith('data: ')) {
                  try {
                    const d = JSON.parse(line.substring(6));
                    if (d.status === 'generating') {
                      if (d.base64) {
                        const prevCont = document.getElementById('media-stream-preview-container');
                        const prevImg = document.getElementById('media-stream-preview');
                        if (prevCont && prevImg) {
                          prevCont.style.display = 'block';
                          prevImg.src = 'data:image/jpeg;base64,' + d.base64;
                        }
                      }
                      if (d.progress !== undefined && genBtn) {
                        const lbl = genBtn.querySelector('.gen-label');
                        const pct = Math.round(d.progress);
                        if (lbl) lbl.textContent = `Generating... ${pct}%`;
                        if (progressBar) {
                          progress.classList.remove('indeterminate');
                          progressBar.style.width = pct + '%';
                        }
                      }
                    } else if (d.status === 'done') {
                      result = d.result;
                    } else if (d.status === 'error') {
                      result = { error: d.message };
                    }
                  } catch (e) { }
                }
              }
            }
          } else {
            result = await resp.json();
          }
        } else if (this.type === 'video') {
          const format = ($('#media-format-video') || {}).value || 'gif';
          const videoModel = ($('#media-model-video') || {}).value || 'cogvideox';
          const duration = parseFloat(($('#media-duration') || {}).value) || 2.0;
          const videoSize = ($('#media-size-video') || {}).value || '704x480';
          const [vidW, vidH] = videoSize.split('x').map(Number);

          // Warn if reference image is set but model doesn't support I2V
          const i2vModels = ['svd_xt', 'cogvideox', 'wan22'];
          if (this.referenceImage && !i2vModels.includes(videoModel)) {
            toast(`⚠️ Model ${videoModel} does not support Image→Video. The image will be ignored. Use CogVideoX 5B or Wan 14B.`, 6000);
          }

          resp = await fetch('/image/animate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: this._abortController ? this._abortController.signal : undefined,
            body: JSON.stringify({
              prompt: prompt.value.trim(),
              negative_prompt: negPrompt,
              format, duration,
              width: vidW,
              height: vidH,
              video_model: videoModel,
              enhance_prompt: enhance,
              backend: this.backend,
              reference_image: this.referenceImage,
            }),
          });

          // Read SSE stream (keepalive + progress + result)
          if (resp.headers.get('content-type')?.includes('text/event-stream')) {
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            while (true) {
              const { done, value } = await reader.read();
              if (done) break;
              buffer += decoder.decode(value, { stream: true });
              let lines = buffer.split('\n');
              buffer = lines.pop();
              for (let line of lines) {
                if (line.startsWith('data: ')) {
                  try {
                    const d = JSON.parse(line.substring(6));
                    if (d.status === 'progress') {
                      if (genBtn) {
                        const lbl = genBtn.querySelector('.gen-label');
                        const pct = Math.round(d.progress);
                        const stage = d.stage === 'encoding' ? 'Encoding...' : `Generating... ${pct}%`;
                        if (lbl) lbl.textContent = stage;
                        if (progressBar) {
                          progress.classList.remove('indeterminate');
                          progressBar.style.width = pct + '%';
                        }
                      }
                    } else if (d.status === 'done') {
                      result = d.result;
                    } else if (d.status === 'error') {
                      result = { error: d.message };
                    }
                  } catch (_) { }
                }
                // SSE comments (": keepalive") are silently ignored
              }
            }
          } else {
            result = await resp.json();
          }
        } else if (this.type === 'audio') {
          const audioText = ($('#media-audio-text') || {}).value || '';
          const audioFmt = ($('#media-format-audio') || {}).value || 'wav';
          const voiceStyle = ($('#media-voice-style') || {}).value || 'female_soft';
          const ttsEngine = ($('#media-tts-engine') || {}).value || 'speecht5';
          const genre = ($('#media-genre') || {}).value || '';
          const tempoBpm = parseInt(($('#media-tempo') || {}).value) || 120;
          const audioDur = parseFloat(($('#media-audio-duration') || {}).value) || 30;
          const language = ($('#media-language') || {}).value || 'auto';
          // Start progress polling for audio generation
          this._genProgressPoll = setInterval(async () => {
            try {
              const pr = await fetch('/audio/generation-progress');
              if (pr.ok) {
                const pg = await pr.json();
                if (pg.active && genBtn) {
                  const lbl = genBtn.querySelector('.gen-label');
                  const pct = Math.round(pg.progress);
                  const stage = pg.stage === 'saving' ? 'Saving...' : `Generating... ${pct}%`;
                  if (lbl) lbl.textContent = stage;
                  if (progressBar) {
                    progress.classList.remove('indeterminate');
                    progressBar.style.width = pct + '%';
                  }
                }
              }
            } catch (_) { /* ignore poll errors */ }
          }, 1000);

          resp = await fetch('/audio/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: this._abortController ? this._abortController.signal : undefined,
            body: JSON.stringify({
              mode: this.audioSubMode,
              text: audioText,
              prompt: audioText,
              voice_style: voiceStyle,
              tts_engine: ttsEngine,
              reference_audio: this.referenceAudio,
              genre, tempo_bpm: tempoBpm,
              duration: audioDur,
              format: audioFmt,
              language,
              enhance_prompt: enhance,
            }),
          });
          result = await resp.json();
        }

        if (result && (result.error || result.detail)) {
          lastError = result.error || result.detail;
        } else if (result && result.status === 'ok') {
          successCount++;
          if (result.prompt) {
            if (this.type === 'audio') {
              const a = document.getElementById("media-audio-text");
              if (a && a.value !== result.prompt) a.value = result.prompt;
            } else if (prompt && prompt.value !== result.prompt) {
              prompt.value = result.prompt;
            }
          }
        }
      }

      // Final progress
      if (progressBar) progressBar.style.width = '100%';

      // Always reload gallery after generation (even on partial success)
      await this.loadGallery();

      // Scroll gallery to top to show the new image
      const galleryEl = $('#media-gallery');
      if (galleryEl) galleryEl.scrollTop = 0;
      const mediaMain = document.querySelector('.media-main');
      if (mediaMain) mediaMain.scrollTop = 0;

      if (successCount > 0) {
        toast(`${ICONS.check(14)} Generated ${successCount}/${totalRuns} image${successCount !== 1 ? 's' : ''}`);
      }
      if (lastError && successCount < totalRuns) {
        toast(' ' + lastError);
      }
    } catch (e) {
      if (e.name === 'AbortError') {
        toast((window.icon ? window.icon('x', 14) : '❌') + ' Génération annulée');
      } else {
        toast(' Generation failed: ' + e.message);
      }
    } finally {
      if (this._genProgressPoll) {
        clearInterval(this._genProgressPoll);
        this._genProgressPoll = null;
      }
      if (this._hfDlPoll) {
        clearInterval(this._hfDlPoll);
        this._hfDlPoll = null;
      }
      this.generating = false;
      this._abortController = null;
      const cancelBtn = $('#media-cancel-btn');
      if (cancelBtn) cancelBtn.style.display = 'none';
      if (genBtn) {
        genBtn.classList.remove('loading');
        genBtn.disabled = false;
        const lbl = genBtn.querySelector('.gen-label');
        if (lbl) lbl.innerHTML = `<span class="media-icon" data-icon="sparkles"></span> Generate`;
      }
      if (progress) progress.classList.remove('active', 'indeterminate');
      if (progressBar) progressBar.style.width = '0%';
      const dlMsg = $('#media-download-msg');
      if (dlMsg) {
        dlMsg.style.display = 'none';
        dlMsg.innerHTML = ICONS.hourglass(14) + ' Downloading model weights (~5-10GB). Please wait, this may take a few minutes...';
      }
      const prevCont = document.getElementById('media-stream-preview-container');
      if (prevCont) {
        prevCont.style.display = 'none';
      }
    }
  }

  async deleteFile(filename) {
    try {
      toast(' Deleting ' + filename + '...');
      const isAudioFile = filename.match(/\.(wav|mp3|ogg)$/i);
      const r = await fetch(isAudioFile ? '/audio/delete' : '/image/delete', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename }),
      });
      if (!r.ok) throw new Error('Server returned ' + r.status);
      this.selected.delete(filename);
      toast(' Deleted ' + filename);
      await this.loadGallery();
    } catch (e) { toast(' Delete failed: ' + e.message); }
  }

  async deleteSelected() {
    const files = [...this.selected];
    if (!files.length) return;
    try {
      toast(`${ICONS.circle(14)} Deleting ${files.length} file(s)...`);
      // Separate audio and image files
      const audioFiles = files.filter(f => f.match(/\.(wav|mp3|ogg)$/i));
      const imageFiles = files.filter(f => !f.match(/\.(wav|mp3|ogg)$/i));
      let deletedCount = 0;
      // Delete image/video files via batch endpoint
      if (imageFiles.length) {
        const r = await fetch('/image/delete-batch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filenames: imageFiles }),
        });
        if (r.ok) {
          const d = await r.json();
          deletedCount += (d.deleted || []).length;
        }
      }
      // Delete audio files individually
      for (const af of audioFiles) {
        try {
          const r = await fetch('/audio/delete', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename: af }),
          });
          if (r.ok) deletedCount++;
        } catch (e) { /* continue */ }
      }
      this.selected.clear();
      toast(`${ICONS.circle(14)} Deleted ${deletedCount} file(s)`);
      await this.loadGallery();
    } catch (e) { toast(' Batch delete failed: ' + e.message); }
  }

  async removeBgSelected() {
    const files = [...this.selected].filter(f => {
      const l = f.toLowerCase();
      return !l.endsWith('.gif') && !l.endsWith('.mp4') && !l.endsWith('.webm') && !l.endsWith('.svg') && !l.endsWith('.mp3') && !l.endsWith('.wav');
    });
    if (!files.length) {
      toast(`${ICONS.x(14)} No valid images selected for Remove BG`);
      return;
    }

    this._openRembgModal(files);
  }

  async makeColoringSelected() {
    const files = [...this.selected].filter(f => {
      const l = f.toLowerCase();
      return !l.endsWith('.gif') && !l.endsWith('.mp4') && !l.endsWith('.webm') && !l.endsWith('.svg') && !l.endsWith('.mp3') && !l.endsWith('.wav');
    });
    if (!files.length) {
      toast(`${ICONS.x(14)} No valid images selected for Crayons`);
      return;
    }
    try {
      toast(`${ICONS.sparkles(14)} Creating coloring pages for ${files.length} file(s)...`);
      for (const file of files) {
        const r = await fetch('/image/make-coloring', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename: file }),
        });
        if (!r.ok) {
          const err = await r.json();
          throw new Error(err.detail || 'Server returned ' + r.status);
        }
      }
      this.selected.clear();
      toast(`${ICONS.check(14)} Coloring pages created!`);
      await this.loadGallery();
    } catch (e) { toast(' Crayons conversion failed: ' + e.message); }
  }

  _openRembgModal(files) {
    if (!files || !files.length) return;
    this._currentRembgFiles = files;
    this._currentRembgFile = files[0];
    const modal = $('#media-rembg-modal');
    const img = $('#media-rembg-preview-img');

    // Reset preview to original image
    img.src = `/data/images/${this._currentRembgFile}`;

    // Reset controls
    const alphaCb = $('#rembg-alpha-matting');
    if (alphaCb) alphaCb.checked = false;
    const alphaCtrls = $('#rembg-alpha-controls');
    if (alphaCtrls) alphaCtrls.style.display = 'none';

    if (modal) modal.classList.add('open');

    // trigger initial preview
    this._refreshRembgPreview();
  }

  closeRembgModal() {
    const modal = $('#media-rembg-modal');
    if (modal) modal.classList.remove('open');
    this._currentRembgFiles = null;
    this._currentRembgFile = null;
    if (this._rembgDebounce) clearTimeout(this._rembgDebounce);
  }

  _getRembgSettings() {
    return {
      model_name: $('#rembg-model')?.value || 'isnet-general-use',
      post_process_mask: $('#rembg-post-process')?.checked || false,
      alpha_matting: $('#rembg-alpha-matting')?.checked || false,
      alpha_matting_foreground_threshold: parseInt($('#rembg-fg-thresh')?.value || 240, 10),
      alpha_matting_background_threshold: parseInt($('#rembg-bg-thresh')?.value || 10, 10),
      alpha_matting_erode_size: parseInt($('#rembg-erode-size')?.value || 10, 10)
    };
  }

  async _refreshRembgPreview() {
    if (!this._currentRembgFile) return;
    const loading = $('#media-rembg-loading');
    if (loading) loading.style.display = 'block';

    try {
      const settings = this._getRembgSettings();
      const r = await fetch('/image/remove-bg-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: this._currentRembgFile, settings })
      });

      if (!r.ok) throw new Error('Preview generation failed');
      const data = await r.json();

      const img = $('#media-rembg-preview-img');
      if (img) {
        // Ensure it's a valid base64 src
        img.src = 'data:image/png;base64,' + data.image_base64;
      }
    } catch (e) {
      console.error(e);
      toast(ICONS.x(14) + ' Preview generation failed');
    } finally {
      if (loading) loading.style.display = 'none';
    }
  }

  async _applyRembg() {
    if (!this._currentRembgFiles || !this._currentRembgFiles.length) return;
    const btn = $('#media-rembg-apply-btn');
    const oldText = btn.textContent;
    btn.textContent = 'Saving...';
    btn.disabled = true;

    try {
      const settings = this._getRembgSettings();
      const r = await fetch('/image/remove-bg', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filenames: this._currentRembgFiles, settings }),
      });
      if (!r.ok) {
        const err = await r.json();
        throw new Error(err.detail || 'Server returned ' + r.status);
      }
      const d = await r.json();
      this.selected.clear();
      toast(`${ICONS.check(14)} Background removed!`);
      this.closeRembgModal();
      await this.loadGallery();
    } catch (e) {
      toast(' Background removal failed: ' + e.message);
    } finally {
      btn.textContent = oldText;
      btn.disabled = false;
    }
  }

  async convertVideo(targetFormat) {
    const files = [...this.selected];
    if (files.length === 0) {
      toast((window.icon ? window.icon('circle', 14) : '⚪') + ' Sélectionnez une vidéo ou un GIF à convertir');
      return;
    }
    if (files.length > 1) {
      toast((window.icon ? window.icon('circle', 14) : '⚪') + ' Veuillez sélectionner un seul fichier à convertir');
      return;
    }
    const filename = files[0];
    const isGif = filename.toLowerCase().endsWith('.gif');
    const isMp4 = filename.toLowerCase().endsWith('.mp4');
    const isWebm = filename.toLowerCase().endsWith('.webm');

    if (!isGif && !isMp4 && !isWebm) {
      toast((window.icon ? window.icon('x', 14) : '❌') + " Le fichier sélectionné n'est ni un GIF ni une vidéo");
      return;
    }
    if (filename.toLowerCase().endsWith(`.${targetFormat}`)) {
      toast((window.icon ? window.icon('circle', 14) : '⚪') + ` Le fichier est déjà au format ${targetFormat.toUpperCase()}`);
      return;
    }

    toast((window.icon ? window.icon('hourglass', 14) : '⏳') + ` Conversion de ${filename} en ${targetFormat.toUpperCase()}...`);
    try {
      const r = await fetch('/image/convert-video', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename, target_format: targetFormat })
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Erreur du serveur');

      toast((window.icon ? window.icon('check', 14) : '✅') + ' Conversion réussie !');
      this.selected.clear();
      await this.loadGallery();
    } catch (e) {
      toast((window.icon ? window.icon('x', 14) : '❌') + ' Échec de la conversion : ' + e.message);
    }
  }

  downloadFile(filename, url) {
    const a = document.createElement('a');
    a.href = url; a.download = filename; a.click();
  }

  async downloadZip() {
    const files = this.selected.size > 0
      ? [...this.selected].join(',')
      : '';  // empty = all
    const url = '/image/download-zip' + (files ? '?files=' + encodeURIComponent(files) : '');
    toast(ICONS.box(14) + ' Preparing ZIP...');
    try {
      const r = await fetch(url);
      if (!r.ok) { toast(ICONS.x(14) + ' ZIP download failed'); return; }
      const blob = await r.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = r.headers.get('Content-Disposition')?.split('filename="')[1]?.replace('"', '') || 'gallery.zip';
      a.click(); URL.revokeObjectURL(a.href);
      toast(ICONS.check(14) + ' ZIP downloaded!');
    } catch (e) { toast(' ZIP failed: ' + e.message); }
  }

  // ---- Lightbox ----
  openLightbox(idx) {
    this.lightboxIdx = idx;
    const item = this.filtered[idx];
    if (!item) return;

    const lb = $('#media-lightbox');
    const content = $('#media-lb-content');
    const info = $('#media-lb-info');
    if (!lb || !content) return;

    content.innerHTML = '';
    // Show/hide I2V button depending on item type (static images only)
    const lbI2VBtn = $('#media-lb-i2v');
    if (lbI2VBtn) {
      const canI2V = !item.isAudio && !item.isVideo && !item.isSvg;
      lbI2VBtn.style.display = canI2V ? '' : 'none';
    }
    if (item.isAudio) {
      content.innerHTML = `
        <div class="media-lightbox-audio">
          <div class="media-lb-audio-icon">${window.icon ? window.icon('music', 64) : '🎵'}</div>
          <div class="media-lb-audio-name">${escHtml(item.filename)}</div>
          <audio controls autoplay src="${item.url}" style="width:100%;max-width:500px;margin-top:16px;"></audio>
        </div>`;
    } else if (item.isVideo && item.format === 'mp4') {
      const vid = el('video', { src: item.url, controls: 'true', autoplay: 'true', loop: 'true' });
      content.appendChild(vid);
    } else {
      const img = el('img', { src: item.url, alt: item.filename });
      if (item.isSvg || item.format === 'transparent_png' || item.format === 'svg') {
        img.classList.add('is-transparent');
      }
      content.appendChild(img);
    }

    if (info) {
      let displayPrompt = item.prompt;
      let styleBadgeHTML = '';
      const styleMatch = displayPrompt.match(/^\[(.*?)\]\s+(.*)/s);
      if (styleMatch) {
        let styleName = styleMatch[1];
        if (styleName === 'none') styleName = 'Z-Image Turbo';
        displayPrompt = styleMatch[2];
        styleBadgeHTML = `<span class="badge" style="background:var(--accent);color:white;font-size:0.85em;margin-right:8px;padding:3px 8px;border-radius:4px">${escHtml(styleName)}</span>`;
      }
      info.innerHTML = `<strong>${item.filename}</strong> — ${item.format.toUpperCase()} — ${idx + 1}/${this.filtered.length}<br><div style="font-size: 0.9em; opacity: 0.8; word-wrap: break-word; cursor: pointer; margin-top: 8px;" title="Click to reuse prompt and style" onclick="window.mediaStudio && window.mediaStudio.reusePrompt(${idx})">${styleBadgeHTML}${escHtml(displayPrompt)}</div>`;
    }

    lb.classList.add('open');
  }

  closeLightbox() {
    const lb = $('#media-lightbox');
    if (lb) lb.classList.remove('open');
    // Stop any playing video
    const vid = lb?.querySelector('video');
    if (vid) vid.pause();
    this.lightboxIdx = -1;
  }

  reusePrompt(idx) {
    const item = this.filtered[idx];
    if (!item) return;

    this.closeLightbox();

    let style = 'none';
    let text = item.prompt;

    const match = text.match(/^\[(.*?)\]\s+(.*)/s);
    if (match) {
      style = match[1];
      text = match[2];
    }

    const promptEl = $('#media-prompt');
    if (promptEl) promptEl.value = text;

    if (item.isVideo) {
      const typeBtn = document.querySelector('.media-type-btn[data-type="video"]');
      if (typeBtn) typeBtn.click();

      const styleEl = $('#media-model-video');
      if (styleEl && Array.from(styleEl.options).some(o => o.value === style)) {
        styleEl.value = style;
      }
    } else {
      const typeBtn = document.querySelector('.media-type-btn[data-type="image"]');
      if (typeBtn) typeBtn.click();

      const styleEl = $('#media-style');
      if (styleEl && Array.from(styleEl.options).some(o => o.value === style)) {
        styleEl.value = style;
      }
    }

    toast(ICONS.sparkles(14) + ' Prompt and style copied');
  }

  lightboxNav(dir) {
    if (this.lightboxIdx < 0) return;
    let newIdx = this.lightboxIdx + dir;
    if (newIdx < 0) newIdx = this.filtered.length - 1;
    if (newIdx >= this.filtered.length) newIdx = 0;
    this.openLightbox(newIdx);
  }

  lightboxDownload() {
    const item = this.filtered[this.lightboxIdx];
    if (item) this.downloadFile(item.filename, item.url);
  }

  async lightboxDelete() {
    const item = this.filtered[this.lightboxIdx];
    if (!item) return;
    this.closeLightbox();
    await this.deleteFile(item.filename);
  }
  // ---- Image-to-Video (one click: import image as video source) ----

  useImageAsVideoSource(item) {
    // Guard: only static raster images
    if (item.isAudio || item.isVideo || item.isSvg) {
      toast(ICONS.circle(14) + ' Sélectionnez une image statique (PNG/JPG) pour Img→Vidéo');
      return;
    }

    // 1. Set as reference image
    this.referenceImage = item.filename;
    const refPreview = $('#media-ref-preview');
    if (refPreview) refPreview.src = item.url;

    // 2. Switch type to video
    this.type = 'video';
    $$('#media-type-toggle .media-type-btn').forEach(b => b.classList.remove('active'));
    const vidBtn = document.querySelector('#media-type-toggle .media-type-btn[data-type="video"]');
    if (vidBtn) vidBtn.classList.add('active');
    this._updateFormVisibility();

    // 3. Auto-select an I2V-compatible model
    const i2vModels = ['svd_xt', 'cogvideox', 'wan22'];
    const videoModelSel = $('#media-model-video');
    if (videoModelSel && !i2vModels.includes(videoModelSel.value)) {
      videoModelSel.value = 'svd_xt'; // SVD-XT is the lightest I2V model (6GB)
    }

    // 4. Pre-fill video prompt from image prompt
    const promptEl = $('#media-prompt');
    if (promptEl && item.prompt) {
      let txt = item.prompt;
      const m = txt.match(/^\[.*?\]\s+(.*)/s);
      if (m) txt = m[1];
      if (!promptEl.value || promptEl.value === txt) promptEl.value = txt;
    }

    // 5. Scroll sidebar into view
    const sidebar = document.querySelector('.media-sidebar');
    if (sidebar) sidebar.scrollTop = 0;

    toast(`${ICONS.sparkles(14)} Image importée comme source vidéo (${videoModelSel?.options[videoModelSel?.selectedIndex]?.text || 'CogVideoX'}) — cliquez Générer`);
  }
}

// Backward compatibility
window.MediaStudio = MediaStudio;
