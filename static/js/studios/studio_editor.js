/**
 * Clawzd — Premiere-style Studio Editor Frontend Engine.
 * Fully modular timeline manager, playhead transport system, and clip inspector.
 */

window.StudioEditor = {
  // Timeline State
  duration: 30.0,
  zoom: 30, // Pixels per second
  playhead: 0.0,
  isPlaying: false,
  currentTool: 'select', // 'select' or 'split'
  selectedClipId: null,
  clips: [], // List of timeline clip models
  mediaBinItems: [], // List of gallery items in Resource Bin
  
  // Playback timer variables
  lastFrameTime: 0,
  animationFrameId: null,

  // HTML Elements
  elements: {},

  init() {
    logger = console; // local logger fallback
    
    // Bind elements
    this.elements = {
      modal: document.getElementById("media-studio-editor-modal"),
      closeBtn: document.getElementById("editor-close-btn"),
      renderBtn: document.getElementById("editor-render-btn"),
      playPauseBtn: document.getElementById("btn-play-pause"),
      stopBtn: document.getElementById("btn-stop"),
      seekStartBtn: document.getElementById("btn-seek-start"),
      seekEndBtn: document.getElementById("btn-seek-end"),
      timecode: document.getElementById("timecode-display"),
      binContainer: document.getElementById("bin-list-container"),
      searchBin: document.getElementById("bin-search"),
      zoomSlider: document.getElementById("timeline-zoom"),
      ruler: document.getElementById("timeline-time-ruler"),
      playheadLine: document.getElementById("timeline-playhead-line"),
      timelineGrid: document.getElementById("timeline-tracks-grid-el"),
      scrollContainer: document.getElementById("timeline-scroll-container"),
      inspectorPlaceholder: document.getElementById("inspector-placeholder"),
      inspectorControls: document.getElementById("inspector-controls"),
      liveText: document.getElementById("live-text-overlay"),
      videoPreview: document.getElementById("editor-preview-video"),
      asciiPreview: document.getElementById("editor-preview-ascii"),
      audioPreview: document.getElementById("editor-preview-audio"),
      previewPlaceholder: document.getElementById("preview-placeholder-msg"),
      toolSelect: document.getElementById("tool-select"),
      toolSplit: document.getElementById("tool-split"),
      toolClear: document.getElementById("tool-clear")
    };

    if (!this.elements.modal) return;

    // Bind launch button
    const launchBtn = document.getElementById("media-studio-editor-btn");
    if (launchBtn) {
      launchBtn.addEventListener("click", () => this.open());
    }

    this.bindEvents();
    this.setupInspectorListeners();
    this.updateZoom(parseInt(this.elements.zoomSlider.value));
  },

  bindEvents() {
    const el = this.elements;

    // Global toggle buttons
    el.closeBtn.addEventListener("click", () => this.close());
    el.renderBtn.addEventListener("click", () => this.exportTimeline());

    // Playback transport buttons
    el.playPauseBtn.addEventListener("click", () => this.togglePlay());
    el.stopBtn.addEventListener("click", () => this.stop());
    el.seekStartBtn.addEventListener("click", () => this.seekTo(0));
    el.seekEndBtn.addEventListener("click", () => this.seekTo(this.duration));

    // Sidebar tab toggles
    document.querySelectorAll(".sidebar-tab").forEach(tab => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".sidebar-tab").forEach(t => t.classList.remove("active"));
        document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
        
        tab.classList.add("active");
        const contentId = `tab-${tab.dataset.tab}`;
        document.getElementById(contentId).classList.add("active");
      });
    });

    // Zoom slider
    el.zoomSlider.addEventListener("input", (e) => {
      this.updateZoom(parseInt(e.target.value));
    });

    // Search media bin
    el.searchBin.addEventListener("input", (e) => {
      this.filterMediaBin(e.target.value);
    });

    // Action tools
    el.toolSelect.addEventListener("click", () => this.setTool('select'));
    el.toolSplit.addEventListener("click", () => this.setTool('split'));
    el.toolClear.addEventListener("click", () => this.clearTimeline());

    // Timeline Ruler playhead seeking
    el.ruler.addEventListener("mousedown", (e) => {
      e.stopPropagation();
      e.preventDefault();

      const seek = (evt) => {
        const rect = el.ruler.getBoundingClientRect();
        const x = evt.clientX - rect.left + el.scrollContainer.scrollLeft;
        const time = Math.max(0, Math.min(x / this.zoom, this.duration));
        this.seekTo(Math.round(time * 10) / 10);
      };

      seek(e);

      const onMouseMove = (moveEvt) => seek(moveEvt);
      const onMouseUp = () => {
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
      };

      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    });
  },

  open() {
    this.elements.modal.style.display = "block";
    this.stop();
    this.loadGalleryAssets();
    this.renderTimeline();
    this.syncPreview();
    
    // Automatically trigger SVG icon styling compilation
    if (window.icon) {
      document.querySelectorAll('#media-studio-editor-modal .media-icon[data-icon]').forEach(n => {
        n.innerHTML = window.icon(n.dataset.icon, 14);
      });
    }
  },

  close() {
    this.stop();
    this.elements.modal.style.display = "none";
  },

  async loadGalleryAssets() {
    try {
      this.mediaBinItems = [];
      
      // Fetch image/video gallery
      const imageResp = await fetch('/image/gallery', { cache: 'no-store' });
      if (imageResp.ok) {
        const data = await imageResp.json();
        const files = data.images || [];
        files.forEach(f => {
          this.mediaBinItems.push({
            filename: f.filename,
            url: f.url,
            type: f.filename.toLowerCase().endsWith('.mp4') || f.filename.toLowerCase().endsWith('.webm') ? 'video' : 'image',
            duration: f.duration || 5.0
          });
        });
      }

      // Fetch audio gallery
      try {
        const audioResp = await fetch('/audio/gallery', { cache: 'no-store' });
        if (audioResp.ok) {
          const data = await audioResp.json();
          const files = data.audio_files || [];
          files.forEach(f => {
            this.mediaBinItems.push({
              filename: f.filename,
              url: f.url,
              type: 'audio',
              duration: f.duration || 5.0
            });
          });
        }
      } catch (ae) { /* optional audio */ }

      this.renderMediaBin();
    } catch (e) {
      console.error("Failed to load media assets into Editor bin", e);
    }
  },

  renderMediaBin() {
    const container = this.elements.binContainer;
    container.innerHTML = '';

    if (this.mediaBinItems.length === 0) {
      container.innerHTML = `
        <div class="empty-inspector" style="padding-top:20px;">
          <p>No media files found in your gallery.</p>
        </div>
      `;
      return;
    }

    this.mediaBinItems.forEach(item => {
      const el = document.createElement("div");
      el.className = "bin-item";
      
      let thumbnailMarkup = '<span class="media-icon" data-icon="file"></span>';
      if (item.type === 'image') {
        thumbnailMarkup = `<img src="${item.url}" alt="thumb">`;
      } else if (item.type === 'video') {
        thumbnailMarkup = `<span class="media-icon" data-icon="video"></span>`;
      } else if (item.type === 'audio') {
        thumbnailMarkup = `<span class="media-icon" data-icon="music"></span>`;
      }

      el.innerHTML = `
        <div class="bin-thumbnail">${thumbnailMarkup}</div>
        <div class="bin-info">
          <div class="bin-name">${item.filename}</div>
          <div class="bin-meta">
            <span>${item.type.toUpperCase()}</span>
            <span>${parseFloat(item.duration).toFixed(1)}s</span>
          </div>
        </div>
        <button class="bin-add-btn" title="Add to Timeline">+ Add</button>
      `;

      // Quick Add action
      el.querySelector(".bin-add-btn").addEventListener("click", () => {
        this.addClipToTimeline(item);
      });

      container.appendChild(el);
    });

    if (window.icon) {
      container.querySelectorAll('.media-icon[data-icon]').forEach(n => {
        n.innerHTML = window.icon(n.dataset.icon, 14);
      });
    }
  },

  filterMediaBin(query) {
    const q = query.toLowerCase();
    const items = document.querySelectorAll(".bin-item");
    items.forEach(el => {
      const name = el.querySelector(".bin-name").textContent.toLowerCase();
      el.style.display = name.includes(q) ? "flex" : "none";
    });
  },

  addClipToTimeline(mediaItem) {
    const trackType = mediaItem.type === 'audio' ? 'audio' : 'video';
    const id = `clip_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
    
    const newClip = {
      id,
      filename: mediaItem.filename,
      track: trackType,
      start: this.playhead,
      duration: mediaItem.duration,
      trim_start: 0.0,
      speed: 1.0,
      volume: 1.0,
      filter: 'none',
      text: 'Sample Subtitle',
      color: 'white',
      font_size: 28,
      position: 'bottom'
    };

    this.clips.push(newClip);
    this.renderTimeline();
    this.selectClip(id);
    this.syncPreview();
    
    // Automatically grow timeline duration if clip overflows
    const clipEnd = newClip.start + newClip.duration;
    if (clipEnd > this.duration) {
      this.duration = Math.ceil(clipEnd + 5.0);
      this.renderTimeline();
    }
  },

  selectClip(clipId) {
    this.selectedClipId = clipId;
    
    // Highlight active element on timeline
    document.querySelectorAll(".timeline-clip").forEach(el => {
      el.classList.toggle("selected", el.dataset.clipId === clipId);
    });

    const clip = this.clips.find(c => c.id === clipId);
    if (!clip) {
      this.elements.inspectorPlaceholder.style.display = "flex";
      this.elements.inspectorControls.style.display = "none";
      return;
    }

    // Populate inspector
    this.elements.inspectorPlaceholder.style.display = "none";
    this.elements.inspectorControls.style.display = "block";
    
    document.getElementById("inspector-clip-name").textContent = clip.filename.substr(0, 15) + '...';
    document.getElementById("prop-start").value = clip.start;
    document.getElementById("prop-duration").value = clip.duration;
    document.getElementById("prop-trim-start").value = clip.trim_start;
    
    const filterGroup = document.querySelector(".inspector-video-only");
    const audioGroup = document.querySelector(".inspector-audio-only");
    const textGroup = document.querySelector(".inspector-text-only");

    // Toggle track fields
    if (clip.track === 'video') {
      filterGroup.style.display = "flex";
      audioGroup.style.display = "none";
      textGroup.style.display = "none";
      document.getElementById("prop-filter").value = clip.filter;
    } else if (clip.track === 'audio') {
      filterGroup.style.display = "none";
      audioGroup.style.display = "flex";
      textGroup.style.display = "none";
      document.getElementById("prop-volume").value = clip.volume;
      document.getElementById("prop-vol-val").textContent = clip.volume;
    } else if (clip.track === 'text') {
      filterGroup.style.display = "none";
      audioGroup.style.display = "none";
      textGroup.style.display = "block";
      document.getElementById("prop-text-str").value = clip.text;
      document.getElementById("prop-text-color").value = clip.color;
      document.getElementById("prop-text-size").value = clip.font_size;
      document.getElementById("prop-text-position").value = clip.position;
    }

    document.getElementById("prop-speed").value = clip.speed;
    document.getElementById("prop-speed-val").textContent = clip.speed;
  },

  setupInspectorListeners() {
    // Volume slider val update
    document.getElementById("prop-volume").addEventListener("input", (e) => {
      document.getElementById("prop-vol-val").textContent = e.target.value;
      this.updateSelectedClipProperty('volume', parseFloat(e.target.value));
    });

    // Speed slider val update
    document.getElementById("prop-speed").addEventListener("input", (e) => {
      document.getElementById("prop-speed-val").textContent = e.target.value;
      this.updateSelectedClipProperty('speed', parseFloat(e.target.value));
    });

    // Precision inputs update
    document.getElementById("prop-start").addEventListener("change", (e) => {
      this.updateSelectedClipProperty('start', parseFloat(e.target.value) || 0.0);
    });

    document.getElementById("prop-duration").addEventListener("change", (e) => {
      this.updateSelectedClipProperty('duration', parseFloat(e.target.value) || 1.0);
    });

    document.getElementById("prop-trim-start").addEventListener("change", (e) => {
      this.updateSelectedClipProperty('trim_start', parseFloat(e.target.value) || 0.0);
    });

    document.getElementById("prop-filter").addEventListener("change", (e) => {
      this.updateSelectedClipProperty('filter', e.target.value);
    });

    // Subtitle specific properties
    document.getElementById("prop-text-str").addEventListener("input", (e) => {
      this.updateSelectedClipProperty('text', e.target.value);
    });
    document.getElementById("prop-text-color").addEventListener("change", (e) => {
      this.updateSelectedClipProperty('color', e.target.value);
    });
    document.getElementById("prop-text-size").addEventListener("change", (e) => {
      this.updateSelectedClipProperty('font_size', parseInt(e.target.value) || 24);
    });
    document.getElementById("prop-text-position").addEventListener("change", (e) => {
      this.updateSelectedClipProperty('position', e.target.value);
    });

    // Inspector Delete Clip
    document.getElementById("prop-delete-btn").addEventListener("click", () => {
      if (this.selectedClipId) {
        this.clips = this.clips.filter(c => c.id !== this.selectedClipId);
        this.selectedClipId = null;
        this.selectClip(null);
        this.renderTimeline();
        this.syncPreview();
      }
    });
  },

  updateSelectedClipProperty(prop, value) {
    if (!this.selectedClipId) return;
    const clip = this.clips.find(c => c.id === this.selectedClipId);
    if (clip) {
      clip[prop] = value;
      
      // Live updates
      const clipEl = document.querySelector(`.timeline-clip[data-clip-id="${clip.id}"]`);
      if (clipEl) {
        if (prop === 'start') {
          clipEl.style.left = (value * this.zoom) + 'px';
        } else if (prop === 'duration') {
          clipEl.style.width = (value * this.zoom) + 'px';
        }
      }
      
      this.syncPreview();
    }
  },

  setTool(tool) {
    this.currentTool = tool;
    this.elements.toolSelect.classList.toggle("active", tool === 'select');
    this.elements.toolSplit.classList.toggle("active", tool === 'split');

    if (tool === 'split') {
      this.splitClipAtPlayhead();
      // Auto revert to selection tool
      setTimeout(() => this.setTool('select'), 300);
    }
  },

  splitClipAtPlayhead() {
    // Find active clip at playhead
    const t = this.playhead;
    const clipToSplit = this.clips.find(c => t > c.start && t < (c.start + c.duration));
    
    if (!clipToSplit) {
      if (window.toast) window.toast("❌ No clip found under playhead to split");
      return;
    }

    const duration1 = t - clipToSplit.start;
    const duration2 = clipToSplit.duration - duration1;
    
    // Resize original clip
    clipToSplit.duration = duration1;

    // Create split copy
    const id = `clip_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
    const clipCopy = {
      ...clipToSplit,
      id,
      start: t,
      duration: duration2,
      trim_start: clipToSplit.trim_start + (duration1 * clipToSplit.speed)
    };

    this.clips.push(clipCopy);
    this.renderTimeline();
    this.selectClip(id);
    this.syncPreview();

    if (window.toast) window.toast("✂️ Clip split successfully");
  },

  clearTimeline() {
    if (confirm("Are you sure you want to clear the timeline?")) {
      this.clips = [];
      this.selectedClipId = null;
      this.selectClip(null);
      this.seekTo(0);
      this.renderTimeline();
      this.syncPreview();
    }
  },

  updateZoom(z) {
    this.zoom = z;
    this.renderTimeline();
    this.updatePlayheadLine();
  },

  seekTo(time) {
    this.playhead = Math.max(0, Math.min(time, this.duration));
    this.updatePlayheadLine();
    this.syncPreview();
  },

  updatePlayheadLine() {
    const leftPos = this.playhead * this.zoom;
    this.elements.playheadLine.style.left = leftPos + 'px';
    
    // Center viewport scrolling around playhead if playing
    if (this.isPlaying) {
      const container = this.elements.scrollContainer;
      const width = container.clientWidth;
      if (leftPos > container.scrollLeft + width - 100) {
        container.scrollLeft = leftPos - 100;
      }
    }

    // Format Digital Timecode
    const formatTimecode = (sec) => {
      const h = Math.floor(sec / 3600).toString().padStart(2, '0');
      const m = Math.floor((sec % 3600) / 60).toString().padStart(2, '0');
      const s = Math.floor(sec % 60).toString().padStart(2, '0');
      const ms = Math.floor((sec % 1) * 100).toString().padStart(2, '0');
      return `${h}:${m}:${s}.${ms}`;
    };

    this.elements.timecode.textContent = formatTimecode(this.playhead);
  },

  renderTimeline() {
    const ruler = this.elements.ruler;
    const totalWidth = this.duration * this.zoom;

    // Render Ruler Tick Marks
    ruler.style.width = totalWidth + 'px';
    ruler.innerHTML = '';
    
    for (let s = 0; s <= this.duration; s++) {
      if (s % 5 === 0 || this.zoom > 35) {
        const tick = document.createElement("div");
        tick.className = "ruler-tick";
        tick.style.left = (s * this.zoom) + 'px';
        if (s % 5 === 0 || this.zoom > 50) {
          tick.textContent = s + "s";
        }
        ruler.appendChild(tick);
      }
    }

    // Adjust grid width
    this.elements.timelineGrid.style.width = (totalWidth + 120) + 'px';

    // Group and render tracks
    const videoLane = document.getElementById("video-track-lane");
    const audioLane = document.getElementById("audio-track-lane");
    const textLane = document.getElementById("text-track-lane");

    [videoLane, audioLane, textLane].forEach(l => l.innerHTML = '');

    this.clips.forEach(clip => {
      const clipEl = document.createElement("div");
      clipEl.className = "timeline-clip";
      clipEl.dataset.clipId = clip.id;
      clipEl.dataset.trackType = clip.track;
      clipEl.style.left = (clip.start * this.zoom) + 'px';
      clipEl.style.width = (clip.duration * this.zoom) + 'px';
      clipEl.textContent = clip.filename.substr(0, 20);

      if (this.selectedClipId === clip.id) {
        clipEl.classList.add("selected");
      }

      // Drag to Move timeline clip
      clipEl.addEventListener("mousedown", (e) => {
        if (this.currentTool !== 'select') return;
        e.stopPropagation();
        e.preventDefault();

        this.selectClip(clip.id);

        const startX = e.clientX;
        const initialStart = clip.start;

        const onMouseMove = (moveEvt) => {
          const deltaX = moveEvt.clientX - startX;
          const deltaT = deltaX / this.zoom;
          let newStart = Math.max(0, initialStart + deltaT);
          
          // Snap start time to 0.1s steps
          newStart = Math.round(newStart * 10) / 10;
          
          clip.start = newStart;
          clipEl.style.left = (newStart * this.zoom) + 'px';

          const startInput = document.getElementById("prop-start");
          if (startInput) startInput.value = newStart;
          
          this.updatePlayheadLine();
        };

        const onMouseUp = () => {
          document.removeEventListener("mousemove", onMouseMove);
          document.removeEventListener("mouseup", onMouseUp);
          this.renderTimeline();
          this.syncPreview();
        };

        document.addEventListener("mousemove", onMouseMove);
        document.addEventListener("mouseup", onMouseUp);
      });

      // Target appropriate lane container
      if (clip.track === 'video') {
        videoLane.appendChild(clipEl);
      } else if (clip.track === 'audio') {
        audioLane.appendChild(clipEl);
      } else if (clip.track === 'text') {
        textLane.appendChild(clipEl);
      }
    });
  },

  syncPreview(isLoopRunning = false) {
    const vEl = this.elements.videoPreview;
    const aEl = this.elements.audioPreview;
    const placeholder = this.elements.previewPlaceholder;
    const textOverlay = this.elements.liveText;

    // Find active clips at current playhead
    const activeVideo = this.clips.find(c => c.track === 'video' && this.playhead >= c.start && this.playhead < (c.start + c.duration));
    const activeAudio = this.clips.find(c => c.track === 'audio' && this.playhead >= c.start && this.playhead < (c.start + c.duration));
    const activeText = this.clips.find(c => c.track === 'text' && this.playhead >= c.start && this.playhead < (c.start + c.duration));

    // 1. VIDEO PREVIEW SYNC
    if (activeVideo) {
      placeholder.style.display = "none";
      
      const videoSrc = `/data/images/${activeVideo.filename}`;
      if (vEl.dataset.currentSrc !== videoSrc) {
        vEl.src = videoSrc;
        vEl.dataset.currentSrc = videoSrc;
        vEl.load();
      }

      // Calculate time offset inside source clip
      const offset = (this.playhead - activeVideo.start) * activeVideo.speed + activeVideo.trim_start;
      
      // Apply filters live in preview screen using CSS mapping
      vEl.className = '';
      if (activeVideo.filter && activeVideo.filter !== 'none') {
        vEl.classList.add(`filter-${activeVideo.filter}`);
      }

      if (vEl.readyState >= 1) {
        if (!isLoopRunning || Math.abs(vEl.currentTime - offset) > 0.25) {
          vEl.currentTime = offset;
        }
      }

      if (this.isPlaying) {
        vEl.play().catch(() => {});
      } else {
        vEl.pause();
      }

      // Handle ASCII Art preview versus standard video display
      if (activeVideo.filter === 'ascii_art') {
        vEl.style.display = "none";
        this.elements.asciiPreview.style.display = "flex";
        this.updateAsciiPreview(vEl);
      } else {
        this.elements.asciiPreview.style.display = "none";
        vEl.style.display = "block";
      }
    } else {
      vEl.style.display = "none";
      vEl.pause();
      this.elements.asciiPreview.style.display = "none";
      placeholder.style.display = "flex";
    }

    // 2. AUDIO PREVIEW SYNC
    if (activeAudio) {
      const audioSrc = activeAudio.filename.toLowerCase().endsWith('.mp3') || activeAudio.filename.toLowerCase().endsWith('.wav') ? 
        `/data/audio/${activeAudio.filename}` : `/data/images/${activeAudio.filename}`;
        
      if (aEl.dataset.currentSrc !== audioSrc) {
        aEl.src = audioSrc;
        aEl.dataset.currentSrc = audioSrc;
        aEl.load();
      }

      const offset = (this.playhead - activeAudio.start) * activeAudio.speed + activeAudio.trim_start;
      aEl.volume = activeAudio.volume;

      if (aEl.readyState >= 1) {
        if (!isLoopRunning || Math.abs(aEl.currentTime - offset) > 0.25) {
          aEl.currentTime = offset;
        }
      }

      if (this.isPlaying) {
        aEl.play().catch(() => {});
      } else {
        aEl.pause();
      }
    } else {
      aEl.pause();
    }

    // 3. TEXT OVERLAY PREVIEW SYNC
    if (activeText) {
      textOverlay.style.display = "block";
      textOverlay.textContent = activeText.text;
      textOverlay.style.color = activeText.color;
      textOverlay.style.fontSize = activeText.font_size + 'px';
      
      // Reset position classes
      textOverlay.className = "live-text-container " + activeText.position;
    } else {
      textOverlay.style.display = "none";
    }
  },

  updateAsciiPreview(videoEl) {
    const asciiEl = this.elements.asciiPreview;
    if (!videoEl || videoEl.readyState < 2) {
      return;
    }

    // Lazy load temporary canvas
    if (!this.asciiCanvas) {
      this.asciiCanvas = document.createElement("canvas");
      this.asciiCtx = this.asciiCanvas.getContext("2d");
    }

    const canvas = this.asciiCanvas;
    const ctx = this.asciiCtx;

    // Grid size for the monospace layout preview
    const cols = 120;
    const rows = 52;

    canvas.width = cols;
    canvas.height = rows;

    // Draw the active frame to canvas
    ctx.drawImage(videoEl, 0, 0, cols, rows);

    let imgData;
    try {
      imgData = ctx.getImageData(0, 0, cols, rows).data;
    } catch (e) {
      return;
    }

    const CHARS = " .:-=+*#%@";
    const numChars = CHARS.length;
    let asciiStr = "";

    for (let y = 0; y < rows; y++) {
      let line = "";
      for (let x = 0; x < cols; x++) {
        const offset = (y * cols + x) * 4;
        const r = imgData[offset];
        const g = imgData[offset + 1];
        const b = imgData[offset + 2];

        // Luma formula for grayscale mapping
        const brightness = 0.299 * r + 0.587 * g + 0.114 * b;
        const charIdx = Math.min(Math.floor(brightness / 256 * numChars), numChars - 1);
        line += CHARS[charIdx];
      }
      asciiStr += line + "\n";
    }

    asciiEl.textContent = asciiStr;
  },

  togglePlay() {
    if (this.isPlaying) {
      this.pause();
    } else {
      this.play();
    }
  },

  play() {
    this.isPlaying = true;
    this.elements.playPauseBtn.innerHTML = window.icon ? window.icon('pause', 20) : '⏸';
    this.lastFrameTime = performance.now();
    this.animationFrameId = requestAnimationFrame((t) => this.playbackStep(t));
    this.syncPreview();
    
    const editorStatus = document.getElementById("editor-status-text");
    if (editorStatus) editorStatus.textContent = "Playing preview";
  },

  pause() {
    this.isPlaying = false;
    this.elements.playPauseBtn.innerHTML = window.icon ? window.icon('play', 20) : '▶';
    if (this.animationFrameId) {
      cancelAnimationFrame(this.animationFrameId);
    }
    
    // Pause previews
    this.elements.videoPreview.pause();
    this.elements.audioPreview.pause();
    
    const editorStatus = document.getElementById("editor-status-text");
    if (editorStatus) editorStatus.textContent = "Paused";
  },

  stop() {
    this.pause();
    this.seekTo(0);
  },

  playbackStep(now) {
    if (!this.isPlaying) return;
    const delta = (now - this.lastFrameTime) / 1000;
    this.lastFrameTime = now;

    this.playhead += delta;

    if (this.playhead >= this.duration) {
      this.stop();
      return;
    }

    this.updatePlayheadLine();
    this.syncPreview(true);

    this.animationFrameId = requestAnimationFrame((t) => this.playbackStep(t));
  },

  async exportTimeline() {
    const renderBtn = this.elements.renderBtn;
    const progressContainer = document.getElementById("editor-progress-container");
    const progressBar = document.getElementById("editor-progress-bar");
    const progressPct = document.getElementById("editor-progress-pct");
    const statusText = document.getElementById("editor-status-text");

    const format = document.getElementById("export-format").value;
    const res = document.getElementById("export-res").value;
    const fps = document.getElementById("export-fps").value;

    if (this.clips.length === 0) {
      if (window.toast) window.toast("⚠️ Import at least one video, image, or audio clip to render !");
      return;
    }

    this.pause();

    // Map properties strictly for backend compiler
    const videoTrackClips = this.clips.filter(c => c.track === 'video').map(c => ({
      filename: c.filename,
      start: c.start,
      duration: c.duration,
      trim_start: c.trim_start,
      speed: c.speed,
      filter: c.filter
    }));

    const audioTrackClips = this.clips.filter(c => c.track === 'audio').map(c => ({
      filename: c.filename,
      start: c.start,
      duration: c.duration,
      trim_start: c.trim_start,
      volume: c.volume,
      speed: c.speed
    }));

    const textTrackClips = this.clips.filter(c => c.track === 'text').map(c => ({
      text: c.text,
      start: c.start,
      duration: c.duration,
      color: c.color,
      font_size: c.font_size,
      position: c.position
    }));

    // Trigger rendering progress state
    renderBtn.disabled = true;
    progressContainer.style.display = "flex";
    statusText.textContent = "Rendering...";
    
    // Simulate compilation progress
    let simPct = 0;
    progressBar.style.width = '0%';
    progressPct.textContent = '0%';
    const progressInterval = setInterval(() => {
      simPct = Math.min(simPct + Math.floor(Math.random() * 5) + 1, 95);
      progressBar.style.width = simPct + '%';
      progressPct.textContent = simPct + '%';
    }, 400);

    try {
      const resp = await fetch("/studio/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          export_format: format,
          resolution: res,
          fps: parseInt(fps),
          tracks: {
            video: videoTrackClips,
            audio: audioTrackClips,
            text: textTrackClips
          }
        })
      });

      clearInterval(progressInterval);

      if (resp.ok) {
        const result = await resp.json();
        
        progressBar.style.width = '100%';
        progressPct.textContent = '100%';
        
        setTimeout(() => {
          progressContainer.style.display = "none";
          renderBtn.disabled = false;
          statusText.textContent = "Idle";
          
          if (window.toast) window.toast("🎉 Compilation completed! Saved to gallery.");
          
          this.close();

          // Sync the main Clawzd Media Studio gallery view immediately
          const mediaStudioEl = document.getElementById("media-refresh");
          if (mediaStudioEl) {
            mediaStudioEl.click();
          }
        }, 1000);

      } else {
        const err = await resp.json();
        throw new Error(err.detail || "Server failed to compile timeline");
      }

    } catch (e) {
      clearInterval(progressInterval);
      progressContainer.style.display = "none";
      renderBtn.disabled = false;
      statusText.textContent = "Error";
      
      console.error(e);
      if (window.toast) window.toast("❌ Rendering failed: " + e.message);
    }
  }
};

// Auto initialize on DOM Load
document.addEventListener("DOMContentLoaded", () => {
  window.StudioEditor.init();
});
